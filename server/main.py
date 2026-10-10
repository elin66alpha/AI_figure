# -*- coding: utf-8 -*-
"""Stage 6.5 — 回声服务器入口。

    python main.py

rev.5 起默认按**公网 VPS + stunnel(TLS-PSK)**部署:

    设备 --wss://域名:443--> stunnel --明文--> 本进程 127.0.0.1:8765

所以这个进程默认只监听环回口。能走到这里的连接**都已经过了 PSK 握手**
(AGENT.md §7.4:密钥即身份),本层不再做鉴权。
部署步骤见 deploy/README.md。

局域网直连的老玩法还在,加一个环境变量就行:

    ESP32_SERVER_HOST=0.0.0.0 python main.py

Stage 8~10 往 session.py 里加 ASR/LLM/TTS,这个文件基本不用动。
"""
import asyncio
import logging
import socket
import sys
from http import HTTPStatus

import config
from session import EchoSession

try:
    from websockets.asyncio.server import serve
except ImportError:                       # websockets < 13
    print("需要 websockets >= 14:  pip install -r requirements.txt", file=sys.stderr)
    raise

log = logging.getLogger("main")
_counter = 0
_live = 0                                  # 当前在线连接数


def local_ipv4s():
    """列出本机所有 IPv4。用 UDP connect 的办法拿到"出口"那一张网卡的地址。

    只在 HOST=0.0.0.0(局域网直连模式)下才有意义 —— 公网 VPS 上出口地址往往是
    内网地址,设备要连的是域名,不是这里打出来的东西。
    """
    addrs = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))        # 不会真的发包
        addrs.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addrs:
                addrs.append(ip)
    except OSError:
        pass
    return addrs


def process_request(connection, request):
    """握手阶段的门卫。在这里拒绝比放进 Session 再关干净 —— 公网上扫描器很多。"""
    if config.STRICT_PATH and request.path != config.WS_PATH:
        log.warning("路径 %r 不是约定的 %r —— 拒绝", request.path[:60], config.WS_PATH)
        return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
    if _live >= config.MAX_CONNECTIONS:
        log.warning("在线连接已达上限 %d —— 拒绝新连接", config.MAX_CONNECTIONS)
        return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")
    return None


async def handler(ws):
    global _counter, _live
    _counter += 1
    _live += 1
    sid = "c%03d" % _counter
    path = getattr(getattr(ws, "request", None), "path", "?")
    if path != config.WS_PATH:
        # STRICT_PATH=0 时才可能走到这里。
        log.warning("[%s] 连接路径是 %r,设备侧约定的是 %r —— 先放行,但对一下",
                    sid, path, config.WS_PATH)
    try:
        await EchoSession(ws, sid).run()
    finally:
        _live -= 1


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("Stage 6.5 回声服务器 —— 协议级回声,不依赖任何云厂商")
    log.info("监听 ws://%s:%d%s", config.HOST, config.PORT, config.WS_PATH)
    log.info("音频 %d Hz / PCM16LE / 单声道,下行每包 %d B(%d ms),首包突发 %d ms",
             config.SAMPLE_RATE, config.CHUNK_BYTES, config.CHUNK_MS, config.BURST_MS)

    if config.HOST in ("127.0.0.1", "localhost", "::1"):
        log.info("只监听环回口 —— 公网入口由前面的 stunnel(TLS-PSK)负责,见 deploy/README.md")
        log.info("本地自测:  python tools/smoke_echo.py")
        log.info("从开发机测线上:  ssh -N -L 8765:127.0.0.1:%d <vps> 然后跑 smoke_echo",
                 config.PORT)
    else:
        # 绑了非环回地址。局域网里没问题,公网 VPS 上这是个大洞 —— 本层零鉴权。
        log.warning("!! 监听在 %s 上,这个端口**没有任何鉴权**。", config.HOST)
        log.warning("!! 公网 VPS 上别这么跑:要么绑回 127.0.0.1 让 stunnel 终结 TLS-PSK,")
        log.warning("!! 要么确认防火墙/安全组只放行了你自己的局域网。")
        for ip in local_ipv4s():
            log.info("  本机地址 → secrets.h 里填这个: %s", ip)
        log.info("连不上先查:防火墙放行入站 %d 端口;设备和本机在同一网段;"
                 "设备连的不是 127.0.0.1", config.PORT)

    async with serve(
        handler,
        config.HOST,
        config.PORT,
        process_request=process_request,
        max_size=config.MAX_WS_FRAME,
        ping_interval=config.PING_INTERVAL_S,
        ping_timeout=config.PING_TIMEOUT_S,
    ):
        await asyncio.get_running_loop().create_future()   # 跑到被 Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n收工。")
