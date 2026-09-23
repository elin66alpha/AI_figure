# -*- coding: utf-8 -*-
"""每条设备连接一个 Session。Stage 6.5 = **协议级回声**。

"协议级"的意思是:它说全套 AGENT.md §5.2 的话,而不是把字节原样弹回去。
    hello       -> ready
    turn_start  -> 开始收集 PCM
    binary      -> 攒进本回合缓冲
    turn_end    -> seq++ -> audio_begin(seq) -> 按 pacer 整形回送 -> audio_end(seq)
    abort       -> seq++ -> 立刻取消在途音频,不发 audio_end
    say         -> (Stage 8 调试入口,设备不发)文本 -> TTS(tts.py 分派厂商)-> 同一套下行

回合结束后回什么由 REPLY_MODE 决定(config.py),pc_client 可在 turn_start 里带 mode 临时覆盖:
    echo  原样送回(Stage 7)
    asr   turn_start 就开 ASR 流、边收边转发;turn_end 拿最终文本 -> {"t":"asr","text"}
          -> TTS 念"我听到的是:…"(Stage 9)。设备会静默忽略 {"t":"asr"}(AGENT.md §5.2)

这样设备侧 Stage 7 写的就是**最终代码**,Stage 11 传输层一行不用改;
服务器侧 Stage 8~10 只是把下面 `_echo_turn()` 里"原样送回"换成
"ASR -> LLM -> TTS",这个外壳同样不动。
"""
import asyncio
import json
import logging

import asr
import config
import pacer
import tts

log = logging.getLogger("session")


class EchoSession:
    def __init__(self, ws, sid: str):
        self.ws = ws
        self.sid = sid
        self.dev = "?"           # 设备自报的 ID,仅用于日志
        self.seq = 0             # 回合号。AGENT.md §5.3(a)
        self.recording = False
        self.buf = bytearray()
        self.task = None         # 在途的回送任务
        self.dropped = 0         # 非录音期收到的 binary 帧数
        self.first_frame_logged = False
        self.mode = config.REPLY_MODE
        self.asr = None          # 本回合的 ASR 流(asr 模式下 turn_start 就开)

    # ------------------------------------------------------------ 出口
    async def send_json(self, **obj):
        await self.ws.send(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))

    # ------------------------------------------------------------ 主循环
    async def run(self):
        log.info("[%s] 连接建立", self.sid)
        try:
            async for msg in self.ws:
                if isinstance(msg, (bytes, bytearray)):
                    self._on_audio(msg)
                else:
                    await self._on_text(msg)
        finally:
            await self._cancel_turn("连接关闭")
            log.info("[%s] 连接结束 (dev=%s, seq=%d, 丢弃的野帧=%d)",
                     self.sid, self.dev, self.seq, self.dropped)

    # ------------------------------------------------------------ 上行
    def _on_audio(self, data: bytes):
        if not self.recording:
            # turn_end 之后、下一个 turn_start 之前收到的音频。
            # 设备侧按键抖动或网络乱序都可能造成,丢掉即可,但要记数。
            self.dropped += 1
            return

        if not self.first_frame_logged:
            # AGENT.md §9.2 排查表第 3 行:第一帧的尺寸对不对,一眼就能定位上行打包问题。
            self.first_frame_logged = True
            mark = "ok" if len(data) == config.CHUNK_BYTES else "!! 期望 %d" % config.CHUNK_BYTES
            log.info("[%s] 首个音频帧 %d 字节 (%s)", self.sid, len(data), mark)

        if len(self.buf) + len(data) > config.MAX_TURN_BYTES:
            return                      # 超长回合,静默截断
        self.buf += data
        if self.asr:
            self.asr.feed(data)

    async def _on_text(self, raw: str):
        try:
            m = json.loads(raw)
            t = m.get("t")
        except Exception:
            log.warning("[%s] 收到非 JSON 文本帧: %r", self.sid, raw[:80])
            return

        if t == "hello":
            self.dev = str(m.get("dev", "?"))
            log.info("[%s] hello dev=%s fw=%s", self.sid, self.dev, m.get("fw"))
            await self.send_json(t="ready", sr=config.SAMPLE_RATE)

        elif t == "turn_start":
            await self._cancel_turn("新回合开始")
            self.buf = bytearray()
            self.recording = True
            self.first_frame_logged = False
            self.mode = m.get("mode") or config.REPLY_MODE
            if self.mode not in ("echo", "asr"):
                log.warning("[%s] 未知 mode=%r,按 echo 处理", self.sid, self.mode)
                self.mode = "echo"
            if self.mode != "echo":
                try:
                    # 现在就建连,跨洋握手藏进用户说话的时间里(asr.py 开头的说明)
                    self.asr = asr.open_stream(self.dev)
                except ValueError as e:
                    await self.send_json(t="error", code="asr_failed", msg=str(e))
                    self.mode = "echo"
            log.info("[%s] turn_start mode=%s", self.sid, self.mode)

        elif t == "turn_end":
            self.recording = False
            ms = len(self.buf) * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
            log.info("[%s] turn_end — 收到 %d 字节 (%d ms)", self.sid, len(self.buf), ms)
            stream, self.asr = self.asr, None
            if not self.buf:
                if stream:
                    await stream.cancel()
                await self.send_json(t="error", code="empty_turn", msg="没有收到任何音频")
            elif stream:
                self.task = asyncio.create_task(self._asr_turn(stream))
            else:
                self.task = asyncio.create_task(self._echo_turn(bytes(self.buf)))

        elif t == "abort":
            # AGENT.md §5.3(c):打断不掐连接。seq++ 让设备丢弃在途的残帧。
            self.recording = False
            self.seq += 1
            await self._cancel_turn("abort")
            log.info("[%s] abort -> seq=%d", self.sid, self.seq)

        elif t == "say" and config.ALLOW_SAY:
            # Stage 8:tools/pc_client.py 发文本,服务器 TTS 后按正常回合下发。
            # 走的是和回声**同一条**下行路径,Stage 11 换成真回复时这条已经验过了。
            text = str(m.get("text", "")).strip()[:config.MAX_SAY_CHARS]
            if not text:
                await self.send_json(t="error", code="empty_say", msg="text 为空")
                return
            await self._cancel_turn("say")
            log.info("[%s] say %r", self.sid, text[:40])
            self.task = asyncio.create_task(
                self._reply(tts.synthesize(text, uid=self.dev), "tts"))

        else:
            log.info("[%s] 忽略未知消息 t=%r", self.sid, t)

    # ------------------------------------------------------------ 下行
    async def _echo_turn(self, pcm: bytes):
        """Stage 8~10 要替换的就是这里:把"原样送回"换成 ASR -> LLM -> TTS。"""
        async def once():
            yield pcm
        await self._reply(once(), "回声")

    async def _asr_turn(self, stream):
        """Stage 9:ASR 最终文本 -> {"t":"asr"} -> TTS 念回去。Stage 10 在这里接 LLM。"""
        try:
            text = await stream.finish()
        except asyncio.CancelledError:
            await stream.cancel()
            raise
        except Exception as e:
            log.warning("[%s] ASR 失败: %s", self.sid, e)
            await self.send_json(t="error", code="asr_failed", msg=str(e)[:200])
            return
        log.info("[%s] ASR: %r", self.sid, text)
        await self.send_json(t="asr", text=text)
        if not text.strip():
            await self.send_json(t="error", code="asr_empty", msg="没听清")
            return
        await self._reply(tts.synthesize("我听到的是:" + text, uid=self.dev), "tts")

    async def _reply(self, source, what: str):
        """一次下行回复:audio_begin(seq) -> 整形后的 PCM -> audio_end(seq)。

        source 是 PCM 的异步迭代器。**先等到第一块音频才发 audio_begin** ——
        上游(TTS)在出声之前就失败的话,设备只会收到一个 error,
        而不是一个空回合。出声之后才失败,照常收尾 audio_end 再报 error,
        设备不会卡在 PLAYING 里等一个永远不来的结束。
        """
        self.seq += 1
        seq = self.seq
        began = False
        try:
            if config.SEND_CUE:
                await self.send_json(t="cue", name="thinking")
            it = source.__aiter__()
            try:
                first = await it.__anext__()
            except StopAsyncIteration:
                first = b""

            async def rest():
                if first:
                    yield first
                async for c in it:
                    yield c

            await self.send_json(t="audio_begin", seq=seq)
            began = True
            n = await pacer.pace_stream(self.ws.send, rest())
            await self.send_json(t="audio_end", seq=seq)
            log.info("[%s] seq=%d %s下发完毕 %d 字节", self.sid, seq, what, n)
        except asyncio.CancelledError:
            log.info("[%s] seq=%d 被取消 —— 不发 audio_end", self.sid, seq)
            raise
        except Exception as e:
            log.warning("[%s] seq=%d %s失败: %s", self.sid, seq, what, e)
            try:
                if began:
                    await self.send_json(t="audio_end", seq=seq)
                await self.send_json(t="error", code=what + "_failed", msg=str(e)[:200])
            except Exception:
                pass                    # 连接已经没了
        finally:
            self.task = None

    async def _cancel_turn(self, why: str):
        stream, self.asr = self.asr, None
        if stream:
            await stream.cancel()       # 录音中途被打断/断线:别让到厂商的连接挂着
        t = self.task
        if t and not t.done():
            log.info("[%s] 取消在途音频 (%s)", self.sid, why)
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self.task = None
