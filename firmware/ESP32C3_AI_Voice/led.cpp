#include "platform.h"
#include "led.h"
#include "config.h"
#include "driver/gpio.h"
#include "esp_err.h"

static LedMode  s_mode   = LedMode::OFF;
static uint32_t s_phase0 = 0;     // 本模式起点,换模式时重置,免得相位跳变

void ledBegin() {
  ESP_ERROR_CHECK(gpio_set_level(static_cast<gpio_num_t>(PIN_STATUS_LED), !LED_ON_LEVEL));
  ESP_ERROR_CHECK(gpio_set_direction(static_cast<gpio_num_t>(PIN_STATUS_LED), GPIO_MODE_OUTPUT));
  gpio_set_level(static_cast<gpio_num_t>(PIN_STATUS_LED), !LED_ON_LEVEL);
  s_mode = LedMode::OFF;
  s_phase0 = appMillis();
}

void ledSet(LedMode m) {
  if (m == s_mode) return;
  s_mode = m;
  s_phase0 = appMillis();
}

void ledUpdate() {
  const uint32_t t = appMillis() - s_phase0;
  bool on = false;

  switch (s_mode) {
    case LedMode::OFF:        on = false;                    break;
    case LedMode::ON:         on = true;                     break;
    case LedMode::HEARTBEAT:  on = (t % 3000) < 60;          break;
    case LedMode::BLINK_SLOW: on = (t % 1000) < 500;         break;
    case LedMode::BLINK_FAST: on = (t %  240) < 120;         break;
    case LedMode::DOUBLE:     { uint32_t k = t % 1500; on = k < 80 || (k >= 240 && k < 320); } break;
  }

  gpio_set_level(static_cast<gpio_num_t>(PIN_STATUS_LED), on ? LED_ON_LEVEL : !LED_ON_LEVEL);
}
