# ESP32-C3 AI Voice — Agent 工作规格 (修订版)

> 本文件取代 `ESP32_C3_AI_Voice_MVP.md` 中与网络层、状态机、I2S 切换相关的部分。
> 原文档的**硬件接线与引脚分配依然有效,不要改动**。
> 服务器侧规格见 `SERVER.md`。
> 最后更新:2026-09-22(rev.3 — Stage 1~5 硬件验收全部通过,§4 时钟所有权已修正)

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
| 服务器部署 | **开发阶段:本机 PC** | 最终形态未定,见 `SERVER.md` |
| 设备↔服务器传输 | 开发阶段 **明文 `ws://`**,上线前换 `wss://` | 见 §5.6 的堆预算与 Stage 6 探针 |
| ASR / TTS / LLM | 火山豆包语音 + DeepSeek | **全部在服务器侧**,详见 `SERVER.md` |

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

### 3.3 ⚠️ 供电(当前最高风险项,尚未处理)

现状:MAX98357A 的 VIN 直接吃 SuperMini 的 5V 脚,**未加大电容**。

SuperMini 的 5V 脚经小肖特基二极管从 USB VBUS 引来,电流余量有限。MAX98357A 推 4Ω 到 3W 时峰值电流 >1A。

**后果是确定性的,不是可能性**:大音量播放 → 5V 塌陷 → brownout 重启。且症状看起来像固件 bug。

**处理**:

```
MAX98357A VIN ──┬── 470µF ~ 1000µF 电解(长脚接正)
                └── 0.1µF 陶瓷
                     另一端均接 GND
```

**在加电容之前,固件中的 `OUTPUT_GAIN_DEFAULT` 必须保持在 100/256 (≈39%)。** 加了电容并实测稳定后才可上调。

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

- TX 在 `audioBegin()` 里 enable,之后**永不 disable**(直到 `audioEnd`),它是整条总线的时钟源
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
   正确顺序:补满 DMA 长度的静音 → 延时 DMA 时长 → 关功放。
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

不动:`audio_io.*`、`button.*`。新增:

```
net_ws.h/.cpp    极简 WS 客户端:握手、帧解析、掩码、ping/pong、边读边回调
proto.h/.cpp     控制消息编解码。消息就这几种,**手写字符串匹配,不引 ArduinoJson**
ring.h/.cpp      播放环形缓冲,静态数组 24 KB(≈750 ms),绝不 malloc
session.h/.cpp   设备状态机,见 §8
```

`config.h` 需要加:WiFi SSID/密码、服务器 IP 与端口、设备 ID;并把 `NET_CHUNK_SAMPLES` 从 3200(200 ms)改为 **1600(100 ms)**——200 ms 是火山的要求,现在由服务器重新打包满足,设备不再受此约束。

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

⚠️ **开发阶段服务器跑在本机 PC 上,PC→火山这一段走家宽 RTT,上面的数字要往上加 100~300 ms。** 这是开发期的正常代价,不代表最终形态。

### 5.6 明文 → TLS 的堆预算

当前选择:开发阶段用明文 `ws://`,上线前再换 `wss://`。
这么做的风险是**最后加 TLS 时才发现堆不够**。该风险可以在 Stage 6 就消掉,不必等到最后(见 §9)。

估算:

| | 明文 | 加 TLS 后 |
|---|---|---|
| WS 缓冲 | 4 KB | 4 KB |
| 播放环形缓冲 | 24 KB | 24 KB |
| I2S DMA | 8 KB | 8 KB |
| 录音帧缓冲 | 3 KB | 3 KB |
| mbedTLS 稳态(`setBufferSizes(2048,2048)`) | — | ~12 KB |
| mbedTLS 握手峰值 | — | ~45 KB |
| **峰值合计** | **~39 KB** | **~96 KB** |

150 KB 可用堆下应该过得去,但余量不大。**不要信这张表,用 Stage 6 的探针实测。**
若实测紧张,第一个可以往下压的旋钮是 `ring.h` 的 24 KB → 16 KB(预缓冲 750 ms → 500 ms)。

TLS 方案(未最终决定,见 §10):倾向**自签 CA + IP 直连 + 固件内置根证书 `setCACert()`**——不用域名、不用备案,且只信任自己这一个 CA,内存开销比信任公共证书库还小。

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

- `client.setBufferSizes(2048, 2048)` 把 TLS record buffer 从默认 16KB 降下来(换成 wss 后)
- 每回合结束打印 `ESP.getFreeHeap()` 和 `ESP.getMaxAllocHeap()`——**碎片化先体现在后者暴跌**
- 设水位线,`getMaxAllocHeap()` 低于阈值主动重连 WiFi 或软复位(带提示音,不是无声重启)
- **新增关注点**:长连接下要盯的是"反复断线重连 N 次之后"的堆,而不是"连续对话 N 轮之后"。测试用例要相应改成拔网线/关服务器来制造重连

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

**打断(barge-in)**:任意非 IDLE 状态按下按钮 →

```
发 {"t":"abort"}  →  停止播放(补静音 → drain → 关功放)  →  清环形缓冲
→  丢弃后续所有 binary 帧直到下一个 audio_begin  →  进 RECORDING
```

注意顺序:**先发 abort 再关功放**。abort 是上行,不受下行缓冲拥塞影响,越早发服务器越早停止烧 token。
另外**不掐连接**——见 §5.3(c)。

---

## 9. 实施阶段

| 阶段 | 内容 | 在哪 | 依赖厂商? | 状态 |
|---|---|---|---|---|
| 1 | config.h + 按键去抖 + GPIO10 功放控制 | 设备 | ✗ | **✓ 通过 09-22** |
| 2 | I2S TX 放测试音(含限幅、drain) | 设备 | ✗ | **✓ 通过 09-22**(改查表生成后) |
| 3 | I2S RX 采 INMP441,打 min/max/RMS 标定增益 | 设备 | ✗ | **✓ 通过 09-22**,标定出 shift=11 |
| 4 | RX enable/disable 反复切换压力测试 | 设备 | ✗ | **✓ 通过 09-22**,200 轮不漏 |
| 5 | 录 3 秒 → 回放(硬件验收) | 设备 | ✗ | **✓ 通过 09-22**,回放清晰 |
| 6 | WiFi + 堆监控 + **TLS 预算探针** | 设备 | ✗ | 待做 |
| 6.5 | 服务器骨架:WS **回声**服务(收到 PCM 原样送回) | 服务器 | ✗ | 待做 |
| 7 | 设备 WS 客户端 → 连回声服务器 → 录 1 秒、收回、播 | 设备 | ✗ | 待做 |
| 8 | 服务器 TTS 单通,`pc_client.py` 发文本 → 存 wav | 服务器 | ✓ | 待做 |
| 9 | 服务器 ASR 单通,`pc_client.py` 推 wav → 打印文本 | 服务器 | ✓ | 待做 |
| 10 | 服务器 LLM + 句级流水线,`pc_client.py` 跑全链路 | 服务器 | ✓ | 待做 |
| 11 | 设备接全链路 + 状态机 + 打断 | 两边 | ✓ | 待做 |
| 12 | 换 `wss://` + 设备 token 鉴权 | 两边 | ✗ | 待做 |

**Stage 1~5 完全不依赖云厂商,先做完并通过硬件验收,后续网络层出问题时不必再怀疑硬件。**

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
> 需要三角函数/滤波就预先查表或用定点。固件里保留了 `t` 命令(逐样本 `sinf` 对照组)
> 专门用来复现这个现象,别删。

**供电**:Stage 2 在 `OUTPUT_GAIN=100`、幅度 0.6 FS 下实测无断续也无重启。
算一下就知道为什么:0.6 × 100/256 = 0.234 FS,MAX98357A 9 dB 增益 5 V 供电下
约 0.47 Vrms,4 Ω 负载 ≈ **0.055 W**,平均电流几十 mA。
**这个功率下 §3.3 的 brownout 风险根本够不着 —— 但那是因为增益压得低,不是因为电容不需要。**

**堆**:Stage 4 前后 `free=278352 / maxAlloc=139252` 三次测量完全不变(复位后基线、
Stage 4 后、Stage 5 的 `malloc(96000)` 后),既无泄漏也无碎片累积。
`maxAlloc` 只有 `free` 的一半是静态布局造成的(堆中间横着一个启动期分配),不是问题。
`maxAlloc > 131072` 说明 heap region 已合并。**进 Stage 6 后这两个数会因 WiFi 大幅下降,
以这组数字为基线对比。**

三个关于新阶段划分的说明:

**Stage 6 的 TLS 预算探针要现在做,不能推到 Stage 12。**
既然决定了开发阶段走明文,那 §5.6 那张表就得尽早验证,否则 Stage 12 才发现堆不够会很被动。
探针只有十几行:不写任何业务逻辑,用 `WiFiClientSecure` 对任意 https 站点握手一次,打印握手前 / 峰值 / 握手后的 `getFreeHeap()` 与 `getMaxAllocHeap()`。

**Stage 7 的回声测试取代了 rev.1 的"TTS 先打通"。**
它一次性验证 WS 客户端、环形缓冲、TCP 背压、I2S 播放四件事,而且完全不依赖厂商——出问题时排查面小得多。rev.1 把 TTS 排在最前是因为当时没有服务器可以先立起来。

**`tools/pc_client.py` 是整个计划里效率杠杆最大的一件东西。**
Stage 8~10 全部在 PC 上用它调通,ESP32 一次都不用烧。改一行服务器代码立刻能测,而不是等一轮烧录。详见 `SERVER.md`。

---

## 10. 待办 / 未决

### 硬件(不受 rev.2 影响)

- [ ] **加 470µF~1000µF 电解电容到 MAX98357A VIN**
      → 不再阻塞 Stage 1~5(增益 100 下实测 ≈0.055 W,够不着 brownout,见 §9.1),
      **但阻塞 `OUTPUT_GAIN` 上调**。想要正常音量就得先焊。
- [x] ~~量 GPIO10 悬空时 SD 脚电压~~ → Stage 1 实测能自由开关功放,
      说明 SD 没被焊死到 VDD,GPIO10 驱动得动。无需再量。
- [x] ~~确认 INMP441 模块是否自带 SD→GND 100kΩ 下拉~~ → Stage 3/5 取到干净信号,
      间接证明没问题。
- [x] ~~Stage 3 标定 `MIC_SHIFT`~~ → **实测 11**,已回填 `config.h`

### 设备侧(rev.2 新增)

- [ ] `config.h` 加 WiFi 凭据、服务器 IP/端口、设备 ID;`NET_CHUNK_SAMPLES` 3200 → 1600
- [ ] Stage 6 实测 TLS 堆预算,回填 §5.6 那张表的实测列
- [ ] 确定 `ring.h` 环形缓冲最终大小(起点 24 KB,视 Stage 6 实测结果可降到 16 KB)
- [ ] 决定是否要 `cue` 提示音,以及要几种

### 服务器侧(详见 `SERVER.md`)

- [ ] 申请/填入火山 `X-Api-Key` 与 `X-Api-Resource-Id`(ASR 与 TTS 的 Resource-Id 不同)
- [ ] 申请/填入 DeepSeek API Key
- [ ] 选定 TTS 音色 `speaker`(火山发音人列表)
- [ ] 决定最终部署位置(当前:开发阶段本机 PC;上线形态未定)
- [ ] 决定 TLS 方案(倾向自签 CA + IP + 固件内置根证书,见 §5.6)
- [ ] 决定设备鉴权方式(Stage 12)

---

## 11. 参考

厂商 API 文档已移到 `SERVER.md`——设备侧不需要它们。

- `SERVER.md` — 服务器侧规格
- `ESP32_C3_AI_Voice_MVP.md` — 最初设想稿。硬件部分有效;§9 的网络层设想在 rev.2 下重新生效
