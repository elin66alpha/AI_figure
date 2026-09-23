# -*- coding: utf-8 -*-
"""每条设备连接一个 Session。Stage 6.5 = **协议级回声**。

"协议级"的意思是:它说全套 AGENT.md §5.2 的话,而不是把字节原样弹回去。
    hello       -> ready
    turn_start  -> 开始收集 PCM
    binary      -> 攒进本回合缓冲
    turn_end    -> seq++ -> audio_begin(seq) -> 按 pacer 整形回送 -> audio_end(seq)
    abort       -> seq++ -> 立刻取消在途音频,不发 audio_end

这样设备侧 Stage 7 写的就是**最终代码**,Stage 11 传输层一行不用改;
服务器侧 Stage 8~10 只是把下面 `_echo_turn()` 里"原样送回"换成
"ASR -> LLM -> TTS",这个外壳同样不动。
"""
import asyncio
import json
import logging

import config
import pacer

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
            log.info("[%s] turn_start", self.sid)

        elif t == "turn_end":
            self.recording = False
            ms = len(self.buf) * 1000 // (config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
            log.info("[%s] turn_end — 收到 %d 字节 (%d ms)", self.sid, len(self.buf), ms)
            if self.buf:
                self.task = asyncio.create_task(self._echo_turn(bytes(self.buf)))
            else:
                await self.send_json(t="error", code="empty_turn", msg="没有收到任何音频")

        elif t == "abort":
            # AGENT.md §5.3(c):打断不掐连接。seq++ 让设备丢弃在途的残帧。
            self.recording = False
            self.seq += 1
            await self._cancel_turn("abort")
            log.info("[%s] abort -> seq=%d", self.sid, self.seq)

        else:
            log.info("[%s] 忽略未知消息 t=%r", self.sid, t)

    # ------------------------------------------------------------ 下行
    async def _echo_turn(self, pcm: bytes):
        """Stage 8~10 要替换的就是这个函数体,外面的一切都不用动。"""
        self.seq += 1
        seq = self.seq
        try:
            if config.SEND_CUE:
                await self.send_json(t="cue", name="thinking")
            await self.send_json(t="audio_begin", seq=seq)
            n = await pacer.pace_pcm(self.ws.send, pcm)
            await self.send_json(t="audio_end", seq=seq)
            log.info("[%s] seq=%d 回送完毕 %d 字节", self.sid, seq, n)
        except asyncio.CancelledError:
            log.info("[%s] seq=%d 被取消 —— 不发 audio_end", self.sid, seq)
            raise
        except Exception as e:
            log.warning("[%s] seq=%d 回送失败: %r", self.sid, seq, e)
        finally:
            self.task = None

    async def _cancel_turn(self, why: str):
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
