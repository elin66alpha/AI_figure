// ESP32-C3 AI Voice — Stage 1~5 硬件验收台 (+ 6 号对照组)
//
// 开发板: MakerGO ESP32 C3 SuperMini   (核心 3.3.12 / IDF 5.5.5)
// 规格:   ../../AGENT.md
//
// 这一版只验证本地音频硬件,不连 WiFi、不连云。
// Stage 1~5 全部通过之前不要开始写网络层 —— 否则后面分不清是硬件还是协议的锅。
//
// 串口 115200,输入数字选择测试项,测试中按 x 中止。

#include <Arduino.h>
#include <math.h>
#include <esp_heap_caps.h>
#include "config.h"
#include "button.h"
#include "audio_io.h"

static Button g_btn;

// ---------------------------------------------------------------- 工具
//
// free 和 maxAlloc 差得大 ≠ 漏内存。
//   free     = 所有空闲块的**字节总和**
//   maxAlloc = 单个**最大连续**空闲块
// 两者的差距只说明堆被切碎了。C3 的 DRAM 是 0x3FC80000~0x3FCE0000 一整块 384 KB
// (soc.h: SOC_DRAM_LOW/HIGH),天然不分段 —— 所以差距来自运行期的分配把空闲区切开了。
// 真正判断泄漏要看 **同一个 tag 的 before/after 是否回到原值**,以及 freeBlk 有没有一路涨。
static void printHeap(const char *tag) {
  multi_heap_info_t h;
  heap_caps_get_info(&h, MALLOC_CAP_DEFAULT);
  Serial.printf("[HEAP] %-10s free=%u  maxAlloc=%u  freeBlk=%u  allocBlk=%u  minEver=%u\n",
                tag, (unsigned)h.total_free_bytes, (unsigned)h.largest_free_block,
                (unsigned)h.free_blocks, (unsigned)h.allocated_blocks,
                (unsigned)h.minimum_free_bytes);
}

// 'i' 命令:把堆按 caps 拆开看。DMA 那一栏是 I2S 描述符+缓冲的去处。
static void heapReport() {
  struct { const char *name; uint32_t caps; } rows[] = {
    { "DEFAULT ", MALLOC_CAP_DEFAULT  },
    { "INTERNAL", MALLOC_CAP_INTERNAL },
    { "DMA     ", MALLOC_CAP_DMA      },
  };
  Serial.println("\n[HEAP] caps       free    maxAlloc  freeBlk  allocBlk   minEver");
  for (auto &r : rows) {
    multi_heap_info_t h;
    heap_caps_get_info(&h, r.caps);
    Serial.printf("       %s  %7u   %7u   %6u   %7u   %7u\n",
                  r.name, (unsigned)h.total_free_bytes, (unsigned)h.largest_free_block,
                  (unsigned)h.free_blocks, (unsigned)h.allocated_blocks,
                  (unsigned)h.minimum_free_bytes);
  }
  Serial.println("  freeBlk=2 且 free≈2*maxAlloc  -> 堆里横着一个活分配,把空闲区劈成两半");
  Serial.println("  freeBlk 很大                  -> 真碎片化");
  Serial.println("  反复跑同一个 Stage,free 逐次下降 -> 才是漏");

  // 把两个最大的空闲块各占住一次,打印地址区间。中间的缝隙就是那个劈开堆的块,
  // 地址本身能说明它是谁:紧贴 .bss 的是启动期分配,靠 DRAM 顶的是 ROM 保留区。
  // 分配完立刻还回去,对堆没有净影响。
  size_t s1 = heap_caps_get_largest_free_block(MALLOC_CAP_DEFAULT);
  void  *p1 = s1 ? heap_caps_malloc(s1, MALLOC_CAP_DEFAULT) : nullptr;
  size_t s2 = heap_caps_get_largest_free_block(MALLOC_CAP_DEFAULT);
  void  *p2 = s2 ? heap_caps_malloc(s2, MALLOC_CAP_DEFAULT) : nullptr;

  Serial.printf("\n  .bss 参考点 (&g_btn) = %p     DRAM 窗口 = 0x3FC80000..0x3FCE0000\n",
                (void *)&g_btn);
  if (p1) Serial.printf("  空闲块A: %p .. %p  (%u B)\n", p1, (uint8_t *)p1 + s1, (unsigned)s1);
  if (p2) Serial.printf("  空闲块B: %p .. %p  (%u B)\n", p2, (uint8_t *)p2 + s2, (unsigned)s2);
  if (p1 && p2) {
    uint8_t *lo   = (uint8_t *)(p1 < p2 ? p1 : p2);
    size_t   loSz = (p1 < p2 ? s1 : s2);
    uint8_t *hi   = (uint8_t *)(p1 < p2 ? p2 : p1);
    Serial.printf("  两块之间的缝隙 = %ld B  <- 劈开堆的就是它\n",
                  (long)(hi - (lo + loSz)));
  }
  if (p2) heap_caps_free(p2);
  if (p1) heap_caps_free(p1);
}

// 测试中断:串口收到 'x' 就退出
static bool aborted() {
  while (Serial.available()) {
    int c = Serial.read();
    if (c == 'x' || c == 'X') { Serial.println("\n-- 已中止 --"); return true; }
  }
  return false;
}

static void printMenu() {
  Serial.println();
  Serial.println("========= ESP32-C3 AI Voice / 硬件验收台 =========");
  Serial.println("  1  Stage 1  按键 + 功放 SD 控制");
  Serial.println("  2  Stage 2  扬声器测试音 (I2S TX, 查表生成)");
  Serial.println("  3  Stage 3  麦克风电平标定 (I2S RX, min/max/RMS)");
  Serial.println("  4  Stage 4  RX/TX 反复切换压力测试  <<< 关键里程碑");
  Serial.printf ("  5  Stage 5  录 %d 秒后回放 (硬件总验收)\n", REC_TEST_SECONDS);
  Serial.println("  6  对照组   同样的测试音,但逐样本调 sinf(故意让 CPU 跟不上)");
  Serial.println("  g  设置输出增益 (0-256)");
  Serial.println("  m  设置麦克风移位 (8-20)");
  Serial.println("  d  切换 DC blocker");
  Serial.println("  i  堆诊断 (free / maxAlloc / 碎片块数)");
  Serial.println("  h  重新显示菜单");
  Serial.println("  x  中止当前测试");
  Serial.printf ("当前: 增益=%u/256   micShift=%u   DCblocker=%s\n",
                 getOutputGain(), getMicShift(), getDcBlocker() ? "on" : "off");
  if (getOutputGain() > 120)
    Serial.println("!! 增益 >120:确认 MAX98357A VIN 上已焊 470uF+ 电解电容,否则会 brownout 重启");
  Serial.println("==================================================");
  Serial.print("> ");
}

// ---------------------------------------------------------------- Stage 1
static void stage1_gpio() {
  Serial.println("\n[STAGE 1] 按住按键 = 功放使能(GPIO10 HIGH),松开 = 关断。按 x 退出。");
  Serial.println("          注意:此时不送音频数据,只验证 GPIO 通断。");
  g_btn.clearEvents();

  while (!aborted()) {
    g_btn.update();
    if (g_btn.tookPress()) {
      ampSet(true);
      Serial.println("BUTTON DOWN   -> AMP ON  (GPIO10=HIGH)");
    }
    if (g_btn.tookRelease()) {
      ampSet(false);
      Serial.println("BUTTON UP     -> AMP OFF (GPIO10=LOW)");
    }
    delay(2);
  }
  ampSet(false);
}

// ---------------------------------------------------------------- Stage 2 / 6
//
// 440 Hz 在 16 kHz 下不是整周期(16000/440 = 36.36),但 **11 个周期 = 正好 400 个样本**,
// 所以一张 400 样本的表可以无缝循环,内层循环里一个浮点运算都没有。
#define TONE_HZ       440
#define TONE_LUT_LEN  400          // 11 个 440 Hz 周期 @16 kHz
#define TONE_AMP_FS   0.6f

static int16_t s_toneLut[TONE_LUT_LEN];
static bool    s_toneLutReady = false;

static void buildToneLut() {
  if (s_toneLutReady) return;
  const float amp = TONE_AMP_FS * 32767.0f;
  for (int i = 0; i < TONE_LUT_LEN; i++) {
    // 这里参数最大 2π*440*(400/16000) ≈ 69 rad < 201,走 newlib 的 medium 路径,
    // 400 次一次性开销而已,不在实时路径上。
    s_toneLut[i] = (int16_t)(amp * sinf(2.0f * (float)PI * (float)TONE_HZ
                                        * (float)i / (float)SAMPLE_RATE_HZ));
  }
  s_toneLutReady = true;
}

// useLut=false 是对照组:逐样本调 sinf,相位参数单调递增到 5529 rad。
// newlib 的 __ieee754_rem_pio2f 在 |x| >= 2^7*(π/2) ≈ 201 之后改走 Payne-Hanek
// 多精度规约(全程 double)。C3 是 RV32IMC,**没有 FPU**,double 全靠软件模拟,
// 一次调用就能吃掉 62.5 µs 的单样本预算 —— TX DMA 欠载,auto_clear 填零,
// 听感就是断续的"滴滴滴"。t=0.0727 s(第 4 帧)开始翻车。
static void runTone(bool useLut) {
  const char *tag = useLut ? "STAGE 2" : "STAGE 6";
  Serial.printf("\n[%s] %d Hz 测试音 2 秒,输出增益 %u/256,生成方式:%s\n",
                tag, TONE_HZ, getOutputGain(),
                useLut ? "查表(实时路径无浮点)" : "逐样本 sinf(对照组)");
  if (useLut) {
    Serial.println("          听不到声音先查:GPIO10 有没有到 3.3V、喇叭两端是否都没接地。");
    buildToneLut();
  }

  if (!audioStartPlayback(true)) { Serial.printf("[%s] 播放启动失败\n", tag); return; }

  static int16_t buf[FRAME_SAMPLES];
  const float amp = TONE_AMP_FS * 32767.0f;
  const uint32_t total = (uint32_t)SAMPLE_RATE_HZ * 2;
  uint32_t n = 0;
  bool stuck = false;

  const uint32_t t0 = millis();
  while (n < total && !aborted()) {
    if (useLut) {
      for (int i = 0; i < FRAME_SAMPLES; i++)
        buf[i] = s_toneLut[(n + i) % TONE_LUT_LEN];
    } else {
      for (int i = 0; i < FRAME_SAMPLES; i++) {
        float t = (float)(n + i) / (float)SAMPLE_RATE_HZ;
        buf[i] = (int16_t)(amp * sinf(2.0f * (float)PI * (float)TONE_HZ * t));
      }
    }
    // 按**实际写入量**推进,写少了相位也不会跳
    size_t w = audioWrite(buf, FRAME_SAMPLES, 200);
    if (w == 0) { stuck = true; break; }
    n += w;
  }
  const uint32_t dt = millis() - t0;
  const uint32_t under = audioTxUnderruns();

  audioStopPlayback();   // 内含补静音 + drain + 关功放

  if (stuck) { Serial.printf("[%s] audioWrite 返回 0,TX 卡住了\n", tag); return; }

  const uint32_t ideal = total * 1000UL / SAMPLE_RATE_HZ;
  Serial.printf("[%s] 送出 %lu 样本,墙钟 %lu ms(理论 %lu ms),TX 欠载 %lu 次\n",
                tag, (unsigned long)n, (unsigned long)dt,
                (unsigned long)ideal, (unsigned long)under);
  if (under == 0 && dt <= ideal + 120)
    Serial.println("          -> 生产者跟得上,DMA 没断。这时候还听到断续才该怀疑供电。");
  else
    Serial.println("          -> 生产者跟不上,DMA 欠载被 auto_clear 填了零 —— 断续来自这里,不是硬件。");
}

static void stage2_tone()      { runTone(true);  }
static void stage6_tone_sinf() { runTone(false); }

// ---------------------------------------------------------------- Stage 3
static void stage3_mic() {
  Serial.printf("\n[STAGE 3] 麦克风电平,micShift=%u  DCblocker=%s。对着麦说话。按 x 退出。\n",
                getMicShift(), getDcBlocker() ? "on" : "off");
  Serial.println("          目标:说话时 peak 在 8000~20000 之间。太小 ASR 识别不出来。");

  if (!audioStartCapture()) { Serial.println("录音启动失败"); return; }

  static int16_t buf[FRAME_SAMPLES];
  int32_t  mn = 32767, mx = -32768;
  uint64_t sumSq = 0;
  uint32_t cnt = 0;
  uint32_t lastPrint = millis();

  while (!aborted()) {
    size_t got = audioRead(buf, FRAME_SAMPLES, 200);
    for (size_t i = 0; i < got; i++) {
      int32_t v = buf[i];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
      sumSq += (uint64_t)((int64_t)v * v);
      cnt++;
    }

    // cnt==0 也要出声 —— 之前这里是"什么都不打印",看起来像死机,
    // 实际是 audioRead 一路超时返回 0(GPIO4/5 没时钟)。别再让它静默失败。
    if (millis() - lastPrint >= 500 && cnt == 0) {
      Serial.println("!! 500 ms 内一个样本都没读到 —— RX 超时。查 BCLK/WS 是否在跑、GPIO6 接线。");
      lastPrint = millis();
      continue;
    }

    if (millis() - lastPrint >= 500 && cnt > 0) {
      uint32_t rms  = (uint32_t)sqrt((double)sumSq / (double)cnt);
      int32_t  peak = (mx > -mn) ? mx : -mn;
      Serial.printf("min=%6ld  max=%6ld  rms=%5lu  peak=%6ld",
                    (long)mn, (long)mx, (unsigned long)rms, (long)peak);

      if (peak > 20) {
        int delta = (int)lroundf(log2f(12000.0f / (float)peak));
        int sugg  = (int)getMicShift() - delta;
        if (sugg < 8)  sugg = 8;
        if (sugg > 20) sugg = 20;
        if (sugg != (int)getMicShift())
          Serial.printf("   -> 建议 micShift=%d  (输入 m 修改)", sugg);
        else
          Serial.print("   -> 电平合适");
      } else {
        Serial.print("   -> 几乎没信号,查 GPIO6 / L-R 是否接 GND");
      }
      Serial.println();

      mn = 32767; mx = -32768; sumSq = 0; cnt = 0;
      lastPrint = millis();
    }
  }
  audioStopCapture();
}

// ---------------------------------------------------------------- Stage 4
static void stage4_switch() {
  const int ROUNDS = 200;
  Serial.printf("\n[STAGE 4] 录/放切换 %d 轮(不开功放,安静测试)。这是关键里程碑。\n", ROUNDS);
  Serial.println("          验证:RX 反复 enable/disable、TX 常开供时钟,不重装驱动,不漏堆。");
  Serial.println("          每轮都必须读到 RX 数据 —— 读不到就说明 GPIO4/5 上没时钟。");
  printHeap("before");

  static int16_t buf[FRAME_SAMPLES];
  int fails = 0;

  for (int i = 0; i < ROUNDS; i++) {
    if (aborted()) break;

    if (!audioStartCapture()) { Serial.printf("  第 %d 轮 RX enable 失败\n", i); fails++; break; }
    if (audioRead(buf, FRAME_SAMPLES, 200) == 0) {
      Serial.printf("  第 %d 轮 RX 读不到数据(BCLK/WS 停了?)\n", i);
      if (++fails >= 5) { Serial.println("  连续失败,提前收工。"); break; }
    }
    audioStopCapture();

    if (!audioStartPlayback(false)) { Serial.printf("  第 %d 轮 TX enable 失败\n", i); fails++; break; }
    memset(buf, 0, sizeof(buf));
    audioWrite(buf, FRAME_SAMPLES, 200);
    audioStopPlayback();

    if ((i + 1) % 50 == 0) {
      Serial.printf("  %3d/%d ok   free=%u  maxAlloc=%u\n", i + 1, ROUNDS,
                    (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
    }
  }

  printHeap("after");
  if (fails == 0) Serial.println("[STAGE 4] 通过。free/maxAlloc 前后应基本持平 —— 有明显下降就是漏了。");
  else            Serial.printf("[STAGE 4] 失败 %d 次,先别往下做。\n", fails);
}

// ---------------------------------------------------------------- Stage 5
static void stage5_loopback() {
  const size_t total = (size_t)REC_TEST_SECONDS * SAMPLE_RATE_HZ;
  Serial.printf("\n[STAGE 5] 录 %d 秒 (%u 样本 / %u 字节) 后回放。\n",
                REC_TEST_SECONDS, (unsigned)total, (unsigned)(total * 2));
  Serial.println("          注意:整段录进 RAM 只是硬件验收手段,最终固件不会这么做。");

  int16_t *rec = (int16_t *)malloc(total * sizeof(int16_t));
  if (!rec) { Serial.println("malloc 失败,堆不够"); printHeap("fail"); return; }
  printHeap("alloc'd");

  // ---- 录 ----
  if (!audioStartCapture()) { free(rec); Serial.println("录音启动失败"); return; }
  Serial.println("  >>> 开始说话...");
  size_t n = 0;
  while (n < total && !aborted()) {
    size_t got = audioRead(rec + n, total - n, 300);
    if (got == 0) break;
    n += got;
  }
  audioStopCapture();
  Serial.printf("  录到 %u 样本 (%.2f s)\n", (unsigned)n, (float)n / SAMPLE_RATE_HZ);

  // ---- 放 ----
  delay(300);
  Serial.println("  <<< 回放...");
  if (audioStartPlayback(true)) {
    size_t p = 0;
    while (p < n && !aborted()) {
      size_t w = audioWrite(rec + p, n - p, 300);
      if (w == 0) break;
      p += w;
    }
    audioStopPlayback();
  }

  free(rec);
  printHeap("freed");
  Serial.println("[STAGE 5] 完成。听得清自己说话 = 麦克风+功放+半双工切换全部正常。");
}

// ---------------------------------------------------------------- 交互输入
static long readNumber(const char *prompt, long lo, long hi) {
  Serial.printf("%s (%ld-%ld,回车确认): ", prompt, lo, hi);
  String s;
  uint32_t t0 = millis();
  while (millis() - t0 < 15000) {
    while (Serial.available()) {
      int c = Serial.read();
      if (c == '\r' || c == '\n') {
        if (s.length() == 0) continue;
        long v = s.toInt();
        Serial.println(v);
        if (v < lo) v = lo;
        if (v > hi) v = hi;
        return v;
      }
      if (c >= '0' && c <= '9') { s += (char)c; Serial.write(c); }
    }
    delay(5);
  }
  Serial.println(" (超时)");
  return -1;
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  delay(400);                      // 等 USB CDC 枚举

  Serial.println("\n\n[BOOT] ESP32-C3 AI Voice — Stage 1~5 硬件验收台 (+ 6 号对照组)");
  Serial.printf("[BOOT] 核心 %s   CPU %u MHz\n", ESP.getSdkVersion(), (unsigned)getCpuFrequencyMhz());
  printHeap("boot");

  g_btn.begin(PIN_PTT_BUTTON, BUTTON_DEBOUNCE_MS);

  if (!audioBegin()) {
    Serial.println("[BOOT] 音频初始化失败,停在这里。");
    while (true) delay(1000);
  }
  printHeap("audio ok");

  Serial.println("\n!! 开始 Stage 2/5 之前,确认 MAX98357A VIN 上已焊 470uF~1000uF 电解电容 !!");
  Serial.printf("!! 未焊接时请保持输出增益 <= %d,否则大音量会 brownout 重启 !!\n", OUTPUT_GAIN_DEFAULT);

  printMenu();
}

void loop() {
  g_btn.update();

  if (!Serial.available()) { delay(5); return; }

  int c = Serial.read();
  if (c == '\r' || c == '\n') return;
  Serial.println((char)c);

  switch (c) {
    case '1': stage1_gpio();     break;
    case '2': stage2_tone();     break;
    case '3': stage3_mic();      break;
    case '4': stage4_switch();   break;
    case '5': stage5_loopback(); break;
    case '6': stage6_tone_sinf(); break;

    case 'g': case 'G': {
      long v = readNumber("输出增益", 0, 256);
      if (v >= 0) {
        setOutputGain((uint16_t)v);
        if (v > 120) Serial.println("!! 确认已焊 470uF+ 电容,否则大音量必重启");
      }
      break;
    }
    case 'm': case 'M': {
      long v = readNumber("麦克风移位", 8, 20);
      if (v >= 0) {
        setMicShift((uint8_t)v);
        Serial.println("标定好之后记得回填 config.h 的 MIC_SHIFT_DEFAULT");
      }
      break;
    }
    case 'd': case 'D':
      setDcBlocker(!getDcBlocker());
      Serial.printf("DC blocker = %s\n", getDcBlocker() ? "on" : "off");
      break;

    case 'i': case 'I': heapReport(); break;

    case 'h': case 'H': break;
    default:  Serial.println("未知命令"); break;
  }

  printMenu();
}
