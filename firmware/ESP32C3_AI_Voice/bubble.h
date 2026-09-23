#pragma once
#include <Arduino.h>
#include <stddef.h>

// 等待音效:"咕噜咕噜"的冒泡声。Stage 11,由服务器的 {"t":"cue","name":"thinking"} 触发,
// 在 WAITING 期间循环,直到回复的音频接上。
//
// 和 cue.* 的区别:cuePlay 是**阻塞**的,只能在没有音频流要伺候的时刻响。
// 等待音效要一直响、同时 loop 还得接着 wsPoll 收 audio_begin —— 所以这里只是个
// **样本发生器**:session 每轮 loop 取一帧(20 ms)写进 I2S,audioWrite 的阻塞就是节拍器,
// 和 PLAYING 状态完全同一个套路。
//
// 声音模型:每个气泡是一段**音调上扬、指数衰减**的正弦(气泡上浮时共振频率升高,
// 这正是"咕嘟"声的来源)。气泡成串冒(一串 3~6 个,间隔很短),串与串之间停一会儿。
// 参数全靠伪随机抖动,听起来不机械。
//
// !! 实时路径上零浮点(AGENT.md §9.1b)!! 正弦查 cue.* 的 256 点表,相位 Q32 累加,
// 包络 Q15 乘法衰减,随机数 xorshift32。64 位除法只在每个气泡开头算一次。

void   bubbleStart();                   // 从头开始冒泡(先停一小段再出第一个泡)
void   bubbleStop();
bool   bubbleActive();
// 当前处在两个气泡之间的静音里。从冒泡切到正式回复时等这个时刻再切,
// 否则在气泡中间硬切会"啪"一声。最多等一个气泡的长度(~120 ms)。
bool   bubbleInGap();
void   bubbleFill(int16_t *dst, size_t n);
