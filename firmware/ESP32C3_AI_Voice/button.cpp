#include "platform.h"
#include "button.h"
#include "driver/gpio.h"
#include "esp_err.h"

void Button::begin(uint8_t pin, uint16_t debounceMs) {
  _pin        = pin;
  _debounceMs = debounceMs;
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << _pin;
  cfg.mode = GPIO_MODE_INPUT;
  cfg.pull_up_en = GPIO_PULLUP_DISABLE; // External 100k pull-up on the PCB.
  ESP_ERROR_CHECK(gpio_config(&cfg));
  _raw = _stable = gpio_get_level(static_cast<gpio_num_t>(_pin));
  _lastEdgeMs = appMillis();
  clearEvents();
}

void Button::update() {
  int now = gpio_get_level(static_cast<gpio_num_t>(_pin));

  if (now != _raw) {          // 电平抖了,重新计时
    _raw = now;
    _lastEdgeMs = appMillis();
    return;
  }

  if (now == _stable) return;                      // 已经稳定在这个电平
  if (appMillis() - _lastEdgeMs < _debounceMs) return; // 还没稳够时间

  _stable = now;
  if (_stable == 0) _press = true;
  else                _release = true;
}

bool Button::tookPress() {
  if (!_press) return false;
  _press = false;
  return true;
}

bool Button::tookRelease() {
  if (!_release) return false;
  _release = false;
  return true;
}
