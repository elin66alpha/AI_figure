# -*- coding: utf-8 -*-
"""阿里云百炼 Qwen-TTS-Realtime(qwen3-tts-flash-realtime)。规格见 ../SERVER.md §4.6。

    async for pcm in synthesize("你好"):          # 一次性:连 -> 合成 -> 关
        ...                      # 裸 PCM16LE / 16 kHz / 单声道,直接喂 pacer

    s = AliTtsSession(); s.start()              # Stage 10:一条连接念多句
    async for pcm in s.synth("第一句。"): ...
    async for pcm in s.synth("第二句。"): ...
    s.close()

接口和 volc_tts 一模一样 —— session.py 不关心是哪家。

协议(OpenAI Realtime 风格,纯 JSON 文本帧,音频是 base64):

    连 wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=...
        Authorization: Bearer <DASHSCOPE_API_KEY>
    <- session.created
    -> session.update   {mode:"commit", voice, response_format:"pcm", sample_rate:16000}
    <- session.updated
    -> input_text_buffer.append {text}
    -> input_text_buffer.commit
    <- response.audio.delta {delta:"<base64>"} ...
    <- response.done
    -> session.finish
    <- session.finished

用 commit 模式而不是 server_commit:一次合成就是"一段文本、一个回复",
由我们决定什么时候开合成,不让服务端自己攒。

**一条连接可以 commit 多次**(2026-09-22 真连实测):每次 commit 各自出一轮
response.created ... response.done,顺序不乱;每句 commit -> 首包 ~0.35 s。
Stage 10 的句级流水线就是每切出一句 append + commit 一次,省掉每句 ~1 s 的建连。

单独自测(不经过 main.py,只验密钥/音色/网络):

    python ali_tts.py "你好,我是小助手。" out.wav
"""
import asyncio
import base64
import json
import logging
import time

from websockets.asyncio.client import connect
from websockets.protocol import State

import config
from aioutil import close_ws_in_background

log = logging.getLogger("tts")

_SESSION_FINISH = json.dumps({"type": "session.finish"})


class TTSError(Exception):
    pass


async def _recv_event(ws, timeout):
    msg = await asyncio.wait_for(ws.recv(), timeout)
    if isinstance(msg, (bytes, bytearray)):
        raise TTSError("百炼回了 binary 帧(%d B),协议不是这样的" % len(msg))
    ev = json.loads(msg)
    if ev.get("type") == "error":
        err = ev.get("error") or {}
        raise TTSError("百炼报错 %s: %s" % (err.get("code"), err.get("message")))
    return ev


async def _expect(ws, typ, deadline):
    while True:
        ev = await _recv_event(ws, max(0.1, deadline - time.monotonic()))
        if ev.get("type") == typ:
            return ev
        log.debug("等 %s 途中收到 %s", typ, ev.get("type"))


class AliTtsSession:
    """一条到百炼的 TTS 连接,可以顺序合成多句。

    start() 立刻在后台建连(Stage 10:turn_end 一到就建,和 ASR 收尾 / LLM 首 token 并行)。
    synth(text) 会先等连接就绪。同一时刻只能有一个 synth 在跑 —— 调用方负责按句顺序调。
    close() 在后台关,不挡下行。
    """

    def __init__(self, uid: str = "esp32"):
        self.uid = uid
        self.ws = None
        self._ready = None
        self.chars = 0                  # 百炼计费字符数(用量里的 characters),日志用

    def start(self):
        if self._ready is None:
            self._ready = asyncio.get_running_loop().create_task(self._open())
        return self

    async def _open(self):
        if not config.DASHSCOPE_API_KEY:
            raise TTSError("没配百炼密钥:设 DASHSCOPE_API_KEY")
        url = "%s?model=%s" % (config.ALI_REALTIME_URL, config.ALI_TTS_MODEL)
        t0 = time.monotonic()
        deadline = t0 + config.ALI_TTS_TIMEOUT_S
        try:
            self.ws = await connect(url, additional_headers={
                "Authorization": "Bearer " + config.DASHSCOPE_API_KEY},
                max_size=None, open_timeout=5)
            await _expect(self.ws, "session.created", deadline)
            await self.ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "mode": "commit",
                    "voice": config.ALI_TTS_VOICE,
                    # 必须 16k PCM:设备 I2S 全双工共享时钟,服务器不做重采样(AGENT.md §4)。
                    # 百炼默认是 24000,不写这一行就会快放、变调。
                    "response_format": "pcm",
                    "sample_rate": config.SAMPLE_RATE,
                },
            }))
            upd = await _expect(self.ws, "session.updated", deadline)
        except TTSError:
            raise
        except asyncio.TimeoutError:
            raise TTSError("百炼 TTS 建连超时")
        except Exception as e:
            # 握手 401/403 = 密钥错或密钥和地域对不上(北京的 key 不能连新加坡)
            raise TTSError("连百炼失败: %r" % e)
        sr = (upd.get("session") or {}).get("sample_rate")
        if sr is not None and sr != config.SAMPLE_RATE:
            raise TTSError("百炼没接受 sample_rate=%d(回的是 %s)" % (config.SAMPLE_RATE, sr))
        log.info("TTS 就绪 %.0f ms(建连 + session.update)", (time.monotonic() - t0) * 1000)

    async def synth(self, text: str):
        """异步生成器,逐块产出这一句的裸 PCM。出错抛 TTSError。"""
        self.start()
        await self._ready                     # 建连失败的异常在这里抛出
        if self.ws is None or self.ws.state is not State.OPEN:
            # turn_start 预热的连接,用户说得久了可能被对端关掉(实测空闲 65 s 还活着,
            # 这里只是兜底)。重连一次,代价就是这一回合多等一个建连。
            log.warning("TTS 预热的连接已经断了,重连")
            self.ws = None
            self._ready = asyncio.get_running_loop().create_task(self._open())
            await self._ready
        ws = self.ws
        t0 = time.monotonic()
        deadline = t0 + config.ALI_TTS_TIMEOUT_S
        first = None
        total = 0
        try:
            await ws.send(json.dumps({"type": "input_text_buffer.append", "text": text},
                                     ensure_ascii=False))
            await ws.send(json.dumps({"type": "input_text_buffer.commit"}))

            carry = b""                  # base64 解出来万一是奇数字节,留到下一块
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TTSError("超时 %.0f s 没收到 response.done" % config.ALI_TTS_TIMEOUT_S)
                ev = await _recv_event(ws, left)
                typ = ev.get("type")

                if typ == "response.audio.delta":
                    pcm = carry + base64.b64decode(ev.get("delta") or "")
                    if len(pcm) & 1:
                        pcm, carry = pcm[:-1], pcm[-1:]
                    else:
                        carry = b""
                    if pcm:
                        if first is None:
                            first = time.monotonic() - t0
                        total += len(pcm)
                        yield pcm

                elif typ == "response.done":
                    resp = ev.get("response") or {}
                    status = resp.get("status")
                    if status not in (None, "completed"):
                        raise TTSError("response.done status=%s %s"
                                       % (status, resp.get("status_details")))
                    self.chars += (resp.get("usage") or {}).get("characters", 0)
                    break
        except TTSError:
            raise
        except asyncio.TimeoutError:
            raise TTSError("百炼超时(%.0f s 内没收完)" % config.ALI_TTS_TIMEOUT_S)
        except Exception as e:
            raise TTSError("百炼 TTS 连接断了: %r" % e)

        log.info("合成 %d 字 -> %d ms 音频,首包 %.0f ms,耗时 %.0f ms: %s",
                 len(text), total * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE),
                 (first or 0) * 1000, (time.monotonic() - t0) * 1000, text[:30])
        if total == 0:
            raise TTSError("合成成功但没有音频 —— 文本是不是全是标点?")

    def close(self):
        """正常结束、出错、被 abort cancel 都要调。abort 时尽快关,不再合成后面的字。"""
        r = self._ready
        if r is not None and not r.done():
            r.cancel()                        # 还在建连就直接掐掉
        elif r is not None and not r.cancelled():
            r.exception()                     # 取走异常,免得 asyncio 报 "never retrieved"
        if self.ws is not None:
            close_ws_in_background(self.ws, _SESSION_FINISH)   # 不挡下行
            self.ws = None


async def synthesize(text: str, *, uid: str = "esp32"):
    """一次性合成一段文本(Stage 8 的 say 用)。"""
    s = AliTtsSession(uid).start()
    try:
        async for pcm in s.synth(text):
            yield pcm
    finally:
        s.close()


# ---------------------------------------------------------------- 自测
async def _main(text, out):
    import wave
    pcm = bytearray()
    async for chunk in synthesize(text):
        pcm += chunk
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(config.BYTES_PER_SAMPLE)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    print("写入 %s(%d B)" % (out, len(pcm)))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "tts_out.wav"))
