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

# ---------------------------------------------------------------- 开关(Stage 11)
# 收到 turn_end 立刻下发 {"t":"cue","name":"thinking"},设备在 WAITING 期间
# 循环播"咕噜咕噜"的等待音效,直到回复的音频接上(固件 bubble.*,fw >= 0.3)。
# 老固件(0.2)收到会打一行日志然后忽略,所以默认开着没有副作用。
CUE_THINKING = os.getenv("ESP32_SERVER_CUE", "1") == "1"

# chat 模式下 turn_start 就开 TTS 连接(跨洋建连 ~1.4 s,藏进用户说话的时间)。
# 百炼 TTS 连接空闲 65 s 仍可用(2026-09-22 实测),单回合最长 30 s,够。
# 万一预热的连接到用的时候已经断了,ali_tts 会自动重连一次。
TTS_PREWARM = os.getenv("TTS_PREWARM", "1") == "1"

# ---------------------------------------------------------------- 厂商选择
# ASR / TTS / LLM 各自独立选,分派在 asr.py / tts.py / llm.py,session.py 不关心是哪家。
#   ASR:ali = 百炼 qwen-audio-3.1-asr-flash-streaming(默认) / volc = 火山流式识别
#   TTS:ali = 百炼 qwen3-tts-flash-realtime(默认)          / volc = 火山语音合成
#   LLM:qwen = 百炼 Qwen(默认)                             / deepseek = DeepSeek
# 2026-09-22 默认全换到百炼:免费额度够调通 Stage 8~10。
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "ali")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "ali")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "qwen")

# 回合结束后服务器回什么。设备不带 mode,用这个默认值;pc_client 可以在
# turn_start 里带 "mode" 临时覆盖(调试用)。
#   echo  把录音原样送回(Stage 7)
#   asr   ASR 出文字 -> 下发 {"t":"asr"} -> TTS 念"我听到的是:…"(Stage 9,设备上也能听出识别对不对)
#   chat  ASR -> LLM 切句 -> TTS,真正的对话(Stage 10)。Stage 11 起改成默认
REPLY_MODE = os.getenv("REPLY_MODE", "echo")

# chat 模式的兜底台词。出声总比让设备干等到 WAITING 超时(8 s)好。
NOT_HEARD_TEXT = os.getenv("NOT_HEARD_TEXT", "没听清,能再说一遍吗?")
LLM_FAIL_TEXT = os.getenv("LLM_FAIL_TEXT", "我脑子有点卡住了,等一下再问我吧。")

# ---------------------------------------------------------------- 阿里云百炼
# 规格见 SERVER.md §4.6。密钥只从环境变量读,不进 git。
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
# ⚠️ 地域和 API Key 是绑定的:北京控制台的 key 只能连北京,国际站(新加坡)同理,
# 连错了握手就 401。下面三个 URL 都由它推出来,单独设环境变量可以逐个覆盖。
#   cn   = 北京       dashscope.aliyuncs.com
#   intl = 新加坡     dashscope-intl.aliyuncs.com
DASHSCOPE_REGION = os.getenv("DASHSCOPE_REGION", "cn")
_DS_HOST = "dashscope-intl.aliyuncs.com" if DASHSCOPE_REGION == "intl" else "dashscope.aliyuncs.com"
ALI_REALTIME_URL = os.getenv("ALI_REALTIME_URL", "wss://%s/api-ws/v1/realtime" % _DS_HOST)    # TTS
ALI_INFERENCE_URL = os.getenv("ALI_INFERENCE_URL", "wss://%s/api-ws/v1/inference" % _DS_HOST)  # ASR
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://%s/compatible-mode/v1" % _DS_HOST)        # LLM

ALI_ASR_MODEL = os.getenv("ALI_ASR_MODEL", "qwen-audio-3.1-asr-flash-streaming")

ALI_TTS_MODEL = os.getenv("ALI_TTS_MODEL", "qwen3-tts-flash-realtime")
# 音色。Cherry(芊悦)是文档默认音色,中文可用。其他音色见百炼控制台的音色列表。
ALI_TTS_VOICE = os.getenv("ALI_TTS_VOICE", "Cherry")
ALI_TTS_TIMEOUT_S = float(os.getenv("ALI_TTS_TIMEOUT_S", "15"))

# ---------------------------------------------------------------- 火山 ASR(备选)
VOLC_ASR_URL = os.getenv(
    "VOLC_ASR_URL", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async")
# 流式语音识别 2.0 小时版。按并发买的填 volc.seedasr.sauc.concurrent;
# 1.0 是 volc.bigasr.sauc.duration。⚠️ 和 TTS 的 Resource-Id 不同(SERVER.md §4.5)
VOLC_ASR_RESOURCE_ID = os.getenv("VOLC_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration")

# ---------------------------------------------------------------- 火山 TTS(备选)
# 规格见 SERVER.md §4.2。密钥**只从环境变量读**,不进 git。
# VPS 上放 /etc/esp32-server.env(600),由 systemd 的 EnvironmentFile 注入;
# 本机调试直接 export。模板见 env.example。
#
# 鉴权两种写法,火山控制台新旧版各一种,填其一即可:
#   新版:VOLC_API_KEY                           -> X-Api-Key
#   旧版:VOLC_APP_ID + VOLC_ACCESS_KEY          -> X-Api-App-Id / X-Api-Access-Key
VOLC_API_KEY = os.getenv("VOLC_API_KEY", "")
VOLC_APP_ID = os.getenv("VOLC_APP_ID", "")
VOLC_ACCESS_KEY = os.getenv("VOLC_ACCESS_KEY", "")

VOLC_TTS_URL = os.getenv(
    "VOLC_TTS_URL", "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream")
# ⚠️ 和 ASR 的 Resource-Id **不同**(SERVER.md §4.5)。
# seed-tts-2.0 = 豆包语音合成模型 2.0(控制台开通的就是这个);1.0 填 seed-tts-1.0。
VOLC_TTS_RESOURCE_ID = os.getenv("VOLC_TTS_RESOURCE_ID", "seed-tts-2.0")
# 发音人。必须是 Resource-Id 对应模型下有权限的音色,否则报 45000xxx。
# ⚠️ 下面这个默认值是 1.0 的音色,开的是 2.0 就一定要在 env 里换成 2.0 列表里的。
VOLC_TTS_SPEAKER = os.getenv("VOLC_TTS_SPEAKER", "zh_female_shuangkuaisisi_moon_bigtts")

# 单次合成的超时:从发出请求到 SessionFinished。一两句话正常 1~3 s。
VOLC_TTS_TIMEOUT_S = float(os.getenv("VOLC_TTS_TIMEOUT_S", "15"))

# ---------------------------------------------------------------- 调试消息
# {"t":"say","text":"..."} —— 让服务器把一段文本 TTS 后按正常回合下发。
# 设备从来不发这条,它是 tools/pc_client.py 的 Stage 8 入口。
# 能走到这里的连接都过了 PSK(见上面"监听"),所以默认开着;
# 但它会花 TTS 额度,不放心就关掉。
ALLOW_SAY = os.getenv("ESP32_SERVER_ALLOW_SAY", "1") == "1"
MAX_SAY_CHARS = 300

# ---------------------------------------------------------------- ASR 公共
# turn_end 之后等最终文本的上限。实测百炼 ~0.6 s(美国 VPS -> 新加坡)。
ASR_FINISH_TIMEOUT_S = float(os.getenv("ASR_FINISH_TIMEOUT_S", "8"))

# ---------------------------------------------------------------- LLM(Stage 10 接入回合)
# 两家都是 OpenAI 兼容的 /chat/completions,llm.py 一套代码,只换地址/密钥/模型。
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "") or DASHSCOPE_API_KEY    # 默认和 ASR/TTS 共用
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.5-flash-2026-02-23")  # 也可 qwen-flash / qwen-turbo / qwen-plus

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

# ⚠️ 两家的模型最大输出都很长(DeepSeek 384K),必须压小,否则 TTS 念不完(SERVER.md §5)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "150"))
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))
# chat 模式 turn_start 时后台预热到 LLM 的连接(HEAD /models,不耗 token),见 llm.prewarm()。
LLM_PREWARM = os.getenv("LLM_PREWARM", "1") == "1"
# 连接池里空闲连接的保留时长。aiohttp 默认 15 s,对"一问一答间隔十几秒"的对话太短。
LLM_KEEPALIVE_S = float(os.getenv("LLM_KEEPALIVE_S", "60"))
# 保留最近几轮对话(一问一答算一轮)。system prompt 永远置顶,不参与截断。
LLM_HISTORY_TURNS = int(os.getenv("LLM_HISTORY_TURNS", "10"))
LLM_SYSTEM_PROMPT = os.getenv("LLM_SYSTEM_PROMPT", (
    "你是一个桌面小玩偶里的语音助手。用户是在按住按键对你说话,你的回答会被念出来。"
    "用口语回答,一到两句话,不超过六十个字。不要用列表、标题、表情符号或 Markdown,"
    "数字和符号写成念得出来的样子。"))
