#pragma once
#include <Arduino.h>

// 板载 LED 状态指示(GPIO8,低电平点亮)。
//
// 不接串口的时候,这是唯一能看出设备在干嘛的东西。全程非阻塞:
// ledSet() 只改目标状态,真正的闪烁由 loop 里的 ledUpdate() 按 millis() 推进。
// **不要在这里 delay()** —— 它和 16 kHz 的音频循环共用同一个线程。

enum class LedMode : uint8_t {
  OFF,          // 灭
  ON,           // 常亮        —— 录音中 / 播放中
  HEARTBEAT,    // 每 3 s 闪一下 —— IDLE,一切正常
  BLINK_SLOW,   // 500 ms      —— ERROR:WiFi 或 WS 断了,正在重连
  BLINK_FAST,   // 120 ms      —— 连接过程中 / WAITING 等服务器
};

void ledBegin();
void ledSet(LedMode m);
void ledUpdate();     // 每次 loop 都调一次
