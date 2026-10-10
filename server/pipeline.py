# -*- coding: utf-8 -*-
"""Stage 10 句级流水线:LLM 切句 -> TTS -> 下行。规格见 ../SERVER.md §3.1 / §3.2 / §6.3。

    source = pipeline.chat_audio(user_text, chat, tts_session, on_sentence=..., stats=...)
    await session._reply(source, "chat")        # 和回声、say 走同一条下行

三段各跑各的,中间用队列接起来:

    [LLM task]  流式生成 -> 切句 ----sent_q----> [TTS task] 每句 append+commit ----pcm_q----> 下行(pacer)

**为什么一定要拆成后台 task,而不是一个 async for 套一个 async for:**
pacer 是按 1x 实时从 source 里拿数据的。如果 TTS 直接挂在 pacer 下面,
那它也只能按 1x 实时往前走 —— 念完第一句才会去 commit 第二句,
这时设备缓冲里只剩 pacer 的 300 ms 余量,而 commit -> 首包要 ~0.35 s(实测),
句与句之间就会欠载断一下。拆开之后 TTS 以 ~5x 实时的速度一直往前合成,
pcm_q 里始终攒着后面的句子,pacer 从不空等。LLM 同理。

abort / 断线时 _reply 会 aclose() 这个生成器,finally 里把两个 task 都 cancel 掉、
关掉 TTS 连接 —— 不再烧 LLM token,也不再合成后面的字。
"""
import asyncio
import logging
import time

import config
import llm

log = logging.getLogger("pipeline")

_END = object()


async def chat_audio(user_text, chat, tts_session, *, on_sentence=None, stats=None):
    """异步逐块产出回复的 PCM。

    chat         llm.Chat,这台设备的对话历史
    tts_session  tts.open_session() 拿到的会话,**所有权交给这里**,结束时负责 close
    on_sentence  async 回调,每切出一句调一次(session 用它下发 {"t":"reply"})
    stats        dict,填 llm_first / tts_first(monotonic 时间戳),给 session 打延迟分解
    """
    stats = stats if stats is not None else {}
    sent_q = asyncio.Queue()
    pcm_q = asyncio.Queue()

    async def speak(s):
        if "llm_first" not in stats:
            stats["llm_first"] = time.monotonic()
        if on_sentence:
            try:
                await on_sentence(s)
            except Exception:
                pass                    # 下发调试文本失败不影响出声
        sent_q.put_nowait(s)

    async def run_llm():
        n = 0
        try:
            async for s in chat.reply(user_text):
                n += 1
                await speak(s)
        except llm.LLMError as e:
            log.warning("LLM 失败: %s", e)
            if n == 0:
                # 一个字都没出来:说句兜底的话,别让设备干等到超时
                await speak(config.LLM_FAIL_TEXT)
            # 出过声之后失败:已经念出去的就算了,正常收尾
        finally:
            sent_q.put_nowait(None)

    async def run_tts():
        try:
            while True:
                s = await sent_q.get()
                if s is None:
                    break
                async for pcm in tts_session.synth(s):
                    if "tts_first" not in stats:
                        stats["tts_first"] = time.monotonic()
                    pcm_q.put_nowait(pcm)
            pcm_q.put_nowait(_END)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            pcm_q.put_nowait(e)

    loop = asyncio.get_running_loop()
    t_llm = loop.create_task(run_llm())
    t_tts = loop.create_task(run_tts())
    try:
        while True:
            item = await pcm_q.get()
            if item is _END:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        for t in (t_llm, t_tts):
            if not t.done():
                t.cancel()
        for t in (t_llm, t_tts):
            try:
                await t
            except BaseException:
                pass
        tts_session.close()


async def one_sentence(text, tts_session):
    """用已经在建连的 TTS 会话念一句固定的话(没听清之类),结束时 close。"""
    try:
        async for pcm in tts_session.synth(text):
            yield pcm
    finally:
        tts_session.close()
