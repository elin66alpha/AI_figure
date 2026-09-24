#pragma once
#include <Arduino.h>
#include <stddef.h>

// I2S 全双工(共享 BCLK/WS)+ MAX98357A 功放控制。
//
// audioBegin() 一次性建好 TX/RX 两个 channel 并 init,之后**永不重装驱动**。
//
// !! 时钟所有权 !!
// 全双工(i2s_new_channel 两个 handle 都非 NULL)下驱动会置 tx_conf.sig_loopback,
// GPIO4/GPIO5 上的 BCLK/WS 由 **TX 模块**产生,RX 从 TX 内部取时钟。
// 所以 TX 一 disable,麦克风就没有时钟,i2s_channel_read 只会一路超时返回 0。
//   => TX 在 audioBegin() 里 enable,之后**永不 disable**。
//   => 不播放时 chan_cfg.auto_clear 让 TX 自动输出零,功放 SD 拉低,完全无声。
//   => "半双工"由功放开关 + RX 的 enable/disable 保证,不靠关时钟。
//
// 对外一律是 16 kHz 单声道 PCM16;32-bit slot、左右声道复制这些细节封装在内部。
// 功放(MAX98357A SD / GPIO10)由播放开始/结束内部控制,不对外暴露。

bool  audioBegin();

// ---- 录音 ----
bool  audioStartCapture();
void  audioStopCapture();
bool  audioIsCapturing();
// 返回实际读到的**样本数**(不是字节数)。maxSamples 超过 FRAME_SAMPLES 时按 FRAME_SAMPLES 截断。
size_t audioRead(int16_t *dst, size_t maxSamples, uint32_t timeoutMs);

// ---- 播放 ----
// 推两帧静音对齐管线 -> 开功放 -> 等功放唤醒。
bool  audioStartPlayback();
// 补静音 -> 等 DMA 放完 -> 关功放。TX 本身保持运行。阻塞 ~60 ms(尾音在这段时间里播完)。
void  audioStopPlayback();
// 打断(barge-in)专用:不保护尾音,立刻关功放,不阻塞。
// DMA 里残留的旧音频留给下一次 audioStartPlayback 冲掉。
void  audioCutPlayback();
bool  audioIsPlaying();
size_t audioWrite(const int16_t *src, size_t samples, uint32_t timeoutMs);

// ---- TX 欠载统计(判断"生产者跟不跟得上"的唯一硬证据) ----
// TX DMA 队列溢出 = 应用层落后 >= 3 个 DMA 缓冲 = 这段时间硬件在输出零。
// 只在 s_playing 期间计数;audioStartPlayback() 会自动清零。
uint32_t audioTxUnderruns();

// ---- 输出音量 ----
// 麦克风增益(MIC_SHIFT)和 DC blocker 是编译期常量(config.h),只有它是运行期变量 ——
// **故意的**:以后手机 App 要能调音量(ROADMAP.md §3.1)。0..256,默认 OUTPUT_GAIN_DEFAULT。
void     setOutputGain(uint16_t g);
uint16_t getOutputGain();
