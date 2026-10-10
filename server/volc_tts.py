# -*- coding: utf-8 -*-
"""火山 TTS —— WebSocket 单向流式 V3。规格见 ../SERVER.md §4.2。

    async for pcm in synthesize("你好"):
        ...                      # 裸 PCM16LE / 16 kHz / 单声道,直接喂 pacer

一次合成 = 一条 WS:发一帧 full client request(JSON),然后收
TTSResponse(352,音频)... 直到 SessionFinished(152)。

单独自测(不经过 main.py,只验密钥/音色/网络):

    python volc_tts.py "你好,我是小助手。" out.wav
"""
import asyncio
import logging
import time

from websockets.asyncio.client import connect

import config
import volc_proto as vp

log = logging.getLogger("tts")


class TTSError(Exception):
    pass


def _headers() -> dict:
    try:
        return vp.auth_headers(config.VOLC_TTS_RESOURCE_ID)
    except ValueError as e:
        raise TTSError(str(e))


def _request(text: str, uid: str) -> dict:
    return {
        "user": {"uid": uid},
        "req_params": {
            "text": text,
            "speaker": config.VOLC_TTS_SPEAKER,
            # 必须 16k PCM:设备 I2S 全双工共享时钟,服务器不做重采样(AGENT.md §4)
            "audio_params": {
                "format": "pcm",
                "sample_rate": config.SAMPLE_RATE,
            },
        },
    }


async def synthesize(text: str, *, uid: str = "esp32"):
    """异步生成器,逐块产出裸 PCM。出错抛 TTSError。

    被 cancel(abort)时 async with 会关掉到火山的 WS —— 不再计费后面的字。
    """
    t0 = time.monotonic()
    first = None
    total = 0
    async with connect(config.VOLC_TTS_URL, additional_headers=_headers(),
                       max_size=None, open_timeout=5) as ws:
        logid = ws.response.headers.get("X-Tt-Logid", "?")
        log.info("合成 %d 字 speaker=%s logid=%s", len(text), config.VOLC_TTS_SPEAKER, logid)
        await ws.send(vp.encode_json(vp.FULL_CLIENT_REQUEST, _request(text, uid)))

        deadline = t0 + config.VOLC_TTS_TIMEOUT_S
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TTSError("超时 %.0f s 没收到 SessionFinished (logid=%s)"
                               % (config.VOLC_TTS_TIMEOUT_S, logid))
            msg = await asyncio.wait_for(ws.recv(), left)
            if isinstance(msg, str):
                raise TTSError("火山回了文本帧: %r" % msg[:200])
            f = vp.decode(msg)

            if f.is_error:
                raise TTSError("火山报错 code=%s %s (logid=%s)"
                               % (f.error_code, f.json() or f.payload[:200], logid))

            if f.msg_type == vp.AUDIO_ONLY_RESPONSE:
                if f.payload:
                    if first is None:
                        first = time.monotonic() - t0
                        log.info("首包 %.0f ms", first * 1000)
                    total += len(f.payload)
                    yield f.payload
                continue

            if f.event == vp.EV_SESSION_FINISHED:
                body = f.json() or {}
                code = body.get("status_code", body.get("code", 20000000))
                if code not in (0, 20000000):
                    raise TTSError("SessionFinished 带错误: %s (logid=%s)" % (body, logid))
                break
            # 350/351 句子起止、其他事件:只记日志
            log.debug("%r", f)

    ms = total * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
    log.info("合成完毕 %d B (%d ms 音频),耗时 %.0f ms",
             total, ms, (time.monotonic() - t0) * 1000)
    if total == 0:
        raise TTSError("合成成功但没有音频 —— 文本是不是全是标点?")


class VolcTtsSession:
    """和 ali_tts.AliTtsSession 同一个接口。

    火山的单向流式接口一条连接只合成一段文本,所以这里每句各开一条 ——
    句间会多一个建连(~0.3 s 国内 / ~1 s 跨洋)。要省掉得换 bidirection 接口(§4.2),
    火山目前只是备选,先不做。
    """

    def __init__(self, uid: str = "esp32"):
        self.uid = uid
        self.chars = 0

    def start(self):
        return self

    def synth(self, text: str):
        return synthesize(text, uid=self.uid)

    def close(self):
        pass


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
