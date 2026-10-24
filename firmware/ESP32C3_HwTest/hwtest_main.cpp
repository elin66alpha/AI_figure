// Offline hardware self-test for the AI_figure board. No WiFi, no server.
//
// The PC script (hardware/bringup/自检包/scripts/selftest.ps1) drives it over
// USB-Serial-JTAG: it sends one command letter per test and waits for "[DONE] <letter>".
// Tests that need human senses (LED, speaker, playback) only report "done"; the script
// asks the engineer. Tests the board can judge itself print "[RESULT] <name> PASS|FAIL".
//
// Audio, LED, button and cue code are the production sources from ../ESP32C3_AI_Voice,
// so a pass here means the production drivers work on this board.
#include "platform.h"
#include "config.h"
#include "audio_io.h"
#include "cue.h"
#include "led.h"
#include "button.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_heap_caps.h"
#include <cstdarg>
#include <cstdlib>

#define HWTEST_VERSION "hwtest-1"

static Button s_btn;
static bool s_audioOk = false;
static adc_oneshot_unit_handle_t s_adc = nullptr;
static adc_cali_handle_t s_cali = nullptr;

static void say(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vprintf(fmt, ap);
  va_end(ap);
  printf("\n");
  fflush(stdout);
}

// Integer square root; the C3 has no FPU (AGENT.md §9.1).
static uint32_t isqrt64(uint64_t v) {
  uint64_t r = 0, bit = 1ULL << 62;
  while (bit > v) bit >>= 2;
  while (bit) {
    if (v >= r + bit) { v -= r + bit; r = (r >> 1) + bit; } else { r >>= 1; }
    bit >>= 2;
  }
  return static_cast<uint32_t>(r);
}

struct Stats {
  uint32_t rms = 0;
  int32_t peak = 0, minV = 32767, maxV = -32768;
};

static void accumulate(const int16_t *s, size_t n, uint64_t &sumSq, Stats &st) {
  for (size_t i = 0; i < n; ++i) {
    const int32_t v = s[i];
    sumSq += static_cast<uint64_t>(static_cast<int64_t>(v) * v);
    if (v < st.minV) st.minV = v;
    if (v > st.maxV) st.maxV = v;
    const int32_t a = v < 0 ? -v : v;
    if (a > st.peak) st.peak = a;
  }
}

// ---------------------------------------------------------------- L: LED
static void testLed() {
  say("[LED] 3 blinks: 1 s on, 1 s off");
  for (int i = 0; i < 3; ++i) {
    ledSet(LedMode::ON);  ledUpdate(); appDelay(1000);
    ledSet(LedMode::OFF); ledUpdate(); appDelay(1000);
  }
}

// ---------------------------------------------------------------- S: speaker
static void testSpeaker() {
  if (!s_audioOk) { say("[SPK] audio init failed, nothing played"); return; }
  say("[SPK] tones 500 Hz, 1000 Hz, 2000 Hz, 0.6 s each");
  static const CueNote n[] = {
    {500, 600, 160}, {0, 300, 0}, {1000, 600, 160}, {0, 300, 0}, {2000, 600, 160},
  };
  cuePlay(n, 5);
  say("[SPK] tx underruns=%lu", static_cast<unsigned long>(audioTxUnderruns()));
}

// ---------------------------------------------------------------- B: button
static void testButton() {
  const uint32_t timeoutMs = 20000;
  if (gpio_get_level(static_cast<gpio_num_t>(PIN_PTT_BUTTON)) == 0) {
    say("[BTN] input is LOW before any press (stuck pressed or shorted to GND)");
    say("[RESULT] BTN FAIL stuck_low");
    return;
  }
  s_btn.clearEvents();
  say("[BTN] waiting %lu s for press and release", static_cast<unsigned long>(timeoutMs / 1000));
  const uint32_t start = appMillis();
  uint32_t pressedAt = 0;
  bool pressed = false;
  while (appMillis() - start < timeoutMs) {
    s_btn.update();
    if (!pressed && s_btn.tookPress()) {
      pressed = true;
      pressedAt = appMillis();
      ledSet(LedMode::ON); ledUpdate();
      say("[BTN] press");
    }
    if (pressed && s_btn.tookRelease()) {
      ledSet(LedMode::OFF); ledUpdate();
      say("[BTN] release, held %lu ms", static_cast<unsigned long>(appMillis() - pressedAt));
      say("[RESULT] BTN PASS");
      return;
    }
    appDelay(2);
  }
  ledSet(LedMode::OFF); ledUpdate();
  say("[RESULT] BTN FAIL %s", pressed ? "no_release" : "no_press");
}

// ---------------------------------------------------------------- M: microphone
// Records 1.5 s of quiet, beeps, records 3 s of speech, beeps, judges, plays it back.
static size_t recordInto(int16_t *dst, size_t samples, uint64_t &sumSq, Stats &st) {
  static int16_t frame[FRAME_SAMPLES];
  size_t got = 0;
  while (got < samples) {
    size_t want = samples - got;
    if (want > FRAME_SAMPLES) want = FRAME_SAMPLES;
    const size_t n = audioRead(dst ? dst + got : frame, want, 200);
    if (n == 0) break;
    accumulate(dst ? dst + got : frame, n, sumSq, st);
    got += n;
  }
  return got;
}

static void beep() {
  static const CueNote n[] = { {1046, 120, 160} };
  cuePlay(n, 1);
}

static void testMic() {
  if (!s_audioOk) { say("[RESULT] MIC FAIL audio_init"); return; }
  const size_t quietN = SAMPLE_RATE_HZ * 3 / 2, speechN = SAMPLE_RATE_HZ * 3;
  int16_t *rec = static_cast<int16_t *>(heap_caps_malloc(speechN * sizeof(int16_t), MALLOC_CAP_8BIT));
  if (!rec) { say("[RESULT] MIC FAIL no_memory"); return; }

  if (!audioStartCapture()) { free(rec); say("[RESULT] MIC FAIL start_capture"); return; }
  uint64_t junkSq = 0; Stats junk;
  recordInto(nullptr, SAMPLE_RATE_HZ / 4, junkSq, junk);   // filter and DC blocker settle

  say("[MIC] phase 1: stay quiet");
  uint64_t qSq = 0; Stats q;
  const size_t qGot = recordInto(nullptr, quietN, qSq, q);
  audioStopCapture();
  q.rms = qGot ? isqrt64(qSq / qGot) : 0;

  beep();
  say("[MIC] phase 2: speak or clap now");
  ledSet(LedMode::ON); ledUpdate();
  audioStartCapture();
  recordInto(nullptr, SAMPLE_RATE_HZ / 10, junkSq, junk);
  uint64_t sSq = 0; Stats s;
  const size_t sGot = recordInto(rec, speechN, sSq, s);
  audioStopCapture();
  ledSet(LedMode::OFF); ledUpdate();
  s.rms = sGot ? isqrt64(sSq / sGot) : 0;
  beep();

  say("[MIC] quiet  samples=%u rms=%lu peak=%ld min=%ld max=%ld", (unsigned)qGot,
      (unsigned long)q.rms, (long)q.peak, (long)q.minV, (long)q.maxV);
  say("[MIC] speech samples=%u rms=%lu peak=%ld min=%ld max=%ld", (unsigned)sGot,
      (unsigned long)s.rms, (long)s.peak, (long)s.minV, (long)s.maxV);

  // Pass rules: data arrives; it is not a constant (dead CLK/DATA reads as a flat line);
  // speech is at least 10 dB (x3.16) above the quiet floor and has a usable peak.
  const char *fail = nullptr;
  if (qGot < quietN / 2 || sGot < speechN / 2)            fail = "no_data";
  else if (s.maxV - s.minV < 8 && q.maxV - q.minV < 8)     fail = "flat_signal";
  else if (static_cast<uint64_t>(s.rms) * 100 < static_cast<uint64_t>(q.rms) * 316) fail = "no_level_change";
  else if (s.peak < 500)                                    fail = "too_quiet";
  if (fail) say("[RESULT] MIC FAIL %s", fail); else say("[RESULT] MIC PASS");

  // Playback: normalise the peak to about 0.6 FS (the level cue.cpp was validated at),
  // with at most x32 boost so a silent recording does not turn into loud noise.
  if (sGot) {
    int32_t gainQ8 = s.peak ? (19660 * 256) / s.peak : 256;
    if (gainQ8 > 32 * 256) gainQ8 = 32 * 256;
    for (size_t i = 0; i < sGot; ++i) {
      int32_t v = (static_cast<int32_t>(rec[i]) * gainQ8) >> 8;
      if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
      rec[i] = static_cast<int16_t>(v);
    }
    say("[MIC] playback, gain x%ld.%02ld", (long)(gainQ8 / 256), (long)((gainQ8 % 256) * 100 / 256));
    if (audioStartPlayback()) {
      size_t done = 0;
      while (done < sGot) {
        const size_t w = audioWrite(rec + done, sGot - done, 500);
        if (!w) break;
        done += w;
      }
      audioStopPlayback();
    }
  }
  free(rec);
}

// ---------------------------------------------------------------- P: power
static void powerInit() {
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << PIN_VBUS_DET;
  cfg.mode = GPIO_MODE_INPUT;
  ESP_ERROR_CHECK(gpio_config(&cfg));   // External 68k/100k divider, no internal pulls.
  adc_oneshot_unit_init_cfg_t unit = {};
  unit.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&unit, &s_adc) != ESP_OK) { s_adc = nullptr; return; }
  adc_oneshot_chan_cfg_t ch = {};
  ch.atten = ADC_ATTEN_DB_12;
  ch.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_oneshot_config_channel(s_adc, ADC_CHANNEL_1, &ch);
  adc_cali_curve_fitting_config_t cal = {};
  cal.unit_id = ADC_UNIT_1;
  cal.chan = ADC_CHANNEL_1;
  cal.atten = ch.atten;
  cal.bitwidth = ch.bitwidth;
  if (adc_cali_create_scheme_curve_fitting(&cal, &s_cali) != ESP_OK) s_cali = nullptr;
}

static int batteryMv() {
  if (!s_adc || !s_cali) return -1;
  int raw = 0, total = 0, mv = 0;
  for (int i = 0; i < 16; ++i) {
    if (adc_oneshot_read(s_adc, ADC_CHANNEL_1, &raw) != ESP_OK) return -1;
    total += raw;
  }
  if (adc_cali_raw_to_voltage(s_cali, (total + 8) / 16, &mv) != ESP_OK) return -1;
  return mv * 2;   // VBAT -> 1M -> GPIO1 -> 1M -> GND
}

static void testPower() {
  int minMv = 100000, maxMv = -1;
  int usbHigh = 0;
  for (int i = 0; i < 5; ++i) {
    const int mv = batteryMv();
    const int usb = gpio_get_level(static_cast<gpio_num_t>(PIN_VBUS_DET));
    usbHigh += usb;
    if (mv < minMv) minMv = mv;
    if (mv > maxMv) maxMv = mv;
    say("[PWR] sample %d VBAT=%d mV USB=%d", i + 1, mv, usb);
    appDelay(1000);
  }
  // The board is powered over USB during this test, so VBUS detection must read high.
  say("[RESULT] USB %s", usbHigh == 5 ? "PASS" : "FAIL");
  // Battery voltage is only meaningful with a battery attached; the script judges it.
  say("[RESULT] VBAT min=%d max=%d", minMv, maxMv);
}

// ---------------------------------------------------------------- main
extern "C" void app_main() {
  usb_serial_jtag_driver_config_t ucfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&ucfg));
  usb_serial_jtag_vfs_use_driver();

  gpio_set_direction(static_cast<gpio_num_t>(PIN_AMP_SD), GPIO_MODE_OUTPUT);
  gpio_set_level(static_cast<gpio_num_t>(PIN_AMP_SD), 0);
  ledBegin();
  s_btn.begin(PIN_PTT_BUTTON, BUTTON_DEBOUNCE_MS);
  s_audioOk = audioBegin();
  cueBegin();
  powerInit();

  say("[HWTEST] READY %s audio=%d", HWTEST_VERSION, s_audioOk ? 1 : 0);
  for (;;) {
    uint8_t c = 0;
    if (usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(100)) != 1) continue;
    switch (c) {
      case '?': say("[HWTEST] READY %s audio=%d", HWTEST_VERSION, s_audioOk ? 1 : 0); break;
      case 'L': testLed();     say("[DONE] L"); break;
      case 'S': testSpeaker(); say("[DONE] S"); break;
      case 'B': testButton();  say("[DONE] B"); break;
      case 'M': testMic();     say("[DONE] M"); break;
      case 'P': testPower();   say("[DONE] P"); break;
      default: break;          // newlines and anything else
    }
  }
}
