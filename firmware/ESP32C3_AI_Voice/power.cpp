#include "platform.h"
#include "power.h"
#include "power_policy.h"
#include "audio_io.h"
#include "net_wifi.h"
#include "net_ws.h"
#include "net_prov.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_sleep.h"
#include "esp_attr.h"

static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_calibration;
static PowerPolicy s_policy;
static int s_batteryMv = -1;
static bool s_valid = false, s_usb = false, s_usbRaw = false, s_woke = false;
static uint32_t s_sampleAt = 0, s_usbEdgeAt = 0;
RTC_DATA_ATTR static SleepReason s_sleepReason = SleepReason::NONE;

static gpio_num_t pin(int p) { return static_cast<gpio_num_t>(p); }
static void outputOff(int p, int level) {
  gpio_reset_pin(pin(p)); // Disconnect a previously routed I2S clock before holding LOW.
  gpio_set_level(pin(p), level);
  gpio_set_direction(pin(p), GPIO_MODE_OUTPUT);
  gpio_hold_dis(pin(p));
}
static void input(int p) {
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << p;
  cfg.mode = GPIO_MODE_INPUT;
  // PTT has an external pull-up; VBUS_DET has a 68k/100k divider.
  cfg.pull_up_en = GPIO_PULLUP_DISABLE;
  cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
  ESP_ERROR_CHECK(gpio_config(&cfg));
}
static bool sampleBattery() {
  if (!s_adc || !s_calibration) return false;
  int raw = 0, total = 0, mv = 0;
  if (adc_oneshot_read(s_adc, ADC_CHANNEL_1, &raw) != ESP_OK) return false;
  for (int i = 0; i < 16; ++i) {
    if (adc_oneshot_read(s_adc, ADC_CHANNEL_1, &raw) != ESP_OK) return false;
    total += raw;
  }
  if (adc_cali_raw_to_voltage(s_calibration, (total + 8) / 16, &mv) != ESP_OK) return false;
  s_batteryMv = mv * 2; // VBAT -> 1M -> GPIO1 -> 1M -> GND.
  return true;
}
static void updateUsb() {
  const uint32_t now = appMillis();
  bool raw = gpio_get_level(pin(PIN_VBUS_DET)) != 0;
  if (raw != s_usbRaw) { s_usbRaw = raw; s_usbEdgeAt = now; }
  if (now - s_usbEdgeAt >= VBUS_DEBOUNCE_MS) s_usb = raw;
}
[[noreturn]] static void sleepNow(SleepReason reason) {
  printf("[POWER] sleep=%s VBAT=%d mV USB=%d; wake=PTT only\n",
         reason == SleepReason::LOW_BATTERY ? "low battery" : "idle", s_batteryMv, s_usb);
  audioCutPlayback();
  audioStopCapture();
  wsClose("deep sleep");
  provStop();
  netWifiStop();
  outputOff(PIN_AMP_SD, 0);
  outputOff(PIN_STATUS_LED, 1);
  outputOff(PIN_MIC_CLK, 0);
  // Level wake must be armed after release, otherwise a held PTT creates a boot loop.
  uint32_t releasedAt = appMillis();
  while (appMillis() - releasedAt < BUTTON_DEBOUNCE_MS) {
    if (gpio_get_level(pin(PIN_PTT_BUTTON)) == 0) releasedAt = appMillis();
    appDelay(5);
  }
  s_sleepReason = reason;
  ESP_ERROR_CHECK(esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL));
  ESP_ERROR_CHECK(esp_sleep_enable_gpio_wakeup_on_hp_periph_powerdown(
      1ULL << PIN_PTT_BUTTON, ESP_GPIO_WAKEUP_GPIO_LOW));
  ESP_ERROR_CHECK(gpio_hold_en(pin(PIN_AMP_SD)));
  ESP_ERROR_CHECK(gpio_hold_en(pin(PIN_STATUS_LED)));
  ESP_ERROR_CHECK(gpio_hold_en(pin(PIN_MIC_CLK)));
  gpio_deep_sleep_hold_en();
  esp_deep_sleep_start();
}
bool powerBegin() {
  s_woke = (esp_sleep_get_wakeup_causes() & (1u << ESP_SLEEP_WAKEUP_GPIO)) != 0;
  outputOff(PIN_AMP_SD, 0);
  outputOff(PIN_STATUS_LED, 1);
  outputOff(PIN_MIC_CLK, 0);
  gpio_deep_sleep_hold_dis();
  input(PIN_PTT_BUTTON);
  input(PIN_VBUS_DET);
  s_usbRaw = gpio_get_level(pin(PIN_VBUS_DET)) != 0;
  s_usbEdgeAt = appMillis();
  adc_oneshot_unit_init_cfg_t unit = {};
  unit.unit_id = ADC_UNIT_1;
  ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit, &s_adc));
  adc_oneshot_chan_cfg_t channel = {};
  channel.atten = ADC_ATTEN_DB_12;
  channel.bitwidth = ADC_BITWIDTH_DEFAULT;
  ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc, ADC_CHANNEL_1, &channel));
  adc_cali_curve_fitting_config_t calibration = {};
  calibration.unit_id = ADC_UNIT_1;
  calibration.chan = ADC_CHANNEL_1;
  calibration.atten = channel.atten;
  calibration.bitwidth = channel.bitwidth;
  esp_err_t e = adc_cali_create_scheme_curve_fitting(&calibration, &s_calibration);
  if (e != ESP_OK) printf("[POWER] ADC calibration unavailable: %s\n", esp_err_to_name(e));
  appDelay(250); // Existing 1M/1M/100nF divider has a 50 ms time constant.
  updateUsb();
  s_valid = sampleBattery();
  s_sampleAt = appMillis();
  s_policy.begin(s_sampleAt);
  if (!s_valid && !s_usb) sleepNow(SleepReason::LOW_BATTERY);
  if (s_valid && !PowerPolicy::canResume(s_woke && s_sleepReason == SleepReason::LOW_BATTERY,
                                        s_usb, s_batteryMv)) {
    sleepNow(SleepReason::LOW_BATTERY);
  }
  // Confirm a low battery before starting WiFi or playing the boot cue.
  while (!s_usb && s_valid && s_batteryMv < BAT_LOW_MV) {
    powerUpdate(false);
    appDelay(10);
  }
  s_sleepReason = SleepReason::NONE;
  // Consume the wake press; the next deliberate press is the first record event.
  if (s_woke) {
    while (gpio_get_level(pin(PIN_PTT_BUTTON)) == 0) {
      powerUpdate(false);
      appDelay(10);
    }
    appDelay(BUTTON_DEBOUNCE_MS);
  }
  powerNoteActivity();
  printf("[POWER] VBAT=%d mV USB=%d wake=%s\n", s_batteryMv, s_usb, s_woke ? "PTT" : "boot");
  return true;
}
void powerUpdate(bool busy) {
  updateUsb();
  const uint32_t now = appMillis();
  if (now - s_sampleAt >= BAT_SAMPLE_MS) {
    s_sampleAt = now;
    s_valid = sampleBattery();
    if (!s_valid && !s_usb) {
      printf("[POWER] Battery ADC failed; stopping battery-only operation\n");
      sleepNow(SleepReason::LOW_BATTERY);
    }
  }
  const SleepReason reason = s_policy.update(now, s_usb, s_valid, s_batteryMv, busy);
  if (reason != SleepReason::NONE) sleepNow(reason);
}
void powerNoteActivity() { s_policy.activity(appMillis()); }
int powerBatteryMv() { return s_valid ? s_batteryMv : -1; }
bool powerUsbPresent() { return s_usb; }
bool powerWokeFromSleep() { return s_woke; }
