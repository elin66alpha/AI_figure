#pragma once
#include <stdint.h>
#include <stddef.h>

// GPIO3 按键,外部 100k 上拉,按下接 GND。按下 = 0。
// 软件去抖,边沿事件读一次就消费掉。
class Button {
public:
  void begin(uint8_t pin, uint16_t debounceMs);
  void update();                                   // 在主循环里高频调用

  bool tookPress();                               // 消费一次"按下"事件
  bool tookRelease();                              // 消费一次"松开"事件
  void clearEvents() { _press = _release = false; }

private:
  uint8_t  _pin        = 0;
  uint16_t _debounceMs = BUTTON_DEBOUNCE_MS_FALLBACK;
  int      _stable     = 1;
  int      _raw        = 1;
  uint32_t _lastEdgeMs = 0;
  bool     _press      = false;
  bool     _release    = false;

  static const uint16_t BUTTON_DEBOUNCE_MS_FALLBACK = 25;
};
