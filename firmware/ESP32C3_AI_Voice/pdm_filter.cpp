#include "pdm_filter.h"
#include "config.h"
#include <string.h>
#include <limits.h>

// Hamming-windowed sinc, 63 taps, 7 kHz cutoff at 32 kHz, Q15 sum=32768.
static constexpr int16_t kFir[63] = {
  -26, -11, 27, 27, -25, -51, 13, 83, 20, -113, -82, 125, 174, -94, -283, 0, 385, 174, -438, -430, 392, 756, -186, -1118, -259, 1475, 1093, -1777, -2833, 1979, 10216, 14342, 10216, 1979, -2833, -1777, 1093, 1475, -259, -1118, -186, 756, 392, -430, -438, 174, 385, 0, -283, -94, 174, 125, -82, -113, 20, 83, 13, -51, -25, 27, 27, -11, -26
};
static_assert(MIC_PDM_CLK_HZ / MIC_CIC_DECIMATION / 2 == SAMPLE_RATE_HZ);
static int16_t saturate(int64_t x) {
  return x > INT16_MAX ? INT16_MAX : x < INT16_MIN ? INT16_MIN : static_cast<int16_t>(x);
}
void PdmFilter::reset() {
  memset(integrator_, 0, sizeof(integrator_));
  memset(comb_, 0, sizeof(comb_));
  memset(history_, 0, sizeof(history_));
  bitCount_ = firPosition_ = phase_ = 0;
  dcX_ = dcY_ = 0;
}
size_t PdmFilter::process(const uint16_t *words, size_t count, int16_t *pcm, size_t capacity) {
  size_t out = 0;
  // Each group of eight words creates one PCM sample. The caller limits
  // count to capacity*8, so neither input nor output is silently discarded.
  if (!words || !pcm || count > capacity * MIC_PDM_WORDS_PER_PCM) return 0;
  for (size_t w = 0; w < count; ++w) {
    for (int b = 15; b >= 0; --b) {
      // Unsigned modular integration is intentional; signed overflow is undefined.
      integrator_[0] += (words[w] & (1u << b)) ? 1u : UINT32_MAX;
      integrator_[1] += integrator_[0];
      integrator_[2] += integrator_[1];
      if (++bitCount_ != MIC_CIC_DECIMATION) continue;
      bitCount_ = 0;
      uint32_t v = integrator_[2];
      for (unsigned j = 0; j < 3; ++j) {
        uint32_t next = v - comb_[j];
        comb_[j] = v;
        v = next;
      }
      // CIC gain is 64^3. Map density [-1,1] to signed PCM scale.
      int32_t signedValue;
      memcpy(&signedValue, &v, sizeof(v));
      history_[firPosition_] = signedValue / 8;
      firPosition_ = (firPosition_ + 1) % 63;
      phase_ ^= 1;
      if (phase_) continue;
      int64_t acc = 0;
      unsigned pos = firPosition_;
      for (unsigned j = 0; j < 63; ++j) {
        pos = pos == 0 ? 62 : pos - 1;
        acc += static_cast<int64_t>(history_[pos]) * kFir[j];
      }
      int32_t sample = static_cast<int32_t>(acc / 32768);
      if (DC_BLOCKER_ON) {
        int32_t y = sample - dcX_ + static_cast<int32_t>(static_cast<int64_t>(dcY_) * 2036 / 2048);
        dcX_ = sample;
        dcY_ = y;
        sample = y;
      }
      pcm[out++] = saturate(static_cast<int64_t>(sample) * MIC_GAIN_Q8 / 256);
    }
  }
  return out;
}
