# ESP32-C3 AI Voice — 服务器侧规格

> 设备侧规格见 `AGENT.md`。两边的交界是 `AGENT.md` §5 定义的那套 WS 协议。
> 本文件只管交界**以上**:厂商协议、会话编排、对话历史、密钥。
> 最后更新:2026-09-22(随 AGENT.md rev.2 新建)

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

- 多一个必须常开的组件。开发阶段跑在本机 PC 上,PC 一关机设备就是块砖
- 多一跳。服务器在家里时,服务器→火山这段走家宽,§3 的延迟数字要往上加 100~300 ms
- 上行 PCM 256 kbps 会持续占家宽上行
- 服务器本身要写、要部署、要监控。工作量大概和设备侧省下来的相当——只是换到了一个好调试得多的环境里

---

## 1. 技术选型

| 项 | 取值 | 理由 |
|---|---|---|
| 语言 | **Python 3.11+ / asyncio** | 火山 ASR/TTS 官方 demo 是 Python,那套二进制帧协议可以直接抄,不用从文档重新翻译一遍 |
| WS 服务端 | `websockets` | 够用,API 简单。不需要 FastAPI 的那套 HTTP 能力 |
| HTTP 客户端 | `aiohttp` | 连接池常驻,DeepSeek 调用无握手开销 |
| 部署 | **开发阶段:本机 PC** | 最终形态未定,见 §7 |
| 密钥 | 环境变量 / `.env`,**不进 git** | |

---

## 2. 目录结构

```
esp32_server/
  main.py             # websockets.serve,每连接一个 Session
  session.py          # 回合状态机 + 对话历史 + seq 管理
  volc_proto.py       # 火山二进制帧的编解码(ASR/TTS 共用)
  volc_asr.py         # ASR WS 客户端
  volc_tts.py         # TTS WS 客户端
  llm.py              # DeepSeek,stream=True,句子切分
  pacer.py            # 下行音频速率整形
  config.py           # 从环境变量读密钥
  tools/
    pc_client.py      # ★ PC 端假设备,见 §6
```

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

⚠️ 开发阶段跑在本机 PC 上时,PC→火山走家宽 RTT,上面每一项都要往上加。

### 3.4 连接复用

- **DeepSeek**:`aiohttp.ClientSession` 全局常驻,keep-alive。这一项在 rev.1 里是最贵的(每回合 1.5~3.0 s,含握手),复用后降到 0.3~0.6 s
- **ASR / TTS**:两者同在 `openspeech.bytedance.com`,TLS session 可复用。火山的 session 是绑回合的,但底层 TCP/TLS 连接可以预热
- 可以在 `IDLE` 期间预热下一回合的 ASR 连接,把 0.3~0.5 s 里的握手部分也吃掉

### 3.5 下行速率整形(`pacer.py`)

TTS 生成通常快于实时播放。一次性推下去会打爆设备的 24 KB 环形缓冲,也让打断变得迟钝(TCP 缓冲里积压一堆已经不该播的音频)。

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

---

## 5. DeepSeek 要点

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

---

## 7. 部署

### 7.1 当前:本机 PC(开发阶段)

实操注意,这几条是最常见的"连不上"原因:

- ESP32 要连的是 **PC 的局域网 IP**(`192.168.x.x`),**不是 `localhost`**
- Windows 防火墙默认拦入站,要给 Python 或监听端口放行
- PC 的 DHCP 地址会变 → 路由器里绑静态,或在 `config.h` 里留一个串口可改的服务器地址
- PC 睡眠会断连,开发时关掉睡眠

### 7.2 最终形态(未定)

若上公网,倾向**国内轻量 VPS**(阿里云/腾讯云/火山云,1C2G 足够):和 `openspeech.bytedance.com` 同区域,新增的一跳几乎不花时间,而且省掉了设备侧每回合的 TLS 握手——净延迟反而比直连低。

### 7.3 TLS(Stage 12)

当前开发阶段走明文 `ws://`。上线前换 `wss://`。

倾向方案:**自签 CA + IP 直连 + 固件内置根证书**

- 自己签一个 CA,签发带 **IP SAN** 的服务器证书
- CA 公钥(约 1.4 KB)编进固件,`client.setCACert()`
- 不用域名、不用 ICP 备案
- 只信任自己这一个 CA,内存开销比信任公共证书库还小,安全性也比 rev.1 考虑过的 `setInsecure()` 强得多

设备侧的堆预算见 `AGENT.md` §5.6,**Stage 6 就要实测,不要等到 Stage 12**。

### 7.4 设备鉴权(Stage 12)

`hello` 帧里带 per-device token,服务器校验后才回 `ready`。开发阶段可以先不做。

---

## 8. 参考

- [大模型流式语音识别 API — 豆包语音](https://docs.volcengine.com/docs/6561/1354869)
- [WebSocket 单向流式-V3(语音合成) — 豆包语音](https://docs.volcengine.com/docs/DoubaoVoice/WebSocketUnidirectionalStreaming-V3?lang=zh)
- [HTTP Chunked/SSE 单向流式-V3 — 豆包语音](https://docs.volcengine.com/docs/6561/1598757?lang=zh)
- [DeepSeek API 定价与模型列表](https://api-docs.deepseek.com/quick_start/pricing)
