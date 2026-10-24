# ESP32-C3 AI Voice — 设备侧规格

> 硬件以 `hardware/schematics.pdf` 和 `hardware/DESIGN_CONSTRAINTS.md` 为准；引脚、电源策略、构建和烧录见 `firmware/ESP32C3_AI_Voice/README.md`。
> 服务器侧规格见 `SERVER.md`，后续计划见 `ROADMAP.md`。

---

## 1. 分工

- **本文件** = 设备侧：设备↔服务器协议、音频播放规则、状态机、资源约束、TLS-PSK、BLE 配网。设备不认识任何云厂商。
- **`SERVER.md`** = 服务器侧：厂商协议（ASR / TTS / LLM）、会话编排、对话历史、密钥。

两边的交界是 §3 的 WS 协议。冲突时以本文件为准。

## 2. 当前选型

| 项 | 取值 |
|---|---|
| 主板 | AI_figure 定制板，ESP32-C3-MINI-1-H4X（单核 RISC-V 160 MHz，4 MB flash，无 PSRAM） |
| 固件 | ESP-IDF 6.1.0 原生接口，入口 `main.cpp / app_main()` |
| 麦克风 | LMD2718T261 PDM，软件抽取到 16 kHz PCM |
| 功放 | NS4168 I2S，AMP_CTRL 控制关断和声道 |
| 架构 | 设备 ⇄ 自建服务器 ⇄ 云 API。设备只有一条持久 WS |
| 传输 | `wss://` + TLS-PSK（TLS 1.2，纯 PSK 套件）；`SERVER_USE_TLS=0` 退回明文，只用于局域网调试 |

---

## 3. 设备 ↔ 服务器协议

### 3.1 传输

一条持久 WebSocket，开机即连，断线指数退避重连（1 s → 2 s → 4 s → … → 30 s 封顶）。保活用 WebSocket 的 ping/pong 控制帧，30 s 一次，连续两次无 pong 视为断线。

用 opcode 区分控制和音频，不自定义帧头：

```
Binary frame  =  裸 PCM16LE / 16 kHz / 单声道，无任何头部
Text   frame  =  JSON 控制消息
```

设备收到 binary 帧时边从 socket 读边写进播放环形缓冲，不落地完整帧，内存恒定（§6）。

### 3.2 消息

**上行（设备 → 服务器）**

```json
{"t":"hello","dev":"c3-01","fw":"0.5.0-idf61"}   // 连上后第一帧，服务器回 ready
{"t":"turn_start"}                                // 按键按下
{"t":"turn_end"}                                  // 按键松开
{"t":"abort"}                                     // 打断（barge-in）
```

`turn_start` 与 `turn_end` 之间夹 binary PCM 帧，**100 ms / 1600 样本 / 3200 字节**一包。

**下行（服务器 → 设备）**

```json
{"t":"ready","sr":16000}                  // 握手确认
{"t":"cue","name":"thinking"}             // 让设备播本地等待音效
{"t":"audio_begin","seq":7}               // 之后的 binary 帧属于第 7 回合
{"t":"audio_end","seq":7}                 // 本回合音频结束 → 收尾 → 关功放
{"t":"asr","text":"...","final":true}     // 仅供调试，设备忽略
{"t":"reply","text":"..."}                // 仅供调试，设备忽略
{"t":"error","code":"asr_timeout","msg":"..."}
```

设备必须容忍未知的 `t` 值并静默忽略，好让服务器先行升级。消息只有这几种，设备侧手写字符串匹配，不引 JSON 库。

### 3.3 三个必须实现的细节

**(a) `seq` 回合号。** 打断时服务器可能还有在途音频帧在 TCP 缓冲里。设备记住当前 `seq`，丢弃所有不属于当前回合的 binary 帧：收到 `audio_begin` 才认 seq 并开始接收；`abort` 之后到下一个 `audio_begin` 之间的 binary 帧一律丢弃。

**(b) 背压靠 TCP，不做应用层流控。** 设备只在播放环形缓冲有空间时才从 socket 读，TCP 窗口自然反压到服务器。服务器配合做速率整形：首包突发 300 ms，之后按 1× 实时喂。缓冲满时控制帧也读不到，可以接受：此时唯一需要及时送达的是上行 `abort`，方向相反不受影响。

**(c) 打断不掐连接。** 发 `{"t":"abort"}` → 服务器取消在途的 ASR / LLM / TTS 任务并 `seq++` → 连接始终保持。掐连接就要重连，反而慢。

### 3.4 联调排查顺序

设备和服务器连不通时，按这个顺序往下查，不要跳着猜：

| # | 看什么 | 不对时问题在哪 |
|---|---|---|
| 1 | 串口有没有打印出 IP | WiFi：凭据、是不是 2.4 GHz、信号强度 |
| 2 | 服务器有没有收到 `hello` | WS / TLS 握手：地址、端口、PSK、防火墙 |
| 3 | 服务器有没有收到 binary 帧，每帧是不是 3200 B | 上行打包或掩码 |
| 4 | 服务器说已下发，设备 ring 水位却不涨 | 下行帧解析或背压逻辑 |
| 5 | ring 涨了但没声音或断续 | 音频层和 loop 时序 |

上行帧发不出去时整帧丢弃，不发半帧：WS 帧发一半会破坏帧边界，ASR 丢 100 ms 比整条链路卡死强。

---

## 4. 音频格式和播放

- 双向恒为 **16 kHz / PCM16LE / 单声道**。服务器负责让上游满足这一点，设备不做格式协商；`ready` 里的 `sr` 只用于开机断言，对不上就报错。
- I2S0 的 RX（PDM 录音）和 TX（播放）分开申请，各自只在用的时候开时钟。TX 为 16 位 Philips 立体声，两个声道写同一个单声道 PCM。
- **开始播放**：TX 停着时用静音预填满全部 DMA（也冲掉被打断回复的残留）→ 使能 TX → 拉高 AMP_CTRL → 等 `AMP_WAKE_MS`。功放唤醒时面对确定的零信号，不会“啪”一声。
- **正常结束**：补几帧静音把真实音频推出去 → 等 `AMP_TAIL_MS` → 关功放、停 TX。直接关会切掉尾音。
- **打断**：`audioCutPlayback()` 立刻关功放、停 TX，不保护被打断回复的尾音。
- **欠载**：TX 开 `auto_clear`，DMA 欠载时硬件输出零，而不是重复上一个缓冲区发出“滋滋”声。
- **预缓冲**：收到 `audio_begin` 后攒够 `PREBUFFER_BYTES`（300 ms）再起播；回复很短、没攒够就收到 `audio_end` 时，直接播已有的部分。

## 5. 状态机

```cpp
enum class VoiceState {
    IDLE,          // 功放关，等按键。WS 已连接且已收到 ready
    RECORDING,     // 按住：边录边推 100 ms PCM 帧
    WAITING,       // 松开：已发 turn_end，等服务器
    PLAYING,       // 收到 audio_begin，播放中（仍在下载）
    ERROR_STATE,   // WiFi 或 WS 断了。此状态下按键 = 立刻重连
};
```

- 设备不知道服务器走到哪一步，只保留一个总超时：从 `turn_end` 到收到 `audio_begin` 最多 `WAITING_TIMEOUT_MS`（8 s）。分段超时归服务器管。
- `WAITING` 时收到 `error` = 这一回合不会有声音了，立刻回 IDLE 播错误音，不再干等超时。
- **等待音效**：`WAITING` 时收到 `{"t":"cue","name":"thinking"}`，循环播“咕噜咕噜”的冒泡声（`bubble.*`），直到回复接上。
  - 非阻塞：每轮 loop 取 20 ms 写进 I2S，用 `audioWrite` 的阻塞当节拍器。`cue.*` 的提示音是阻塞的，不能用在这里，否则收不到 `audio_begin`。
  - 无缝接回复：`audio_begin` 之后、预缓冲攒够之前继续冒泡，攒够后等两个气泡之间的空隙再切，功放和 I2S 一直开着。
  - 只在 `WAITING` 时认 `thinking`；不认识的 cue 名打日志后忽略。
- **打断**：任意非 IDLE 状态按下按键 → 发 `{"t":"abort"}` → 立刻关功放 → 清环形缓冲 → 丢弃后续 binary 帧直到下一个 `audio_begin` → 进 RECORDING。**先发 abort 再关功放**：abort 走上行，越早发，服务器越早停止消耗 token。

## 6. 资源和实时约束

400 KB SRAM，无 PSRAM。

1. **音频循环内不动态分配内存。** 播放环形缓冲是静态数组：`RING_BYTES` = 16 KB（512 ms）。
2. **自己写极简 WebSocket 客户端，不用现成库。** 现成库会把整帧组装进 RAM 才回调；自写可以读帧头 → 读长度 → 边从 socket 读边写进环形缓冲。
3. **实时路径上不用浮点。** C3 是 RV32IMC，没有 FPU，软件模拟的浮点（尤其是大参数的 `sinf`，内部走 double）一次调用就可能吃光 16 kHz 下 62.5 µs 的单样本预算，结果是 TX 欠载、听感断续。三角函数查表（`cue.*` 的 256 点正弦表 + 定点相位累加器），滤波用定点。建表时的一次性浮点运算不在实时路径上，可以用。
4. **堆遥测常驻。** 每 10 s 一行 `[TLM]`：状态、RSSI、VBAT、USB、`free`、`max`（最大连续块）。堆碎片先体现在最大连续块下降，所以要盯的是它，不是 `free`。最大连续块低于 `HEAP_MIN_MAXALLOC` 时软复位。长连接下要盯的是“反复断线重连 N 次之后”的堆：关掉服务器进程或拔路由器电源就能制造重连。

## 7. TLS-PSK 和设备身份

- 用 TLS-PSK，不用自签 CA 或公网证书：省掉 X.509 解析峰值和证书常驻，不用管证书过期（设备没有便捷的远程升级通道，证书到期 = 所有设备同时失效）。
- **预共享密钥就是设备身份**，不再单独做一套 token。`hello` 里的 `dev` 只用于服务器日志：TLS 在 stunnel 就终结了，服务器的 Python 层看不到 PSK identity，所以 `dev` 不能当鉴权。
- 设备侧 PSK 写在 `secrets.h`（不入库）；服务器侧写在 `/etc/stunnel/psk.secrets`。撤销一台设备 = 删掉它那一行 + 重启 stunnel。
- 设备只支持 TLS 1.2（`CONFIG_MBEDTLS_SSL_PROTO_TLS1_3=n`）。服务器必须钉死 TLS 1.2，并且只留纯 PSK 套件：如果选中 `RSA_PSK` 一类套件，服务器会下发证书链，而设备走 PSK 时没有装 CA，握手必定失败。
- mbedTLS 缓冲按 sdkconfig 配置：接收 16 KB、发送 4 KB，不开动态缓冲。

## 8. BLE 配网

- 用乐鑫 `network_provisioning`，Security 1，**没有 PoP**：玩偶没有屏幕，贴纸或二维码只会增加成本。兜底是物理动作：只有没配过网，或冷启动时按住按键 3 s，才进配网；平时 BLE 不开。
- 配网是独立的开机模式，只跑 BLE + WiFi 验证，不碰 WS / TLS，所以 BLE 和 TLS 不会同时占堆。配网成功后重启进正常模式。
- 连通之后才把凭据写进 NVS 命名空间 `net`（`ssid` / `pass`），所以放弃配网直接断电不会丢掉旧凭据。正常模式先读 NVS，读不到才用 `secrets.h` 的 `WIFI_SSID`（开发用兜底；量产留空）。
- 和微信小程序共用的常量在 `config.h`：`PROV_SERVICE_UUID`、`PROV_NAME_PREFIX`（`AIFIG_`）。改一边必须同时改另一边。小程序侧见 `miniprogram/README.md`。
