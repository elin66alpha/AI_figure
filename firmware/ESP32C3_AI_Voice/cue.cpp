#include "cue.h"
#include "config.h"
#include "audio_io.h"
#include <math.h>

#define CUE_LUT_LEN   256
#define CUE_RAMP      64      // 4 ms 的进出包络。不做的话每个音头尾都"啪"一声

// Stage 2 实测:幅度 0.6 FS * 增益 100/256 ≈ 0.055 W,离 brownout 很远。
// 这里的 160/255 ≈ 0.63 FS,和那次验证过的电平基本一致,别往上加。
#define CUE_AMP       160

static int16_t s_lut[CUE_LUT_LEN];
static bool    s_ready = false;

void cueBegin() {
  if (s_ready) return;
  for (int i = 0; i < CUE_LUT_LEN; i++) {
    // 参数最大 2π,远小于 newlib 走 Payne-Hanek 的 201 阈值;而且只跑这一次。
    s_lut[i] = (int16_t)lroundf(32767.0f * sinf(2.0f * (float)PI * (float)i / (float)CUE_LUT_LEN));
  }
  s_ready = true;
}

const int16_t *cueSineTable() {
  cueBegin();
  return s_lut;
}

void cuePlay(const CueNote *notes, uint8_t count) {
  if (!notes || count == 0) return;
  cueBegin();
  if (!audioStartPlayback(true)) return;

  static int16_t buf[FRAME_SAMPLES];

  for (uint8_t k = 0; k < count; k++) {
    const uint32_t total = (uint32_t)notes[k].ms * SAMPLE_RATE_HZ / 1000u;
    // Q32 相位步长:每个样本前进 hz/SR 圈。整数除法,无浮点。
    const uint32_t step  = (uint32_t)(((uint64_t)notes[k].hz << 32) / SAMPLE_RATE_HZ);
    uint32_t done = 0;

    while (done < total) {
      uint32_t m = total - done;
      if (m > (uint32_t)FRAME_SAMPLES) m = FRAME_SAMPLES;

      for (uint32_t i = 0; i < m; i++) {
        const uint32_t idx = done + i;
        int32_t s = 0;
        if (notes[k].hz) {
          // 相位直接由样本序号算出(无符号乘法自然对 2^32 取模),
          // 这样即使 audioWrite 少写了几个样本,相位也不会跳。
          s = s_lut[(uint32_t)(step * idx) >> 24];
        }
        s = (s * (int32_t)notes[k].amp) >> 8;

        const uint32_t fromEnd = total - idx;
        if (idx < CUE_RAMP)          s = s * (int32_t)idx     / CUE_RAMP;
        else if (fromEnd < CUE_RAMP) s = s * (int32_t)fromEnd / CUE_RAMP;

        buf[i] = (int16_t)s;
      }

      size_t w = audioWrite(buf, m, 200);
      if (w == 0) break;          // TX 卡住,别死等
      done += w;
    }
  }

  audioStopPlayback();            // 内含补静音 -> drain -> 关功放
}

// ---------------------------------------------------------------- 预定义
void cueBoot() {
  static const CueNote n[] = { {660, 90, CUE_AMP}, {880, 110, CUE_AMP} };
  cuePlay(n, 2);
}

void cueLinkUp() {
  static const CueNote n[] = { {1046, 110, CUE_AMP} };
  cuePlay(n, 1);
}

void cueLinkDown() {
  static const CueNote n[] = { {880, 90, CUE_AMP}, {587, 130, CUE_AMP} };
  cuePlay(n, 2);
}

void cueError() {
  static const CueNote n[] = {
    {330, 110, CUE_AMP}, {0, 70, 0},
    {330, 110, CUE_AMP}, {0, 70, 0},
    {330, 110, CUE_AMP},
  };
  cuePlay(n, 5);
}
