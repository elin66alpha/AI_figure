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


async def pace_pcm(send, pcm: bytes, *, on_progress=None) -> int:
    """把 pcm 按实时速率喂给 send(bytes)。返回实际发出的字节数。

    send 必须是 awaitable(websockets 的 ws.send)。被 cancel 时直接抛
    CancelledError —— abort 路径靠这个立刻停掉在途音频。
    """
    if not pcm:
        return 0

    total = len(pcm)
    burst_s = config.BURST_MS / 1000.0
    t0 = time.monotonic()
    sent = 0

    while sent < total:
        # 首包突发:一次把 BURST_MS 推出去。之后每次一个 CHUNK_BYTES。
        n = (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE * config.BURST_MS // 1000
             if sent == 0 else config.CHUNK_BYTES)
        chunk = pcm[sent:sent + n]

        # 发出这一包之后,总共就发了 sent+len(chunk) 字节的音频。
        # 不变量要求这个时长不超过 (已过去时间 + burst)。
        ready_at = t0 + _bytes_to_seconds(sent + len(chunk)) - burst_s
        wait = ready_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

        await send(chunk)
        sent += len(chunk)
        if on_progress:
            on_progress(sent, total)

    return sent
