# ESP32-C3 AI Voice — 服务器侧规格

> 设备侧规格见 `AGENT.md`。两边的交界是 `AGENT.md` §5 定义的那套 WS 协议。
> 本文件只管交界**以上**:厂商协议、会话编排、对话历史、密钥。
> 最后更新:2026-09-22(rev.5 — 部署迁到公网 VPS;TLS-PSK 由 stunnel 终结并落地;
> Python 改为只监听环回口。Stage 6.5 回声骨架已实现)
> 2026-09-22 追加:**TTS / ASR / LLM 默认都走阿里云百炼**,火山和 DeepSeek 留作备选,
> 各自一个开关(`TTS_PROVIDER` / `ASR_PROVIDER` / `LLM_PROVIDER`)。见 §4.6 / §4.7 / §5

---

## 0. 这台服务器为什么存在

`AGENT.md` rev.1 曾定为设备直连火山 + DeepSeek。rev.2 在中间加了这一层。

**收益**

- 密钥不进固件。固件可以随便烧、随便发
- 堆碎片风险基本消失——设备从"每回合建销 2~3 条 TLS"变成"开机一条长连接"。这是 rev.1 里最难排查的风险项
- 设备侧代码量减少约 60%:不实现火山二进制协议、不解析 LLM JSON、不管三套鉴权
- **多轮对话记忆**。C3 的 150 KB 堆上做不了,服务器上是几行代码
- 改 prompt、换模型、调音色,不用重新烧录
- **句级流水线把延迟砍掉近一半**(见 §3)
- 一份服务器带多台设备

**代价(照实记)**

- 多一个必须常开的组件。rev.5 上了 VPS + systemd 自启,这一条比当初跑在 PC 上时轻很多
- 多一跳。服务器与云厂商不同区域时,§3 的延迟数字要往上加 —— 当前 MVP 服务器在美国,正是这种情况
- 上行 PCM 256 kbps 持续占带宽(上了 VPS 之后占的是设备侧家宽的上行)
- 服务器本身要写、要部署、要监控。工作量大概和设备侧省下来的相当——只是换到了一个好调试得多的环境里

---

## 1. 技术选型

| 项 | 取值 | 理由 |
|---|---|---|
| 语言 | **Python 3.11+ / asyncio** | 火山 ASR/TTS 官方 demo 是 Python,那套二进制帧协议可以直接抄,不用从文档重新翻译一遍。~~PSK 需要 3.13~~ → rev.5 由 stunnel 终结 TLS,**Python 侧不碰 TLS**,3.11 够用 |
| WS 服务端 | `websockets` | 够用,API 简单。不需要 FastAPI 的那套 HTTP 能力 |
| HTTP 客户端 | `aiohttp` | 连接池常驻,DeepSeek 调用无握手开销 |
| TLS 终结 | **stunnel(TLS 1.2 + 纯 PSK)** | 见 §7.2。设备侧 mbedTLS 缓冲编译期钉死,CA 方案余量太薄 |
| 部署 | **公网 VPS + systemd**,Python 只听 `127.0.0.1` | 见 §7.1,操作步骤在 `esp32_server/deploy/README.md` |
| TTS | **阿里云百炼 `qwen3-tts-flash-realtime`**(默认);火山留作备选 | 有免费额度,够调通 Stage 8~10。换厂商 = 改 `TTS_PROVIDER`,见 §4.6 |
| ASR | **百炼 `qwen-audio-3.1-asr-flash-streaming`**(默认);火山留作备选 | 免费额度最大、有效期到 12/20。换厂商 = 改 `ASR_PROVIDER`,见 §4.7 |
| LLM | **百炼 Qwen `qwen3.5-flash-2026-02-23`**(默认);DeepSeek `deepseek-flash` 备选 | 两家都是 OpenAI 兼容接口,`llm.py` 一套代码。换 = 改 `LLM_PROVIDER`,见 §5 |
| 密钥 | 环境变量 / `.env`,**不进 git**;PSK 在 `/etc/stunnel/psk.secrets` | |

---

## 2. 目录结构

```
esp32_server/
  main.py             # websockets.serve,每连接一个 Session          [Stage 6.5 ✓]
  session.py          # 回合状态机 + 对话历史 + seq 管理              [Stage 6.5 ✓ 回声版]
  pacer.py            # 下行音频速率整形;Stage 8 起支持流式源        [Stage 8 ✓]
  config.py           # 监听地址/端口,从环境变量读密钥                [Stage 8 ✓]
  env.example         # 密钥模板 -> /etc/esp32-server.env              [Stage 8 ✓]
  volc_proto.py       # 火山二进制帧的编解码(ASR/TTS 共用)           [Stage 8 ✓]
  asr.py              # ASR 厂商分派 + 流式外壳;单独跑可自测          [Stage 9 ✓]
  ali_asr.py          # 百炼 ASR 客户端(默认)                        [Stage 9 ✓]
  volc_asr.py         # 火山 ASR 客户端(备选,只用 mock 验过)          [Stage 9 ✓]
  tts.py              # TTS 厂商分派(TTS_PROVIDER=ali/volc)         [Stage 8 ✓]
  ali_tts.py          # 百炼 TTS 客户端(默认);单独跑可自测密钥/音色  [Stage 8 ✓]
  volc_tts.py         # 火山 TTS 客户端(备选)                        [Stage 8 ✓]
  llm.py              # Qwen / DeepSeek,stream=True,切句,对话历史    [Stage 10 ✓]
  pipeline.py         # 句级流水线:LLM -> TTS -> 下行,三段解耦       [Stage 10 ✓]
  tools/
    smoke_echo.py     # 不用 ESP32 的服务器自测,见 §7.5 第 2 行       [Stage 6.5 ✓]
    pc_client.py      # ★ PC 端假设备,见 §6                          [Stage 8 ✓]
  deploy/             # 公网 VPS 部署,见 §7.1                        [rev.5 ✓]
    README.md               # 操作步骤(这是唯一要照着敲的一份)
    esp32-server.service    # systemd unit:Python 本体
    stunnel-esp32.conf      # TLS-PSK 终结:443 -> 127.0.0.1:8765
    stunnel-esp32.service   # systemd unit:stunnel(不用 Debian 打包那个)
    psk.secrets.example     # 设备密钥表;真身在 VPS 上,已 gitignore
```

**Stage 6.5 的回声是"协议级回声",不是裸回声。** 它说全套 `AGENT.md` §5.2 的话:
`hello`→`ready`、`turn_start`/`turn_end`、`audio_begin(seq)`→按 §3.5 整形回送→`audio_end(seq)`、
`abort`→`seq++`。这样设备侧 Stage 7 写的就是最终代码,**Stage 11 传输层一行不用改**;
服务器侧 Stage 8~10 只是把 `session.py` 里"把收到的 PCM 原样送回"换成
"ASR → LLM → TTS",**外壳同样不动**。

---

## 3. 会话编排

### 3.1 核心流程

```
turn_start
  → 开 ASR WS(或复用预热的连接),清本回合缓冲

binary PCM 帧(设备发来 100ms / 3200B 一包)
  → 重新打包成 200ms / 6400B  ← 火山的要求,由服务器承担
  → 推给火山 ASR

turn_end
  → 给 ASR 发负包 → 等最终文本
  → history.append({"role":"user", ...})
  → DeepSeek /chat/completions, stream=True
  → 边收 token 边切句,收到第一个句末标点就立刻送 TTS
  → TTS 返回裸 PCM → pacer 整形 → 下发给设备
  → history.append({"role":"assistant", ...})

abort
  → cancel 所有在途 task,seq += 1,不动连接
```

### 3.2 句级流水线 —— 服务器带来的最大延迟收益

**不要等 LLM 生成完再送 TTS。** 流式读 DeepSeek,遇到 `。！？；\n` 就把这一句切出来立刻送 TTS。LLM 还在生成第二句时,第一句已经在设备上播了。

切句要注意的:

- 第一句可以短(降低首包延迟),后续句子可以攒长一点(减少 TTS 连接开销)。建议第一句 ≥6 字就切,之后 ≥20 字再切
- 数字、小数点、省略号不要误切。`3.14` 里的点不是句末
- LLM 流结束时把残余不足一句的尾巴也送出去

### 3.3 延迟预算(服务器在公网 VPS 时)

```
turn_end 到达
  ├─ ASR 最终文本        0.3 ~ 0.5 s   (ASR WS 常驻保活)
  ├─ DeepSeek 首 token   0.3 ~ 0.6 s   (aiohttp 连接池,无握手)
  ├─ 攒够第一句           0.1 ~ 0.3 s
  ├─ TTS 首个 PCM 包      0.2 ~ 0.4 s
  └─ (设备侧预缓冲         0.2 ~ 0.3 s)
──────────────────────────────────
  1.2 ~ 2.1 s      (rev.1 直连方案是 2.5 ~ 4.5 s)
```

rev.5 之后这张表才真正成立 —— 服务器就在公网 VPS 上。
(rev.4 跑在本机 PC 时,PC→火山走家宽 RTT,每一项都要往上加 100~300 ms。)

国内 VPS 和 `openspeech.bytedance.com` 同区域时,服务器→火山这一跳几乎不花时间;
新增的那一跳(设备→VPS)换来的是设备侧**每回合两三次 TLS 握手直接归零** ——
长连接开机建一次就够。净延迟比 rev.1 的设备直连方案低。

### 3.4 连接复用

- **DeepSeek**:`aiohttp.ClientSession` 全局常驻,keep-alive。这一项在 rev.1 里是最贵的(每回合 1.5~3.0 s,含握手),复用后降到 0.3~0.6 s
- **ASR / TTS**:两者同在 `openspeech.bytedance.com`,TLS session 可复用。火山的 session 是绑回合的,但底层 TCP/TLS 连接可以预热
- 可以在 `IDLE` 期间预热下一回合的 ASR 连接,把 0.3~0.5 s 里的握手部分也吃掉

### 3.5 下行速率整形(`pacer.py`)

TTS 生成通常快于实时播放。一次性推下去会打爆设备的 16 KB 环形缓冲,也让打断变得迟钝(TCP 缓冲里积压一堆已经不该播的音频)。

规则:

- 首包**突发 300 ms**,让设备尽快攒够预缓冲开始播(对应 `AGENT.md` §4 的要求)
- 之后按 **1× 实时**喂:每 100 ms 发 3200 字节
- 设备不读时 TCP 会自然反压,这是预期行为,不要加应用层流控

---

## 4. 火山协议要点(从官方文档核实过,原在 AGENT.md §5)

> ⚠️ 用户最初提供的链接 `docs.volcengine.com/docs/real_time_communication/AccesscustomASRorTTS`
> 属于**实时音视频 RTC** 产品线(让火山 RTC 服务器去调用户自己的 ASR/TTS)。与本项目无关。
> 正确的产品线是 **豆包语音 / 语音技术**。

### 4.1 gzip 可关

火山二进制协议 header 第 2 字节低 4 位:

```
0b0000 - 无压缩     ← 用这个
0b0001 - Gzip
```

文档明确:"服务端将使用客户端的压缩方法"。

> 历史注:这一条在 rev.1 里是**排除了最大技术风险**的关键发现(ESP32 装不下 miniz/zlib)。
> rev.2 之后服务器侧有 zlib 随便用,这条不再是风险,但**仍然建议关掉 gzip**——16 kHz PCM 的压缩率本来就低,不值得为此增加一层调试难度。

### 4.2 TTS 走 WebSocket 才能拿裸 PCM

火山 TTS 有四个接口,只有 WebSocket 那两个返回裸二进制:

| 接口 | 音频形态 | 适用 |
|---|---|---|
| HTTP Chunked `/api/v3/tts/unidirectional` | `{"code":0,"data":"<base64>"}` | ✗ 需流式 base64 解码 |
| HTTP SSE `/api/v3/tts/unidirectional/sse` | 同上 | ✗ |
| **WS `/api/v3/tts/unidirectional/stream`** | **裸 `audio_binary`** | ✓ **采用** |
| WS `/api/v3/tts/bidirection` | 裸二进制 | 文本也要流式输入,本项目不需要 |

> 注:rev.2 之后 base64 解码对服务器已经不是负担,理论上 HTTP SSE 也能用。
> 但仍选 WS,因为**和 ASR 同域名同连接池**,且省掉一层解码。

端点:`wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream`

`TTSResponse`(event 352)帧结构:

```
[0]     0x11            协议版本1 + header 长度 4 字节
[1]     0xB4            msgtype=0b1011 (Audio-only response) + flags=0b0100 (带 event number)
[2]     0x10            serialization=JSON, compression=none
[3]     0x00            reserved
[4:8]   uint32 = 352    event = TTSResponse
[8:12]  uint32          session_id 长度
[12:..] bytes           session_id
[..:+4] uint32          audio 长度
[..]    bytes           ← 裸 PCM16 16kHz,转发给设备
```

其他事件:`TTSSentenceStart`=350,`TTSSentenceEnd`=351,`SessionFinished`=152(合成结束),上行 `FinishConnection`=2 关连接。

上行只需一帧 SendText:header `0x11 0x10 0x10 0x00` + uint32 长度 + JSON。

**音频参数必须设成 `sample_rate:16000` / `format:"pcm"`** —— 设备侧的 I2S 全双工共享时钟依赖这一点,见 `AGENT.md` §4。服务器不做重采样。

### 4.3 ASR 要点

- 端点:`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`(双向流式优化版,只在结果变化时下发,包更少)
- 鉴权 header(新版控制台):`X-Api-Key`、`X-Api-Resource-Id`、`X-Api-Request-Id`(UUID)、`X-Api-Sequence: -1`
- 音频参数:`format:"pcm"`, `rate:16000`, `bits:16`, `channel:1`
- **单包 100~200 ms,双向流式模式 200 ms 时性能最优** → 200 ms = 3200 样本 = 6400 字节
  → 设备发来的是 100 ms 包,**服务器负责两两合并**再上送
- 帧类型:`0b0001` full client request(JSON 参数)、`0b0010` audio only request、`0b1001` full server response、`0b1111` error
- 最后一包:flags 用 `0b0010`(负包,无 sequence 字段)
- PTT 场景不需要 VAD,收到 `turn_end` 即发负包

### 4.4 ASR 与 TTS 同域名

两者都在 `openspeech.bytedance.com` → TLS session 可复用。

### 4.5 鉴权

ASR 和 TTS 的 `X-Api-Resource-Id` **不同**,不要混用。

### 4.6 阿里云百炼 TTS(2026-09-22 起为默认)

换过来的理由很实际:百炼账号里有免费额度,够把 Stage 8~10 调通;火山要另外开通付费。
厂商这一层只有 `ali_tts.py` 一个文件,`session.py`/`pacer.py`/固件都不知道换了。

从官方文档核实过的要点(Qwen-TTS-Realtime WebSocket API):

- 端点:`wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-tts-flash-realtime`(北京)。
  国际站是 `dashscope-intl.aliyuncs.com`。**API Key 和地域绑定**,北京的 key 连新加坡会 401
- 鉴权:握手头 `Authorization: Bearer <DASHSCOPE_API_KEY>`
- 协议是 OpenAI Realtime 风格:**全是 JSON 文本帧,音频是 base64**,不像火山那样是二进制帧
- `session.update` 里必须写 `"response_format":"pcm", "sample_rate":16000` ——
  **默认是 24000**,不写就会在设备上快放变调。支持 8000/16000/24000。
  `ali_tts.py` 会核对 `session.updated` 回来的采样率,不对直接报错,不会带病下发
- 用 `commit` 模式:`append(text)` → `commit` → 一串 `response.audio.delta` → `response.done`。
  Stage 10 的句级流水线同样是每句 append + commit
- `response.audio.delta` 的 `delta` 是 base64 **字符串**。解出来不保证偶数字节,`ali_tts.py` 会把落单的那个字节留到下一块
- 默认音色 `Cherry`

免费额度大多 **2026-10-01 到期**,TTS 只有 10K(约 250 句回复)。开通时打开"免费额度用完即停"。

### 4.7 阿里云百炼 ASR(2026-09-22 起为默认)

模型 `qwen-audio-3.1-asr-flash-streaming`。协议是 DashScope 的 **inference WS**,
和 TTS 的 realtime WS 不是一套(真连核实过):

- 端点 `wss://dashscope[-intl].aliyuncs.com/api-ws/v1/inference`,鉴权 `Authorization: Bearer`
- `run-task`(JSON,`parameters: {format:"pcm", sample_rate:16000}`)→ 等 `task-started`
  → **直接转发设备的 100 ms 包**(不用像火山那样两两合并)→ `finish-task` → `task-finished`
- `result-generated` 里同一个 `sentence_id` 会反复下发,`text` 是**这一句到目前的全文**,不是增量;
  一段话可能被切成多句,最终文本按 `sentence_id` 拼。`heartbeat:true` 的包跳过
- 失败是 `task-failed`,错误在 `header.error_code / error_message`
- 服务端空闲超时 23 s —— 所以**不能**在 IDLE 时就预开一条挂着等下一回合

**`turn_start` 就建连**,不等 `turn_end`:建连 + `run-task` 实测 ~1.0 s(美国 → 新加坡),
正好藏进用户说话的时间里。建连期间到的音频先进队列,连上后一次补发。

---

## 5. LLM 要点(Qwen / DeepSeek 二选一)

`LLM_PROVIDER=qwen`(默认)或 `deepseek`。两家都是 OpenAI 兼容的 `/chat/completions` + SSE,
`llm.py` 一套代码,只换地址 / 密钥 / 模型:

| | Qwen(百炼) | DeepSeek |
|---|---|---|
| 地址 | `https://dashscope[-intl].aliyuncs.com/compatible-mode/v1` | `https://api.deepseek.com` |
| 密钥 | `DASHSCOPE_API_KEY`(和 ASR/TTS 共用) | `DEEPSEEK_API_KEY` |
| 模型 | `qwen3.5-flash-2026-02-23`(2026-09-22 起默认;`qwen-flash` / `qwen-turbo` / `qwen-plus` / `qwen3.5-flash` 在国际站也都实测可用) | `deepseek-flash` |
| 特殊字段 | `enable_thinking: false` —— Qwen3 是混合思考模型,不关会先"想"再说,首字延迟翻倍 | 无;只取 `delta.content`,`reasoning_content` 丢弃 |

**实测(2026-09-22,美国 VPS → 新加坡,`qwen-flash`)**:首 token 冷启动 ~1.0 s(含 TLS),
**连接池热了之后 ~0.3 s**。三轮对话历史正常(第二轮能答出第一轮说的名字和年龄)。
**换成 `qwen3.5-flash-2026-02-23` 后**:首 token 冷 ~1.5 s / 热 ~0.8 s,比 `qwen-flash` 慢约 0.5 s;
`enable_thinking:false` 对它同样生效,历史正常。嫌慢可以 `QWEN_MODEL=qwen-flash` 切回。
DeepSeek 还没有 key,没真连过。

### 5.1 DeepSeek 细节

- `POST https://api.deepseek.com/chat/completions`,OpenAI 兼容格式
- `"model": "deepseek-flash"`
- `"stream": true` —— **必须**,句级流水线依赖它
- ⚠️ 该模型最大输出 384K tokens。**必须设 `max_tokens` 为小值(建议 100~150)**,否则回复过长,TTS 念不完,体验崩坏
- system prompt 限制"一到两句话口语回答"。这是服务器侧一个字符串,改它不用烧录固件——这正是加服务器的收益之一

### 对话历史

- 每个设备一条历史,内存里存即可(开发阶段不需要持久化)
- **必须限长**,否则 token 成本和首字延迟都会线性涨。建议保留最近 10 轮,或按 token 数截断
- system prompt 永远置顶,不参与截断

---

## 6. `tools/pc_client.py` —— 整个计划里效率杠杆最大的一件东西

一个 PC 上的假设备,说 `AGENT.md` §5 那套 WS 协议:

- 读一个 wav 文件,按 100 ms 切片,当作 `turn_start` → PCM 帧 → `turn_end` 上送
- 把收到的 binary 帧存成 wav,把收到的 JSON 打到终端
- 支持模拟 `abort`(发完一半就打断),用来测 `seq` 逻辑

**Stage 8~10 全部用它调通,ESP32 一次都不用烧。** 改一行服务器代码立刻能测,而不是等一轮烧录。
它同时也是协议的可执行文档——设备侧实现有歧义时,以它的行为为准。

### 6.1 Stage 8 —— TTS 单通(2026-09-22 代码完成,百炼 + 火山两套)

设备协议里没有"文本"这个概念,所以加了一条**调试消息** `{"t":"say","text":"..."}`:
服务器把文本送火山 TTS,出来的 PCM 走**和回声完全同一条**下行路径
(`session._reply()` → `pacer.pace_stream()` → `audio_begin/…/audio_end`)。
设备从不发这条;`ESP32_SERVER_ALLOW_SAY=0` 可关。

下行路径在 Stage 8 顺手定了两条语义,Stage 11 直接沿用:

- **拿到第一块音频才发 `audio_begin`。** 上游出声前就失败 → 设备只收到 `{"t":"error"}`,
  不会有空回合;出声后才失败 → 照常 `audio_end` 收尾再报 `error`,设备不会卡在 PLAYING
- **pacer 改成吃异步迭代器**,首包仍攒满 `BURST_MS` 再突发,之后 1× 实时。
  TTS 帧长不对齐(甚至奇数字节)没关系,pacer 重新切成 3200 B

验收分三步,前一步不过别往下走:

| # | 命令 | 验什么 |
|---|---|---|
| 1 | `python ali_tts.py "你好" out.wav`(火山:`volc_tts.py`) | 只验密钥 / 地域 / 音色 / 网络,不经过 main.py |
| 2 | `python main.py` + `python tools/pc_client.py say "你好,今天天气怎么样?"` | 整条下行:整形、seq、wav 能听 |
| 3 | 同上加 `--abort-after 500` | 打断:服务器立刻停,不发 `audio_end`,且到火山的 WS 被关掉(不再计费) |

**已做**:百炼和火山各写了一个本地 mock 服务器,1/2/3 三步都跑通,外加 TTS 报错路径和 `smoke_echo.py` 回归。
mock 故意用奇数字节的音频帧,验了 base64 落单字节和 pacer 的重新切片 —— 设备收到的和 mock 发出的逐字节一致。
**未做**:真连厂商 —— 还没有密钥。百炼第 1 步的常见报错:握手 401/403 = key 错或地域不对;
`invalid_value` 多半是音色名写错。火山的常见报错:
`45000xxx` 多半是音色不在该 Resource-Id 的授权范围里;握手 401/403 是密钥或 Resource-Id 填错
(TTS 和 ASR 的 Resource-Id 不同,§4.5)。

**✅ 实测(2026-09-22,美国 VPS → 百炼新加坡,`DASHSCOPE_API_KEY` 是国际站 key)**:
三步全过。一句 16 字的回复:

| 段 | 耗时 | 说明 |
|---|---|---|
| WS 建连(TLS) | 0.8 ~ 1.1 s | **大头**。美国到新加坡的跨洋握手 |
| `session.update` 往返 | ~0.25 s | |
| commit → 首个音频 | ~0.4 s | 合成本身 |
| 生成 3.2 s 音频 | ~0.6 s | 5× 实时,pacer 喂得动 |
| **请求 → 设备收到首包** | **1.4 ~ 1.8 s** | |

计费:这句 16 字(含标点)记了 `characters: 29` —— **汉字大约按 2 个字符计**,
10K 免费额度实际约 5000 汉字 ≈ 170 句回复。

踩到的一个坑已修:最初在生成器里同步做 `session.finish` + 关连接,
最后不满一包的尾巴和 `audio_end` 都要等那两个跨洋来回,拖了 ~1 s。
现在 `response.done` 一到生成器就结束,关连接丢到后台。

**降首包延迟的两条路**(都不急,Stage 11 再说):
(1) 在 `turn_start` 时就**预热**百炼连接,把建连的 1 s 藏进用户说话的时间里 ——
这一条收益最大且不花钱;(2) VPS 换到新加坡/国内,和百炼同区域。

⚠️ 当前 VPS 在美国,第 1 步测出的首包延迟会比 §3.3 的预算高一个跨太平洋 RTT。
这是**已知的部署问题**,不是 TTS 客户端的问题 —— 功能验证在美国做就行,延迟要等换国内服务器再量。

### 6.2 Stage 9 —— ASR 单通(2026-09-22 ✓ 真连百炼)

`REPLY_MODE=asr`(或 pc_client 在 `turn_start` 里带 `"mode":"asr"`)时,一个回合是:

```
turn_start  -> 立刻开 ASR 流(和用户说话并行建连)
binary      -> 攒进缓冲的同时转发给 ASR
turn_end    -> finish -> 最终文本 -> {"t":"asr","text":...} -> TTS 念"我听到的是:…"
```

`{"t":"asr"}` 设备会静默忽略(固件 `session.cpp` 的 `default:` 分支,AGENT.md §5.2),
所以把 VPS 的 `REPLY_MODE` 改成 `asr`,**不用重烧固件**就能在真机上听识别结果。

```bash
python asr.py input.wav                                   # 只验 ASR
python tools/pc_client.py turn input.wav --mode asr      # 整条
```

**实测**(用 Stage 8 合成的"你好,我是小助手,今天天气不错。"当输入):识别一字不差、标点正确;
ASR 就绪 ~1.0 s(藏在说话时间里),**turn_end → 最终文本 0.51 s**,turn_end → 设备收到首包 1.94 s
(其中 TTS 建连 0.86 s —— Stage 11 做 TTS 预热后能再砍掉)。

火山 ASR 客户端也写了,帧格式和 200 ms 合包用 mock 验过,没真连。

### 6.3 Stage 10 —— 全链路对话(2026-09-22 ✓ 真连百炼)

`REPLY_MODE=chat`(或 pc_client `--mode chat`):

```
turn_start  -> 开 ASR 流
turn_end    -> 同时:ASR 收尾 + 开 TTS 连接(和 ASR/LLM 并行,藏建连)
            -> {"t":"asr"} -> LLM 流式生成、切句 -> 每句 {"t":"reply"} + append/commit 给同一条 TTS 连接
            -> pacer -> audio_begin / PCM / audio_end
```

**三段用队列解耦(`pipeline.py`)**,这是不断顿的关键:pacer 按 1x 实时拿数据,如果 TTS 直接挂在
pacer 下面,它也只能 1x 实时前进,念完一句才去 commit 下一句,而 commit -> 首包要 ~0.35 s,
比 pacer 留的 300 ms 余量还长,句间就会断。拆开后 TTS 以 ~5x 实时一直往前合成。
**一条 TTS 连接念整个回复**:百炼 commit 模式支持同一连接多次 commit(真连实测,顺序不乱)。

兜底:ASR 空文本 -> 念 `NOT_HEARD_TEXT`;LLM 一个字都没出就失败 -> 念 `LLM_FAIL_TEXT`;
LLM 出过声后中途断 -> 已出的照常念完、正常收尾。**任何情况都出声**,不让设备干等到 8 s 超时。
abort:`_reply` 显式 `aclose()` 流水线,LLM 的 HTTP 流和 TTS 连接 50 ms 内切断(mock 验过),
被打断那轮已生成的半句照样记进历史。对话历史按设备 ID 存,断线重连后还在,进程重启清空。

**实测(美国 VPS -> 新加坡,qwen3.5-flash-2026-02-23,两轮对话)**:

| turn_end 起 | 第 1 轮(LLM 冷) | 第 2 轮(LLM 热) |
|---|---|---|
| ASR 最终文本 | 521 ms | 595 ms |
| LLM 第一句切出 | 1878 ms | 1000 ms |
| TTS 首包 = 设备开始收音频 | **2225 ms** | **1834 ms** |

- 第二轮答出了"你叫小明",历史正常;两轮都**无断顿**(9128 ms 音频收了 8830 ms,正好超前 300 ms)
- **现在的瓶颈是 TTS 建连**:第 2 轮 TTS 就绪要 1426 ms,LLM 第一句 1000 ms 就好了,干等了 ~0.4 s。
  Stage 11 把 TTS 建连挪到 `turn_start`,预计首包降到 ~1.4 s
- 设备真正出声还要再加设备侧预缓冲 ~300 ms

`{"t":"reply"}` 和 `{"t":"asr"}` 一样,设备静默忽略 —— VPS 上改 `REPLY_MODE=chat` **不用重烧固件**就能在真机上对话。

---

## 7. 部署

### 7.1 当前形态:公网 VPS + stunnel(rev.5)

> **当前实例(2026-09-22 已上线,MVP 临时用):** `torqtac.tech` / RackNerd 得州,
> Ubuntu 24.04.5,Python 3.12.3,stunnel 5.72 + OpenSSL 3.0.13。
> 两个服务都 `enabled + active`,内存 14 MB(python)+ 2 MB(stunnel)。
> ufw:默认 deny incoming,只放行 22 + 443;已验证 8765 从外网不可达。
> **这台是临时的** —— ASR/TTS/LLM 都在国内,Stage 8 之前要换到国内合规备案的服务器,
> 否则 §3.3 那张延迟预算表不成立(它的前提是"和 `openspeech.bytedance.com` 同区域")。

```
ESP32-C3 ──wss://<域名>:443──> stunnel ──明文──> 127.0.0.1:8765 Python
            TLS 1.2 / 纯 PSK      (TLS 在这里终结)      零鉴权,只监听环回口
```

操作步骤在 **`esp32_server/deploy/README.md`**,本节只说为什么长这样。

三件事是一体的,拆开看会觉得多余:

1. **Python 只监听 `127.0.0.1`。** 这个进程没有任何鉴权 —— 鉴权全在 PSK 握手上。
   绑 `0.0.0.0` 等于把裸端口开给全网,Stage 8 接上火山和 DeepSeek 之后
   那就是别人在烧你的额度。`config.py` 的默认值因此从 `0.0.0.0` 改成了 `127.0.0.1`
2. **TLS 由 stunnel 终结,不由 Python 做。** Python 3.13 才有
   `set_psk_server_callback`,而 stunnel 一行 `PSKsecrets` 就完事,
   **Python 侧一行不改**。这条在 rev.4 就定了,只是当时以为是树莓派专属的权宜之计
3. **设备填域名不填裸 IP。** 这台设备没有运行期改地址的入口,换 VPS = 每台重烧。
   一条 DNS 记录能省掉这件事

相比 rev.4 的"本机 PC",搬上 VPS 顺带解决了三个老问题:
PC 睡眠断连、DHCP 地址会变、上行 PCM 持续占家宽。
§3.3 的延迟预算本来就是按"服务器在公网 VPS"算的,现在才真正成立。

### 7.2 为什么是 PSK,不是 Let's Encrypt 证书

有域名之后,"Caddy + 自动证书"看起来是更省事的路。**但设备侧过不去。**

AGENT.md §5.6 查 arduino-esp32 3.3.12 的预编译 sdkconfig 得到的硬事实,
2026-09-22 复核过一遍,都还成立:

```
CONFIG_MBEDTLS_SSL_MAX_CONTENT_LEN=16384        <- in 16K + out 16K,钉死
# CONFIG_MBEDTLS_ASYMMETRIC_CONTENT_LEN is not set   <- 收发不能不对称
# CONFIG_MBEDTLS_SSL_PROTO_TLS1_3 is not set     <- 设备只会 TLS 1.2
CONFIG_MBEDTLS_KEY_EXCHANGE_PSK=y / ECDHE_PSK=y / RSA_PSK=y
```

150 KB 可用堆上,CA 方案握手峰值 ~87 KB(含 ~20 KB 的 X.509 解析峰值),
纯 PSK ~67 KB。而且 PSK 还白送两件事:**密钥即身份**(§7.3),
以及**不用管证书过期** —— 这台设备没有便捷的远程升级通道,
证书到期那天等于所有设备同时变砖。

这两条决定了 stunnel 那边的配置不能松:

| 必须钉死 | 为什么 |
|---|---|
| `sslVersionMin/Max = TLSv1.2` | 设备不会 TLS 1.3,见上面的 sdkconfig |
| `ciphers` 只留**纯 PSK**套件 | RSA-PSK 会让服务器下发证书链,而设备侧走 PSK 分支时没装 CA(`ssl_client.cpp` 里 CA/PSK 是互斥的 else-if),验证必挂 |

同理,固件里**不要**在设了 PSK 之后再调 `setCACert()` —— CA 分支排在前面,
PSK 会被静默无视,然后挂在一个和 PSK 毫无关系的错误上。

### 7.3 设备鉴权 —— 由 PSK 承担

rev.3 计划在 `hello` 帧里带 per-device token。**rev.4 取消了这套 token,rev.5 落地。**

一台设备一个 `identity` + 一把 32 字节密钥,**TLS 握手成功本身就证明了身份** ——
握不上手的连 WS 层都到不了。撤销一台设备 = 从 `/etc/stunnel/psk.secrets`
删掉那一行 + 重启 stunnel。

**一个已知的、接受了的缺口:** TLS 在 stunnel 就终结了,Python 侧看到的
peer 永远是 `127.0.0.1`,**拿不到 PSK identity**。所以服务器日志里的设备 ID
只能来自 `hello` 里的 `dev` 字段,那是设备自报的,不具密码学约束力。
现阶段无所谓(能连上的都是持密钥的自己人);真要把会话和身份绑死,
得让 stunnel 走 PROXY protocol 或改用 Python 3.13 自己终结 TLS。不在当前计划里。

### 7.4 历史方案(留档)

#### 本机 PC(rev.4 及之前)

最常见的"连不上"原因,现在只在 `SERVER_USE_TLS=0` 的局域网调试路径上还适用:
ESP32 要连的是 PC 的局域网 IP 不是 `localhost`;Windows 防火墙默认拦入站;
PC 的 DHCP 地址会变;PC 睡眠会断连。

#### 树莓派 3 够不够?(2026-09-22 评估:够,余量很大)

结论留档,因为它同时解释了"这台服务器到底有多轻":
**不做任何信号处理**,ASR/TTS/LLM 全在云上,本机只是搬运 + 编排。
16 kHz PCM16 = 32 KB/s 单向,一台设备满打满算 64 KB/s。
Pi 3 的 A53 没有 ARMv8 crypto 扩展,软件 AES 也有几十 MB/s —— 差三个数量级。
1 GB 内存,Python + `websockets` + `aiohttp` 常驻约 60~80 MB。

真跑不动 Pi 3 的只有一种情况:哪天想把 ASR 换成本机 Whisper。不在当前计划里。

若哪天换回 Pi:走有线网别用板载 2.4 GHz WiFi(会和 ESP32 抢同一个 AP,
抖动直接加到音频链路上);日志别往 SD 卡猛写。
stunnel 那条在 Pi 上同样适用,而且正是当初选它的理由。

### 7.5 连不上的时候按这个顺序查

一条链路四段,**每段都有不用烧 ESP32 就能单独验的办法**。
别跳着查 —— 现象在最后一段,原因往往在前面。

| # | 查什么 | 怎么验 | 常见原因 |
|---|---|---|---|
| 1 | Python 活着吗 | `systemctl status esp32-server` | venv 路径、`WorkingDirectory` |
| 2 | 服务器逻辑对吗 | VPS 上直接跑 `tools/smoke_echo.py` | 逻辑锅,和网络无关 |
| 3 | 监听面对吗 | `ss -lntp \| grep -E ':443\|:8765'` | 8765 显示成 `0.0.0.0` → 立刻停下,那是个洞 |
| 4 | TLS-PSK 握得上吗 | `openssl s_client -psk_identity ... -psk ... -tls1_2` | `psk.secrets` 权限/属主、hex 抄错、套件没限死 |
| 4b | stunnel 配置本身 | `journalctl -u stunnel-esp32 -n 20` | **行尾 `;` 注释** —— 见下 |
| 5 | 公网到得了吗 | 从开发机对域名跑同一条 `s_client` | **云厂商安全组** —— 和 ufw 是两道独立的墙 |
| 6 | 设备侧 | 串口日志 | SSID 是 5G、PSK 抄错、域名没填 |

第 5 行是"配置全对但就是连不上"的头号原因,改了 ufw 不等于改了安全组。

**2026-09-22 首次部署实际踩到的两个坑,都已经修进 `deploy/` 里了:**

1. **stunnel 的配置解析器不支持行尾 `;` 注释。**
   `debug = 4    ; 0~7` 会把 `4    ; 0~7` 整个当成值,报 `Illegal debug level` 拒绝启动。
   注释必须独占一行。这一条在 stunnel 文档里没有明说
2. **`output = /dev/stdout` 在 systemd 下会让服务起不来。**
   `StandardOutput=journal` 时 `/dev/stdout` 指向的是 journald 的 unix socket,
   stunnel 拿它当普通文件去 `open()`,在 socket 上失败。
   前台模式默认就打 stderr,journald 照样收 —— **什么都不配是对的**

另外 stunnel 5.72 **没有** `-test` 参数(它会把 `-test` 当成配置文件名),
想验配置只能直接起服务看 journal。

## 8. 参考

- [大模型流式语音识别 API — 豆包语音](https://docs.volcengine.com/docs/6561/1354869)
- [WebSocket 单向流式-V3(语音合成) — 豆包语音](https://docs.volcengine.com/docs/DoubaoVoice/WebSocketUnidirectionalStreaming-V3?lang=zh)
- [HTTP Chunked/SSE 单向流式-V3 — 豆包语音](https://docs.volcengine.com/docs/6561/1598757?lang=zh)
- [DeepSeek API 定价与模型列表](https://api-docs.deepseek.com/quick_start/pricing)
