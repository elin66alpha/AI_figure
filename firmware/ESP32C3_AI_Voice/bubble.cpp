#include "bubble.h"
#include "config.h"
#include "cue.h"

// ---------------------------------------------------------------- 可调参数
// 音量:比提示音(CUE_AMP=160)小一截 —— 这是背景里的"我在想",不是通知。
#define BUBBLE_AMP          110
#define BUBBLE_F_MIN        170     // 起始频率范围 Hz。低 = 大泡 = "咕"
#define BUBBLE_F_SPAN       260
#define BUBBLE_RISE_MIN     140     // 结束频率 = 起始 × (RISE/100),即上扬 40%~110%
#define BUBBLE_RISE_SPAN    70
#define BUBBLE_MS_MIN       55      // 单个气泡时长
#define BUBBLE_MS_SPAN      55
#define BUBBLE_ATTACK       48      // 3 ms 起音,防"啪"
#define BUBBLE_PER_BURST_MIN 3      // 一串几个泡
#define BUBBLE_PER_BURST_SPAN 4
#define BUBBLE_GAP_IN_MS    12      // 串内间隔 12~50 ms
#define BUBBLE_GAP_IN_SPAN  38
#define BUBBLE_GAP_OUT_MS   160     // 串间间隔 160~420 ms
#define BUBBLE_GAP_OUT_SPAN 260
#define BUBBLE_LEAD_MS      60      // bubbleStart 后先静一下,和 turn_end 的按键动作隔开

// ---------------------------------------------------------------- 状态
static bool     s_active = false;
static uint32_t s_rng    = 0x9E3779B9u;

// 当前气泡
static uint32_t s_len    = 0;       // 气泡总样本数;0 = 在间隔里
static uint32_t s_pos    = 0;
static uint32_t s_phase  = 0;       // Q32
static uint32_t s_step   = 0;       // Q32 每样本相位增量(随时间线性增大 = 音调上扬)
static uint32_t s_dstep  = 0;
static int32_t  s_env    = 0;       // Q15 包络
static int32_t  s_decay  = 0;       // Q15 每样本衰减系数
static int32_t  s_amp    = 0;       // 0..255

// 间隔 / 串
static uint32_t s_gapLeft   = 0;    // 还要静多少样本
static uint8_t  s_burstLeft = 0;    // 本串还剩几个泡

static inline uint32_t rnd() {        // xorshift32
  uint32_t x = s_rng;
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  return s_rng = x;
}
static inline uint32_t rndSpan(uint32_t span) { return span ? rnd() % span : 0; }
static inline uint32_t msToSamples(uint32_t ms) { return ms * SAMPLE_RATE_HZ / 1000u; }

static void newBubble() {
  const uint32_t f0   = BUBBLE_F_MIN + rndSpan(BUBBLE_F_SPAN);
  const uint32_t f1   = f0 * (BUBBLE_RISE_MIN + rndSpan(BUBBLE_RISE_SPAN)) / 100u;
  s_len   = msToSamples(BUBBLE_MS_MIN + rndSpan(BUBBLE_MS_SPAN));
  s_pos   = 0;
  s_phase = 0;
  // 64 位除法:每个气泡一次,不在逐样本路径上
  s_step  = (uint32_t)(((uint64_t)f0 << 32) / SAMPLE_RATE_HZ);
  const uint32_t step1 = (uint32_t)(((uint64_t)f1 << 32) / SAMPLE_RATE_HZ);
  s_dstep = (step1 - s_step) / s_len;
  s_env   = 32767;
  // 衰减:气泡结束时包络降到约 2%(ln(0.02) ≈ -4),结尾直接归零也听不出"咔"。
  // 每样本系数 ≈ 1 - 4/len,Q15 下 = 32768 - 131072/len。
  s_decay = 32768 - (int32_t)(131072u / s_len);
  s_amp   = BUBBLE_AMP * (60 + (int32_t)rndSpan(41)) / 100;   // 每个泡响度 60%~100%
}

static void scheduleGap() {
  s_len = 0;
  if (s_burstLeft > 0) {
    s_burstLeft--;
    s_gapLeft = msToSamples(BUBBLE_GAP_IN_MS + rndSpan(BUBBLE_GAP_IN_SPAN));
  } else {
    s_burstLeft = BUBBLE_PER_BURST_MIN + rndSpan(BUBBLE_PER_BURST_SPAN) - 1;
    s_gapLeft = msToSamples(BUBBLE_GAP_OUT_MS + rndSpan(BUBBLE_GAP_OUT_SPAN));
  }
}

// ---------------------------------------------------------------- 对外
void bubbleStart() {
  s_rng ^= millis() | 1u;             // 每次听起来不一样
  s_active    = true;
  s_len       = 0;
  s_burstLeft = BUBBLE_PER_BURST_MIN + rndSpan(BUBBLE_PER_BURST_SPAN);
  s_gapLeft   = msToSamples(BUBBLE_LEAD_MS);
}

void bubbleStop()   { s_active = false; s_len = 0; }
bool bubbleActive() { return s_active; }
bool bubbleInGap()  { return !s_active || s_len == 0; }

void bubbleFill(int16_t *dst, size_t n) {
  const int16_t *lut = cueSineTable();
  for (size_t i = 0; i < n; i++) {
    if (!s_active) { dst[i] = 0; continue; }

    if (s_len == 0) {                        // 间隔里
      dst[i] = 0;
      if (s_gapLeft > 0) s_gapLeft--;
      if (s_gapLeft == 0) newBubble();
      continue;
    }

    int32_t s = lut[s_phase >> 24];                     // -32767..32767
    s = (s * s_env) >> 15;
    s = (s * s_amp) >> 8;
    if (s_pos < BUBBLE_ATTACK) s = s * (int32_t)s_pos / BUBBLE_ATTACK;
    dst[i] = (int16_t)s;

    s_phase += s_step;
    s_step  += s_dstep;
    s_env    = (s_env * s_decay) >> 15;
    if (++s_pos >= s_len) scheduleGap();     // 包络已衰减到 ~2%,在这里收不会"啪"
  }
}
