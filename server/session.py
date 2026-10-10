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
    chat  同上拿到文本 -> LLM 边生成边切句 -> 每句 {"t":"reply","text"} + TTS -> 下行(Stage 10)
          流水线见 pipeline.py。对话历史按设备 ID 存,断线重连后还在

这样设备侧 Stage 7 写的就是**最终代码**,Stage 11 传输层一行不用改;
服务器侧 Stage 8~10 只是把下面 `_echo_turn()` 里"原样送回"换成
"ASR -> LLM -> TTS",这个外壳同样不动。
"""
import asyncio
import json
import logging
import time

import asr
import config
import llm
import pacer
import pipeline
import tts

log = logging.getLogger("session")

MODES = ("echo", "asr", "chat")

# 对话历史按设备自报的 ID 存,活得比连接久:设备断线重连后接着聊。
# 进程重启就没了 —— 开发阶段不持久化(SERVER.md §5)。
_chats = {}


def chat_for(dev: str) -> llm.Chat:
    c = _chats.get(dev)
    if c is None:
        c = _chats[dev] = llm.Chat()
    return c


class EchoSession:
    def __init__(self, ws, sid: str):
        self.ws = ws
        self.sid = sid
        self.dev = "?"           # 设备自报的 ID,仅用于日志
        self.seq = 0             # 回合号。AGENT.md §5.3(a)
        self.recording = False
        self.buf = bytearray()   # 本回合录音,只有 echo 模式要攒(要原样送回)
        self.nbytes = 0          # 本回合收到的音频字节数,所有模式都记
        self.task = None         # 在途的回送任务
        self.dropped = 0         # 非录音期收到的 binary 帧数
        self.first_frame_logged = False
        self.mode = config.REPLY_MODE
        self.asr = None          # 本回合的 ASR 流(asr 模式下 turn_start 就开)
        self.tts_pre = None      # 本回合预热的 TTS 会话(chat 模式下 turn_start 就开,Stage 11)

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

        if self.nbytes + len(data) > config.MAX_TURN_BYTES:
            return                      # 超长回合,静默截断
        self.nbytes += len(data)
        if self.mode == "echo":
            self.buf += data            # asr/chat 模式直接流给 ASR,不必再攒一份(最长 ~960 KB)
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
            self.nbytes = 0
            self.recording = True
            self.first_frame_logged = False
            self.mode = m.get("mode") or config.REPLY_MODE
            if self.mode not in MODES:
                log.warning("[%s] 未知 mode=%r,按 echo 处理", self.sid, self.mode)
                self.mode = "echo"
            if self.mode != "echo":
                try:
                    # 现在就建连,跨洋握手藏进用户说话的时间里(asr.py 开头的说明)
                    self.asr = asr.open_stream(self.dev)
                except ValueError as e:
                    await self.send_json(t="error", code="asr_failed", msg=str(e))
                    self.mode = "echo"
            if self.mode == "chat":
                llm.prewarm()           # 到 LLM 的连接同理,藏进用户说话的时间里
                if config.TTS_PREWARM:
                    try:
                        self.tts_pre = tts.open_session(self.dev)
                    except ValueError as e:
                        log.warning("[%s] TTS 预热失败: %s", self.sid, e)
            log.info("[%s] turn_start mode=%s", self.sid, self.mode)

        elif t == "turn_end":
            self.recording = False
            self.t_end = time.monotonic()
            ms = self.nbytes * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
            log.info("[%s] turn_end — 收到 %d 字节 (%d ms)", self.sid, self.nbytes, ms)
            stream, self.asr = self.asr, None
            ts, self.tts_pre = self.tts_pre, None
            if not self.nbytes:
                if stream:
                    await stream.cancel()
                if ts:
                    ts.close()
                await self.send_json(t="error", code="empty_turn", msg="没有收到任何音频")
                return
            if config.CUE_THINKING:
                # 越早越好:设备一松手就能听到"我在想"。服务器此刻还不知道要等多久。
                await self.send_json(t="cue", name="thinking")
            if stream:
                self.task = asyncio.create_task(self._asr_turn(stream, ts))
            else:
                if ts:
                    ts.close()
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

    async def _asr_turn(self, stream, ts=None):
        """ASR 最终文本 -> {"t":"asr"} -> 按 mode 回复。

        asr   念"我听到的是:…"(Stage 9)
        chat  LLM -> 切句 -> TTS(Stage 10)。ts 是 turn_start 时预热好的 TTS 会话
              (Stage 11);没开预热就在这里开,和 ASR 收尾 / LLM 首句并行
        """
        mode = self.mode
        if mode == "chat" and ts is None:
            ts = tts.open_session(self.dev)
        try:
            text = await stream.finish()
        except asyncio.CancelledError:
            await stream.cancel()
            if ts:
                ts.close()
            raise
        except Exception as e:
            if ts:
                ts.close()
            log.warning("[%s] ASR 失败: %s", self.sid, e)
            await self.send_json(t="error", code="asr_failed", msg=str(e)[:200])
            return
        t_asr = time.monotonic()
        log.info("[%s] ASR(%.0f ms): %r", self.sid, (t_asr - self.t_end) * 1000, text)
        await self.send_json(t="asr", text=text)

        if mode == "asr":
            if not text.strip():
                await self.send_json(t="error", code="asr_empty", msg="没听清")
                return
            await self._reply(tts.synthesize("我听到的是:" + text, uid=self.dev), "tts")
            return

        # ---- chat
        if not text.strip():
            # 没听清也要出声,别让设备干等到 WAITING 超时
            await self._reply(pipeline.one_sentence(config.NOT_HEARD_TEXT, ts), "chat")
            return

        async def on_sentence(sent):
            await self.send_json(t="reply", text=sent)

        stats = {}
        await self._reply(pipeline.chat_audio(text, chat_for(self.dev), ts,
                                              on_sentence=on_sentence, stats=stats), "chat")
        # 延迟分解:turn_end 为 0 点。设备真正出声还要再加设备侧预缓冲(~300 ms)
        ms = lambda k: "%.0f" % ((stats[k] - self.t_end) * 1000) if k in stats else "-"
        log.info("[%s] 延迟(ms,turn_end 起) ASR=%.0f  LLM首句=%s  TTS首包=%s",
                 self.sid, (t_asr - self.t_end) * 1000, ms("llm_first"), ms("tts_first"))

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
            # 显式关掉 source:abort 时 pacer 可能正停在两包之间,source 挂在 yield 上,
            # 不 aclose 的话它的 finally(取消 LLM/TTS、关厂商连接)要等 GC 才跑。
            aclose = getattr(source, "aclose", None)
            if aclose:
                try:
                    await aclose()
                except BaseException:
                    pass
            self.task = None

    async def _cancel_turn(self, why: str):
        stream, self.asr = self.asr, None
        if stream:
            await stream.cancel()       # 录音中途被打断/断线:别让到厂商的连接挂着
        ts, self.tts_pre = self.tts_pre, None
        if ts:
            ts.close()
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
