#include "led.h"
#include "config.h"

static LedMode  s_mode   = LedMode::OFF;
static uint32_t s_phase0 = 0;     // 本模式起点,换模式时重置,免得相位跳变

void ledBegin() {
  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, !LED_ON_LEVEL);
  s_mode = LedMode::OFF;
  s_phase0 = millis();
}

void ledSet(LedMode m) {
  if (m == s_mode) return;
  s_mode = m;
  s_phase0 = millis();
}

void ledUpdate() {
  const uint32_t t = millis() - s_phase0;
  bool on = false;

  switch (s_mode) {
    case LedMode::OFF:        on = false;                    break;
    case LedMode::ON:         on = true;                     break;
    case LedMode::HEARTBEAT:  on = (t % 3000) < 60;          break;
    case LedMode::BLINK_SLOW: on = (t % 1000) < 500;         break;
    case LedMode::BLINK_FAST: on = (t %  240) < 120;         break;
    case LedMode::DOUBLE:     { uint32_t k = t % 1500; on = k < 80 || (k >= 240 && k < 320); } break;
  }

  digitalWrite(PIN_STATUS_LED, on ? LED_ON_LEVEL : !LED_ON_LEVEL);
}
