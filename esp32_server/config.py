# -*- coding: utf-8 -*-
"""服务器配置。规格见 ../SERVER.md,设备侧协议见 ../AGENT.md §5。

Stage 6.5 只用得到监听地址和音频参数;厂商密钥等 Stage 8 再加。
"""
import os

# ---------------------------------------------------------------- 监听
#
# **默认 127.0.0.1,这是故意的。**
#
# rev.5 起部署形态是公网 VPS,TLS 由前面的 stunnel 终结(SERVER.md §7.3):
#
#     设备 --wss/TLS-PSK--> stunnel :443 --明文--> 本进程 127.0.0.1:8765
#
# 这个进程**不应该**自己暴露在公网上 —— 它没有任何鉴权,鉴权全靠 PSK 握手
# (AGENT.md §7.4:握不上手的连 WS 层都到不了)。绑 0.0.0.0 等于把裸端口
# 开给全网,Stage 8 接上火山和 DeepSeek 之后那就是别人在烧你的额度。
#
# 局域网直连调试(老的 Stage 6.5 玩法)才需要 0.0.0.0:
#     ESP32_SERVER_HOST=0.0.0.0 python main.py
HOST = os.getenv("ESP32_SERVER_HOST", "127.0.0.1")
PORT = int(os.getenv("ESP32_SERVER_PORT", "8765"))
WS_PATH = os.getenv("ESP32_SERVER_PATH", "/ws")

# 路径不符时是拒绝(404)还是只告警放行。
# 公网部署下默认拒绝 —— 扫描器打进来的 GET / 不该走到 Session 里去。
STRICT_PATH = os.getenv("ESP32_SERVER_STRICT_PATH", "1") == "1"

# ---------------------------------------------------------------- 音频
# 双向恒定 16 kHz / PCM16LE / 单声道。AGENT.md §4 "前提条件" —— 设备侧不做格式协商,
# 全双工共享时钟要求收发采样率相同,这个值不能改。
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2

# 下行每包 100 ms。设备上行也是 100 ms/3200 B(AGENT.md §5.2)。
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS // 1000   # 3200

# 首包突发,让设备尽快攒够预缓冲开始播(SERVER.md §3.5 / AGENT.md §4)。
# 设备侧 ring 是 16 KB(512 ms),预缓冲阈值 300 ms —— 突发量必须 >= 阈值且 < ring。
#
# ⚠️ 走公网之后这个值的意义变了:局域网里 300 ms 是纯余量,公网上它还要吸收
# 跨运营商抖动。抖动大到啃穿 300 ms 就会断续 —— 那时候往上调,同时把设备侧的
# PREBUFFER_BYTES 一起调(两边必须对齐),ring 的上限是 512 ms。
BURST_MS = int(os.getenv("ESP32_SERVER_BURST_MS", "300"))

# ---------------------------------------------------------------- 保活
# 设备侧自己也会 30 s 发一次 ping(AGENT.md §5.1)。两个方向都开着没坏处,
# 但设备**必须**回应服务器的 ping,否则会被这里判死。
#
# 公网上 NAT/防火墙会回收空闲连接,保活比局域网更重要 —— PTT 设备大部分时间是
# 空闲的,没有保活的话下次按键才发现连接早就死了。
PING_INTERVAL_S = 30
PING_TIMEOUT_S = 20

# ---------------------------------------------------------------- 限额
# 单个回合最长录音。设备侧是按住按键才录,正常不会到;这里只防呆。
MAX_TURN_SECONDS = 30
MAX_TURN_BYTES = MAX_TURN_SECONDS * SAMPLE_RATE * BYTES_PER_SAMPLE

# WS 单帧上限。设备上行帧是 3200 B,留几倍余量。
MAX_WS_FRAME = 16384

# 同时在线连接数上限。公网部署的防呆:正常就几台设备,
# 真的爬到这个数说明要么 PSK 泄了,要么有 bug 在疯狂重连。
MAX_CONNECTIONS = int(os.getenv("ESP32_SERVER_MAX_CONN", "8"))

# ---------------------------------------------------------------- 开关
# 回合开始时下发 {"t":"cue","name":"thinking"}。
# Stage 7 的设备还不处理服务器驱动的 cue(会按 AGENT.md §5.2 静默忽略未知消息),
# 打开它可以顺带验证"设备能忽略不认识的消息"这条。Stage 11 才真正用。
SEND_CUE = os.getenv("ESP32_SERVER_CUE", "0") == "1"
