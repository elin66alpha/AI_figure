# -*- coding: utf-8 -*-
"""Stage 6.5 自测:不用 ESP32,先确认服务器自己是对的。

    python main.py                  # 另一个终端
    python tools/smoke_echo.py

它按 AGENT.md §5.2 冒充设备跑三件事:
  1. hello/ready 握手
  2. 一个完整回合:turn_start -> N 个 100ms 帧 -> turn_end,核对回来的字节数
     和速率(必须是 1x 实时,且服务器超前不超过 BURST_MS + 一包)
  3. abort:发一半就打断,确认服务器立刻停、且**不发** audio_end

Stage 7 联调时设备那边不通,先跑这个 —— 通了就说明锅在设备侧,
不通就说明锅在服务器或防火墙。这是 AGENT.md §9.2 排查表的第一把刀。
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config                                            # noqa: E402

from websockets.asyncio.client import connect            # noqa: E402

URL = os.getenv("SMOKE_URL", "ws://127.0.0.1:%d%s" % (config.PORT, config.WS_PATH))
TURN_MS = 1000
FRAME = config.CHUNK_BYTES


def fake_pcm(ms):
    """一段可辨认的假音频:16-bit 递增锯齿。内容不重要,字节数和顺序重要。"""
    n = config.SAMPLE_RATE * ms // 1000
    return b"".join(((i * 137) & 0x7FFF).to_bytes(2, "little") for i in range(n))


async def expect_json(ws, t, timeout=5.0):
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout)
        if isinstance(msg, (bytes, bytearray)):
            raise AssertionError("等 %s 的时候收到了 binary 帧" % t)
        m = json.loads(msg)
        if m.get("t") == t:
            return m
        print("   (途中收到 %s)" % m)


async def case_full_turn(ws):
    print("\n[2] 完整回合 —— 上行 %d ms" % TURN_MS)
    pcm = fake_pcm(TURN_MS)
    await ws.send(json.dumps({"t": "turn_start"}))
    for i in range(0, len(pcm), FRAME):
        await ws.send(pcm[i:i + FRAME])
    await ws.send(json.dumps({"t": "turn_end"}))

    m = await expect_json(ws, "audio_begin")
    seq = m["seq"]
    print("   audio_begin seq=%d" % seq)

    t0 = time.monotonic()
    got = bytearray()
    worst_lead_ms = 0.0
    while True:
        msg = await asyncio.wait_for(ws.recv(), 10.0)
        if isinstance(msg, (bytes, bytearray)):
            got += msg
            # 服务器领先量 = 已发音频时长 - 已过去时间
            audio_s = len(got) / float(config.SAMPLE_RATE * config.BYTES_PER_SAMPLE)
            lead_ms = (audio_s - (time.monotonic() - t0)) * 1000
            worst_lead_ms = max(worst_lead_ms, lead_ms)
        else:
            m = json.loads(msg)
            assert m["t"] == "audio_end" and m["seq"] == seq, m
            break

    elapsed = (time.monotonic() - t0) * 1000
    print("   收回 %d 字节(送出 %d),墙钟 %.0f ms" % (len(got), len(pcm), elapsed))
    print("   服务器最大领先 %.0f ms(上限 = BURST %d + 一包 %d = %d)"
          % (worst_lead_ms, config.BURST_MS, config.CHUNK_MS,
             config.BURST_MS + config.CHUNK_MS))

    assert bytes(got) == pcm, "回来的字节和送出去的不一致"
    assert worst_lead_ms <= config.BURST_MS + config.CHUNK_MS + 30, "整形失效,推太快了"
    assert worst_lead_ms >= config.BURST_MS - 60, "首包突发没生效,设备会攒不够预缓冲"
    # 1000 ms 音频、超前 300 ms → 墙钟应该在 700 ms 上下
    assert elapsed >= TURN_MS - config.BURST_MS - 120, "整体比实时快太多"
    print("   ✓ 字节一致、速率是 1x 实时、突发余量正确")


async def case_abort(ws):
    print("\n[3] 打断 —— 收到一半就发 abort")
    pcm = fake_pcm(3000)
    await ws.send(json.dumps({"t": "turn_start"}))
    for i in range(0, len(pcm), FRAME):
        await ws.send(pcm[i:i + FRAME])
    await ws.send(json.dumps({"t": "turn_end"}))

    m = await expect_json(ws, "audio_begin")
    print("   audio_begin seq=%d" % m["seq"])

    got = 0
    while got < len(pcm) // 3:
        msg = await asyncio.wait_for(ws.recv(), 10.0)
        if isinstance(msg, (bytes, bytearray)):
            got += len(msg)

    await ws.send(json.dumps({"t": "abort"}))
    print("   已发 abort(此时收了 %d 字节)" % got)

    # abort 之后允许有几个在途帧,但必须很快停,而且不能有 audio_end
    tail = 0
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), 0.8)
            if isinstance(msg, (bytes, bytearray)):
                tail += len(msg)
            else:
                raise AssertionError("abort 之后不该再收到 %s" % msg)
    except asyncio.TimeoutError:
        pass
    print("   abort 后又收到 %d 字节的在途残帧(设备靠 seq 丢弃,AGENT.md §5.3a)" % tail)
    assert tail <= config.CHUNK_BYTES * 3, "abort 之后还在猛发,取消没生效"
    print("   ✓ 服务器已停,且没有发 audio_end")


async def main():
    print("连 %s" % URL)
    async with connect(URL, max_size=config.MAX_WS_FRAME) as ws:
        print("\n[1] 握手")
        await ws.send(json.dumps({"t": "hello", "dev": "smoke", "fw": "0.0"}))
        m = await expect_json(ws, "ready")
        assert m.get("sr") == config.SAMPLE_RATE, m
        print("   ready sr=%d  ✓" % m["sr"])

        await case_full_turn(ws)
        await case_abort(ws)

    print("\n全部通过 —— 服务器侧是好的。Stage 7 连不上就去查设备侧/防火墙。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print("\n!! 失败: %s" % e)
        sys.exit(1)
