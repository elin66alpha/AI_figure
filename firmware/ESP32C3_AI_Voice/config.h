#pragma once
// ESP32-C3 AI Voice — 全局硬件/音频/网络常量
// 规格见 ../../AGENT.md。GPIO 号只在这里出现,别散到别处。
//
// rev.4 起串口是**纯日志**,没有交互菜单。下面这些值改了就得重新烧录 —— 这是故意的:
// Stage 3 已经把 MIC_SHIFT 标定成 11,再留一个运行期旋钮只会让现场和固件对不上。
//
// WiFi 凭据、服务器地址、设备 ID 不在这个文件里,见 secrets.h(已 gitignore)。

// 随 {"t":"hello"} 上报,服务器日志里能看到。
// 0.3 = Stage 11:服务器驱动的等待音效
// 0.3.1 = 冗余清理(删标定期遗留接口、合并缓冲),行为与 0.3 相同
// 0.3.2 = 停播少等 66 ms、打断立刻关功放、wsPoll 少做 TLS 查询、上行零拷贝(AGENT.md §9.4)
// 0.4.0 = BLE 配网(微信小程序),WiFi 凭据改存 NVS。分区表须选 Minimal SPIFFS(AGENT.md §5.7)
#define FW_VERSION  "0.4.0"

// ---------------------------------------------------------------- GPIO
#define PIN_I2S_BCLK    4    // 共享:INMP441 SCK + MAX98357A BCLK
#define PIN_I2S_WS      5    // 共享:INMP441 WS  + MAX98357A LRC
#define PIN_MIC_DATA    6    // INMP441 SD  -> ESP32   (I2S DIN)
#define PIN_AMP_DATA    7    // ESP32 -> MAX98357A DIN (I2S DOUT)
#define PIN_AMP_SD      10   // MAX98357A SD: LOW=关断, 3.3V=使能且选左声道
#define PIN_PTT_BUTTON  3    // 按键接 GND,INPUT_PULLUP,按下=LOW

// 板载 LED。MakerGO variant 里 LED_BUILTIN = 8,是普通 LED 不是可寻址 RGB
// (这也是 AGENT.md §2 不选 "ESP32C3 Dev Module" 的原因)。
// GPIO8 是 strapping 脚 —— 但 strapping 只在复位那一刻采样,复位之后当输出驱动没问题。
#define PIN_STATUS_LED  8
#define LED_ON_LEVEL    LOW        // SuperMini 板载 LED 低电平点亮

// ---------------------------------------------------------------- 音频
#define SAMPLE_RATE_HZ      16000
// INMP441 需要 32-bit slot;MAX98357A 也接受 32-bit。
// 全双工共享时钟要求 TX/RX 配置完全一致,所以两边都用 STEREO 32-bit。
// BCLK = 16000 * 32 * 2 = 1.024 MHz

#define FRAME_SAMPLES       320   // 20 ms @16k — 单次 I2S 读写的粒度
                                  // 暂存缓冲 = 320 * 2 slot * 4 B = 2560 B
                                  // 录音时它同时是 loop 的节拍器:audioRead 阻塞 20 ms

// 上行每包 100 ms。AGENT.md §6 第 4 条:200 ms 是火山的要求,
// 现在由服务器重新打包满足,设备不再受此约束。
#define NET_CHUNK_SAMPLES   1600          // 100 ms @16k
#define NET_CHUNK_BYTES     (NET_CHUNK_SAMPLES * 2)   // 3200 B

// ---------------------------------------------------------------- 麦克风增益
// INMP441 的 24-bit 采样左对齐在 32-bit slot 的 bit31..8。
//   >>16 = 1:1    >>14 = x4    >>11 = x32
// **11 是 2026-09-22 用 Stage 3 现场标定出来的值,不是猜的。**
// 改这个值等于改 ASR 的输入电平。验收台已删除,要重新标定得先 checkout 提交 f955db1。
#define MIC_SHIFT           11

// 一阶高通,滤掉 INMP441 的直流偏置。对 ASR 识别率帮助明显。
#define DC_BLOCKER_ON       true

// ---------------------------------------------------------------- 输出限幅
// 0..256 的定点增益(256 = 原始音量)。这是**开机默认值**:运行期可以 setOutputGain() 改
// (以后手机 App 调音量用,ROADMAP.md §3.1)。
//
// VIN 上的 470µF~1000µF 电解电容 **2026-09-22 已焊**,所以这个值可以往上调了。
// 之所以还留在 100:合适的音量得在板上用耳朵试,不是算出来的。上调时一次一档。
//
// 电容解决的是音频瞬态尖峰,**没有**把 USB VBUS 的平均电流余量变大。
// 而 Stage 6 起同一路 5V 上还多了 WiFi 发射的约 350 mA 峰值,
// Stage 7 更是第一次出现"WiFi 满负荷 + 连续播放"的组合 ——
// 听到断续或莫名重启时,仍然是先量供电再怀疑代码(AGENT.md §9.2 第 5 行)。
#define OUTPUT_GAIN_DEFAULT 100   // ≈39%

// ---------------------------------------------------------------- DMA
#define DMA_DESC_NUM    4
#define DMA_FRAME_NUM   240       // 4 * 240 / 16000 = 60 ms 的 TX 缓冲深度
#define DMA_TOTAL_MS    ((DMA_DESC_NUM * DMA_FRAME_NUM * 1000) / SAMPLE_RATE_HZ)

// MAX98357A 离开 shutdown 需要几 ms 才稳定
#define AMP_WAKE_MS     8
// 停播时静音写满 DMA 之后、关功放之前的余量:只给 I2S TX FIFO 里最后几个样本出引脚
// (FIFO 只有几十个样本 = 2 ms 量级)。尾音被切就往上加,别加回 70。
#define AMP_TAIL_MS     4

// ---------------------------------------------------------------- 按键
#define BUTTON_DEBOUNCE_MS  25

// ---------------------------------------------------------------- 播放环形缓冲
// AGENT.md §5.6 定案:16 KB。静态数组,绝不 malloc。
//   16384 B = 8192 样本 = 512 ms
// 预缓冲阈值 300 ms —— 和服务器 pacer 的首包突发(SERVER.md §3.5)对齐:
// 服务器一次突发 300 ms,设备攒够 300 ms 就起播,之后服务器按 1x 实时喂,
// 这 300 ms 就一直躺在缓冲里当抗抖动余量。
#define RING_BYTES          16384
#define PREBUFFER_BYTES     9600          // 300 ms @16k/PCM16

// ---------------------------------------------------------------- WiFi
// 指数退避重连:1s -> 2s -> 4s -> ... -> 30s 封顶(AGENT.md §5.1)
#define WIFI_RETRY_MIN_MS   1000
#define WIFI_RETRY_MAX_MS   30000
#define WIFI_CONNECT_TIMEOUT_MS 12000

// WiFi modem sleep 会给收发引入几十 ms 的抖动。音频流受不了,关掉。
// 代价是功耗上升 —— 这台设备是 USB 供电的,无所谓。
#define WIFI_SLEEP_OFF      true

// ---------------------------------------------------------------- BLE 配网(微信小程序)
// 协议是乐鑫 network_provisioning(Security 1),小程序端见 ../../miniprogram/README.md。
// 下面两项是**和小程序共用的常量**,改一边就得改另一边。
//
// 服务 UUID 10624c9a-f2aa-4ca8-8594-9cd3cc78db3f,按 NimBLE 的要求 LSB 在前。
// 各端点特征的 UUID 由它派生(第一段的第 5~8 位换成 FF4F/FF50/FF51/FF52/FF53)。
#define PROV_SERVICE_UUID   { 0x3f, 0xdb, 0x78, 0xcc, 0xd3, 0x9c, 0x94, 0x85, \
                              0xa8, 0x4c, 0xaa, 0xf2, 0x9a, 0x4c, 0x62, 0x10 }
#define PROV_NAME_PREFIX    "AIFIG_"      // 广播名 = 前缀 + MAC 后 3 字节
#define PROV_HOLD_MS        3000          // 上电时按住按键这么久 = 重新配网

// ---------------------------------------------------------------- WebSocket
//
// rev.5 起服务器在公网 VPS 上,下面这几个超时都是按**跨运营商的广域网**定的,
// 不再是局域网那点 RTT。改小了会在网络抖一下的时候莫名其妙重连。

// TCP 三次握手的预算。
//
// ⚠️ 这个值**一身二任**,改之前先看 net_ws.cpp 里 wsConnect() 上面那段注释:
// arduino-esp32 的 ssl_client.cpp 在 connect 时把它存进 socket_timeout,
// 之后 send_ssl_data() 拿它当"多久没进展就放弃"的窗口,而且**之后改不动**。
// 所以它既是"连不上多久算失败",也是"一次上行最坏能把音频循环卡多久"。
// 2.5 s:TCP connect 只要 1 个 RTT,国内 VPS 几十毫秒就够,余量足够大;
// 同时 2.5 s 的最坏阻塞虽然难受,但比明文时代 NetworkClient::write 的 10 s 好得多。
#define WS_TCP_CONNECT_TIMEOUT_MS 2500

// TLS 握手的预算,**单位是秒**(setHandshakeTimeout 的签名如此)。
// 和上面那条是独立计时的。C3 没有硬件 ECC,但纯 PSK 不做非对称运算,
// 握手主要花在 2 个 RTT 上,8 s 是很宽的余量。
#define WS_TLS_HANDSHAKE_TIMEOUT_S 8

// HTTP Upgrade 那几行的读取预算(TLS 之上)。
// 局域网时代是 4000;公网上一次 RTT 就可能上百毫秒,放宽到 6 s。
#define WS_HANDSHAKE_TIMEOUT_MS 6000
#define WS_PING_INTERVAL_MS     30000     // 自己每 30 s 发一次 ping
#define WS_PONG_TIMEOUT_MS      70000     // 连续两次没 pong 判死(AGENT.md §5.1)
#define WS_RETRY_MIN_MS         1000
#define WS_RETRY_MAX_MS         30000
#define WS_TEXT_MAX             256       // 控制消息上限,超了截断并告警
#define WS_SEND_TIMEOUT_MS      300       // 控制消息(turn_start/end/abort)的发送超时
// 音频帧和 pong 用更短的超时。理由是 RX DMA 只有 60 ms 深
// (DMA_DESC_NUM * DMA_FRAME_NUM / SR),录音路径上阻塞超过这个数就开始丢采样。
// 宁可丢一帧上行(ASR 少 100 ms)也不能让整个循环停住 —— AGENT.md §9.2 第 5 行。
#define WS_AUDIO_SEND_TIMEOUT_MS 30
#define WS_UPLINK_DROP_LIMIT    10        // 连续丢这么多帧就认为链路坏了,断开重连

// ---------------------------------------------------------------- 状态机
// 设备只保留一个总超时:从 turn_end 起算到收到 audio_begin。
// 分段超时归服务器管(AGENT.md §8)。
#define WAITING_TIMEOUT_MS      8000

// ---------------------------------------------------------------- 遥测 / 看门狗
#define TELEMETRY_INTERVAL_MS   10000
// maxAlloc 跌破这个值说明堆碎片化到了危险区(AGENT.md §7)。
// 播错误提示音后软复位 —— **不是无声重启**,否则现场会以为是掉电。
#define HEAP_MIN_MAXALLOC       24576
