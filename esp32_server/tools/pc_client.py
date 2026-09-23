# -*- coding: utf-8 -*-
"""PC 端假设备。说 AGENT.md §5 那套 WS 协议。规格见 SERVER.md §6。

Stage 8~10 全部用它调通,ESP32 一次都不用烧。设备侧实现有歧义时以它的行为为准。

    # Stage 8:文本 -> 服务器 TTS -> 存 wav
    python tools/pc_client.py say "你好,今天天气怎么样?" -o reply.wav

    # Stage 7:wav -> 按 100 ms 切片走完整回合 -> 存回复(默认用服务器的 REPLY_MODE)
    python tools/pc_client.py turn input.wav -o reply.wav

    # Stage 9:同上,但让服务器走 ASR,打印识别文本,回复是"我听到的是:…"
    python tools/pc_client.py turn input.wav --mode asr
    python tools/pc_client.py turn input.wav --abort-after 500     # 收到 500 ms 就打断

连线上 VPS:Python 只听环回口,先开隧道再跑(不用 PSK):
    ssh -N -L 8765:127.0.0.1:8765 <vps>
或者 --url 指向任何 ws:// 地址。

输入 wav 必须是 16 kHz / 16 bit / 单声道 —— 设备侧不做格式协商,这里也不做重采样。
"""
import argparse
import asyncio
import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config                                            # noqa: E402

from websockets.asyncio.client import connect            # noqa: E402

BPS = config.SAMPLE_RATE * config.BYTES_PER_SAMPLE       # 每秒字节数


def ms(nbytes):
    return nbytes * 1000 // BPS


def read_wav(path):
    with wave.open(path, "rb") as w:
        fmt = (w.getframerate(), w.getsampwidth(), w.getnchannels())
        if fmt != (config.SAMPLE_RATE, config.BYTES_PER_SAMPLE, 1):
            sys.exit("!! %s 是 %d Hz / %d bit / %d ch,要 16000 Hz / 16 bit / 1 ch\n"
                     "   ffmpeg -i in.wav -ar 16000 -ac 1 -sample_fmt s16 out.wav"
                     % (path, fmt[0], fmt[1] * 8, fmt[2]))
        return w.readframes(w.getnframes())


def write_wav(path, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(config.BYTES_PER_SAMPLE)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)


async def send_json(ws, **obj):
    await ws.send(json.dumps(obj, ensure_ascii=False))


async def collect_reply(ws, t_req, abort_after_ms=None):
    """收一个回复回合。像设备一样按 seq 丢弃过期帧。返回 (pcm, 是否正常结束)。"""
    seq = None
    pcm = bytearray()
    stale = 0
    t_first = None
    while True:
        try:
            msg = await asyncio.wait_for(ws.recv(), 30.0)
        except asyncio.TimeoutError:
            print("!! 30 s 没动静")
            return bytes(pcm), False
        now = time.monotonic()

        if isinstance(msg, (bytes, bytearray)):
            if seq is None:
                stale += len(msg)           # audio_begin 之前 / abort 之后的残帧
                continue
            if t_first is None:
                t_first = now
                print("   首个音频帧:请求后 %.0f ms" % ((now - t_req) * 1000))
            pcm += msg
            if abort_after_ms is not None and ms(len(pcm)) >= abort_after_ms:
                await send_json(ws, t="abort")
                print("   已发 abort(收到 %d ms)" % ms(len(pcm)))
                seq = None
                abort_after_ms = None
                # 等残帧流完。abort 之后服务器不该再发 audio_end。
                try:
                    while True:
                        m = await asyncio.wait_for(ws.recv(), 1.0)
                        if isinstance(m, (bytes, bytearray)):
                            stale += len(m)
                        else:
                            print("   !! abort 之后还收到 %s" % m)
                except asyncio.TimeoutError:
                    pass
                print("   abort 后丢弃残帧 %d B" % stale)
                return bytes(pcm), False
            continue

        m = json.loads(msg)
        t = m.get("t")
        if t == "audio_begin":
            seq = m.get("seq")
            print("   audio_begin seq=%s(请求后 %.0f ms)" % (seq, (now - t_req) * 1000))
        elif t == "audio_end":
            if m.get("seq") != seq:
                print("   (过期的 audio_end seq=%s,忽略)" % m.get("seq"))
                continue
            dur = (now - t_first) * 1000 if t_first else 0
            print("   audio_end seq=%s —— %d B = %d ms 音频,收了 %.0f ms"
                  % (seq, len(pcm), ms(len(pcm)), dur))
            if stale:
                print("   丢弃了 %d B 不属于本回合的帧" % stale)
            return bytes(pcm), True
        elif t == "asr":
            print("   ASR:%s(turn_end 后 %.0f ms)" % (m.get("text"), (now - t_req) * 1000))
        elif t == "error":
            print("   !! error %s: %s" % (m.get("code"), m.get("msg")))
            if seq is None:                  # 出声之前就失败,不会再有 audio_end
                return bytes(pcm), False
        else:
            print("   %s" % m)


async def run(args):
    print("连 %s" % args.url)
    async with connect(args.url, max_size=config.MAX_WS_FRAME) as ws:
        await send_json(ws, t="hello", dev=args.dev, fw="pc_client")
        m = json.loads(await asyncio.wait_for(ws.recv(), 5.0))
        if m.get("t") != "ready":
            sys.exit("!! 握手回的是 %s" % m)
        print("ready sr=%s" % m.get("sr"))

        if args.cmd == "say":
            print("\nsay %r" % args.text)
            t_req = time.monotonic()
            await send_json(ws, t="say", text=args.text)
        else:
            pcm = read_wav(args.wav)
            print("\nturn %s(%d ms)" % (args.wav, ms(len(pcm))))
            if args.mode:
                await send_json(ws, t="turn_start", mode=args.mode)
            else:
                await send_json(ws, t="turn_start")
            # 像设备一样按实时速率上送;--fast 就一口气推完
            t0 = time.monotonic()
            for i in range(0, len(pcm), config.CHUNK_BYTES):
                await ws.send(pcm[i:i + config.CHUNK_BYTES])
                if not args.fast:
                    lag = t0 + (i + config.CHUNK_BYTES) / BPS - time.monotonic()
                    if lag > 0:
                        await asyncio.sleep(lag)
            t_req = time.monotonic()
            await send_json(ws, t="turn_end")

        reply, ok = await collect_reply(ws, t_req, args.abort_after)

    if reply and args.out:
        write_wav(args.out, reply)
        print("\n写入 %s" % args.out)
    return 0 if ok or args.abort_after is not None else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.getenv(
        "PC_CLIENT_URL", "ws://127.0.0.1:%d%s" % (config.PORT, config.WS_PATH)))
    ap.add_argument("--dev", default="pc")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("say", help="文本 -> TTS(Stage 8)")
    p.add_argument("text")

    p = sub.add_parser("turn", help="wav -> 完整回合")
    p.add_argument("wav")
    p.add_argument("--fast", action="store_true", help="不按实时速率上送")
    p.add_argument("--mode", choices=("echo", "asr"),
                   help="覆盖服务器的 REPLY_MODE(设备不发这个字段)")

    for p in sub.choices.values():
        p.add_argument("-o", "--out", default="reply.wav")
        p.add_argument("--abort-after", type=int, metavar="MS",
                       help="收到这么多毫秒的音频就发 abort")

    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
