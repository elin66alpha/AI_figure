#include "platform.h"
#include "audio_io.h"
#include "config.h"
#include "pdm_filter.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "driver/i2s_pdm.h"
#include <atomic>

static i2s_chan_handle_t s_tx = nullptr, s_rx = nullptr;
static bool s_ready = false, s_capturing = false;
static std::atomic<bool> s_playing{false};
static std::atomic<uint32_t> s_txUnderruns{0};
static uint16_t s_outGain = OUTPUT_GAIN_DEFAULT;
static PdmFilter s_filter;
static uint16_t s_raw[FRAME_SAMPLES * MIC_PDM_WORDS_PER_PCM];
static int16_t s_stereo[FRAME_SAMPLES * 2];
static const int16_t s_dmaSilence[DMA_DESC_NUM * DMA_FRAME_NUM * 2] = {};
static const int16_t s_frameSilence[FRAME_SAMPLES] = {};
static constexpr unsigned kDrainFrames =
    (DMA_DESC_NUM * DMA_FRAME_NUM + FRAME_SAMPLES - 1) / FRAME_SAMPLES;

static void ampSet(bool on) { gpio_set_level(static_cast<gpio_num_t>(PIN_AMP_SD), on); }
static bool onTxOverflow(i2s_chan_handle_t, i2s_event_data_t *, void *) {
  if (s_playing.load(std::memory_order_relaxed))
    s_txUnderruns.fetch_add(1, std::memory_order_relaxed);
  return false;
}
static bool checked(esp_err_t e, const char *operation) {
  if (e == ESP_OK) return true;
  printf("[AUDIO] %s: %s\n", operation, esp_err_to_name(e));
  return false;
}
bool audioBegin() {
  if (s_ready) return true;
  gpio_set_direction(static_cast<gpio_num_t>(PIN_AMP_SD), GPIO_MODE_OUTPUT);
  ampSet(false);

  // Separate allocations deliberately avoid full duplex and clock loopback.
  // C3 I2S0 RX receives raw PDM; TX uses Philips I2S for NS4168.
  i2s_chan_config_t txCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  txCfg.dma_desc_num = DMA_DESC_NUM;
  txCfg.dma_frame_num = DMA_FRAME_NUM;
  txCfg.auto_clear = true;
  if (!checked(i2s_new_channel(&txCfg, &s_tx, nullptr), "allocate TX")) return false;
  i2s_std_config_t tx = {};
  tx.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE_HZ);
  tx.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  tx.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  tx.gpio_cfg.bclk = static_cast<gpio_num_t>(PIN_I2S_BCLK);
  tx.gpio_cfg.ws = static_cast<gpio_num_t>(PIN_I2S_WS);
  tx.gpio_cfg.dout = static_cast<gpio_num_t>(PIN_AMP_DATA);
  tx.gpio_cfg.din = I2S_GPIO_UNUSED;
  if (!checked(i2s_channel_init_std_mode(s_tx, &tx), "init TX")) return false;
  i2s_event_callbacks_t callbacks = {};
  callbacks.on_send_q_ovf = onTxOverflow;
  if (!checked(i2s_channel_register_event_callback(s_tx, &callbacks, nullptr), "TX callback")) return false;

  i2s_chan_config_t rxCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  rxCfg.dma_desc_num = MIC_RAW_DMA_DESC_NUM;
  rxCfg.dma_frame_num = MIC_RAW_DMA_WORDS;
  if (!checked(i2s_new_channel(&rxCfg, nullptr, &s_rx), "allocate RX")) return false;
  i2s_pdm_rx_config_t rx = {};
  // IDF 6.1 raw RX calculates physical BCLK = sample_rate_hz*2.
  rx.clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(MIC_PDM_DRIVER_RATE);
  rx.slot_cfg = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  rx.slot_cfg.slot_mask = I2S_PDM_SLOT_LEFT; // Microphone L/R is tied to GND.
  rx.gpio_cfg.clk = static_cast<gpio_num_t>(PIN_MIC_CLK);
  rx.gpio_cfg.din = static_cast<gpio_num_t>(PIN_MIC_DATA);
  if (!checked(i2s_channel_init_pdm_rx_mode(s_rx, &rx), "init PDM RX")) return false;
  s_ready = true;
  printf("[AUDIO] PDM CLK=%u Hz, software PCM=%u Hz; NS4168 stereo I2S\n",
         MIC_PDM_CLK_HZ, SAMPLE_RATE_HZ);
  return true;
}
bool audioStartCapture() {
  if (!s_ready) return false;
  if (s_capturing) return true;
  audioCutPlayback();
  s_filter.reset();
  if (!checked(i2s_channel_enable(s_rx), "enable RX")) return false;
  s_capturing = true;
  return true;
}
void audioStopCapture() {
  if (!s_capturing) return;
  i2s_channel_disable(s_rx);
  s_capturing = false;
}
bool audioIsCapturing() { return s_capturing; }
size_t audioRead(int16_t *dst, size_t maxSamples, uint32_t timeoutMs) {
  if (!s_capturing || !dst) return 0;
  const size_t n = maxSamples < FRAME_SAMPLES ? maxSamples : FRAME_SAMPLES;
  if (!n) return 0;
  size_t bytes = 0;
  esp_err_t e = i2s_channel_read(s_rx, s_raw,
      n * MIC_PDM_WORDS_PER_PCM * sizeof(uint16_t), &bytes, timeoutMs);
  // A timeout can return a valid partial block; keep it rather than dropping time.
  if (e != ESP_OK && e != ESP_ERR_TIMEOUT) return 0;
  return s_filter.process(s_raw, bytes / sizeof(uint16_t), dst, n);
}
bool audioStartPlayback() {
  if (!s_ready) return false;
  if (s_playing.load()) return true;
  audioStopCapture();
  size_t loaded = 0;
  // Overwrite every DMA buffer while TX is stopped, including interrupted audio.
  if (!checked(i2s_channel_preload_data(s_tx, s_dmaSilence, sizeof(s_dmaSilence), &loaded),
               "preload silence") || loaded != sizeof(s_dmaSilence)) return false;
  if (!checked(i2s_channel_enable(s_tx), "enable TX")) return false;
  s_txUnderruns.store(0);
  ampSet(true); // NS4168 CTRL=HIGH selects right; both slots carry the same mono PCM.
  appDelay(AMP_WAKE_MS);
  s_playing.store(true);
  return true;
}
void audioStopPlayback() {
  if (!s_playing.load()) return;
  for (unsigned i = 0; i < kDrainFrames; ++i)
    audioWrite(s_frameSilence, FRAME_SAMPLES, 200);
  appDelay(AMP_TAIL_MS);
  audioCutPlayback();
}
void audioCutPlayback() {
  if (!s_playing.exchange(false)) return;
  ampSet(false);
  i2s_channel_disable(s_tx);
}
bool audioIsPlaying() { return s_playing.load(); }
uint32_t audioTxUnderruns() { return s_txUnderruns.load(); }
size_t audioWrite(const int16_t *src, size_t samples, uint32_t timeoutMs) {
  if (!s_playing.load() || !src) return 0;
  const uint32_t start = appMillis();
  size_t done = 0;
  while (done < samples) {
    size_t n = samples - done;
    if (n > FRAME_SAMPLES) n = FRAME_SAMPLES;
    for (size_t i = 0; i < n; ++i) {
      int32_t v = static_cast<int32_t>(src[done + i]) * s_outGain / 256;
      s_stereo[i * 2] = s_stereo[i * 2 + 1] = static_cast<int16_t>(v);
    }
    const uint32_t elapsed = appMillis() - start;
    if (elapsed >= timeoutMs) break;
    size_t bytes = 0;
    esp_err_t e = i2s_channel_write(s_tx, s_stereo, n * 2 * sizeof(int16_t),
                                   &bytes, timeoutMs - elapsed);
    done += bytes / (2 * sizeof(int16_t));
    if (e != ESP_OK || !bytes) break;
  }
  return done;
}
void setOutputGain(uint16_t g) { s_outGain = g > 256 ? 256 : g; }
uint16_t getOutputGain() { return s_outGain; }
