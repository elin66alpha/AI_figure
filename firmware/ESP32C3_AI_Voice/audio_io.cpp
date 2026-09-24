#include "audio_io.h"
#include "config.h"
#include <driver/i2s_std.h>

// ---------------------------------------------------------------- 内部状态
static i2s_chan_handle_t s_tx = nullptr;
static i2s_chan_handle_t s_rx = nullptr;
static bool s_capturing = false;
static bool s_playing   = false;   // 逻辑状态:是否在送真实音频(功放开着)。TX 硬件一直在跑。
static bool s_ready     = false;

static uint16_t s_outGain   = OUTPUT_GAIN_DEFAULT;   // 运行期可调,见 audio_io.h

static volatile uint32_t s_txUnderruns = 0;

// DC blocker: y[n] = x[n] - x[n-1] + a*y[n-1], a ≈ 0.994
static int32_t s_dcX1 = 0, s_dcY1 = 0;

// 32-bit 立体声暂存。严格半双工,所以读写共用一块(320*2*4 = 2560 B)。
static int32_t s_scratch[FRAME_SAMPLES * 2];

// 补尾用的静音(.bss,自动清零)
static int16_t s_silence16[FRAME_SAMPLES];

// 写满整个 DMA 需要几帧:ceil(4*240 / 320) = 3 帧 = 7680 B = 正好 4 个描述符。
static const int DMA_FLUSH_FRAMES = (DMA_DESC_NUM * DMA_FRAME_NUM + FRAME_SAMPLES - 1) / FRAME_SAMPLES;

// audioCutPlayback() 掐断后,DMA 里还躺着被打断那一轮的音频(最多 DMA_TOTAL_MS)。
// 功放关着听不见,但下次开播前得先冲干净,否则开功放那一下会漏出旧回复的尾巴。
static bool s_txDirty = false;

static inline int16_t sat16(int32_t v) {
  if (v >  32767) return  32767;
  if (v < -32768) return -32768;
  return (int16_t)v;
}

// TX DMA 队列溢出 = 应用层落后 >= dma_desc_num-1 个缓冲。
// 此时 auto_clear 已经把那些缓冲清零,硬件正在输出静音 —— 这就是"断续"。
// 不播放时 TX 空转,必然一直溢出,所以只在 s_playing 期间计数。
static bool onTxQueueOverflow(i2s_chan_handle_t, i2s_event_data_t *, void *) {
  if (s_playing) s_txUnderruns++;
  return false;
}

// 功放 (MAX98357A SD / GPIO10)
static inline void ampSet(bool on) { digitalWrite(PIN_AMP_SD, on ? HIGH : LOW); }

// ---------------------------------------------------------------- 初始化
bool audioBegin() {
  if (s_ready) return true;

  pinMode(PIN_AMP_SD, OUTPUT);
  ampSet(false);                   // 上电先关断功放

  i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan_cfg.dma_desc_num  = DMA_DESC_NUM;
  chan_cfg.dma_frame_num = DMA_FRAME_NUM;
  // 欠载时硬件自动输出零,而不是重复上一个 DMA 缓冲(那会变成循环"滋滋"声)。
  // 也正是靠这一条,TX 常开却不需要人一直喂数据。
  chan_cfg.auto_clear    = true;

  // 两个 handle 都传非 NULL => 同一个 I2S 控制器全双工,TX/RX 共享 BCLK/WS。
  // 正好对应 GPIO4/GPIO5 两根线被麦克风和功放共用的接法。
  if (i2s_new_channel(&chan_cfg, &s_tx, &s_rx) != ESP_OK) {
    Serial.println("[AUDIO] i2s_new_channel 失败");
    return false;
  }

  i2s_std_config_t std_cfg = {
    .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE_HZ),
    // STEREO 32-bit:INMP441 要求 32-bit slot;两边配置必须一致才能共享时钟
    .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                    I2S_SLOT_MODE_STEREO),
    .gpio_cfg = {
      .mclk = I2S_GPIO_UNUSED,
      .bclk = (gpio_num_t)PIN_I2S_BCLK,
      .ws   = (gpio_num_t)PIN_I2S_WS,
      .dout = (gpio_num_t)PIN_AMP_DATA,
      .din  = (gpio_num_t)PIN_MIC_DATA,
      .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
    },
  };

  if (i2s_channel_init_std_mode(s_tx, &std_cfg) != ESP_OK) {
    Serial.println("[AUDIO] TX init_std_mode 失败");
    return false;
  }
  if (i2s_channel_init_std_mode(s_rx, &std_cfg) != ESP_OK) {
    Serial.println("[AUDIO] RX init_std_mode 失败");
    return false;
  }

  // 回调必须在 enable 之前注册(要求 channel 处于 READY 态)
  i2s_event_callbacks_t cbs = {};
  cbs.on_send_q_ovf = onTxQueueOverflow;
  i2s_channel_register_event_callback(s_tx, &cbs, nullptr);

  // ---- TX 常开 ----
  // 全双工下 BCLK/WS 归 TX 模块所有。i2s_channel_enable 的文档原话:
  //   "It will start outputting BCLK and WS signal."
  // TX 一停,INMP441 这个纯从机就没有时钟,i2s_channel_read 只会一路超时返回 0。
  // 所以从这里开始 TX 就不再 disable 了。
  // DMA 缓冲是 calloc 出来的,首次输出即静音;功放此刻也还关着,不会有"啪"声。
  if (i2s_channel_enable(s_tx) != ESP_OK) {
    Serial.println("[AUDIO] TX enable 失败");
    return false;
  }

  s_ready = true;
  Serial.printf("[AUDIO] 就绪 %d Hz, 32-bit slot, BCLK=%d Hz, DMA=%d ms, TX 常开供时钟\n",
                SAMPLE_RATE_HZ, SAMPLE_RATE_HZ * 32 * 2, DMA_TOTAL_MS);
  return true;
}

// ---------------------------------------------------------------- 统计
uint32_t audioTxUnderruns()  { return s_txUnderruns; }

// ---------------------------------------------------------------- 录音
bool audioStartCapture() {
  if (!s_ready) return false;
  if (s_capturing) return true;
  if (s_playing) audioStopPlayback();        // 半双工:先停播放(TX 硬件保持运行)

  // TX 一直在跑,所以 GPIO4/5 上此刻已经有 BCLK/WS,INMP441 有时钟可用。
  if (i2s_channel_enable(s_rx) != ESP_OK) {
    Serial.println("[AUDIO] RX enable 失败");
    return false;
  }
  s_dcX1 = s_dcY1 = 0;
  s_capturing = true;
  return true;
}

void audioStopCapture() {
  if (!s_capturing) return;
  i2s_channel_disable(s_rx);                 // 不影响时钟,时钟在 TX 那边
  s_capturing = false;
}

bool audioIsCapturing() { return s_capturing; }

size_t audioRead(int16_t *dst, size_t maxSamples, uint32_t timeoutMs) {
  if (!s_capturing || dst == nullptr) return 0;

  size_t want = maxSamples < (size_t)FRAME_SAMPLES ? maxSamples : (size_t)FRAME_SAMPLES;
  if (want == 0) return 0;

  size_t got = 0;
  if (i2s_channel_read(s_rx, s_scratch, want * 2 * sizeof(int32_t), &got, timeoutMs) != ESP_OK)
    return 0;

  size_t frames = got / (2 * sizeof(int32_t));
  for (size_t i = 0; i < frames; i++) {
    // INMP441 的 L/R 接 GND => 数据在左时隙。右时隙是高阻/垃圾,丢掉。
    int32_t v = s_scratch[i * 2] >> MIC_SHIFT;

    if (DC_BLOCKER_ON) {                     // 编译期常量,分支被编译器折掉
      int32_t y = v - s_dcX1 + (int32_t)(((int64_t)s_dcY1 * 2036) >> 11); // a≈0.9941
      s_dcX1 = v;
      s_dcY1 = y;
      v = y;
    }
    dst[i] = sat16(v);
  }
  return frames;
}

// ---------------------------------------------------------------- 播放
bool audioStartPlayback() {
  if (!s_ready) return false;
  if (s_playing) return true;
  if (s_capturing) audioStopCapture();       // 半双工

  s_playing = true;
  s_txUnderruns = 0;

  // TX 一直在跑,DMA 里可能还留着上一轮的游标。先推两帧静音把管线对齐,
  // 再开功放 —— 功放唤醒时面对的是确定的零信号,不会"啪"一声。
  // 刚被掐断过(s_txDirty)就多推:冲满整个 DMA 再加一帧余量,把旧音频全部顶出去(原理见 audioStopPlayback)。
  const int n = s_txDirty ? DMA_FLUSH_FRAMES + 1 : 2;
  for (int i = 0; i < n; i++) audioWrite(s_silence16, FRAME_SAMPLES, 200);
  s_txDirty = false;

  ampSet(true);
  delay(AMP_WAKE_MS);                        // MAX98357A 离开 shutdown 需要几 ms
  return true;
}

void audioStopPlayback() {
  if (!s_playing) return;

  // 补一整个 DMA 长度的静音(DMA_FLUSH_FRAMES 帧 = 4 个描述符)。
  //
  // 为什么写完这些就说明尾音已经出去了:i2s_channel_write 只能拿到 DMA **已经播完**
  // (EOF 中断回收)的描述符来写。装着真实音频的描述符,要被我们拿来写静音,
  // 就必须先被 DMA 播完一遍。4 个描述符全部写完 = 所有装着真实音频的描述符都播过了。
  // (最后一个描述符只写了一半的情况也成立:那一半要写满,还得再等它 EOF 一次。)
  //
  // 2026-09-24 之前这里还有一个 delay(DMA_TOTAL_MS + 10) = 70 ms —— 那等的是
  // 刚写进去的静音,纯属白等,每次停播(提示音、回复结束、出错)都付一遍。
  // 现在只留 AMP_TAIL_MS,给 I2S TX FIFO 里最后几个样本出引脚。
  for (int i = 0; i < DMA_FLUSH_FRAMES; i++) audioWrite(s_silence16, FRAME_SAMPLES, 200);
  delay(AMP_TAIL_MS);

  ampSet(false);
  s_playing = false;
  // TX 不 disable:它是全双工下的时钟源,关了麦克风就聋了。
  // auto_clear 会让它继续输出零,功放已关,无声。
}

void audioCutPlayback() {
  if (!s_playing) return;
  // 打断专用。被打断的回复反正要扔,不必花 ~60 ms 把它的尾巴播完 —— 那段时间用户
  // 已经开口了,录音晚开一截就吃掉第一个字。MAX98357A 的 SD 关断自带防爆音。
  ampSet(false);
  s_playing = false;
  s_txDirty = true;                          // DMA 里的旧音频由下次 audioStartPlayback 冲掉
}

bool audioIsPlaying() { return s_playing; }

size_t audioWrite(const int16_t *src, size_t samples, uint32_t timeoutMs) {
  if (!s_playing || src == nullptr) return 0;

  size_t done = 0;
  while (done < samples) {
    size_t n = samples - done;
    if (n > (size_t)FRAME_SAMPLES) n = FRAME_SAMPLES;

    for (size_t i = 0; i < n; i++) {
      int32_t s = ((int32_t)src[done + i] * (int32_t)s_outGain) >> 8;  // 输出限幅
      int32_t w = (int32_t)((uint32_t)sat16(s) << 16);                 // PCM16 -> 32-bit slot 高位
      // MAX98357A 的 SD 被拉到 3.3V => 选左声道。右声道写同一个值,保险。
      s_scratch[i * 2]     = w;
      s_scratch[i * 2 + 1] = w;
    }

    size_t written = 0;
    if (i2s_channel_write(s_tx, s_scratch, n * 2 * sizeof(int32_t), &written, timeoutMs) != ESP_OK)
      break;
    if (written == 0) break;
    done += written / (2 * sizeof(int32_t));
  }
  return done;
}

// ---------------------------------------------------------------- 输出音量
void     setOutputGain(uint16_t g)  { s_outGain = (g > 256) ? 256 : g; }
uint16_t getOutputGain()            { return s_outGain; }
