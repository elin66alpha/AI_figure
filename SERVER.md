# ESP32-C3 AI Voice — 服务器侧规格

> 设备侧规格见 `AGENT.md`。两边的交界是 `AGENT.md` §3 定义的 WS 协议。
> 本文件只管交界以上：厂商协议、会话编排、对话历史、密钥、部署。

---

## 0. 这台服务器为什么存在

设备不直连云厂商，中间隔一台自建服务器。

**收益**

- 密钥不进固件，固件可以随便烧、随便发。
- 设备只维持一条开机建立的长连接，不用每回合建销多条 TLS 连接，堆碎片风险基本消失。
- 设备不实现厂商协议、不解析 LLM JSON、不管多套鉴权。
- 多轮对话记忆、改 prompt、换模型、调音色，都不用重新烧录。
- 句级流水线大幅降低延迟（§3.2）。
- 一台服务器带多台设备。

**代价**

- 多一个必须常开的组件（VPS + systemd 自启）。
- 多一跳。服务器和云厂商不在同一区域时，§3.3 的延迟要往上加。
- 上行 PCM 持续占用 256 kbps 带宽。

---

## 1. 技术选型

| 项 | 取值 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ / asyncio | 厂商官方 demo 多为 Python；TLS 由 stunnel 终结，Python 侧不碰 TLS |
| WS 服务端 | `websockets` | 够用，API 简单 |
| HTTP 客户端 | `aiohttp` | 连接池常驻，LLM 调用没有握手开销 |
| TLS 终结 | stunnel（TLS 1.2 + 纯 PSK） | 见 §7.2 |
| 部署 | 公网 VPS + systemd，Python 只听 `127.0.0.1` | 见 §7.1，操作步骤在 `server/deploy/README.md` |
| TTS | 阿里云百炼 `qwen3-tts-flash-realtime`（默认）；火山备选 | 换厂商 = 改 `TTS_PROVIDER`，见 §4.1 |
| ASR | 百炼 `qwen-audio-3.1-asr-flash-streaming`（默认）；火山备选 | 换厂商 = 改 `ASR_PROVIDER`，见 §4.2 |
| LLM | 百炼 Qwen `qwen3.5-flash-2026-02-23`（默认）；DeepSeek `deepseek-flash` 备选 | 两家都是 OpenAI 兼容接口，`llm.py` 一套代码；换 = 改 `LLM_PROVIDER`，见 §5 |
| 密钥 | 环境变量 / `/etc/esp32-server.env`，不进 git；PSK 在 `/etc/stunnel/psk.secrets` | |

火山、DeepSeek 等备选厂商的代码要保留：以后会成为小程序里可选的选项（`ROADMAP.md`）。

---

## 2. 目录结构

```
server/
  main.py             # websockets.serve，每条连接一个 Session
  session.py          # 回合状态机 + 对话历史 + seq 管理
  pacer.py            # 下行音频速率整形，吃异步迭代器
  config.py           # 监听地址/端口、各类开关，从环境变量读密钥
  env.example         # 密钥模板 -> /etc/esp32-server.env
  asr.py / tts.py     # ASR / TTS 厂商分派；单独运行可自测
  ali_asr.py          # 百炼 ASR 客户端（默认）
  ali_tts.py          # 百炼 TTS 客户端（默认）；单独运行可自测密钥/音色
  volc_proto.py       # 火山二进制帧编解码（ASR/TTS 共用）
  volc_asr.py         # 火山 ASR 客户端（备选）
  volc_tts.py         # 火山 TTS 客户端（备选）
  llm.py              # Qwen / DeepSeek，stream=True，切句，对话历史
  pipeline.py         # 句级流水线：LLM -> TTS -> 下行，三段解耦
  aioutil.py          # 厂商 WS 后台关闭（ASR/TTS 共用）
  tools/
    smoke_echo.py     # 不用 ESP32 的服务器自测
    pc_client.py      # PC 端假设备，见 §6
  deploy/             # 公网 VPS 部署，见 §7.1
    README.md               # 操作步骤
    esp32-server.service    # systemd unit：Python 本体
    stunnel-esp32.conf      # TLS-PSK 终结：443 -> 127.0.0.1:8765
    stunnel-esp32.service   # systemd unit：stunnel
    psk.secrets.example     # 设备密钥表模板；真实文件在 VPS 上，不入库
```

`REPLY_MODE` 决定一个回合结束后回什么，三种模式共用同一套协议外壳（`hello`→`ready`、`turn_start`/`turn_end`、`audio_begin(seq)` → 整形下发 → `audio_end(seq)`、`abort`→`seq++`），切换模式不用改固件：

| 模式 | 回合结束后 |
|---|---|
| `echo`（`config.py` 默认值） | 把录音原样送回。验设备和链路，不依赖任何厂商 |
| `asr` | ASR 出文字 → 下发 `{"t":"asr"}` → TTS 念“我听到的是：…”。设备会忽略 `asr` 消息，所以在真机上能直接听出识别对不对 |
| `chat` | ASR → LLM 切句 → 每句 `{"t":"reply"}` + TTS → 下行。真正的对话 |

---

## 3. 会话编排

### 3.1 核心流程（chat 模式）

```
turn_start
  → 开 ASR 流（和用户说话并行建连），预热 TTS 连接和 LLM 连接
  → 建连期间到的音频先进队列，连上后一次补发

binary PCM 帧（设备 100 ms / 3200 B 一包）
  → 百炼 ASR：直接转发；火山 ASR：两两合并成 200 ms / 6400 B 再上送

turn_end
  → 下发 {"t":"cue","name":"thinking"}，设备开始播等待音效
  → ASR 收尾 → 最终文本 → history.append(user)
  → LLM stream=True，边收 token 边切句，切出一句立刻送 TTS
  → TTS 返回裸 PCM → pacer 整形 → 下发给设备
  → history.append(assistant)

abort
  → cancel 所有在途任务，seq += 1，不动连接
```

### 3.2 句级流水线

不要等 LLM 生成完再送 TTS。流式读 LLM，遇到 `。！？；\n` 就把这一句切出来立刻送 TTS。LLM 还在生成第二句时，第一句已经在设备上播了。

- 第一句可以短（降低首包延迟），后续句子可以攒长一点（减少 TTS 开销）。第一句 ≥6 字就切，之后 ≥20 字再切。
- 数字、小数点、省略号不要误切：`3.14` 里的点不是句末。
- LLM 流结束时，把残余不足一句的尾巴也送出去。
- **三段用队列解耦（`pipeline.py`）**：pacer 按 1× 实时拿数据，如果 TTS 直接挂在 pacer 下面，它也只能 1× 实时前进，念完一句才去 commit 下一句，句间就会断。拆开后 TTS 以约 5× 实时一直往前合成。
- 一条 TTS 连接念完整个回复：百炼 commit 模式支持同一连接多次 commit，顺序不乱。

兜底，**任何情况都出声**，不让设备干等到 8 s 超时：

- ASR 空文本 → 念 `NOT_HEARD_TEXT`。
- LLM 一个字都没出就失败 → 念 `LLM_FAIL_TEXT`。
- LLM 出过声后中途断开 → 已出的照常念完、正常收尾。

打断时 `_reply` 显式 `aclose()` 流水线，LLM 的 HTTP 流和 TTS 连接立刻切断；被打断那轮已生成的半句照样记进历史。

### 3.3 延迟预算

服务器和云厂商在同一区域时：

```
turn_end 到达
  ├─ ASR 最终文本        0.3 ~ 0.5 s
  ├─ LLM 首 token        0.3 ~ 0.6 s   (aiohttp 连接池，无握手)
  ├─ 攒够第一句           0.1 ~ 0.3 s
  ├─ TTS 首个 PCM 包      0.2 ~ 0.4 s   (连接已在 turn_start 预热)
  └─ (设备侧预缓冲         0.3 s，期间有等待音效)
──────────────────────────────────
  1.2 ~ 2.1 s
```

服务器和厂商跨区域时，每一段都要再加一个往返时间。

### 3.4 连接复用和预热

- **LLM**：`aiohttp.ClientSession` 全局常驻。aiohttp 默认空闲连接只保留 15 s，比一问一答的间隔短，所以 `LLM_KEEPALIVE_S=60`，并且 chat 模式在 `turn_start` 时用 `llm.prewarm()` 发一个 `HEAD /models`（不耗 token）把连接建好。
- **TTS**：chat 模式在 `turn_start` 就开 TTS 连接（`TTS_PREWARM`，默认开）。百炼 TTS 连接空闲 65 s 仍可用，单回合最长 30 s，够用；到用时已断开的话，`ali_tts` 自动重连一次。
- **ASR**：`turn_start` 就建连。百炼 ASR 服务端空闲超时 23 s，所以**不能**在 IDLE 时预开一条挂着等下一回合。

### 3.5 下行速率整形（`pacer.py`）

TTS 生成通常快于实时播放。一次性推下去会打爆设备的 16 KB 环形缓冲，也让打断变得迟钝（TCP 缓冲里积压一堆已经不该播的音频）。

- 首包突发 `BURST_MS`（300 ms），让设备尽快攒够预缓冲开始播。
- 之后按 1× 实时喂：每 100 ms 发 3200 字节。TTS 帧长不对齐（甚至奇数字节）没关系，pacer 会重新切成 3200 B。
- 设备不读时 TCP 自然反压，这是预期行为，不要加应用层流控。
- 拿到第一块音频才发 `audio_begin`：上游出声前就失败 → 设备只收到 `{"t":"error"}`，不会有空回合；出声后才失败 → 照常 `audio_end` 收尾再报 `error`，设备不会卡在 PLAYING。

### 3.6 等待音效

收到 `turn_end` 立刻下发 `{"t":"cue","name":"thinking"}`（`ESP32_SERVER_CUE`，默认开），设备播“咕噜咕噜”，直到回复接上。echo 模式也发，无害。

---

## 4. 厂商协议要点

音频参数一律设成 **16 kHz / PCM16 / 单声道**：设备只按这个格式解释下行音频，服务器不做重采样（`AGENT.md` §4）。

### 4.1 阿里云百炼 TTS（默认）

- 端点：`wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-tts-flash-realtime`（北京）；国际站是 `dashscope-intl.aliyuncs.com`（`DASHSCOPE_REGION=intl`）。**API Key 和地域绑定**，北京的 key 连新加坡会返回 401。
- 鉴权：握手头 `Authorization: Bearer <DASHSCOPE_API_KEY>`。
- 协议是 OpenAI Realtime 风格：全是 JSON 文本帧，音频是 base64。
- `session.update` 里必须写 `"response_format":"pcm", "sample_rate":16000`。默认是 24000，不写就会在设备上快放变调。`ali_tts.py` 会核对 `session.updated` 回来的采样率，不对直接报错。
- 用 `commit` 模式：`append(text)` → `commit` → 一串 `response.audio.delta` → `response.done`。
- `response.audio.delta` 的 `delta` 是 base64 字符串，解出来不保证偶数字节；`ali_tts.py` 会把落单的字节留到下一块。
- `response.done` 一到生成器就结束，`session.finish` 和关连接放到后台做，不拖慢最后一包和 `audio_end`。
- 默认音色 `Cherry`（`ALI_TTS_VOICE`）。
- 计费：汉字大约按 2 个字符计。
- 有并发连接上限：同时开 4 条会被拒（`Requests rate limit exceeded`）。一台设备同一时刻最多 1~2 条（预热的那条 + 刚打断还没关完的那条），碰不到；多台设备同时用时要注意。
- 常见报错：握手 401/403 = key 错或地域不对；`invalid_value` 多半是音色名写错。

### 4.2 阿里云百炼 ASR（默认）

模型 `qwen-audio-3.1-asr-flash-streaming`。协议是 DashScope 的 inference WS，和 TTS 的 realtime WS 不是一套：

- 端点 `wss://dashscope[-intl].aliyuncs.com/api-ws/v1/inference`，鉴权 `Authorization: Bearer`。
- `run-task`（JSON，`parameters: {format:"pcm", sample_rate:16000}`）→ 等 `task-started` → 直接转发设备的 100 ms 包 → `finish-task` → `task-finished`。
- `result-generated` 里同一个 `sentence_id` 会反复下发，`text` 是这一句到目前为止的全文，不是增量；一段话可能被切成多句，最终文本按 `sentence_id` 拼。`heartbeat:true` 的包跳过。
- 失败是 `task-failed`，错误在 `header.error_code / error_message`。

### 4.3 火山（备选）

正确的产品线是**豆包语音 / 语音技术**；“实时音视频 RTC”那条产品线与本项目无关。

- **gzip 关掉**：二进制协议 header 第 2 字节低 4 位用 `0b0000`（无压缩），服务端会沿用客户端的压缩方法。16 kHz PCM 压缩率本来就低，不值得多一层调试难度。
- **TTS 走 WebSocket 才能拿裸 PCM**：端点 `wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream`。HTTP Chunked / SSE 接口返回 base64，`/api/v3/tts/bidirection` 要求文本也流式输入，都不用。
- `TTSResponse`（event 352）帧结构：

  ```
  [0]     0x11            协议版本1 + header 长度 4 字节
  [1]     0xB4            msgtype=0b1011 (Audio-only response) + flags=0b0100 (带 event number)
  [2]     0x10            serialization=JSON, compression=none
  [3]     0x00            reserved
  [4:8]   uint32 = 352    event = TTSResponse
  [8:12]  uint32          session_id 长度
  [12:..] bytes           session_id
  [..:+4] uint32          audio 长度
  [..]    bytes           裸 PCM16 16kHz，转发给设备
  ```

  其他事件：`TTSSentenceStart`=350，`TTSSentenceEnd`=351，`SessionFinished`=152（合成结束），上行 `FinishConnection`=2 关连接。上行只需一帧 SendText：header `0x11 0x10 0x10 0x00` + uint32 长度 + JSON。
- **ASR**：端点 `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`（双向流式优化版，只在结果变化时下发）。
  - 鉴权 header：`X-Api-Key`、`X-Api-Resource-Id`、`X-Api-Request-Id`（UUID）、`X-Api-Sequence: -1`。
  - 音频参数 `format:"pcm"`、`rate:16000`、`bits:16`、`channel:1`。
  - 单包 200 ms 时性能最优：服务器把设备的 100 ms 包两两合并再上送。
  - 帧类型：`0b0001` full client request（JSON 参数）、`0b0010` audio only request、`0b1001` full server response、`0b1111` error。最后一包 flags 用 `0b0010`（负包，无 sequence 字段）。PTT 场景不需要 VAD，收到 `turn_end` 即发负包。
- ASR 和 TTS 同在 `openspeech.bytedance.com`，TLS session 可复用；但两者的 `X-Api-Resource-Id` **不同**，不要混用。
- 常见报错：`45000xxx` 多半是音色不在该 Resource-Id 的授权范围里；握手 401/403 是密钥或 Resource-Id 填错。

---

## 5. LLM 要点（Qwen / DeepSeek 二选一）

`LLM_PROVIDER=qwen`（默认）或 `deepseek`。两家都是 OpenAI 兼容的 `/chat/completions` + SSE，`llm.py` 一套代码，只换地址、密钥和模型：

| | Qwen（百炼） | DeepSeek |
|---|---|---|
| 地址 | `https://dashscope[-intl].aliyuncs.com/compatible-mode/v1` | `https://api.deepseek.com` |
| 密钥 | `DASHSCOPE_API_KEY`（和 ASR/TTS 共用） | `DEEPSEEK_API_KEY` |
| 模型 | `qwen3.5-flash-2026-02-23`（默认）；`qwen-flash` 首 token 更快 | `deepseek-flash` |
| 特殊字段 | `enable_thinking: false`：Qwen3 是混合思考模型，不关会先“想”再说，首字延迟翻倍 | 无；只取 `delta.content`，丢弃 `reasoning_content` |

- `"stream": true` 是必须的，句级流水线依赖它。
- `max_tokens` 必须设小值（`LLM_MAX_TOKENS`，默认 150），否则回复过长，TTS 念不完。
- system prompt 限制“一到两句话口语回答”（`LLM_SYSTEM_PROMPT`）。改它不用烧录固件。

### 对话历史

- 每个设备一条历史，按设备 ID 存在内存里：断线重连后还在，进程重启清空。
- 必须限长，否则 token 成本和首字延迟都会线性增长：保留最近 `LLM_HISTORY_TURNS`（默认 10）轮。
- system prompt 永远置顶，不参与截断。

---

## 6. `tools/pc_client.py`：PC 端假设备

说 `AGENT.md` §3 那套 WS 协议。改一行服务器代码立刻能测，不用烧 ESP32。它同时是协议的可执行文档：设备侧实现有歧义时，以它的行为为准。

- 读一个 wav 文件，按 100 ms 切片，当作 `turn_start` → PCM 帧 → `turn_end` 上送。
- 把收到的 binary 帧存成 wav，把收到的 JSON 打到终端。
- `--abort-after <ms>` 模拟打断，用来测 `seq` 逻辑。
- 调试消息 `{"t":"say","text":"..."}`：服务器把文本送 TTS，出来的 PCM 走和正常回复同一条下行路径。设备从不发这条；`ESP32_SERVER_ALLOW_SAY=0` 可关闭。

```bash
python ali_tts.py "你好" out.wav                           # 只验 TTS 密钥/地域/音色（火山：volc_tts.py）
python asr.py input.wav                                    # 只验 ASR
python tools/pc_client.py say "你好,今天天气怎么样?"        # 整条下行：整形、seq、wav 能听
python tools/pc_client.py say "..." --abort-after 500      # 打断：服务器立刻停，不发 audio_end，厂商连接被关掉
python tools/pc_client.py turn input.wav --mode asr        # 一个回合，走 ASR
python tools/pc_client.py turn input.wav --mode chat       # 一个回合，真正对话；多跑几次 = 多轮
```

`{"t":"asr"}` 和 `{"t":"reply"}` 设备都会静默忽略，所以在 VPS 上改 `REPLY_MODE` 就能在真机上切换模式，不用重烧固件。

---

## 7. 部署

### 7.1 公网 VPS + stunnel

```
ESP32-C3 ──wss://<域名>:443──> stunnel ──明文──> 127.0.0.1:8765 Python
            TLS 1.2 / 纯 PSK      (TLS 在这里终结)      零鉴权，只监听环回口
```

操作步骤在 `server/deploy/README.md`，本节只说为什么这样部署。三件事是一体的：

1. **Python 只监听 `127.0.0.1`。** 这个进程没有任何鉴权，鉴权全在 PSK 握手上。绑 `0.0.0.0` 等于把裸端口开给全网，别人就能用你的厂商额度。
2. **TLS 由 stunnel 终结，不由 Python 做。** Python 3.13 才有 `set_psk_server_callback`；stunnel 一行 `PSKsecrets` 就完成，Python 侧不用改。
3. **设备填域名，不填裸 IP。** 设备没有运行期改服务器地址的入口，换 VPS = 每台重烧；一条 DNS 记录就能省掉这件事。

VPS 要放在 ASR / TTS / LLM 所在的区域附近，否则 §3.3 的延迟预算不成立。防火墙：默认拒绝入站，只放行 22 和 443；8765 必须从外网不可达。

### 7.2 为什么是 PSK，不是 Let's Encrypt 证书

PSK 白送两件事：**密钥即身份**（§7.3），以及**不用管证书过期**——设备没有便捷的远程升级通道，证书到期那天等于所有设备同时失效。还省掉了设备侧 X.509 解析的堆峰值。

这决定了 stunnel 的配置不能放松：

| 必须钉死 | 为什么 |
|---|---|
| `sslVersionMin/Max = TLSv1.2` | 设备固件关闭了 TLS 1.3（`CONFIG_MBEDTLS_SSL_PROTO_TLS1_3=n`） |
| `ciphers` 只留纯 PSK 套件 | RSA-PSK 一类套件会让服务器下发证书链，而设备走 PSK 时没有装 CA，握手必定失败 |

### 7.3 设备鉴权由 PSK 承担

一台设备一个 `identity` + 一把 32 字节密钥，TLS 握手成功本身就证明了身份，握不上手的连 WS 层都到不了。撤销一台设备 = 从 `/etc/stunnel/psk.secrets` 删掉那一行 + 重启 stunnel。

**已知并接受的缺口：** TLS 在 stunnel 就终结了，Python 侧看到的 peer 永远是 `127.0.0.1`，拿不到 PSK identity。所以服务器日志里的设备 ID 只能来自 `hello` 里的 `dev` 字段，那是设备自报的，没有密码学约束力。要把会话和身份绑死，得让 stunnel 走 PROXY protocol，或改用 Python 3.13 自己终结 TLS。

`SERVER_USE_TLS=0` 的局域网明文调试路径上：设备要连 PC 的局域网 IP 而不是 `localhost`，Windows 防火墙默认拦截入站，PC 的 DHCP 地址会变，PC 睡眠会断连。

### 7.4 连不上的时候按这个顺序查

一条链路分几段，每段都有不用烧 ESP32 就能单独验的办法。别跳着查：现象在最后一段，原因往往在前面。

| # | 查什么 | 怎么验 | 常见原因 |
|---|---|---|---|
| 1 | Python 活着吗 | `systemctl status esp32-server` | venv 路径、`WorkingDirectory` |
| 2 | 服务器逻辑对吗 | VPS 上直接跑 `tools/smoke_echo.py` | 逻辑问题，和网络无关 |
| 3 | 监听面对吗 | `ss -lntp \| grep -E ':443\|:8765'` | 8765 显示成 `0.0.0.0` → 立刻停下，那是个安全漏洞 |
| 4 | TLS-PSK 握得上吗 | `openssl s_client -psk_identity ... -psk ... -tls1_2` | `psk.secrets` 权限/属主、hex 抄错、套件没限死 |
| 4b | stunnel 配置本身 | `journalctl -u stunnel-esp32 -n 20` | 行尾 `;` 注释（见下） |
| 5 | 公网到得了吗 | 从开发机对域名跑同一条 `s_client` | **云厂商安全组**：和 ufw 是两道独立的防火墙 |
| 6 | 设备侧 | 串口日志，按 `AGENT.md` §3.4 | SSID 是 5 GHz、PSK 抄错、域名没填 |

第 5 行是“配置全对但就是连不上”的头号原因：改了 ufw 不等于改了安全组。

stunnel 配置的规矩（已写进 `deploy/`）：

- **注释必须独占一行。** stunnel 不支持行尾 `;` 注释：`debug = 4    ; 0~7` 会把 `4    ; 0~7` 整个当成值，报 `Illegal debug level` 并拒绝启动。
- **不要配 `output = /dev/stdout`。** systemd 下 `/dev/stdout` 指向 journald 的 unix socket，stunnel 把它当普通文件 `open()` 会失败，服务起不来。前台模式默认就输出到 stderr，journald 照样能收到。
- stunnel 5.72 没有 `-test` 参数（会把 `-test` 当成配置文件名），要验配置只能直接起服务看 journal。

---

## 8. 参考

- `ROADMAP.md`：后续计划，包括小程序按设备配置 ASR/TTS/LLM、音量和电量中转。
- [大模型流式语音识别 API — 豆包语音](https://docs.volcengine.com/docs/6561/1354869)
- [WebSocket 单向流式-V3（语音合成） — 豆包语音](https://docs.volcengine.com/docs/DoubaoVoice/WebSocketUnidirectionalStreaming-V3?lang=zh)
- [HTTP Chunked/SSE 单向流式-V3 — 豆包语音](https://docs.volcengine.com/docs/6561/1598757?lang=zh)
- [DeepSeek API 定价与模型列表](https://api-docs.deepseek.com/quick_start/pricing)
