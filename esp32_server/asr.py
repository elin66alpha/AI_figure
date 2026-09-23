# -*- coding: utf-8 -*-
"""ASR 厂商分派 + 公共外壳。session.py 只认这一个入口,换厂商 = 改 ASR_PROVIDER。

    ali   阿里云百炼 qwen-audio-3.1-asr-flash-streaming(默认)  ali_asr.py
    volc  火山流式语音识别                                       volc_asr.py

用法(一个回合一个流):

    s = asr.open_stream(uid)      # turn_start:立刻开始建连,和用户说话并行
    s.feed(pcm)                   # 每个上行帧,不阻塞
    text = await s.finish()       # turn_end:发结束包,等最终文本
    await s.cancel()              # abort / 连接断开

**turn_start 就建连**是故意的:跨洋 TLS 握手要 ~1 s,放在 turn_end 之后做,
这 1 s 就直接加在首字延迟上;放在 turn_start 就藏进了用户说话的时间里。
建连期间到的音频先进队列,连上之后一次补发。

单独自测(不经过 main.py,按实时速率推一个 wav):

    python asr.py input.wav
"""
import asyncio
import logging

import config

log = logging.getLogger("asr")


class ASRError(Exception):
    pass


class AsrStream:
    """子类只实现 _run():建连、发音频(从 self._q 取,None = 结束)、收结果,返回最终文本。"""

    def __init__(self, uid: str):
        self.uid = uid
        self._q = asyncio.Queue()
        self._task = None
        self._ended = False
        self.fed = 0                      # 已喂的字节数,日志用

    def start(self):
        self._task = asyncio.get_running_loop().create_task(self._run())
        return self

    def feed(self, pcm: bytes):
        if not self._ended:
            self.fed += len(pcm)
            self._q.put_nowait(pcm)

    async def finish(self) -> str:
        """发结束包,等最终文本。_run 里的异常(ASRError)在这里抛出来。"""
        self._ended = True
        self._q.put_nowait(None)
        try:
            return await asyncio.wait_for(asyncio.shield(self._task), config.ASR_FINISH_TIMEOUT_S)
        except asyncio.TimeoutError:
            await self.cancel()
            raise ASRError("turn_end 后 %.0f s 没拿到最终文本" % config.ASR_FINISH_TIMEOUT_S)

    async def cancel(self):
        self._ended = True
        t = self._task
        if t and not t.done():
            t.cancel()
            try:
                await t
            except BaseException:
                pass
        elif t and t.done() and not t.cancelled():
            t.exception()                 # 取走异常,免得 asyncio 报 "never retrieved"

    async def _run(self) -> str:
        raise NotImplementedError


_closing = set()                          # 后台关连接的 task,留引用防止被 GC


def close_ws_in_background(ws, last_words=None):
    """关 WS 放后台,不挡回合(跨洋 close 握手一个来回 ~200 ms)。"""
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


def open_stream(uid: str = "esp32") -> AsrStream:
    if config.ASR_PROVIDER == "ali":
        import ali_asr
        return ali_asr.AliAsrStream(uid).start()
    if config.ASR_PROVIDER == "volc":
        import volc_asr
        return volc_asr.VolcAsrStream(uid).start()
    raise ValueError("未知 ASR_PROVIDER=%r(可选 ali / volc)" % config.ASR_PROVIDER)


# ---------------------------------------------------------------- 自测
async def _main(path):
    import time
    import wave
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (16000, 2, 1):
            raise SystemExit("要 16 kHz / 16 bit / 单声道 wav")
        pcm = w.readframes(w.getnframes())
    s = open_stream("selftest")
    t0 = time.monotonic()
    for i in range(0, len(pcm), config.CHUNK_BYTES):
        s.feed(pcm[i:i + config.CHUNK_BYTES])
        await asyncio.sleep(config.CHUNK_MS / 1000)
    t1 = time.monotonic()
    text = await s.finish()
    print("识别(%s,音频 %.1f s,turn_end -> 文本 %.0f ms):%s"
          % (config.ASR_PROVIDER, t1 - t0, (time.monotonic() - t1) * 1000, text))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1]))
