# -*- coding: utf-8 -*-
"""厂商连接共用的小工具。"""
import asyncio

_closing = set()                          # 后台关连接的 task,留引用防止被 GC


def close_ws_in_background(ws, last_words=None):
    """关 WS 放后台,**不挡回合**。

    美国 VPS 到新加坡一个来回 ~200 ms,close 握手还要再等一个来回。
    同步做的话,TTS 最后不满一包的尾巴和 audio_end 都要等它 —— 2026-09-22 实测因此拖了 ~1 s。
    last_words:关之前先发的一帧(比如百炼 TTS 的 session.finish)。
    """
    async def go():
        try:
            if last_words is not None:
                await ws.send(last_words)
            await asyncio.wait_for(ws.close(), 3)
        except Exception:
            pass
    t = asyncio.get_running_loop().create_task(go())
    _closing.add(t)
    t.add_done_callback(_closing.discard)
