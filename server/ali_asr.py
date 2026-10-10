# -*- coding: utf-8 -*-
"""阿里云百炼流式识别(qwen-audio-3.1-asr-flash-streaming)。规格见 ../SERVER.md §4.7。

协议是 DashScope 的 inference WS(和 TTS 的 realtime WS 不是一套):

    连 wss://dashscope[-intl].aliyuncs.com/api-ws/v1/inference
        Authorization: Bearer <DASHSCOPE_API_KEY>
    -> {"header":{"action":"run-task",...}, "payload":{model, parameters:{format:pcm, sample_rate:16000}}}
    <- task-started
    -> binary PCM(直接转发设备的 100 ms 包,不用像火山那样合并)
    <- result-generated {output.sentence: {sentence_id, text, sentence_end, heartbeat}} ...
    -> {"header":{"action":"finish-task",...}}
    <- result-generated(最终句,sentence_end=true)
    <- task-finished        或  task-failed {header.error_code, error_message}

同一个 sentence_id 会反复下发,text 是**这一句到目前为止的全文**(不是增量)。
一段话可能被切成多句。最终文本 = 按 sentence_id 顺序拼起来。
"""
import asyncio
import json
import logging
import time
import uuid

from websockets.asyncio.client import connect

import config
from aioutil import close_ws_in_background
from asr import ASRError, AsrStream

log = logging.getLogger("asr")


class AliAsrStream(AsrStream):
    def _header(self, action):
        return {"action": action, "task_id": self._tid, "streaming": "duplex"}

    async def _run(self) -> str:
        if not config.DASHSCOPE_API_KEY:
            raise ASRError("没配百炼密钥:设 DASHSCOPE_API_KEY")
        self._tid = uuid.uuid4().hex
        self._sent = {}                   # sentence_id -> 最新全文
        t0 = time.monotonic()
        ws = None
        try:
            ws = await connect(config.ALI_INFERENCE_URL,
                               additional_headers={"Authorization": "Bearer " + config.DASHSCOPE_API_KEY},
                               open_timeout=5)
            await ws.send(json.dumps({
                "header": self._header("run-task"),
                "payload": {
                    "task_group": "audio", "task": "asr", "function": "recognition",
                    "model": config.ALI_ASR_MODEL,
                    "parameters": {"format": "pcm", "sample_rate": config.SAMPLE_RATE},
                    "input": {},
                },
            }))
            ev = await self._recv(ws, 5)
            if ev != "task-started":
                raise ASRError("run-task 之后收到 %s" % ev)
            log.info("百炼 ASR 就绪 %.0f ms(建连 + run-task)", (time.monotonic() - t0) * 1000)

            rx = asyncio.get_running_loop().create_task(self._rx(ws))
            try:
                while True:
                    pcm = await self._q.get()
                    if pcm is None or rx.done():   # rx 提前结束 = 服务端失败,别再往死连接里写
                        break
                    await ws.send(pcm)
                if not rx.done():
                    await ws.send(json.dumps({"header": self._header("finish-task"),
                                              "payload": {"input": {}}}))
                await rx                  # 等 task-finished;task-failed 在这里抛出来
            finally:
                if not rx.done():
                    rx.cancel()

            text = "".join(self._sent[k] for k in sorted(self._sent))
            log.info("百炼 ASR 结果 %r", text)
            return text
        except (ASRError, asyncio.CancelledError):
            raise
        except Exception as e:
            raise ASRError("百炼 ASR 连接失败: %r" % e)
        finally:
            if ws is not None:
                close_ws_in_background(ws)

    async def _recv(self, ws, timeout):
        msg = await asyncio.wait_for(ws.recv(), timeout)
        ev = json.loads(msg)
        h = ev.get("header") or {}
        name = h.get("event")
        if name == "task-failed":
            raise ASRError("百炼 ASR 失败 %s: %s" % (h.get("error_code"), h.get("error_message")))
        self._last = ev
        return name

    async def _rx(self, ws):
        while True:
            # 百炼自己的空闲超时是 23 s;这里只防服务端彻底不吭声
            name = await self._recv(ws, 30)
            if name == "task-finished":
                return
            if name != "result-generated":
                continue
            sen = ((self._last.get("payload") or {}).get("output") or {}).get("sentence") or {}
            if sen.get("heartbeat"):
                continue
            self._sent[sen.get("sentence_id", 0)] = sen.get("text") or ""
