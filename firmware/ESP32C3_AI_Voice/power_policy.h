#pragma once
#include <stdint.h>
#include "config.h"

// Pure policy, independent of ADC/GPIO drivers, so transitions can be tested.
enum class SleepReason : uint8_t { NONE, IDLE, LOW_BATTERY };
class PowerPolicy {
 public:
  void begin(uint32_t now) { lastActivity_ = now; lowPending_ = false; }
  void activity(uint32_t now) { lastActivity_ = now; }
  static bool canResume(bool lowBatterySleep, bool usb, int batteryMv) {
    return usb || !lowBatterySleep || batteryMv >= BAT_RESUME_MV;
  }
  SleepReason update(uint32_t now, bool usb, bool valid, int batteryMv, bool busy) {
    if (busy) activity(now);
    if (usb || !valid || batteryMv >= BAT_LOW_MV) {
      lowPending_ = false;
    } else if (!lowPending_) {
      lowPending_ = true;
      lowSince_ = now;
    } else if (now - lowSince_ >= BAT_LOW_CONFIRM_MS) {
      return SleepReason::LOW_BATTERY;
    }
    return now - lastActivity_ >= IDLE_SLEEP_MS ? SleepReason::IDLE : SleepReason::NONE;
  }
 private:
  uint32_t lastActivity_ = 0, lowSince_ = 0;
  bool lowPending_ = false;
};
