# -*- coding: utf-8 -*-
"""火山流式语音识别(bigmodel_async,双向流式优化版)。规格见 ../SERVER.md §4.3。

    -> full client request(JSON 参数)
    -> audio only request × N         每包 200 ms / 6400 B(设备的 100 ms 包两两合并)
    -> audio only request, flags=0b0010(负包 = 最后一包)
    <- full server response × N       payload.result.text 是**到目前为止的全文**
    <- 带负包标记的 full server response = 最终结果
    <- 或 error frame

⚠️ 这一家还没有真连过(没开通火山),只用 mock 验过帧格式。
"""
import asyncio
import logging
import time

from websockets.asyncio.client import connect

import config
import volc_proto as vp
from aioutil import close_ws_in_background
from asr import ASRError, AsrStream

log = logging.getLogger("asr")

PACKET = config.CHUNK_BYTES * 2       # 200 ms:火山双向流式模式的最优包长(§4.3)


class VolcAsrStream(AsrStream):
    async def _run(self) -> str:
        try:
            headers = vp.auth_headers(config.VOLC_ASR_RESOURCE_ID)
        except ValueError as e:
            raise ASRError(str(e))
        t0 = time.monotonic()
        ws = None
        self._text = ""
        try:
            ws = await connect(config.VOLC_ASR_URL, additional_headers=headers,
                               max_size=None, open_timeout=5)
            logid = ws.response.headers.get("X-Tt-Logid", "?")
            await ws.send(vp.encode_json(vp.FULL_CLIENT_REQUEST, {
                "user": {"uid": self.uid},
                "audio": {"format": "pcm", "codec": "raw", "rate": config.SAMPLE_RATE,
                          "bits": 16, "channel": 1},
                "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True},
            }))
            log.info("火山 ASR 建连 %.0f ms logid=%s", (time.monotonic() - t0) * 1000, logid)

            rx = asyncio.get_running_loop().create_task(self._rx(ws))
            buf = bytearray()
            try:
                while True:
                    pcm = await self._q.get()
                    if rx.done():
                        break
                    if pcm is None:
                        # 负包:把残余(可能为空)带上,标记最后一包
                        await ws.send(vp.encode(vp.AUDIO_ONLY_REQUEST, bytes(buf),
                                                flags=vp.FLAG_LAST_NO_SEQ, serialization=vp.SER_RAW))
                        break
                    buf += pcm
                    while len(buf) >= PACKET:
                        await ws.send(vp.encode(vp.AUDIO_ONLY_REQUEST, bytes(buf[:PACKET]),
                                                serialization=vp.SER_RAW))
                        del buf[:PACKET]
                await rx
            finally:
                if not rx.done():
                    rx.cancel()
            log.info("火山 ASR 结果 %r", self._text)
            return self._text
        except (ASRError, asyncio.CancelledError):
            raise
        except Exception as e:
            raise ASRError("火山 ASR 连接失败: %r" % e)
        finally:
            if ws is not None:
                close_ws_in_background(ws)

    async def _rx(self, ws):
        while True:
            msg = await asyncio.wait_for(ws.recv(), 30)
            if isinstance(msg, str):
                raise ASRError("火山回了文本帧: %r" % msg[:200])
            f = vp.decode(msg)
            if f.is_error:
                raise ASRError("火山 ASR 报错 code=%s %s" % (f.error_code, f.json() or f.payload[:200]))
            if f.msg_type != vp.FULL_SERVER_RESPONSE:
                continue
            body = f.json() or {}
            text = (body.get("result") or {}).get("text")
            if text is not None:
                self._text = text
            if f.is_last:
                return
