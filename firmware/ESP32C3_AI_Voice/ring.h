#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stddef.h>

// 播放环形缓冲。**静态数组,绝不 malloc**(AGENT.md §7 第 1 条)。
//
//   RING_BYTES = 16384 B = 8192 样本 = 512 ms
//
// 尺寸是 AGENT.md §5.6 定的:PSK-TLS 下 mbedTLS 要吃掉钉死的 32 KB,
// 从 rev.3 的 24 KB 降到 16 KB 换回来的余量就是给它的。
//
// 单生产者(net_ws 的接收路径)、单消费者(session 的播放路径),而且两者都在
// **同一个 loop 线程**里 —— 没有中断、没有 FreeRTOS 任务碰它,所以不需要
// 原子操作或临界区。哪天真要拆任务,这里得整个重写,别忘了。
//
// 里面装的是 PCM16LE。ESP32 也是小端,所以字节流可以直接当 int16 用 ——
// 前提是读写的字节数始终是偶数,ringRead 会把奇数向下取整来保证这一点。

void   ringReset();
size_t ringUsed();
size_t ringFree();
size_t ringCapacity();

// 零拷贝写入(net_ws 直接从 socket 读进来):
//   p = 写指针,返回值 = 从 p 起**连续**可写的字节数(绕回之前那一段,可能小于 ringFree())
//   往 p 里写 n 字节(n <= 返回值)之后调 ringCommit(n)
size_t ringWriteSpan(uint8_t **p);
void   ringCommit(size_t n);

// 返回实际读出的字节数(偶数)。
size_t ringRead(uint8_t *dst, size_t n);
