#pragma once
#include <stddef.h>
#include <stdint.h>

// ESP32-C3 supplies raw PDM. CIC3 /64 and FIR /2 produce 16 kHz PCM.
// Input words are consumed MSB first (ESP-IDF PDM RX wire order).
class PdmFilter {
 public:
  void reset();
  size_t process(const uint16_t *words, size_t count, int16_t *pcm, size_t capacity);
 private:
  uint32_t integrator_[3] = {}, comb_[3] = {};
  int32_t history_[63] = {};
  unsigned bitCount_ = 0, firPosition_ = 0, phase_ = 0;
  int32_t dcX_ = 0, dcY_ = 0;
};
