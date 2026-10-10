# -*- coding: utf-8 -*-
"""TTS 厂商分派。session.py 只认这一个入口,换厂商 = 改 TTS_PROVIDER。

    ali   阿里云百炼 qwen3-tts-flash-realtime(默认)   ali_tts.py
    volc  火山豆包语音合成                              volc_tts.py

两边接口一致:
    synthesize(text, uid=)     一次性合成一段,异步逐块产出 16 kHz PCM16LE(Stage 8 的 say)
    open_session(uid)          一条连接顺序念多句:.start() / .synth(text) / .close()(Stage 10)
"""
import config


def synthesize(text: str, *, uid: str = "esp32"):
    if config.TTS_PROVIDER == "volc":
        import volc_tts
        return volc_tts.synthesize(text, uid=uid)
    if config.TTS_PROVIDER == "ali":
        import ali_tts
        return ali_tts.synthesize(text, uid=uid)
    raise ValueError("未知 TTS_PROVIDER=%r(可选 ali / volc)" % config.TTS_PROVIDER)


def open_session(uid: str = "esp32"):
    """开一个多句合成会话,并立刻在后台开始建连。"""
    if config.TTS_PROVIDER == "volc":
        import volc_tts
        return volc_tts.VolcTtsSession(uid).start()
    if config.TTS_PROVIDER == "ali":
        import ali_tts
        return ali_tts.AliTtsSession(uid).start()
    raise ValueError("未知 TTS_PROVIDER=%r(可选 ali / volc)" % config.TTS_PROVIDER)
