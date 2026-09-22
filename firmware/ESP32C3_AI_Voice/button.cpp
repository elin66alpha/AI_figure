#include "button.h"

void Button::begin(uint8_t pin, uint16_t debounceMs) {
  _pin        = pin;
  _debounceMs = debounceMs;
  pinMode(_pin, INPUT_PULLUP);
  _raw = _stable = digitalRead(_pin);
  _lastEdgeMs = millis();
  clearEvents();
}

void Button::update() {
  int now = digitalRead(_pin);

  if (now != _raw) {          // 电平抖了,重新计时
    _raw = now;
    _lastEdgeMs = millis();
    return;
  }

  if (now == _stable) return;                      // 已经稳定在这个电平
  if (millis() - _lastEdgeMs < _debounceMs) return; // 还没稳够时间

  _stable = now;
  if (_stable == LOW) _press = true;
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
