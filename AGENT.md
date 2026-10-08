# ESP32-C3 AI Voice — Agent 工作规格 (修订版)

> 本文件取代 `ESP32_C3_AI_Voice_MVP.md` 中与网络层、状态机、I2S 切换相关的部分。
> **2026-10-08 更新：当前固件已迁移至本机 ESP-IDF 6.1.0，目标是 ESP32-C3-MINI-1-H4X 定制板。**
> 硬件以 `hardware/schematics.pdf` 和 `hardware/DESIGN_CONSTRAINTS.md` 为准；本文件旧的 Arduino、SuperMini、INMP441、MAX98357A 接线与构建说明已过时。
> 新固件构建、引脚、电源策略和试板项目见 `firmware/ESP32C3_AI_Voice/README.md`。下文的服务器协议和会话行为继续保留。
> 服务器侧规格见 `SERVER.md`。
> 最后更新:2026-09-22(rev.5 — 服务器搬上公网 VPS;`wss://` + TLS-PSK 从 Stage 12 提前落地;
> 设备侧连接超时按广域网重新标定。rev.4 的阶段定义与 Stage 6+6.5+7 合并交付仍然有效)

---

## 0. 本文件的地位

`ESP32_C3_AI_Voice_MVP.md` 是最初的设想稿,其中硬件部分正确,网络层是按"自定义 WebSocket 长连接 + 自建服务器"写的。

本文件 rev.1 曾把架构定为**设备直连火山 + DeepSeek,无中继服务器**,并据此否掉了原文档 §9。

**rev.2 撤销了这个决定**:在设备与云厂商之间加一台自建服务器。于是设备侧协议**退回到原文档 §9 设想的那条持久 WSS + 自定义消息**(TURN_START / AUDIO_CHUNK / RESPONSE_AUDIO …)。§6 的第 1 条修正因此作废。

分工:

- **本文件** = 设备侧。硬件、I2S、状态机、设备↔服务器协议。设备从此不认识"火山"和"DeepSeek"这两个词。
- **`SERVER.md`** = 服务器侧。厂商协议(火山 ASR/TTS 二进制帧、DeepSeek)、会话编排、对话历史、密钥。

**冲突时以本文件为准。** 第 6 节逐条列出了对原 MVP 文档的修正(含 rev.2 的撤销)。

---

## 1. 已确定的技术选型

| 项 | 取值 | 备注 |
|---|---|---|
| MCU | ESP32-C3 SuperMini (Teyleten Robot) | 单核 RISC-V @160MHz,4MB flash,**无 PSRAM** |
| Arduino 开发板选项 | **MakerGO ESP32 C3 SuperMini** | 见 §2 |
| Arduino-ESP32 核心 | **3.3.12** (ESP-IDF **5.5.5**) | 已安装并核对 `platform.txt` |
| I2S 驱动 | IDF 新版 `driver/i2s_std.h` | 不用 legacy `driver/i2s.h`,不用 Arduino `ESP_I2S` |
| 麦克风 | INMP441,L/R→GND(左声道) | |
| 功放 | MAX98357A,SD 由 GPIO10 直驱 | 3.3V → 左声道 + 使能 |
| **架构** | 设备 ⇄ **自建服务器** ⇄ 云 API | rev.2 决定。设备侧只有一条持久 WS |
| 服务器语言 | **Python + asyncio** | 火山官方 demo 是 Python,二进制协议可直接抄 |
| 服务器部署 | **公网 VPS + systemd**,Python 只听 `127.0.0.1`,TLS 由 stunnel 终结 | rev.5 落地,见 `SERVER.md` §7 |
| 设备↔服务器传输 | **`wss://` + TLS-PSK**(TLS 1.2,纯 PSK 套件);`SERVER_USE_TLS=0` 退回明文,仅供局域网调试 | rev.4 定案,rev.5 随服务器上公网提前落地,见 §5.6 |
| ASR / TTS / LLM | 默认全走阿里云百炼(ASR / TTS / Qwen);火山、DeepSeek 为备选,各一个开关 | **全部在服务器侧**,详见 `SERVER.md`。设备不受影响 |

---

## 2. 开发板选择 (已核对 boards.txt)

**选 `MakerGO ESP32 C3 SuperMini`。**

对比 3.3.12 中三个候选:

| | MakerGO C3 SuperMini | Nologo C3 Super Mini | ESP32C3 Dev Module |
|---|---|---|---|
| variant 引脚定义 | 与 Nologo 一致(多 TX1/RX1、BOOT_BUILTIN) | — | `LED_BUILTIN` 按 **RGB 可寻址灯**定义 ✗ |
| `cdc_on_boot` | **1**(默认开) | 1 | 0(默认关) |
| flash | 4MB / **dio** | 4MB / qio | 需手选 |
| DTR/RTS | 均禁用 | 均启用 | — |

理由:

- Teyleten Robot 的板子是 SuperMini 公版设计,与 MakerGO 同源,引脚完全一致
- `cdc_on_boot=1` 默认开 → 串口直接可见,不必手动改菜单(SuperMini 第一大坑)
- `flash_mode=dio` 对克隆板兼容性更好
- **不要选 ESP32C3 Dev Module**:其 `LED_BUILTIN` 按可寻址 RGB 定义,与 SuperMini 的普通 LED(GPIO8,低电平点亮)不符

---

## 3. 硬件:与现实核对过的结论

### 3.1 引脚(沿用原文档,已验证无误)

```
GPIO4  ─┬─ INMP441 SCK      ┐
        └─ MAX98357A BCLK   │ 共享,C3 单 I2S 控制器全双工
GPIO5  ─┬─ INMP441 WS       │
        └─ MAX98357A LRC    ┘
GPIO6  ─── INMP441 SD   → ESP32 (I2S DIN)
GPIO7  ─── MAX98357A DIN ← ESP32 (I2S DOUT)
GPIO10 ─── MAX98357A SD  (LOW=关断 / 3.3V=使能且选左声道)
GPIO3  ─── 按键 ─── GND   (INPUT_PULLUP)
```

- GPIO4~7 在 C3 上是**外部** JTAG 脚;C3 默认走 USB-JTAG(GPIO18/19),所以这四个是自由的
- 避开了 GPIO2/8/9(strapping + 板载 LED/BOOT)
- GPIO10 在 SuperMini 上有引出,非 strapping 脚

### 3.2 MAX98357A 的 SD 脚不是普通数字脚

它是**电压阈值脚**,内部 100kΩ 下拉:

```
< 0.16 V        → 关断
0.16 ~ 0.77 V   → (L+R)/2 平均
0.77 ~ 1.4 V    → 右声道
> 1.4 V         → 左声道
```

GPIO10 直驱 3.3V 落在左声道区间 → **原文档"HIGH = 使能 + 左声道"的说法正确**。

**开工前必做的检查**:多数模块板载有 1MΩ SD→VDD 电阻(出厂默认 (L+R)/2)。GPIO10 低阻抗直驱能覆盖它。但若你手上这块把 SD 焊死到 VDD,GPIO10 拉低将关不掉功放。
→ **用万用表量 GPIO10 悬空时 SD 脚电压,应为 ~0.45V。**

### 3.3 供电(**2026-09-22 已处理**)

原现状:MAX98357A 的 VIN 直接吃 SuperMini 的 5V 脚,未加大电容。

SuperMini 的 5V 脚经小肖特基二极管从 USB VBUS 引来,电流余量有限。MAX98357A 推 4Ω 到 3W 时峰值电流 >1A。

**后果是确定性的,不是可能性**:大音量播放 → 5V 塌陷 → brownout 重启。且症状看起来像固件 bug。

**处理**:

```
MAX98357A VIN ──┬── 470µF ~ 1000µF 电解(长脚接正)
                └── 0.1µF 陶瓷
                     另一端均接 GND
```

**电容已焊(2026-09-22),`OUTPUT_GAIN_DEFAULT` 的上调因此解禁。**
但固件里仍然保持 100/256 —— 合适的音量得在板上用耳朵试,不是算出来的。
上调时一次加一档、听着调,并注意 Stage 6 起**多了 WiFi 发射约 350 mA 峰值**压在同一路 5V 上:
电容解决的是音频的瞬态尖峰,不是把 USB VBUS 的平均电流余量变大了。

### 3.4 INMP441 SD 下拉

数据手册建议 SD→GND 接 100kΩ(未选中时隙时 SD 为高阻)。多数模块已自带,检查一下;没有就补一个。

---

## 4. I2S 架构:全双工共享时钟,一次初始化永不重配

**这是相对原文档最重要的改动。**

原文档要求每回合在 RX/TX 之间重装 I2S 驱动,并把这件事列为 "critical milestone"。反复 install/uninstall 容易出引脚残留、DMA 未释放、偶发死锁。

新做法(已核对 IDF 5.5.5 头文件可行):

```c
i2s_new_channel(&chan_cfg, &tx_handle, &rx_handle);   // 两个 handle 都非 NULL
                                                       // → 同一控制器全双工,共享 BCLK/WS
```

IDF 文档原文:两个 handle 都非 NULL 即全双工,RX/TX 分配在同一端口,**共享时钟信号**。

之后只用 `i2s_channel_enable()` / `i2s_channel_disable()` 切换,**永不 `i2s_del_channel`**。

### ⚠️ 修正(2026-09-22,Stage 3/4/5 实测全灭后定位)

本节原先写的是"**由软件状态机保证任意时刻只有一个 channel 处于 enable**"。
**这一条是错的,而且是 Stage 3/4/5 全部失败的直接原因。**

共享时钟意味着时钟有**所有权**。全双工下驱动会置 `tx_conf.sig_loopback`
(`soc/i2s_struct.h`:"transmitter module and receiver module sharing the same WS and BCK signals"),
GPIO4/GPIO5 上的 BCLK/WS 由 **TX 模块**产生,RX 从 TX 内部取时钟。
`i2s_channel_enable` 文档原话:"It will start outputting BCLK and WS signal."

=> **TX 一 `i2s_channel_disable`,GPIO4/5 上的时钟就停了。**
=> INMP441 是纯从机,没时钟就不吐数据,`i2s_channel_read` 只会一路超时返回 0。

**正确做法(已落实到 `audio_io.cpp`):**

- TX 在 `audioBegin()` 里 enable,之后**永不 disable**,它是整条总线的时钟源
- 不播放时靠 `auto_clear` 自动输出零,不需要人喂数据
- RX 照常 enable/disable,不影响时钟
- **"半双工"由功放 SD 脚 + RX 的 enable/disable 保证,不靠关时钟**

### 前提条件(已满足)

全双工要求 TX/RX 共用同一套时钟。这要求录音和播放采样率相同:

- 麦克风:16 kHz
- 服务器下发的音频:**约定恒为 16 kHz / PCM16LE / 单声道**(服务器负责让上游满足这一点;火山 TTS 的 `audio_params.sample_rate` 本就可选 16000、`format` 可选 pcm,所以不需要重采样)

→ **双向都是 16 kHz,条件成立。**
→ 设备侧不做任何格式协商,收到的 binary 帧一律按这个格式解释。`{"t":"ready"}` 里的 `sr` 字段仅用于开机时断言,对不上就报错,不是用来切换配置的。

### 统一配置

```
采样率      16000 Hz
slot        STEREO,32-bit slot,Philips 格式 (bit_shift = true)
BCLK        16000 × 32 × 2 = 1.024 MHz
RX          取 LEFT slot(INMP441 的 L/R 接 GND)
TX          PCM16 左移 16 位放进 32-bit slot,左右声道都写同一个值
```

RX/TX 都用 STEREO 而非 MONO,是为了让全双工下两个 channel 的 slot 配置完全一致,消除歧义。代价是 DMA 内存变大,可接受。

### 三个原文档遗漏、必须实现的机制

1. **播放尾部 DMA drain**
   停止播放不能"停止喂数据后立刻关功放"——DMA 里还有几十 ms 未播出,会切掉尾音。
   正确顺序:补满 DMA 长度的静音 → 关功放。
   ~~补完静音后再延时 DMA 时长~~(fw 0.3.2 删掉,只留 `AMP_TAIL_MS`=4 ms 给 I2S FIFO):
   `i2s_channel_write` 只能拿到 DMA **已播完**的描述符来写,静音写满 4 个描述符时,
   装着真实音频的描述符都已经播过一遍了 —— 那 70 ms 等的是静音。
   **打断例外**:被打断的回复不必保护尾音,`audioCutPlayback()` 立刻关功放,
   DMA 里残留的旧音频由下一次 `audioStartPlayback()` 多推一整个 DMA 的静音冲掉。
   **不再 disable TX**(见上方修正段:TX 是时钟源)。功放已关,TX 继续输出零不发声。

2. **欠载喂静音,而非停止喂**
   TX DMA 欠载时 I2S 会重复播放上一个缓冲区,表现为循环"滋滋"声。网络卡顿时必然发生。
   → `chan_cfg.auto_clear = true`(IDF 5.5.5 中是 `auto_clear_after_cb` 的别名),硬件层面自动输出零。
   → 网络侧另外做 200~300 ms 预缓冲再开始播放。

3. **开始播放前先推静音,再开功放**
   功放唤醒时必须面对确定的零信号,否则会"啪"一声。
   ~~原方案 `i2s_channel_preload_data()`~~ 已不适用:那个 API 只能在 READY 态调用,
   而 TX 现在常驻 RUNNING。**改为 `audioStartPlayback()` 里先 `audioWrite()` 两帧静音
   把管线对齐,再拉高 SD、等 `AMP_WAKE_MS`。** 效果相同且不依赖状态机时序。

---

## 5. 设备 ↔ 服务器协议

> 厂商侧协议(火山 ASR/TTS 二进制帧、DeepSeek)**不在本文件**,见 `SERVER.md`。
> 设备只认识下面这一套。

### 5.1 传输

一条持久 WebSocket,开机即连,断线指数退避重连(1s → 2s → 4s → … → 30s 封顶)。
保活用 WebSocket 自己的 ping/pong 控制帧,30 s 一次,连续两次无 pong 视为断线。

**用 WebSocket 的 opcode 区分控制和音频,不自定义帧头:**

```
Binary frame  =  裸 PCM16LE / 16 kHz / 单声道,无任何头部
Text   frame  =  JSON 控制消息
```

这样设备侧收到 binary 帧时可以直接**边从 socket 读边写进 I2S 环形缓冲**,全程不落地完整帧,内存恒定——正是 §7 要求的做法。

### 5.2 消息

**上行(设备 → 服务器)**

```json
{"t":"hello","dev":"c3-01","fw":"0.1"}   // 连上后第一帧,服务器回 ready
{"t":"turn_start"}                        // 按键按下
{"t":"turn_end"}                          // 按键松开
{"t":"abort"}                             // 打断(barge-in)
```

`turn_start` 与 `turn_end` 之间夹 binary PCM 帧,**100 ms / 1600 样本 / 3200 字节**一包。

**下行(服务器 → 设备)**

```json
{"t":"ready","sr":16000}                  // 握手确认
{"t":"cue","name":"thinking"}             // 让设备播本地提示音,可选
{"t":"audio_begin","seq":7}               // 之后的 binary 帧属于第 7 回合
{"t":"audio_end","seq":7}                 // 本回合音频结束 -> drain -> 关功放
{"t":"asr","text":"...","final":true}     // 仅供串口调试
{"t":"reply","text":"..."}                // 仅供串口调试
{"t":"error","code":"asr_timeout","msg":"..."}
```

设备必须容忍未知的 `t` 值并静默忽略,以便服务器先行升级。

### 5.3 三个必须实现的细节

**(a) `seq` 回合号 —— 漏掉会听到上一轮残音**

打断时服务器可能还有在途音频帧躺在 TCP 缓冲里。设备记住当前 `seq`,**丢弃所有不属于当前回合的 binary 帧**。
规则:收到 `audio_begin` 才认 seq 并开始接收;`abort` 之后到下一个 `audio_begin` 之间的所有 binary 帧一律丢弃。

**(b) 背压靠 TCP,不做应用层流控**

设备的读循环**只在播放环形缓冲有空间时才从 socket 读**,TCP 窗口自然反压到服务器。
服务器侧配合做速率整形:首包突发 300 ms 预缓冲,之后按 1× 实时喂。这条同时落实了 §4 要求的"网络侧 200~300 ms 预缓冲再开始播放"。

副作用:缓冲满时控制帧也读不到。可接受——此时唯一需要及时送达的是上行 `abort`,方向相反不受影响。

**(c) 打断不掐连接**

rev.1 §6 第 6 条写的"直接 `client.stop()` 掐断"在有服务器之后是错的:掐了就要重连,反而慢。
改为:发 `{"t":"abort"}` → 服务器 cancel 掉在途的 ASR/LLM/TTS 任务并 `seq++` → 连接始终保持。

### 5.4 设备侧模块划分

不动:`audio_io.*`、`button.*`(Stage 1~5 已验收,rev.4 起一行不改)。新增:

```
led.h/.cpp       板载 LED(GPIO8,低电平点亮)状态指示,非阻塞
cue.h/.cpp       本地提示音。256 点正弦表 + Q16 定点相位累加器,任意频率,零浮点
ring.h/.cpp      播放环形缓冲,静态数组 **16 KB(512 ms)**,绝不 malloc
net_wifi.h/.cpp  WiFi 连接 + 指数退避重连 + RSSI/状态查询;凭据读 NVS,回落 secrets.h
net_prov.h/.cpp  BLE 配网模式(fw 0.4,§5.7),给微信小程序 miniprogram/ 用
net_ws.h/.cpp    极简 WS 客户端:握手、帧解析、掩码、ping/pong、**边读边写进 ring**
proto.h/.cpp     控制消息编解码。消息就这几种,**手写字符串匹配,不引 ArduinoJson**
session.h/.cpp   设备状态机,见 §8
```

`config.h` 改动:加 LED 引脚、ring/预缓冲尺寸、各类超时、堆水位线;
`NET_CHUNK_SAMPLES` 从 3200(200 ms)改为 **1600(100 ms)**——200 ms 是火山的要求,
现在由服务器重新打包满足,设备不再受此约束;删掉只有验收台用的 `REC_TEST_SECONDS`。

WiFi 凭据、服务器域名/端口、设备 ID 和 TLS-PSK **不进 `config.h`**,
放 `secrets.h`(已在 `.gitignore`),仓库里只提交 `secrets.h.example` 占位。

**rev.4 起串口是纯日志,没有交互菜单。** `micShift=11`、`OUTPUT_GAIN=100`、
DC blocker 常开都写死在 `config.h`,改值 = 改常量重烧。

### 5.5 延迟预算(服务器在公网 VPS 时)

```
松开按钮
  ├─ ASR 最终文本        0.3 ~ 0.5 s   (ASR WS 常驻保活)
  ├─ DeepSeek 首 token   0.3 ~ 0.6 s   (aiohttp 连接池,无握手)
  ├─ 攒够第一句           0.1 ~ 0.3 s
  ├─ TTS 首个 PCM 包      0.2 ~ 0.4 s
  └─ 设备预缓冲           0.2 ~ 0.3 s
────────────────────────────────────
  1.2 ~ 2.1 s      (rev.1 的直连方案是 2.5 ~ 4.5 s)
```

收益主要来自服务器侧的**句级流水线**:LLM 流式输出,收到第一个句号就立刻送 TTS,不等整段生成完。详见 `SERVER.md`。

⚠️ **上面的数字成立的前提是服务器与火山/DeepSeek 同区域。** rev.5 当前的 MVP 服务器在美国,
不满足这个前提 —— Stage 8 接入云厂商前要换回国内备案服务器,否则每一项都要往上加一个跨太平洋 RTT。
（Stage 6.5 的回声链路不碰云厂商,不受此影响。）

### 5.6 明文 → TLS:预算与方案(rev.4 定案,**rev.5 提前落地**)

~~开发阶段用明文 `ws://`,Stage 12 换 `wss://`~~。
**rev.5 把 TLS 从 Stage 12 提到了现在** —— 服务器搬上公网 VPS,
明文跑在公网上不是"暂时将就",是把零鉴权的端口开给全网。
所以固件现在默认 `SERVER_USE_TLS=1`,走 `wss://` + TLS-PSK;
`SERVER_USE_TLS=0` 保留给局域网直连调试。

风险原本是**最后加 TLS 时才发现堆不够**。rev.3 打算在 Stage 6 写一个探针去实测;
**rev.4 取消了探针** —— 直接查 arduino-esp32 3.3.12 的 sdkconfig,得到的结论比实测更硬。

#### 先纠正 rev.3 的一个错误:`setBufferSizes()` 根本不存在

rev.3 的预算表和 §7 都把 `client.setBufferSizes(2048, 2048)` 当成"把 TLS record buffer
从 16 KB 降下来"的主要旋钮。**这个 API 在 arduino-esp32 3.x 里没有。**
`WiFiClientSecure` 在 3.x 只是 `NetworkClientSecure` 的别名,其公开方法只有:

```
setInsecure / setPreSharedKey / setCACert / setCertificate / setPrivateKey
setCACertBundle / useBuiltinCACertBundle / setHandshakeTimeout / setAlpnProtocols
```

缓冲区大小是**编译期 sdkconfig 决定**的,而 Arduino 用的是预编译 IDF。实际值
(`packages/esp32/tools/esp32c3-libs/3.3.12/sdkconfig`):

```
CONFIG_MBEDTLS_SSL_MAX_CONTENT_LEN=16384
# CONFIG_MBEDTLS_ASYMMETRIC_CONTENT_LEN is not set      <- 收发不能不对称
  (整个 sdkconfig 里没有 CONFIG_MBEDTLS_DYNAMIC_BUFFER)  <- 不能握手后释放
CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC=y                     <- 只能吃内部 DRAM
CONFIG_MBEDTLS_SSL_KEEP_PEER_CERTIFICATE=y              <- 握手后仍留着对端证书
CONFIG_MBEDTLS_PSK_MODES=y / KEY_EXCHANGE_PSK=y / ECDHE_PSK=y   <- PSK 可用
```

=> **每条 TLS 连接稳态钉死 in 16 KB + out 16 KB = 32 KB,没有任何运行期旋钮。**
真要降下来只能自己编译 core,或转 ESP-IDF/PlatformIO 去开 `DYNAMIC_BUFFER`。

#### 按上面的硬事实重算

| | 明文 | 自签 CA | **PSK(采用)** |
|---|---|---|---|
| WS 缓冲 | 4 KB | 4 KB | 4 KB |
| 播放环形缓冲 | 16 KB | 16 KB | 16 KB |
| I2S DMA | 8 KB | 8 KB | 8 KB |
| 录音帧缓冲 | 3 KB | 3 KB | 3 KB |
| mbedTLS in/out(钉死) | — | 32 KB | 32 KB |
| ssl_ctx + 证书常驻 | — | ~4 KB | ~1 KB |
| 握手峰值额外(X.509 解析) | — | ~20 KB | ~3 KB |
| **峰值合计** | **~31 KB** | **~87 KB** | **~67 KB** |

150 KB 可用堆下,CA 方案能过但余量薄,**PSK 方案舒服**。

#### ✅ 实测(2026-09-22,真机跑通 wss:// 回声回合)

表里和 TLS 相关的三项(in/out 32 KB + ssl_ctx ~1 KB + 握手峰值 ~3 KB = **36 KB**),
实测 **39.2 KB**,高 3.2 KB(9%)。**预算是准的。**

堆的实际去向(`[HEAP]` / `[TLM]` 常驻遥测):

```
开机              free=231624  maxAlloc=114676
  音频初始化       -18232 B  (17.8 KB)  -> 213392
  WiFi 协议栈      -53564 B  (52.3 KB)  -> 159828
  TLS-PSK 握手     -40188 B  (39.2 KB)  -> 119640   maxAlloc=94196
一个回合之后        free=120104  maxAlloc=94196  minEver=101144
```

**两条要记住的:**

1. **余量比本节假设的宽得多。** "150 KB 可用堆"是保守估计,实测开机有 231.6 KB,
   TLS 之后仍有 120 KB,`maxAlloc` 94196 B = `HEAP_MIN_MAXALLOC`(24576)的 **3.8 倍**。
   也就是说 CA 方案(再多 ~20 KB 峰值)其实也放得下 —— **选 PSK 的理由要修正**:
   决定性的不是堆,而是"密钥即身份"省掉一整套 token,以及不用管证书过期
   (这台设备没有便捷的远程升级通道,证书到期 = 所有设备同时变砖)
2. **`maxAlloc` 因 TLS 下降了正好 20480 B(20 KB),而 free 降了 39.2 KB** ——
   差额是碎片。目前无所谓,但长连接反复断线重连之后要盯的就是这个数,
   不是 free(§7)

一个回合前后 `free` 完全一致(120104),**无泄漏**。

#### 方案:PSK-TLS

**Stage 12 走 `TLS-PSK`(`setPreSharedKey()`),不用自签 CA。** 理由:

- 省掉 X.509 解析峰值(~20 KB)和证书常驻,峰值 ~87 KB → ~67 KB
- 不用内置根证书 PEM,不用管证书过期、不用建 CA
- **预共享密钥本身就是设备身份** —— §10 的"设备鉴权"一并解决,不必再做一套 token

代价在服务器侧:Python 的 `ssl.SSLContext.set_psk_server_callback()` 是 **3.13** 才加的。
**rev.5 采用 stunnel** 做 TLS 终结(`PSKsecrets`,Python 侧一行不改),
服务器留在 3.11。见 `SERVER.md` §7.1/§7.2。

#### 落地时核实过的两条,写死在配置里(rev.5)

1. **服务器必须钉死 TLS 1.2。** 预编译 IDF 里
   `# CONFIG_MBEDTLS_SSL_PROTO_TLS1_3 is not set` —— 设备根本不会 1.3
2. **服务器必须只留纯 PSK 套件。** `RSA_PSK` 也是开着的,一旦被选中,
   服务器会下发证书链,而设备侧走 PSK 分支时没装 CA,验证必挂

相应地,固件里设了 PSK 就**不要**再调 `setCACert()` ——
`ssl_client.cpp` 里 CA / CA-bundle / PSK 是一串 else-if,CA 排在前面,
PSK 会被静默无视,然后挂在一个和 PSK 毫无关系的错误上。

#### 真实数字怎么拿到的(回看:这个决定是对的)

**没写探针。** Stage 6 起固件常驻一行遥测(`state / rssi / free / maxAlloc / minEver`),
rev.5 在 `wsConnect()` 握手成功处加打一行 —— 上面那组实测数字就是它们给的,
**一次性代码一行都没写**。rev.3 原计划的探针如果真写了,到今天已经是死代码。

`ring` 16 KB → 12 KB 那个备用旋钮**没用上,也不用留着惦记**:实测余量 3.8 倍。

### 5.7 BLE 配网模式(fw 0.4.0)

WiFi 凭据不再写死:用**微信小程序**(`miniprogram/`,协议细节见它的 README)通过 BLE 下发。

- **协议不自己写**:核心自带的 `WiFiProv`(乐鑫 network_provisioning 1.0.2,NimBLE),
  **Security 1**(X25519 + AES-256-CTR),WiFi 密码在空中是加密的。**必须显式传 `NETWORK_PROV_SECURITY_1`** ——
  `WiFiProv` 的默认值是 Security 0 明文。
- **没有 PoP**(2026-09-26 决定):玩偶没屏幕,贴纸/二维码徒增成本。兜底是物理动作 ——
  只有"没配过网"或"上电按住按键 3 s"才进配网,平时 BLE 根本不开。
- **独立开机模式**:`setup()` 里 `provWanted()` 为真就 `provRun()`,**不返回**。这次开机只有 BLE + WiFi 验证,
  不碰 WS/TLS;小程序读到"已连接"约 1 s 后 WiFiProv 收尾,设备重启进正常模式。BLE 和 TLS 从不同时占堆。
- **凭据**:连通之后才写 NVS 命名空间 `net`(`ssid`/`pass`),所以放弃配网直接断电,旧凭据不受影响。
  正常模式 `net_wifi` 先读 NVS,空才用 `secrets.h` 的 `WIFI_SSID`(开发板兜底;量产留空)。
  WiFiProv 自己也会往 esp_wifi 的 NVS 里存一份,我们不用它,下次进配网时 `reset_provisioned=true` 会清掉。
- **失败不重启**:密码错 / 找不到 AP 时设备放一声降调,等小程序在同一连接里 ctrl reset 后重发。
- **提示**:LED 每 1.5 s 双闪;进入时上行三声 `cueProv()`;连上 WiFi 时 `cueLinkUp()`。
- **和小程序共用的常量**在 `config.h`:`PROV_SERVICE_UUID`(`10624c9a-f2aa-4ca8-8594-9cd3cc78db3f`)、
  `PROV_NAME_PREFIX`(`AIFIG_`)。改一边必须改另一边。
- **代价(2026-09-27 实测,`min_spiffs` 分区)**:flash 1089159 -> 1460383 B(**+371 KB**),
  静态 RAM 62988 -> 65236 B(+2.2 KB)。正常模式不初始化 BLE,运行期堆不受影响。
  **默认分区(1.31 MB)装不下 —— Arduino IDE 里「Partition Scheme」必须选
  `Minimal SPIFFS (1.9MB APP with OTA/128KB SPIFFS)`**(命令行 `PartitionScheme=min_spiffs`),
  还顺带留了以后 OTA 的位置。换分区表后第一次烧录会重写分区表,NVS 位置不变(0x9000)。

---

## 6. 对原 MVP 文档的逐条修正

| # | 原 MVP 文档 | 改为 | rev.2 |
|---|---|---|---|
| 1 | §9 一条持久 WSS + 自定义 TURN_START/END 协议 | ~~三段串行,用厂商协议~~ → **恢复原文档做法**:一条持久 WS + 自定义消息,见 §5 | **已撤销** |
| 2 | §8 单一 `WAITING_FOR_RESPONSE` 状态 | ~~拆为三个状态~~ → 设备侧合并为单一 `WAITING`,分段提示音改由服务器 `cue` 驱动,见 §8 | **已撤销** |
| 3 | §4 每回合切换(重装)I2S 驱动 | 一次性建全双工双 channel,只 enable/disable,永不重装 | 不变 |
| 4 | §10 音频块 20~40 ms | ~~200 ms(火山要求)~~ → 设备上行 **100 ms / 3200 字节**;200 ms 的约束移到服务器侧,由服务器重新打包 | **已修订** |
| 5 | §13 Stage 7 先做上行(ASR) | ~~TTS 先打通~~ → 改为 **回声服务器先打通**,更早、且完全不依赖厂商,见 §9 | **已修订** |
| 6 | §8 打断需发 `CANCEL_RESPONSE` | ~~直接 `client.stop()` 掐断~~ → **恢复协议级取消**:发 `{"t":"abort"}`,连接保持,见 §5.3(c) | **已撤销** |
| 7 | §11 `audio_input.*` / `audio_output.*` 分离 | 合并为 `audio_io.*`——全双工共享初始化后强行拆分反而更易错 | 不变 |
| 8 | §7 停止播放 = 停喂 + 关功放 | 补静音 → drain → 关功放 → disable(否则切尾音) | 不变 |
| 9 | (未提) | 新增:`auto_clear` 防欠载重播;预载静音防爆音;堆水位监控;`seq` 回合号防残音 | 扩充 |
| 10 | §11 `src/main.cpp` (PlatformIO 结构) | Arduino IDE:入口为 `ESP32C3_AI_Voice/ESP32C3_AI_Voice.ino` | 不变 |

第 1、2、6 条的撤销有同一个原因:它们都是"没有服务器"这个前提推出来的结论。前提没了,结论跟着没。
原 MVP 文档 §9 在**有服务器**的假设下是对的——它只是当时和实际选型不匹配。

---

## 7. C3 资源预算(硬约束)

400 KB SRAM,无 PSRAM。WiFi 全开后实际可用:

| 项 | 占用 |
|---|---|
| WiFi 协议栈 | ~50 KB |
| mbedTLS 握手峰值 | ~45 KB |
| 系统/ROM 预留 | ~60 KB |
| **可用堆** | **≈ 150 KB** |

由此产生两条强制规则:

1. **音频循环内严禁动态分配内存**
2. **自己写极简 WebSocket 客户端,不用 Links2004 等现成库**
   现成库会把整帧组装进 RAM 才回调;音频单帧可能几十 KB,在 150 KB 堆上很危险。
   自写可做到:读帧头 → 读长度 → **边从 socket 读边直接写进 I2S 环形缓冲**,全程不落地完整帧,内存恒定。
   顺带也更好控制握手时的自定义 header。

这条规则在 rev.2 下**更容易做到**了:服务器下发的是裸 PCM,没有厂商的嵌套二进制封装要拆。

### 堆碎片:rev.2 后风险大幅下降

rev.1 的直连方案每回合要建立/销毁 2~3 条 TLS 连接,反复 malloc/free 几十 KB 会导致堆碎片化。
典型症状:前 20 轮正常,第 30 轮突然 `connection failed`,重启后又好了。**这曾是本项目最难排查的风险项。**

rev.2 改为一条**开机建立、长期保持**的连接后,这个症状的成因基本消失——稳态运行期间不再有大块 TLS 内存反复申请释放。

但监控不要撤,原因是重连路径仍会碰这些内存:

- ~~`client.setBufferSizes(2048, 2048)`~~ **这个 API 不存在**;TLS 缓冲是编译期钉死的 32 KB,见 §5.6
- 常驻遥测每 10 s 一行 `state / rssi / free / maxAlloc / minEver`——**碎片化先体现在 `maxAlloc` 暴跌**
- 设水位线,`maxAlloc` 低于阈值 → 播错误提示音 + 软复位(不是无声重启)
- **新增关注点**:长连接下要盯的是"反复断线重连 N 次之后"的堆,而不是"连续对话 N 轮之后"。
  制造重连的办法是关掉服务器进程 / 拔路由器电源,**不需要为此单独写测试项**

### 其他现实风险

- **SuperMini 天线**:大量克隆板陶瓷天线阻抗匹配差,信号比正常 C3 模块弱 10~20 dB。音频流对丢包敏感。出现随机卡顿/断连时**先怀疑天线,不是代码**;测试时路由器放近
- **INMP441 增益**:理论上 `>>16` 是 1:1,但 INMP441 实测很小声,常用 `>>14`(×4)或 `>>11`(×32)。必须靠 Stage 3 打 RMS 现场标定,写死数字大概率不对
- **DC 偏置**:INMP441 有明显直流偏置,一阶高通(DC blocker)对 ASR 帮助很大

---

## 8. 状态机

```cpp
enum class VoiceState {
    IDLE,          // 功放关,等按键。WS 已连接
    RECORDING,     // 按住:边录边推 100ms PCM 帧
    WAITING,       // 松开:已发 turn_end,等服务器。设备不知道服务器走到哪一步
    PLAYING,       // 收到 audio_begin,播放中(仍在下载)
    ERROR_STATE,   // 含 WS 断线;此状态下按键只触发立即重连
};
```

rev.1 的 `ASR_FINALIZING` / `LLM_THINKING` / `TTS_FETCHING` 三个状态**合并为 `WAITING`**。
理由:设备不再知道服务器走到哪一步,硬猜只会猜错。想保留分段提示音的话,由服务器发 `{"t":"cue","name":"..."}` 驱动——服务器知道真实进度,比设备猜准。

超时也跟着简化:设备只保留一个总超时(建议 8 s,从 `turn_end` 起算到收到 `audio_begin`),分段超时归服务器管。

**等待音效(Stage 11,fw 0.3)**:服务器收到 `turn_end` 立刻发 `{"t":"cue","name":"thinking"}`,
设备在 `WAITING` 里循环播"咕噜咕噜"的冒泡声(`bubble.*`),直到回复接上:

- **非阻塞**。`cue.*` 的提示音是阻塞的,等待音效不能是 —— 否则收不到 `audio_begin`。
  `bubble.*` 只是个样本发生器,session 每轮 loop 取 20 ms 写进 I2S,`audioWrite` 的阻塞当节拍器,
  和 `PLAYING` 同一个套路
- **无缝接回复**。`audio_begin` 之后预缓冲攒够之前**接着冒泡**,攒够了再等到两个气泡之间的空隙才切,
  功放和 I2S 一直开着。不在气泡中间硬切,不"啪"
- 只在 `WAITING` 时认 `thinking`;不认识的 cue 名打日志后忽略(服务器可以先加新音效)
- `WAITING` 时收到服务器 `error` = 这一回合不会有声音了,**立刻**回 IDLE 播错误音,不再干等 8 s 超时
- 零浮点:正弦查 `cue.*` 的表,相位 Q32、包络 Q15、随机数 xorshift32(§9.1b)

**打断(barge-in)**:任意非 IDLE 状态按下按钮 →

```
发 {"t":"abort"}  →  立刻关功放(fw 0.3.2 起不再 drain 尾音)  →  清环形缓冲
→  丢弃后续所有 binary 帧直到下一个 audio_begin  →  进 RECORDING
```

注意顺序:**先发 abort 再关功放**。abort 是上行,不受下行缓冲拥塞影响,越早发服务器越早停止烧 token。
另外**不掐连接**——见 §5.3(c)。

---

## 9. 实施阶段

### ⚠️ rev.4 换掉了"阶段"的定义

rev.3 的 Stage 1~5 是**串口菜单里一个可以选着跑的测试项**。硬件验收完成后这个形态就该退休。

**rev.4 起,每个阶段 = 一版烧进去就自己跑起来的真固件**,后一版在前一版上加功能,
代码只增不重写。串口是纯日志输出,没有菜单,没有交互。

Stage 1~5 的验收台(`stage1_gpio`~`stage5_loopback`、`runTone`、`heapReport`、
`readNumber`、整个菜单)已从固件中**整体删除**。代码留在提交 `f955db1` 里,
要复现某个硬件现象随时 checkout 回来,不留在工作树上碍事。

| 阶段 | 烧进去它会做什么 / 服务器上跑什么 | 在哪 | 依赖厂商? | 状态 |
|---|---|---|---|---|
| 1~5 | ~~硬件验收台:按键/功放、TX 测试音、RX 标定、切换压测、录放回环~~ | 设备 | ✗ | **✓ 通过 09-22,代码已删** |
| **6** | 上电自连 WiFi、断线自愈、LED + 提示音、常驻堆遥测。**这一版就是最终固件的 `setup()`/`loop()` 外壳** | 设备 | ✗ | **✓ 2026-09-22 真机** |
| **6.5** | 回声服务器骨架。**协议级回声**,不是裸回声——说全套 §5.2 的话 | 服务器 | ✗ | **✓ 2026-09-22 VPS** |
| **7** | 按住说话 → 松开 → 听到自己的声音从服务器回来。**第一个能用的形态** | 设备 | ✗ | **✓ 2026-09-22 真机 wss:// 回合** |
| 8 | 服务器 TTS 单通,`pc_client.py` 发文本 → 存 wav | 服务器 | ✓ | **代码完成,mock 验过;待填密钥真连百炼**(TTS 已从火山换成阿里云百炼,`SERVER.md` §4.6 / §6.1) |
| 9 | 服务器 ASR 单通,`pc_client.py` 推 wav → 打印文本 | 服务器 | ✓ | **✓ 2026-09-22 真连百炼**(`SERVER.md` §6.2);`REPLY_MODE=asr` 时真机也能听到识别结果 |
| 10 | 服务器 LLM + 句级流水线,`pc_client.py` 跑全链路 | 服务器 | ✓ | **✓ 2026-09-22 真连百炼**,turn_end -> 首包 1.8~2.2 s,无断顿(`SERVER.md` §6.3);`REPLY_MODE=chat` 时真机不用重烧就能对话 |
| 11 | 把回声换成真回复:`WAITING` 超时、`abort` 打断、`cue` 驱动 | 两边 | ✓ | **✓ 2026-09-22 真机验收通过**:固件 0.3(咕噜咕噜等待音效)烧录后 §9.3 清单全项通过,无问题(§9.3) |
| 12 | ~~`ws://` → `wss://`~~ **已提前到 rev.5,随服务器迁上公网 VPS 一起做掉**(PSK,见 §5.6),设备鉴权随之解决 | 两边 | ✗ | **✓ 2026-09-22 真机跑通** |

**6 / 6.5 / 7 一次做完再烧**(2026-09-22 决定)。
代价:首次联调时 WiFi、WS 帧解析、环形缓冲、TCP 背压、I2S 播放五件事同时嫌疑。
收益:少一轮烧录,而且 Stage 7 一次就烧出可用形态。排查按 §9.2 的顺序切。

**Stage 7 是设备侧形态定型点** —— 从那以后设备侧只加逻辑,不改结构。

### 9.1 Stage 1~5 验收记录(2026-09-22)

首轮上机 Stage 1 过、Stage 2 声音断续、Stage 3/4/5 全灭。两个独立根因,都在软件:

**(a) 全双工的时钟所有权 —— 害死 Stage 3/4/5**
详见 §4 的修正段。原设计"任意时刻只有一个 channel 处于 enable"会在关掉 TX 时一并停掉
GPIO4/5 上的 BCLK/WS,INMP441 是纯从机,没时钟就不吐数据。
**已改为 TX 常开供时钟,RX 照常 enable/disable。**

**(b) `sinf()` 的大参数规约 —— 害死 Stage 2**
测试音原本逐样本算 `sinf(2π·440·t)`,相位参数随 t 单调涨到 5529 rad。
newlib 的 `__ieee754_rem_pio2f` 在 `|x| >= 2^7·(π/2) ≈ 201` 之后改走 Payne-Hanek
多精度规约,**全程 double**;而 C3 是 RV32IMC,**没有 FPU**,double 全靠软件模拟。
单样本预算只有 62.5 µs,一次调用就吃光了 → TX DMA 欠载 → `auto_clear` 填零 → 断续。
翻车点 t = 0.0727 s(第 4 帧)。**已改为 400 样本查表(11 个 440 Hz 周期,无缝循环),
实时路径上一个浮点运算都没有。**

> ⚠️ **(b) 这条会复发。** 任何跑在 16 kHz 实时路径上的代码都不能碰软件浮点 ——
> Stage 7 的播放回路、Stage 11 的状态机和打断判决都在这条路径上。
> 需要三角函数/滤波就预先查表或用定点。
> rev.3 曾在固件里留一个逐样本 `sinf` 的对照组专门复现这个现象;
> **rev.4 随验收台一起删了** —— 教训留在这份文档里,复现代码留在提交 `f955db1` 里。
> rev.4 的 `cue.*` 用 **256 点正弦表 + Q16 定点相位累加器**,任意频率,实时路径依然零浮点。

**供电**:Stage 2 在 `OUTPUT_GAIN=100`、幅度 0.6 FS 下实测无断续也无重启。
算一下就知道为什么:0.6 × 100/256 = 0.234 FS,MAX98357A 9 dB 增益 5 V 供电下
约 0.47 Vrms,4 Ω 负载 ≈ **0.055 W**,平均电流几十 mA。
**这个功率下 §3.3 的 brownout 风险根本够不着 —— 但那是因为增益压得低,不是因为电容不需要。**

**堆**:Stage 4 前后 `free=278352 / maxAlloc=139252` 三次测量完全不变(复位后基线、
Stage 4 后、Stage 5 的 `malloc(96000)` 后),既无泄漏也无碎片累积。
`maxAlloc` 只有 `free` 的一半是静态布局造成的(堆中间横着一个启动期分配),不是问题。
`maxAlloc > 131072` 说明 heap region 已合并。**进 Stage 6 后这两个数会因 WiFi 大幅下降,
以这组数字为基线对比。**

### 9.2 Stage 6+6.5+7 一次联调的排查顺序

五件事同时上线。出问题时**按这个顺序往下切,不要跳着猜**:

| # | 看什么 | 不对时锅在哪 |
|---|---|---|
| 1 | 串口有没有打印出 IP | WiFi 层:SSID/密码、是不是 2.4G、信号强度。`net_wifi` 以外的都不用看 |
| 2 | 服务器终端有没有收到 `hello` | WS 握手:IP 填错 / Windows 防火墙 / 没返回 101 |
| 3 | 服务器有没有收到 binary 帧、每帧是不是 3200 B | 上行打包或掩码 |
| 4 | 服务器日志说已回送,设备 `ring` 水位却不涨 | 下行帧解析或背压逻辑 |
| 5 | `ring` 涨了但没声音 / 断续 | 回到音频层。§9.1 的两个根因此时都已排除过,**优先怀疑供电**(WiFi 发射 ~350 mA 峰值叠加功放,电容还没焊)和 loop 时序 |

**Stage 7 的回声取代了 rev.1 的"TTS 先打通"。**
它一次性验证 WS 客户端、环形缓冲、TCP 背压、I2S 播放四件事,且完全不依赖厂商——
出问题时排查面小得多。rev.1 把 TTS 排在最前,是因为当时没有服务器可以先立起来。

### 9.3 Stage 11 真机验收清单(fw 0.3,**✓ 2026-09-22 已通过**)

服务器侧已上线且对老固件无害(0.2 收到 cue 只打日志),**先烧再测,顺序无所谓**。

**2026-09-22 真机验收:全 7 项通过,无问题。**

| # | 做什么 | 应该看到/听到 | 结果 |
|---|---|---|---|
| 1 | 烧录后看串口 | `[BOOT] ... Stage 11`、`fw=0.3`;服务器日志 `hello ... fw=0.3` | ✓ |
| 2 | 正常问一句话 | 松手 ~60 ms 后开始"咕噜咕噜",约 2 s 后无缝切到回复,切换处没有"啪" | ✓ |
| 3 | 回复播放中按键 | 立刻停,开始录新的一句(打断);服务器日志 `abort`,不再下发旧回复 | ✓ |
| 4 | 冒泡中按键 | 同上,冒泡立刻停 | ✓ |
| 5 | 拔掉 VPS 的网(或 `systemctl stop esp32-server`)时问一句 | 断线音 + LED 慢闪 -> 自动重连;不会卡在冒泡里 | ✓ |
| 6 | 什么都不说,按一下就松 | 念"没听清,能再说一遍吗?"(服务器兜底),而不是 8 s 后报错 | ✓ |
| 7 | 连问 10 轮 | 串口 `[TLM]` 的 `maxAlloc` 不持续下降、`under` 不涨 | ✓ |

听感不对就调 `bubble.cpp` 顶部那一排参数(频率范围、上扬幅度、泡长、串内/串间间隔、音量),
不用改逻辑。

**`tools/pc_client.py` 是整个计划里效率杠杆最大的一件东西。**
Stage 8~10 全部在 PC 上用它调通,ESP32 一次都不用烧。改一行服务器代码立刻能测,
而不是等一轮烧录。它同时是协议的可执行文档——设备侧实现有歧义时以它的行为为准。详见 `SERVER.md`。

### 9.4 fw 0.3.2 真机验收清单(**待测**)

0.3.2 是行为级改动(2026-09-24),PC 上只能验编译和逻辑移植,**必须烧上去用耳朵听**:

| 改动 | 内容 | 预期收益 |
|---|---|---|
| F1 | `audioStopPlayback` 删掉补静音后的 `delay(70)`,只留 `AMP_TAIL_MS`=4 ms | 每次停播(提示音、回复结束、出错)少阻塞 66 ms |
| F2 | 打断走 `audioCutPlayback`:立刻关功放,不播被打断回复的尾巴 | 按键 -> 开麦快 ~130 ms,第一个字不再被吃 |
| F3 | `wsIsConnected()` 不再碰 socket;`wsPoll` 每段只调一次 `read()`,直接读进 ring/文本/控制缓冲 | 空闲时每轮 loop 少 4~5 次 mbedTLS+lwIP 查询;下行少一次拷贝 |
| F3 | 上行零拷贝:录音直接写进 WS 帧的 payload 区,原地加掩码 | 少一次 3.2 KB 拷贝;静态 RAM 65796 -> 62988 B |
| F4 | PLAYING 预缓冲阶段没冒泡时 `delay(1)`,不再全速空转 | 省 CPU |

| # | 做什么 | 应该看到/听到 | 结果 |
|---|---|---|---|
| 1 | 烧录后看串口 | `fw=0.3.2`;服务器日志 `hello ... fw=0.3.2` | |
| 2 | 正常问一句,听回复**最后一个字** | 尾音完整,不被切(被切就把 `AMP_TAIL_MS` 往上加,别加回 70) | |
| 3 | 听开机音 / 连上音的结尾 | 同上,尾音完整 | |
| 4 | 回复播放中按键说话 | 立刻停、没有"啪";服务器 ASR 文本里**第一个字在** | |
| 5 | 打断后说很短一句(按一下就松) | 冒泡声开始时**听不到上一轮回复的残音** | |
| 6 | §9.3 的 1~7 项全部重跑 | 同 §9.3 | |
| 7 | 连问 10 轮 + 拔一次路由器 | `[TLM]` 的 `maxAlloc` 不持续下降、`under` 不涨、断线后能自己连回来 | |

### 9.5 fw 0.4.0 BLE 配网真机验收清单(**待测**)

前提:分区选 `Minimal SPIFFS`;小程序用测试号 AppID 在微信开发者工具里「真机调试」(见 `miniprogram/README.md`)。
先用乐鑫官方 App「ESP BLE Provisioning」测一遍固件(Security 1、无 PoP),固件没问题再测小程序 —— 这样出错能分清是哪一端。

| # | 做什么 | 应该看到/听到 | 结果 |
|---|---|---|---|
| 1 | `secrets.h` 删掉 WIFI_SSID 两行,烧录 | 串口 `没有 WiFi 凭据 -> 配网模式`、`BLE 广播 "AIFIG_xxxxxx"`;LED 双闪,上行三声 | |
| 2 | 乐鑫官方 App 配网(App 设置里把设备名前缀 `PROV_` 改成 `AIFIG_`,否则扫不到) | 配成功;串口 `凭据已存 NVS`、`配网结束,重启`;重启后 `凭据来自 NVS`,正常连上服务器 | |
| 3 | 按住按键上电 3 s | 进配网模式(串口 `上电时按住了按键`) | |
| 4 | 小程序配网(安卓) | 扫到 `AIFIG_xxxxxx`,约 10 s 显示成功和 IP,玩偶重启后听到连上音 | |
| 5 | 小程序配网(iPhone),**用 32 字节 SSID + 63 位密码** | 同上。这一项验证微信在 iOS 上的长写,是整条链路最大的未知 | |
| 6 | 故意输错密码 | 小程序提示「密码错误」,设备降调一声;改对后点重试,不断蓝牙就能成功 | |
| 7 | 填一个不存在的 SSID / 5G SSID | 小程序提示「找不到这个 WiFi」 | |
| 8 | 进配网后不配,直接断电再上电(之前配过网) | 用旧凭据正常连上 —— 放弃配网不丢旧 WiFi | |
| 9 | 配网后正常对话 + §9.4 第 7 项 | `[TLM]` 的 `free/maxAlloc` 与 fw 0.3.2 相当(正常模式没开 BLE) | |

---

## 10. 待办 / 未决

### 硬件(不受 rev.2 影响)

- [x] ~~**加 470µF~1000µF 电解电容到 MAX98357A VIN**~~ → **2026-09-22 已焊**。
      `OUTPUT_GAIN` 上调解禁,但固件仍留在 100 —— 音量要在板上听着调,见 §3.3
- [x] ~~量 GPIO10 悬空时 SD 脚电压~~ → Stage 1 实测能自由开关功放,
      说明 SD 没被焊死到 VDD,GPIO10 驱动得动。无需再量。
- [x] ~~确认 INMP441 模块是否自带 SD→GND 100kΩ 下拉~~ → Stage 3/5 取到干净信号,
      间接证明没问题。
- [x] ~~Stage 3 标定 `MIC_SHIFT`~~ → **实测 11**,已回填 `config.h`

### 设备侧(rev.2 新增)

- [x] ~~`config.h` 加 WiFi 凭据、服务器 IP/端口、设备 ID~~ → 改放 **`secrets.h`**(已 gitignore),
      仓库只提交 `secrets.h.example`。`NET_CHUNK_SAMPLES` 3200 → 1600 已改
- [x] ~~Stage 6 实测 TLS 堆预算~~ → **取消探针**。sdkconfig 的静态结论比实测更硬(见 §5.6);
      真实数字已由 rev.5 的 `wsConnect()` 那行日志给出:**TLS 实测 39.2 KB,预算 36 KB**(见 §5.6)
- [x] ~~确定 `ring.h` 环形缓冲最终大小~~ → **16 KB(512 ms),预缓冲 300 ms**
- [x] ~~决定是否要 `cue` 提示音~~ → 要。Stage 6 先做四种本地音:开机 / WiFi 连上 / 断线 / 错误。
      服务器驱动的 `{"t":"cue"}` 留到 Stage 11
- [ ] **路由器给开发 PC 绑静态 DHCP 租约** —— 串口已无交互,改服务器地址 = 重烧固件。
      不想动路由器就改上 mDNS,代价是设备侧多几 KB + 服务器加 `zeroconf` 依赖
- [x] ~~编译后看固件大小~~ → Stage 6+7 实测 **988723 B / 1310720 B = 75%**,静态内存 65852 B。
      rev.5 打开 TLS-PSK 后实测 **1088201 B = 83%**,静态内存 66396 B ——
      **TLS 的代价是 +99478 B flash / +544 B 静态 RAM**,还剩 222519 B 余量。
      ~~默认分区 `Default 4MB with spiffs` 够用,不用换。~~ **fw 0.4 加了 BLE 配网后 1460383 B,
      默认分区装不下,改用 `Minimal SPIFFS (1.9MB APP with OTA)`**(§5.7)。
      (注:这是**静态**开销。§5.6 那张表算的是**运行期堆**峰值 ~67 KB,
      要等真机握手时 `wsConnect()` 打的那行 maxAlloc 才有实测值。)

### 服务器侧(详见 `SERVER.md`)

- [ ] 开通百炼 `qwen3-tts-flash-realtime` + `qwen-audio-3.1-asr-flash-streaming`,填入 `DASHSCOPE_API_KEY`
      (2026-09-22 决定从火山换到百炼;火山代码留作备选,`TTS_PROVIDER=volc` 切回)
- [ ] (可选)申请/填入 DeepSeek API Key —— 默认 LLM 已是 Qwen,不填也能跑
- [ ] 选定 TTS 音色(百炼默认 `Cherry`,改 `ALI_TTS_VOICE`)
- [ ] 决定最终部署位置。**rev.5 已上公网 VPS 并跑通**,但当前这台在美国,只适合 MVP 联调;
      Stage 8 前要换国内备案服务器(见 `SERVER.md` §7.1)
- [x] ~~决定 TLS 方案~~ → **PSK-TLS**,见 §5.6。已落地:stunnel 终结,Python 留在 3.11+,**真机跑通**
- [x] ~~决定设备鉴权方式~~ → 由 PSK 的预共享密钥承担,不再单独做 token

---

### 后续计划

手机端(2026-09-26 起改为**微信小程序**,不做原生 App):蓝牙配网(fw 0.4 已写,待真机验收,§5.7)、
用户系统、订阅付费、调音量、看电量,以及电量检测硬件,记在 **`ROADMAP.md`**。其中 §3 列了对现有代码的约束 —— **改固件或服务器之前先看一眼**。

---

## 11. 参考

厂商 API 文档已移到 `SERVER.md`——设备侧不需要它们。

- `SERVER.md` — 服务器侧规格
- `ROADMAP.md` — 后续计划(App、电量)及其对现有代码的约束
- `ESP32_C3_AI_Voice_MVP.md` — 最初设想稿。硬件部分有效;§9 的网络层设想在 rev.2 下重新生效
