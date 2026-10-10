# -*- coding: utf-8 -*-
"""下行音频速率整形。规格见 SERVER.md §3.5。

为什么需要它:
  TTS 生成通常快于实时播放。一次性推下去有两个后果 ——
  (1) 打爆设备的 16 KB 环形缓冲(设备会靠 TCP 反压顶住,但没意义)
  (2) 打断变迟钝:TCP 缓冲里积压一堆已经不该播的音频

规则:
  - 首包突发 BURST_MS,让设备尽快攒够预缓冲开始播
  - 之后按 1x 实时喂
  - 设备不读时 TCP 自然反压,这是预期行为,**不要加应用层流控**

## 不变量

    已发出的音频时长  <=  已过去的墙钟时长 + BURST_MS

也就是"服务器允许比实时超前 BURST_MS,不许更多"。稳态下设备缓冲里
恒定躺着 BURST_MS 的音频 —— 这正是它的抗抖动余量。

这条用**绝对时间基准**判定(`t0 + sent_s - burst_s`),不是 `sleep(chunk_ms)`。
后者会把每包的发送耗时累积成漂移,长回复越播越慢。

⚠️ 一个容易写错的地方:突发完之后**不能**等一整个 BURST_MS 再发下一包。
那样设备在这段时间里正好把 300 ms 播完,缓冲归零,余量白给了。
正确的是突发完立刻进入 1x 节奏,让那 300 ms 一直躺在设备缓冲里。
"""
import asyncio
import time

import config


def _bytes_to_seconds(n: int) -> float:
    return n / float(config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)


async def pace_stream(send, source) -> int:
    """把异步迭代器 source 给出的 pcm 按实时速率喂给 send(bytes)。返回实际发出的字节数。

    send 必须是 awaitable(websockets 的 ws.send)。被 cancel 时直接抛
    CancelledError —— abort 路径靠这个立刻停掉在途音频。

    源给得比实时快(常态,回声也是):按不变量整形。
    源给得比实时慢(TTS 卡顿):有多少发多少,设备那边会欠载一下;
    源恢复后按绝对时间基准最多补回 BURST_MS 的超前量,不会更多 —— 不变量照样成立。

    首包要攒满 BURST_MS 才发(或者源已经结束),否则设备的预缓冲攒不够,
    刚开播就欠载。TTS 首包到这 300 ms 的音频通常只差几十 ms。
    """
    burst_bytes = config.SAMPLE_RATE * config.BYTES_PER_SAMPLE * config.BURST_MS // 1000
    burst_s = config.BURST_MS / 1000.0
    buf = bytearray()
    sent = 0
    t0 = None

    async def emit(chunk):
        nonlocal sent, t0
        if t0 is None:
            t0 = time.monotonic()
        # 发出这一包之后,总共就发了 sent+len(chunk) 字节的音频。
        # 不变量要求这个时长不超过 (已过去时间 + burst)。
        ready_at = t0 + _bytes_to_seconds(sent + len(chunk)) - burst_s
        wait = ready_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        await send(chunk)
        sent += len(chunk)

    async for data in source:
        buf += data
        # 首包突发:一次把 BURST_MS 推出去。之后每次一个 CHUNK_BYTES。
        while len(buf) >= (burst_bytes if sent == 0 else config.CHUNK_BYTES):
            n = burst_bytes if sent == 0 else config.CHUNK_BYTES
            chunk = bytes(buf[:n])
            del buf[:n]
            await emit(chunk)

    # 尾巴。PCM16 必须偶数字节,奇数说明源有问题,丢掉最后那一个字节保对齐。
    if len(buf) & 1:
        del buf[-1]
    while buf:
        chunk = bytes(buf[:config.CHUNK_BYTES])
        del buf[:config.CHUNK_BYTES]
        await emit(chunk)
    return sent
