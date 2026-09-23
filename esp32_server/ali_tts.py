# -*- coding: utf-8 -*-
"""阿里云百炼 Qwen-TTS-Realtime(qwen3-tts-flash-realtime)。规格见 ../SERVER.md §4.6。

    async for pcm in synthesize("你好"):
        ...                      # 裸 PCM16LE / 16 kHz / 单声道,直接喂 pacer

接口和 volc_tts.synthesize() 一模一样 —— session.py 不关心是哪家。

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
由我们决定什么时候开合成,不让服务端自己攒。Stage 10 的句级流水线也是
每切出一句就 append + commit 一次,同一套逻辑。

单独自测(不经过 main.py,只验密钥/音色/网络):

    python ali_tts.py "你好,我是小助手。" out.wav
"""
import asyncio
import base64
import json
import logging
import time

from websockets.asyncio.client import connect

import config

log = logging.getLogger("tts")


class TTSError(Exception):
    pass


_closing = set()                 # 后台关连接的 task,留引用防止被 GC


async def _close_quietly(ws):
    """session.finish + 关 WS。放后台做,**不挡下行**。

    美国 VPS 到新加坡一个来回 ~200 ms,close 握手还要再等一个来回。
    在生成器里同步做的话,最后不满一包的尾巴和 audio_end 都要等它 ——
    2026-09-22 实测因此拖了 ~1 s。
    """
    try:
        await ws.send(json.dumps({"type": "session.finish"}))
        await asyncio.wait_for(ws.close(), 3)
    except Exception:
        pass


def _close_in_background(ws):
    t = asyncio.get_running_loop().create_task(_close_quietly(ws))
    _closing.add(t)
    t.add_done_callback(_closing.discard)


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


async def synthesize(text: str, *, uid: str = "esp32"):
    """异步生成器,逐块产出裸 PCM。出错抛 TTSError。

    被 cancel(abort)时 finally 会在后台关掉到百炼的 WS —— 不再合成后面的字。
    """
    if not config.DASHSCOPE_API_KEY:
        raise TTSError("没配百炼密钥:设 DASHSCOPE_API_KEY")

    url = "%s?model=%s" % (config.ALI_REALTIME_URL, config.ALI_TTS_MODEL)
    headers = {"Authorization": "Bearer " + config.DASHSCOPE_API_KEY}
    t0 = time.monotonic()
    deadline = t0 + config.ALI_TTS_TIMEOUT_S
    first = None
    total = 0

    ws = None
    try:
        ws = await connect(url, additional_headers=headers, max_size=None, open_timeout=5)
        log.info("连接 %.0f ms", (time.monotonic() - t0) * 1000)
        await _expect(ws, "session.created", deadline)
        await ws.send(json.dumps({
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
        upd = await _expect(ws, "session.updated", deadline)
        sr = (upd.get("session") or {}).get("sample_rate")
        if sr is not None and sr != config.SAMPLE_RATE:
            raise TTSError("百炼没接受 sample_rate=%d(回的是 %s)" % (config.SAMPLE_RATE, sr))

        log.info("合成 %d 字 model=%s voice=%s", len(text),
                 config.ALI_TTS_MODEL, config.ALI_TTS_VOICE)
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
                        log.info("首包 %.0f ms", first * 1000)
                    total += len(pcm)
                    yield pcm

            elif typ == "response.done":
                resp = ev.get("response") or {}
                status = resp.get("status")
                if status not in (None, "completed"):
                    raise TTSError("response.done status=%s %s"
                                   % (status, resp.get("status_details")))
                usage = resp.get("usage")
                if usage:
                    log.info("用量 %s", usage)
                break
    except TTSError:
        raise
    except asyncio.TimeoutError:
        raise TTSError("百炼超时(%.0f s 内没收完)" % config.ALI_TTS_TIMEOUT_S)
    except Exception as e:
        # 握手 401/403 = 密钥错或密钥和地域对不上(北京的 key 不能连新加坡)
        raise TTSError("连百炼失败: %r" % e)
    finally:
        # 正常结束、出错、被 abort cancel 都走这里。abort 时同样要尽快关掉,不再合成后面的字。
        if ws is not None:
            _close_in_background(ws)

    ms = total * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
    log.info("合成完毕 %d B (%d ms 音频),耗时 %.0f ms",
             total, ms, (time.monotonic() - t0) * 1000)
    if total == 0:
        raise TTSError("合成成功但没有音频 —— 文本是不是全是标点?")


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
