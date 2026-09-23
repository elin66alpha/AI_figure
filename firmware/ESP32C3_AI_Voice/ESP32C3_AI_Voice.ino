// ESP32-C3 AI Voice — Stage 6 + 7 + 11
//
// 开发板: MakerGO ESP32 C3 SuperMini   (核心 3.3.12 / IDF 5.5.5)
// 规格:   ../../AGENT.md   服务器: ../../SERVER.md
//
// 烧进去就自己跑,**没有串口菜单**:
//   上电 -> 开机音 -> 连 WiFi -> 连服务器 -> 收到 ready -> 连上音 -> IDLE
//   按住按键说话 -> 松开 -> "咕噜咕噜"等待音效 -> 听到服务器的回复
//   (回声 / 对话由服务器的 REPLY_MODE 决定,设备不用管)
//   任何一环断了 -> 错误音 + LED 慢闪 -> 自动重连(按按键可跳过退避)
//
// 串口 115200 是**纯日志输出**,不接收任何输入。
// Stage 1~5 的硬件验收台在提交 f955db1 里,要复现硬件现象就 checkout 回去。

#include <Arduino.h>
#include <esp_heap_caps.h>

#include "config.h"
#include "secrets.h"
#include "audio_io.h"
#include "cue.h"
#include "led.h"
#include "net_wifi.h"
#include "net_ws.h"
#include "ring.h"
#include "session.h"

// ---------------------------------------------------------------- 堆
//
// free 和 maxAlloc 差得大 != 漏内存。
//   free     = 所有空闲块的**字节总和**
//   maxAlloc = 单个**最大连续**空闲块
// 两者的差距只说明堆被切碎了。判断泄漏要看同一个 tag 的 before/after 是否回到原值;
// 判断碎片化要看 **maxAlloc 是不是一路往下掉**(AGENT.md §7)。
//
// Stage 4 不带 WiFi 时的基线是 free=278352 / maxAlloc=139252。
// 开了 WiFi 之后这两个数会大幅下降,以那组数字作对比基准。
static void printHeap(const char *tag) {
  multi_heap_info_t h;
  heap_caps_get_info(&h, MALLOC_CAP_DEFAULT);
  Serial.printf("[HEAP] %-10s free=%u  maxAlloc=%u  freeBlk=%u  minEver=%u\n",
                tag, (unsigned)h.total_free_bytes, (unsigned)h.largest_free_block,
                (unsigned)h.free_blocks, (unsigned)h.minimum_free_bytes);
}

// ---------------------------------------------------------------- 遥测
//
// 这不是测试项,是**常驻功能**。AGENT.md §7 要求的那条监控就是它:
// 长连接下真正要盯的是"反复断线重连 N 次之后"的堆,而碎片化**先体现在 maxAlloc 暴跌**。
// rev.5 换成 wss:// 之后,这一行给出的就是带 TLS 的稳态堆;
// 握手那一瞬间的峰值由 net_ws.cpp 在握手成功后单独打一行 ——
// §5.6 那张预算表的实测列由这两处来填,不需要另写探针。
static void telemetry() {
  static uint32_t last = 0;
  if (millis() - last < TELEMETRY_INTERVAL_MS) return;

  // 录音/播放中就推迟 —— 串口没人读时 USB CDC 的写有可能阻塞,
  // 而这两个状态跑在 16 kHz 的实时路径上,赌不起。
  // Stage 11 起 WAITING 里也可能在放等待音效,同样算实时路径 —— 看 audioIsPlaying()。
  const VoiceState st = sessionState();
  if (st == VoiceState::RECORDING || st == VoiceState::PLAYING || audioIsPlaying()) return;
  last = millis();

  multi_heap_info_t h;
  heap_caps_get_info(&h, MALLOC_CAP_DEFAULT);
  IPAddress ip = netWifiIp();

  Serial.printf("[TLM] %-4s ip=%u.%u.%u.%u rssi=%ld free=%u maxAlloc=%u minEver=%u "
                "wifiDrop=%lu upDrop=%lu rx=%lu under=%lu\n",
                sessionStateName(), ip[0], ip[1], ip[2], ip[3], (long)netWifiRssi(),
                (unsigned)h.total_free_bytes, (unsigned)h.largest_free_block,
                (unsigned)h.minimum_free_bytes,
                (unsigned long)netWifiDisconnectCount(),
                (unsigned long)sessionUplinkDrops(),
                (unsigned long)wsRxAudioBytes(),
                (unsigned long)sessionUnderruns());

  // 水位线。跌破说明堆碎片化进了危险区,与其等 malloc 失败时莫名其妙地挂掉,
  // 不如**带提示音**主动重启 —— 无声重启在现场看起来像掉电,会把人带偏。
  if (h.largest_free_block < HEAP_MIN_MAXALLOC) {
    Serial.printf("[TLM] !! maxAlloc=%u 跌破水位线 %d,主动重启\n",
                  (unsigned)h.largest_free_block, HEAP_MIN_MAXALLOC);
    cueError();
    delay(50);
    ESP.restart();
  }
}

// ---------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  delay(400);                              // 等 USB CDC 枚举

  Serial.println("\n\n[BOOT] ESP32-C3 AI Voice — Stage 11 (WiFi + WS + 对话 + 等待音效)");
  Serial.printf("[BOOT] fw=%s  核心 %s  CPU %u MHz\n",
                FW_VERSION, ESP.getSdkVersion(), (unsigned)getCpuFrequencyMhz());
  Serial.printf("[BOOT] 服务器 %s://%s:%d%s   设备 %s\n",
                SERVER_USE_TLS ? "wss" : "ws",
                SERVER_HOST, SERVER_PORT, SERVER_WS_PATH, DEVICE_ID);
#if !SERVER_USE_TLS
  // 明文只该出现在局域网直连调试里。公网地址 + 明文 = 零鉴权端口暴露在全网。
  Serial.println("[BOOT] !! 明文模式(SERVER_USE_TLS=0)。只在局域网里这么跑。");
#endif
  Serial.printf("[BOOT] 音频 %d Hz  上行 %d ms/包  ring %u B (%u ms)  预缓冲 %u ms\n",
                SAMPLE_RATE_HZ, NET_CHUNK_SAMPLES * 1000 / SAMPLE_RATE_HZ,
                (unsigned)ringCapacity(),
                (unsigned)(ringCapacity() * 1000 / (SAMPLE_RATE_HZ * 2)),
                (unsigned)(PREBUFFER_BYTES * 1000 / (SAMPLE_RATE_HZ * 2)));
  printHeap("boot");

  ledBegin();
  ledSet(LedMode::BLINK_FAST);

  if (!audioBegin()) {
    Serial.println("[BOOT] 音频初始化失败,停在这里。这一层 Stage 1~5 已经验收过,"
                   "现在报错先查接线。");
    ledSet(LedMode::BLINK_SLOW);
    while (true) { ledUpdate(); delay(10); }
  }
  printHeap("audio ok");

  cueBegin();
  cueBoot();

  netWifiBegin();
  sessionBegin();
  printHeap("net begin");

  Serial.printf("[BOOT] 输出增益 %u/256(电容已焊,可上调;同一路 5V 上还有 "
                "WiFi 发射的 ~350 mA 峰值)\n", getOutputGain());
  Serial.println("[BOOT] 串口是纯日志,不接收输入。LED:快闪=连接中 慢闪=错误 "
                 "心跳=空闲 常亮=录音/播放");
}

// ---------------------------------------------------------------- loop
//
// 单线程,不开 FreeRTOS 任务。每个状态都有一个天然的阻塞节拍器:
//   RECORDING  audioRead()  阻塞 ~20 ms
//   PLAYING    audioWrite() 阻塞到 DMA 腾出空间
//   IDLE/ERROR 下面的 delay(2)
// wsPoll() 在这些节拍的间隙里跑,每次最多搬 4 KB,保证一定把控制权还回来。
//
// 没有并发 => 没有锁、没有优先级反转、没有跨任务的堆竞争。
// AGENT.md §9.1(b) 那个 62.5 µs 的单样本预算,单线程下才算得清。
void loop() {
  ledUpdate();
  netWifiUpdate();
  sessionUpdate();
  telemetry();

  const VoiceState st = sessionState();
  if (st != VoiceState::RECORDING && st != VoiceState::PLAYING) delay(2);
}
