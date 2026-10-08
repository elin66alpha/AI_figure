#pragma once
#include <Arduino.h>

// 本地提示音。不接串口时,它和 LED 一起构成设备的全部对外状态输出。
//
// !! 实现上有一条硬规矩:实时路径上一个浮点运算都不能有 !!
// AGENT.md §9.1(b):C3 是 RV32IMC,**没有 FPU**,软件模拟的 double 一次调用就能
// 吃光 16 kHz 下 62.5 µs 的单样本预算,结果是 TX DMA 欠载、auto_clear 填零、
// 听感断续。Stage 2 就是这么翻的车。
//
// 所以这里用 **256 点正弦表 + Q32 相位累加器**:任意频率、任意时长,全整数。
// 建表时调 256 次 sinf(参数 <= 2π,走 newlib 的短路径),那是一次性的,不在实时路径上。
//
// cuePlay 是**阻塞**的(几十到几百 ms)。提示音只在 IDLE / 错误态 / 状态切换时响,
// 那些时刻没有音频流要伺候,阻塞无害。绝不要在 PLAYING 中途调它。

struct CueNote {
  uint16_t hz;    // 0 = 静音间隔
  uint16_t ms;
  uint8_t  amp;   // 0..255,相对满幅。最终还要乘 config.h 的 OUTPUT_GAIN
};

void cueBegin();                                  // 建表。setup() 里调一次
void cuePlay(const CueNote *notes, uint8_t count);
// 256 点正弦表(Q15),给 bubble.* 共用。索引 = Q32 相位 >> 24。
const int16_t *cueSineTable();

// 四种预定义音
void cueBoot();       // 上电:升调两声
void cueLinkUp();     // 收到 ready:单声高音
void cueLinkDown();   // 掉线:降调两声
void cueError();      // 致命错误 / 即将软复位:低音三连
void cueProv();       // 进入 BLE 配网模式:上行三声
