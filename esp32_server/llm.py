# -*- coding: utf-8 -*-
"""LLM:流式对话 + 句子切分。规格见 ../SERVER.md §3.2 / §5。

两家都是 OpenAI 兼容的 POST /chat/completions(stream=true, SSE),一套代码,
只换地址、密钥、模型。LLM_PROVIDER 选:

    qwen      阿里云百炼 Qwen(默认,和 ASR/TTS 共用 DASHSCOPE_API_KEY)
    deepseek  DeepSeek

    chat = llm.Chat()                          # 每台设备一个,里面存对话历史
    async for sentence in chat.reply("你好"):   # 边生成边切句,切出一句给一句
        ...                                    # Stage 10:每句立刻送 TTS

单独自测(多个参数 = 多轮,验对话历史):

    python llm.py "我叫小明" "我叫什么名字?"
"""
import asyncio
import json
import logging
import time

import aiohttp

import config

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


# ---------------------------------------------------------------- 厂商
def _endpoint():
    """-> (base_url, api_key, model, 额外请求字段)"""
    p = config.LLM_PROVIDER
    if p == "qwen":
        # Qwen3 系列是混合思考模型;不关的话会先"想"一段才出字,首字延迟翻倍
        return (config.QWEN_BASE_URL.rstrip("/"),
                config.QWEN_API_KEY, config.QWEN_MODEL, {"enable_thinking": False})
    if p == "deepseek":
        return (config.DEEPSEEK_BASE_URL.rstrip("/"),
                config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL, {})
    raise LLMError("未知 LLM_PROVIDER=%r(可选 qwen / deepseek)" % p)


# aiohttp 连接池全局常驻:keep-alive 省掉每回合的 TLS 握手(SERVER.md §3.4)。
#
# ⚠️ aiohttp 默认只让空闲连接活 15 s。真机上"上一次 LLM 请求结束 -> 放完回复 -> 用户想 ->
# 按键说完"通常超过 15 s,连接早被关了,每回合都要重新跨洋 TCP+TLS 握手(~2 RTT)。
# 所以:空闲超时拉长 + turn_start 时 prewarm(),把建连藏进用户说话的时间里。
_http = None
_warming = None                           # prewarm 的后台 task,留引用防止被 GC


def _session():
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(keepalive_timeout=config.LLM_KEEPALIVE_S),
            timeout=aiohttp.ClientTimeout(
                total=None, sock_connect=5, sock_read=config.LLM_TIMEOUT_S))
    return _http


def prewarm():
    """turn_start 时调(chat 模式):后台把到 LLM 的连接建好,不耗 token。

    发一个 HEAD /models —— 状态码是什么都无所谓(200 / 401 / 405 都行),
    要的只是它留在连接池里的那条 TCP+TLS 连接。连接本来就热的话只花 1 个 RTT,
    顺带刷新了空闲计时。失败静默:大不了 turn_end 时照旧现场建连,和没预热一样。
    """
    global _warming
    if not config.LLM_PREWARM or (_warming is not None and not _warming.done()):
        return
    try:
        base, key, _, _ = _endpoint()
    except LLMError:
        return
    if not key:
        return
    _warming = asyncio.get_running_loop().create_task(_warm(base + "/models", key))


async def _warm(url, key):
    t0 = time.monotonic()
    try:
        async with _session().head(url, headers={"Authorization": "Bearer " + key}) as r:
            pass                          # HEAD 没有 body,退出 with 连接就回到池里
        log.info("%s 连接预热 %.0f ms(HTTP %d)", config.LLM_PROVIDER,
                 (time.monotonic() - t0) * 1000, r.status)
    except Exception as e:
        log.info("%s 连接预热失败(不影响回合): %r", config.LLM_PROVIDER, e)


async def close():
    if _http is not None and not _http.closed:
        await _http.close()


async def stream_tokens(messages):
    """异步逐段产出模型生成的文本(delta.content)。"""
    base, key, model, extra = _endpoint()
    url = base + "/chat/completions"
    if not key:
        raise LLMError("没配 %s 的 API Key" % config.LLM_PROVIDER)
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": config.LLM_MAX_TOKENS,
        **extra,
    }
    try:
        async with _session().post(url, json=body,
                                   headers={"Authorization": "Bearer " + key}) as r:
            if r.status != 200:
                raise LLMError("%s HTTP %d: %s" % (config.LLM_PROVIDER, r.status,
                                                   (await r.text())[:300]))
            async for raw in r.content:          # SSE:一行一个事件
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise LLMError("%s 流中报错: %s" % (config.LLM_PROVIDER, ev["error"]))
                for ch in ev.get("choices") or ():
                    # 只要 content;reasoning_content(思考过程)不念
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        yield piece
    except LLMError:
        raise
    except asyncio.TimeoutError:
        raise LLMError("%s 超时(%.0f s 没有新数据)" % (config.LLM_PROVIDER, config.LLM_TIMEOUT_S))
    except aiohttp.ClientError as e:
        raise LLMError("%s 连接失败: %r" % (config.LLM_PROVIDER, e))


# ---------------------------------------------------------------- 切句
_TERMINAL = "。！？；!?;\n"
_CLOSERS = "”’」』）)】\"'"          # 句末标点后面紧跟的这些归前一句
_STRIP = "*#`>"                     # Markdown 残渣,念出来是噪音


class SentenceSplitter:
    """流式切句。SERVER.md §3.2 的规则:

    - 句末标点 。！？；!?; 和换行处切
    - 第一句 >= FIRST_MIN 字就切(降首包延迟),之后 >= LATER_MIN 字才切(少开几次 TTS)
    - 英文句点只在后面是空白时才算句末,`3.14`、`v1.2` 里的点不切
    - 省略号 …… 不是句末
    - 流结束时 flush() 把不足一句的尾巴也吐出来
    """
    FIRST_MIN = 6
    LATER_MIN = 20

    def __init__(self):
        self.buf = ""
        self.count = 0

    def _min(self):
        return self.FIRST_MIN if self.count == 0 else self.LATER_MIN

    def feed(self, text: str):
        self.buf += "".join(c for c in text if c not in _STRIP)
        out = []
        i = 0
        while i < len(self.buf):
            c = self.buf[i]
            end = None
            if c in _TERMINAL:
                end = i + 1
            elif c == ".":
                if i + 1 >= len(self.buf):
                    break                         # 后一个字还没到,等下一段再判
                if self.buf[i + 1].isspace() and not (i > 0 and self.buf[i - 1].isdigit()):
                    end = i + 1
            if end is not None:
                while end < len(self.buf) and self.buf[end] in _CLOSERS:
                    end += 1
                sent = self.buf[:end].strip()
                if len(sent) >= self._min():
                    out.append(sent)
                    self.count += 1
                    self.buf = self.buf[end:]
                    i = 0
                    continue
            i += 1
        return out

    def flush(self):
        rest = self.buf.strip()
        self.buf = ""
        if rest:
            self.count += 1
            return [rest]
        return []


# ---------------------------------------------------------------- 对话
class Chat:
    """一台设备一条对话历史。内存里存,不持久化(SERVER.md §5)。"""

    def __init__(self):
        self.history = []                 # [{"role":..., "content":...}, ...]

    def _messages(self, user_text):
        keep = self.history[-2 * config.LLM_HISTORY_TURNS:] if config.LLM_HISTORY_TURNS > 0 else []
        return ([{"role": "system", "content": config.LLM_SYSTEM_PROMPT}]
                + keep + [{"role": "user", "content": user_text}])

    async def reply(self, user_text: str):
        """异步逐句产出回复。被 cancel(abort)时,已生成的部分照样记进历史。"""
        t0 = time.monotonic()
        first = None
        full = []
        sp = SentenceSplitter()
        try:
            async for piece in stream_tokens(self._messages(user_text)):
                if first is None:
                    first = time.monotonic() - t0
                    log.info("%s 首 token %.0f ms", config.LLM_PROVIDER, first * 1000)
                full.append(piece)
                for s in sp.feed(piece):
                    yield s
            for s in sp.flush():
                yield s
        finally:
            answer = "".join(full).strip()
            if answer:
                self.history += [{"role": "user", "content": user_text},
                                 {"role": "assistant", "content": answer}]
                self.history = self.history[-2 * max(config.LLM_HISTORY_TURNS, 1):]
            log.info("%s 回复 %d 字,耗时 %.0f ms", config.LLM_PROVIDER, len(answer),
                     (time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------- 自测
async def _main(turns):
    chat = Chat()
    _, _, model, _ = _endpoint()
    print("provider=%s model=%s" % (config.LLM_PROVIDER, model))
    try:
        for q in turns:
            print("\n> %s" % q)
            t0 = time.monotonic()
            async for s in chat.reply(q):
                print("  [%5.0f ms] %s" % ((time.monotonic() - t0) * 1000, s))
    finally:
        await close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1:]))
