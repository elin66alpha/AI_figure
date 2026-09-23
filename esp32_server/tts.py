# -*- coding: utf-8 -*-
"""TTS 厂商分派。session.py 只认这一个入口,换厂商 = 改 TTS_PROVIDER。

    ali   阿里云百炼 qwen3-tts-flash-realtime(默认)   ali_tts.py
    volc  火山豆包语音合成                              volc_tts.py

两边的 synthesize(text, uid=) 签名一致:异步逐块产出 16 kHz PCM16LE,出错抛异常。
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
