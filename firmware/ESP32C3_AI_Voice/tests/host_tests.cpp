#include "../power_policy.h"
#include "../pdm_filter.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>
#include <algorithm>

static void testPower() {
  PowerPolicy p;
  p.begin(0);
  assert(p.update(0, false, true, 3599, false) == SleepReason::NONE);
  assert(p.update(2999, false, true, 3599, true) == SleepReason::NONE);
  assert(p.update(3000, false, true, 3599, true) == SleepReason::LOW_BATTERY);
  p.begin(0);
  p.update(0, false, true, 3500, false);
  assert(p.update(2500, true, true, 3500, false) == SleepReason::NONE);
  assert(p.update(3000, false, true, 3500, false) == SleepReason::NONE);
  assert(p.update(5999, false, true, 3500, false) == SleepReason::NONE);
  assert(p.update(6000, false, true, 3500, false) == SleepReason::LOW_BATTERY);
  p.begin(0);
  p.update(0, false, true, 3500, false);
  p.update(2999, false, true, 3600, false);
  assert(p.update(3000, false, true, 3500, false) == SleepReason::NONE);
  assert(p.update(5999, false, false, 3500, false) == SleepReason::NONE);
  assert(p.update(6000, false, true, 3500, false) == SleepReason::NONE);
  assert(!PowerPolicy::canResume(true, false, 3799));
  assert(PowerPolicy::canResume(true, false, 3800));
  assert(PowerPolicy::canResume(true, true, 3000));
  assert(PowerPolicy::canResume(false, false, 3700));
  p.begin(0);
  assert(p.update(IDLE_SLEEP_MS - 1, true, true, 4200, false) == SleepReason::NONE);
  assert(p.update(IDLE_SLEEP_MS, true, true, 4200, false) == SleepReason::IDLE);
  p.begin(0);
  p.activity(100);
  assert(p.update(IDLE_SLEEP_MS, false, true, 3700, false) == SleepReason::NONE);
  assert(p.update(IDLE_SLEEP_MS + 100, false, true, 3700, false) == SleepReason::IDLE);
  p.begin(0);
  assert(p.update(IDLE_SLEEP_MS + 1, false, true, 3700, true) == SleepReason::NONE);
  const uint32_t nearWrap = UINT32_MAX - 1000;
  p.begin(nearWrap);
  p.update(nearWrap, false, true, 3500, false);
  assert(p.update(nearWrap + 3000u, false, true, 3500, false) == SleepReason::LOW_BATTERY);
  p.begin(nearWrap);
  assert(p.update(nearWrap + IDLE_SLEEP_MS, false, true, 3800, false) == SleepReason::IDLE);
}
static std::vector<uint16_t> pdm(double frequency, double amplitude, double bias = 0) {
  const size_t samples = 8000;
  std::vector<uint16_t> words(samples * MIC_PDM_WORDS_PER_PCM, 0);
  double error = 0;
  size_t bit = 0;
  for (auto &word : words) {
    for (int b = 15; b >= 0; --b, ++bit) {
      double target = bias + amplitude * std::sin(6.283185307179586 * frequency * bit / MIC_PDM_CLK_HZ);
      error += target;
      bool one = error >= 0;
      error -= one ? 1 : -1;
      if (one) word |= static_cast<uint16_t>(1u << b);
    }
  }
  return words;
}
static std::vector<int16_t> decode(const std::vector<uint16_t> &words, bool fragmented) {
  PdmFilter filter;
  filter.reset();
  std::vector<int16_t> result(words.size() / 8);
  if (!fragmented) {
    assert(filter.process(words.data(), words.size(), result.data(), result.size()) == result.size());
  } else {
    size_t in = 0, out = 0;
    while (in < words.size()) {
      // Deliberately split in the middle of a CIC/FIR group.
      size_t n = std::min(static_cast<size_t>(13 + in % 71), words.size() - in);
      int16_t block[16];
      size_t got = filter.process(words.data() + in, n, block, 16);
      std::copy(block, block + got, result.begin() + out);
      in += n;
      out += got;
    }
    assert(out == result.size());
  }
  return result;
}
static double rms(const std::vector<int16_t> &pcm) {
  double sum = 0;
  for (size_t i = 1000; i < pcm.size(); ++i) sum += double(pcm[i]) * pcm[i];
  return std::sqrt(sum / (pcm.size() - 1000));
}
static void testPdm() {
  auto words = pdm(1000, 0.4);
  auto pcm = decode(words, false);
  assert(pcm == decode(words, true));
  double pass = rms(pcm);
  assert(pass > 8500 && pass < 10000);
  double reject = rms(decode(pdm(10000, 0.4), false));
  assert(reject < pass / 30); // >29.5 dB rejection before aliasing to 6 kHz.
  assert(rms(decode(pdm(0, 0), false)) < 2);
  assert(rms(decode(pdm(0, 0, 0.25), false)) < 10); // DC blocker settles.
  std::printf("PDM: 1kHz RMS=%.1f, 10kHz alias RMS=%.1f; chunk continuity passed\n", pass, reject);
}
int main() {
  testPower();
  testPdm();
  std::puts("Power: thresholds, USB bypass/unplug, confirmation reset, idle, rollover passed");
}
