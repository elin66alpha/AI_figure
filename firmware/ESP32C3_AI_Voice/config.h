#pragma once
// ESP32-C3 AI Voice — 全局硬件与音频常量
// 规格见 ../../AGENT.md。GPIO 号只在这里出现,别散到别处。

// ---------------------------------------------------------------- GPIO
#define PIN_I2S_BCLK    4    // 共享:INMP441 SCK + MAX98357A BCLK
#define PIN_I2S_WS      5    // 共享:INMP441 WS  + MAX98357A LRC
#define PIN_MIC_DATA    6    // INMP441 SD  -> ESP32   (I2S DIN)
#define PIN_AMP_DATA    7    // ESP32 -> MAX98357A DIN (I2S DOUT)
#define PIN_AMP_SD      10   // MAX98357A SD: LOW=关断, 3.3V=使能且选左声道
#define PIN_PTT_BUTTON  3    // 按键接 GND,INPUT_PULLUP,按下=LOW

// ---------------------------------------------------------------- 音频
#define SAMPLE_RATE_HZ      16000
// INMP441 需要 32-bit slot;MAX98357A 也接受 32-bit。
// 全双工共享时钟要求 TX/RX 配置完全一致,所以两边都用 STEREO 32-bit。
// BCLK = 16000 * 32 * 2 = 1.024 MHz

#define FRAME_SAMPLES       320   // 20 ms @16k — 单次 I2S 读写的粒度
                                  // 暂存缓冲 = 320 * 2 slot * 4 B = 2560 B

#define NET_CHUNK_SAMPLES   3200  // 200 ms @16k = 6400 B PCM16
                                  // 火山 ASR 明确要求 100~200ms/包,双向流式 200ms 最优

// ---------------------------------------------------------------- 麦克风增益
// INMP441 的 24-bit 采样左对齐在 32-bit slot 的 bit31..8。
//   >>16 = 1:1    >>14 = x4    >>11 = x32
// INMP441 实测偏小声。**11 是 2026-09-22 用 Stage 3 现场标定出来的值,不是猜的。**
// 改这个值等于改 ASR 的输入电平,改之前先用 Stage 3 重新量一遍。
#define MIC_SHIFT_DEFAULT   11

// 一阶高通,滤掉 INMP441 的直流偏置。对 ASR 识别率帮助明显。
#define DC_BLOCKER_DEFAULT  true

// ---------------------------------------------------------------- 输出限幅
// 0..256 的定点增益(256 = 原始音量)。
//
// !! 在 MAX98357A 的 VIN 上焊好 470µF~1000µF 电解电容之前,不要调高这个值 !!
// SuperMini 的 5V 脚经小肖特基从 USB VBUS 引来,电流余量有限;
// MAX98357A 推 4Ω 峰值 >1A,会把 5V 拉塌导致 brownout 重启,
// 而且症状看起来会像固件 bug。加了电容并实测稳定后再往上调。
#define OUTPUT_GAIN_DEFAULT 100   // ≈39%

// ---------------------------------------------------------------- DMA
#define DMA_DESC_NUM    4
#define DMA_FRAME_NUM   240       // 4 * 240 / 16000 = 60 ms 的 TX 缓冲深度
#define DMA_TOTAL_MS    ((DMA_DESC_NUM * DMA_FRAME_NUM * 1000) / SAMPLE_RATE_HZ)

// MAX98357A 离开 shutdown 需要几 ms 才稳定
#define AMP_WAKE_MS     8

// ---------------------------------------------------------------- 按键
#define BUTTON_DEBOUNCE_MS  25

// ---------------------------------------------------------------- Stage 5
#define REC_TEST_SECONDS    3      // 3 s * 16000 * 2 B = 96000 B,不带 WiFi 时堆足够
