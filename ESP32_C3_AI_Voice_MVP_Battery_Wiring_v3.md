# ESP32-C3 半双工 AI 语音 MVP
## 完整硬件接线 + 1S 锂电池充电保护 + 电量检测

> 目标：在现有 **ESP32-C3 SuperMini + INMP441 + MAX98357A + 4Ω/3W Speaker + Push Button** 基础上，加入一颗 1S 锂电池、充电/保护、电池电量检测。  
> 设计优先级：**便宜、模块化、稳定、容易焊、容易调试**。

---

# 1. 推荐电源方案

## 最低成本且比较稳的 MVP 方案

```text
1S Li-ion / LiPo
      │
      ▼
TP4056 USB-C 充电 + DW01A/8205A 保护模块
      │
      ▼
主电源开关
      │
      ├──────────────→ 电池电压检测 → ESP32 GPIO1 ADC
      │
      ▼
TPS61023 5V Boost
      │
      ▼
SS14 Schottky
      │
      ▼
5V SYSTEM
   │
   ├── ESP32-C3 SuperMini 5V
   └── MAX98357A VIN

ESP32-C3 3V3
   └── INMP441 VDD
```

### 为什么选这套

- **TP4056 保护版**：价格低、模块非常常见，完成 1S 锂电池 CC/CV 充电。
- 带 **DW01A + 8205A** 的版本额外提供过充、过放、过流/短路保护。
- **TPS61023**：比最便宜的 MT3608 更适合 Wi-Fi + Class-D 功放这种有瞬时大电流的负载。
- **ESP32-C3 自己的 ADC** 测电池电压，只需要两个电阻和一个电容，不增加 Fuel Gauge IC。
- **SS14** 用于隔离电池 Boost 5V 和 ESP32 USB 5V，避免烧录时两路 5V 直接互相灌电。

> 推荐使用方式：**使用时靠电池；充电时关闭主电源。**
>
> 普通 TP4056 没有真正的 Power Path。  
> 如果要求“边充电边运行”，见本文最后的 BQ24074 升级方案。

---

# 2. 新增 BOM

| 数量 | 器件 | 建议 |
|---:|---|---|
| 1 | 1S Li-ion / LiPo | 3.7V nominal / 4.2V full |
| 1 | TP4056 USB-C 保护版模块 | 必须有 `B+ B- OUT+ OUT-` |
| 1 | TPS61023 5V Boost 模块 | 固定 5V，建议 1.5A 级 |
| 1 | SS14 / 1N5819 | Schottky diode |
| 1 | SPST 主电源开关 | 机械开关即可 |
| 2 | 100kΩ | Battery ADC 分压 |
| 1 | 100nF | Battery ADC 滤波 |
| 1 | 220–470µF / ≥6.3V 电解电容 | 推荐放在 MAX98357A 附近稳定 5V |

已有：

```text
ESP32-C3 SuperMini
INMP441
MAX98357A
4Ω / 3W Speaker
Push Button
```

---

# 3. 电池要求

使用：

```text
1S Li-ion / LiPo
Nominal: 3.6–3.7 V
Full:    4.2 V
```

建议：

```text
容量：≥1000 mAh（按续航需求增减）
持续放电能力：建议 ≥2–3 A
```

原因是系统存在两个明显的瞬时负载：

```text
ESP32-C3 Wi-Fi TX
+
MAX98357A + 4Ω Speaker
```

不要用没有明确放电能力的超小 LiPo 去高音量驱动 4Ω/3W Speaker。

---

# 4. TP4056 模块选择

必须购买这种接口完整的**保护版**：

```text
USB-C

B+      → Battery +
B-      → Battery -

OUT+    → System +
OUT-    → System GND
```

常见模块结构：

```text
TP4056
+
DW01A
+
8205A / FS8205A dual MOSFET
```

不要选只有：

```text
B+
B-
```

而没有 `OUT+ / OUT-` 的纯充电模块。

---

# 5. TP4056 充电电流

很多廉价 TP4056 模块默认设置约：

```text
1 A charge current
```

不要默认所有小 LiPo 都能承受 1A。

典型 TP4056 PROG 电阻关系：

```text
RPROG ≈ 1.2kΩ → ~1000 mA
RPROG ≈ 2.4kΩ → ~500 mA
RPROG ≈ 4.7kΩ → ~250 mA
```

按照你购买电池的数据手册允许充电电流设置。

---

# 6. 电池 → TP4056

```text
Battery +  → TP4056 B+
Battery -  → TP4056 B-
```

极性不要接反。

只接 **1S**。

---

# 7. TP4056 → 主电源开关 → Boost

推荐只切正极：

```text
TP4056 OUT+
      │
      ▼
SPST Master Power Switch
      │
      ├──────────→ Battery Sense Divider
      │
      ▼
TPS61023 VIN+

TP4056 OUT- ─────────→ TPS61023 GND
```

也就是说：

```text
Switch OFF
→ 整机关闭
→ TP4056 可以单独给电池充电

Switch ON
→ 电池通过 Boost 给整机供电
```

---

# 8. TPS61023 Boost

选择固定 5V 或调到：

```text
VOUT = 5.0 V
```

接线：

```text
Switched Battery + → TPS61023 VIN
GND                → TPS61023 GND
```

输出：

```text
TPS61023 5V OUT
      │
      ▼
SS14
      │
      ▼
5V SYSTEM
```

SS14 方向：

```text
TPS61023 OUT ──|>|── 5V SYSTEM
```

也就是允许电流：

```text
Boost → System
```

不允许：

```text
System → Boost
```

---

# 9. 为什么需要 SS14

ESP32-C3 SuperMini 的 5V pin 通常与 USB VBUS 位于同一条 5V rail。

如果：

```text
Battery Boost → ESP32 5V
```

同时你又：

```text
USB-C → ESP32
```

两路 5V 可能互相回灌。

所以：

```text
Battery Boost
     │
    SS14
     │
     ▼
ESP32 5V rail
```

烧录时 USB 5V 不会直接倒灌 Boost 输出。

SS14 会有少量压降，因此 Battery 模式下实际 System Rail 可能约：

```text
4.6–4.9 V
```

ESP32-C3 SuperMini 和 MAX98357A 都可以正常工作。

---

# 10. 5V SYSTEM 分配

```text
5V SYSTEM
   │
   ├──→ ESP32-C3 SuperMini 5V
   │
   └──→ MAX98357A VIN
```

推荐在 MAX98357A 模块旁增加：

```text
5V SYSTEM ──┬── 220–470µF ── GND
            │
            └── MAX98357A VIN
```

用于缓冲扬声器输出时的瞬时电流。

---

# 11. 3.3V 分配

ESP32-C3 SuperMini 自己产生 3.3V：

```text
ESP32-C3 3V3
     │
     └──→ INMP441 VDD
```

不要用 5V 给 INMP441。

---

# 12. 电池电压检测

为了最低成本，不增加 Fuel Gauge。

使用：

```text
ESP32-C3 GPIO1 / ADC1_CH1
```

GPIO1 当前未被本项目其他硬件占用。

---

## 12.1 ADC 分压

**分压必须接在主电源开关之后。**

这样系统关机时不会通过 ADC 分压网络反向给 ESP32 phantom power。

接法：

```text
Switched Battery +
        │
      100kΩ
        │
        ├────────→ GPIO1
        │
      100kΩ
        │
       GND
```

同时：

```text
GPIO1
  │
100nF
  │
 GND
```

完整：

```text
Switched Battery +
        │
      100k
        │
        ├──────────── GPIO1 / ADC1_CH1
        │                │
      100k             100nF
        │                │
       GND              GND
```

---

## 12.2 电压关系

因为：

```text
Rtop    = 100k
Rbottom = 100k
```

所以：

```text
V_ADC = V_BAT / 2
```

满电：

```text
Battery = 4.20 V
ADC     = 2.10 V
```

ESP32-C3 ADC 使用最高 attenuation 档时有效测量范围约到 2.5V，因此 2.1V 在范围内。

---

## 12.3 Arduino GPIO 定义

```cpp
#define PIN_BATTERY_ADC 1
```

建议：

```cpp
analogSetPinAttenuation(PIN_BATTERY_ADC, ADC_11db);
```

不同 Arduino-ESP32 Core 版本可能把最高档名称显示为 11dB 或 12dB；以当前 Core API 为准。

读取时优先使用校准后的：

```cpp
uint32_t adc_mv = analogReadMilliVolts(PIN_BATTERY_ADC);

float battery_voltage =
    (adc_mv / 1000.0f) * 2.0f;
```

建议每次读取：

```text
采样 16–32 次
→ 求平均
```

不需要高频采样。

---

# 13. 电量百分比

仅通过电压估算 SOC 是**近似值**。

不要直接认为：

```text
3.0V = 0%
4.2V = 100%
```

之间是线性的。

MVP 可使用简单查表：

| 电池静置电压 | 粗略状态 |
|---:|---|
| 4.20V | 满电附近 |
| 4.05V | 较高 |
| 3.90V | 中高 |
| 3.80V | 中等 |
| 3.70V | 偏低 |
| 3.55V | 很低 |
| ≤3.4V | 应准备关机 |

这些只能作为 UI 粗略估算。

电池在扬声器大音量播放或 Wi-Fi TX 时电压会瞬时下降，所以：

```text
不要在大电流瞬间更新 SOC
```

推荐：

```text
Idle 状态
+
连续多次平均
```

再更新电量。

---

# 14. 如果以后需要准确电量百分比

增加：

```text
MAX17048 / MAX17049 Fuel Gauge
```

优点：

```text
I2C
SOC 百分比
比单纯电压映射准确
```

但为了最低成本 MVP，当前不需要。

---

# 15. ESP32-C3 ↔ INMP441

保持当前接线不变：

| ESP32-C3 | INMP441 | 功能 |
|---|---|---|
| 3V3 | VDD | 麦克风供电 |
| GND | GND | Ground |
| GND | L/R | Left channel |
| GPIO4 | SCK | I2S BCLK |
| GPIO5 | WS | I2S WS/LRCLK |
| GPIO6 | SD | Mic data → ESP32 |

文本版：

```text
ESP32 3V3   → INMP441 VDD
ESP32 GND   → INMP441 GND
ESP32 GND   → INMP441 L/R

ESP32 GPIO4 → INMP441 SCK
ESP32 GPIO5 → INMP441 WS
ESP32 GPIO6 ← INMP441 SD
```

---

# 16. ESP32-C3 ↔ MAX98357A

保持当前接线不变：

| ESP32-C3 | MAX98357A | 功能 |
|---|---|---|
| 5V SYSTEM | VIN | Amplifier power |
| GND | GND | Ground |
| GPIO4 | BCLK | I2S BCLK |
| GPIO5 | LRC | I2S LRCLK |
| GPIO7 | DIN | ESP32 → Amp data |
| GPIO10 | SD | Amp enable/shutdown |
| — | GAIN | 不接 |

文本：

```text
GPIO4  → MAX98357A BCLK
GPIO5  → MAX98357A LRC
GPIO7  → MAX98357A DIN
GPIO10 → MAX98357A SD

5V SYSTEM → MAX98357A VIN
GND       → MAX98357A GND

GAIN → 不接
```

---

# 17. I2S 共享时钟

```text
GPIO4
   ├──→ INMP441 SCK
   └──→ MAX98357A BCLK

GPIO5
   ├──→ INMP441 WS
   └──→ MAX98357A LRC
```

这是故意设计的。

因为系统是 Half-Duplex：

```text
按住按钮：
I2S RX
INMP441 → ESP32

AI 回复：
I2S TX
ESP32 → MAX98357A
```

录音和播放不同时运行。

---

# 18. Push Button

```text
GPIO3 ─── Button ─── GND
```

Arduino：

```cpp
pinMode(3, INPUT_PULLUP);
```

逻辑：

```text
Pressed  = LOW
Released = HIGH
```

---

# 19. Speaker

```text
MAX98357A SPK+ → Speaker +
MAX98357A SPK- → Speaker -
```

Speaker：

```text
4Ω / 3W
```

重要：

```text
Speaker - 不接系统 GND
```

扬声器直接跨接 MAX98357A 的差分/BTL 输出。

---

# 20. 最终 GPIO 定义

```cpp
#define PIN_BATTERY_ADC   1
#define PIN_PTT_BUTTON    3

#define PIN_I2S_BCLK      4
#define PIN_I2S_WS        5
#define PIN_MIC_DATA      6
#define PIN_AMP_DATA      7
#define PIN_AMP_SD       10
```

表：

| GPIO | 功能 |
|---:|---|
| GPIO1 | Battery Voltage ADC |
| GPIO3 | Push Button |
| GPIO4 | INMP441 SCK + MAX98357A BCLK |
| GPIO5 | INMP441 WS + MAX98357A LRC |
| GPIO6 | INMP441 SD → ESP32 |
| GPIO7 | ESP32 → MAX98357A DIN |
| GPIO10 | MAX98357A SD |

---

# 21. 完整系统总接线

```text
                         TP4056 USB-C
                              │
                              ▼
                    ┌───────────────────┐
Battery + ─────────►│ B+             OUT+├── Master Switch ───┬──► TPS61023 VIN
Battery - ─────────►│ B-             OUT-├────────────────────┴──► GND
                    │ TP4056 + Protection│
                    └───────────────────┘
                                                    │
                                                    │ Battery Sense
                                                    │
                                                    ├──100k──┐
                                                    │        │
                                                    │      GPIO1
                                                    │        │
                                                    │      100k
                                                    │        │
                                                    │       GND
                                                    │
                                                    │   GPIO1
                                                    │     │
                                                    │   100nF
                                                    │     │
                                                    │    GND
                                                    │
                                                    ▼
                                              ┌───────────┐
                                              │ TPS61023  │
                                              │ 3.xV → 5V │
                                              └─────┬─────┘
                                                    │
                                                   SS14
                                                    │
                                                    ▼
                                                5V SYSTEM
                                              ┌─────┴─────┐
                                              │           │
                                              ▼           ▼
                                        ESP32-C3      MAX98357A
                                           5V             VIN
                                           │
                                           │ 3V3
                                           ▼
                                        INMP441 VDD


ESP32-C3 SIGNALS
────────────────────────────────────────────

GPIO1  ← Battery divider

GPIO3  ── Button ── GND

GPIO4  ──┬── INMP441 SCK
         └── MAX98357A BCLK

GPIO5  ──┬── INMP441 WS
         └── MAX98357A LRC

GPIO6  ←──── INMP441 SD

GPIO7  ────→ MAX98357A DIN

GPIO10 ────→ MAX98357A SD


INMP441
────────────────────────────────────────────
VDD → ESP32 3V3
GND → GND
L/R → GND
SCK → GPIO4
WS  → GPIO5
SD  → GPIO6


MAX98357A
────────────────────────────────────────────
VIN  → 5V SYSTEM
GND  → GND
BCLK → GPIO4
LRC  → GPIO5
DIN  → GPIO7
SD   → GPIO10
GAIN → NC


SPEAKER
────────────────────────────────────────────
MAX98357A SPK+ → Speaker +
MAX98357A SPK- → Speaker -
```

---

# 22. Ground

下面所有 GND 必须共地：

```text
TP4056 OUT-
TPS61023 GND
ESP32-C3 GND
INMP441 GND
MAX98357A GND
Button GND
Battery ADC divider GND
```

注意：

```text
Speaker - 不是 GND
```

---

# 23. 两个 USB-C 如何使用

最终实验板可能有：

```text
USB-C #1 → ESP32-C3
USB-C #2 → TP4056
```

## ESP32 USB-C

用途：

```text
烧录
Serial Debug
USB 供电调试
```

## TP4056 USB-C

用途：

```text
Battery charging
```

---

# 24. 推荐使用规则

## Battery Mode

```text
TP4056 USB-C：拔掉
ESP32 USB-C：拔掉
Master Switch：ON

Battery
→ TP4056 protection
→ TPS61023
→ 5V System
```

## Charging Mode

```text
Master Switch：OFF
TP4056 USB-C：插入
```

## Programming / Debug

可以：

```text
ESP32 USB-C：插入
```

SS14 会隔离 Boost 输出，降低 USB 5V 倒灌 Boost 的风险。

为了最简单可靠：

```text
烧录时可以把 Master Switch 关掉。
```

---

# 25. 为什么不推荐最便宜的 MT3608

MT3608 很便宜，也可以在低音量原型上工作。

但是你的负载包含：

```text
ESP32-C3 Wi-Fi 瞬时电流
+
MAX98357A 4Ω Speaker 瞬时电流
```

相比 MT3608，TPS61023 更适合：

- synchronous boost
- 单节锂电池输入
- 5V / 1.5A 官方典型工作点
- 低输入电压能力更好
- 轻载效率更好
- shutdown 时有 true load disconnect
- output over-voltage protection
- thermal protection
- short-circuit protection

所以：

```text
极限便宜 → MT3608
更稳且仍很便宜 → TPS61023
```

本项目推荐 **TPS61023**。

---

# 26. 为什么普通 TP4056 不建议边充边用

普通 TP4056 的充电终止判断与流向电池端的电流有关。

如果：

```text
Charger
   │
Battery + System Load
```

同时工作，TP4056 可能把系统负载误认为仍在给电池充电，使 charge termination 判断不正确。

所以本 MVP：

```text
充电 → System OFF
使用 → Charger disconnected
```

最简单。

---

# 27. 如果必须边充边用

将 TP4056 方案升级为带真正 Power Path 的：

```text
BQ24074
```

架构：

```text
USB 5V
   │
   ▼
BQ24074
   │
   ├── BAT → 1S Battery
   │
   └── OUT → TPS61023 → 5V System
```

BQ24074 可以：

```text
USB 给系统供电
+
同时独立管理电池充电
+
电池在系统需求高时补充电流
```

这是更像正式产品的电源架构。

代价：

```text
模块贵一些
外围/接线复杂一些
```

所以：

```text
最低成本 MVP
→ TP4056 protected + TPS61023

需要真正 charge-and-play
→ BQ24074 + TPS61023
```

---

# 28. 最终购买清单

## 必买

```text
1 × 1S LiPo / Li-ion battery
1 × TP4056 USB-C protected module (B+/B-/OUT+/OUT-)
1 × TPS61023 5V boost module
1 × SS14 Schottky diode
1 × SPST power switch
2 × 100kΩ resistor
1 × 100nF capacitor
```

## 推荐增加

```text
1 × 220–470µF / ≥6.3V electrolytic capacitor
```

安装在：

```text
MAX98357A VIN ↔ GND
```

附近。

---

# 29. 官方技术依据

### TPS61023

Texas Instruments:

https://www.ti.com/product/TPS61023

关键参数：

```text
VIN: 0.5–5.5V
VOUT: up to 5.5V
3.7A typical switch current limit
94% efficiency at:
VIN = 3.6V
VOUT = 5V
IOUT = 1.5A
true load disconnect in shutdown
```

### BQ24074

Texas Instruments:

https://www.ti.com/product/BQ24074

关键功能：

```text
1-cell Li-ion/LiPo charger
up to 1.5A
Dynamic Power Path Management
system power + battery charging simultaneously
```

### ESP32-C3 ADC

Espressif:

https://documentation.espressif.com/esp32-c3_datasheet_en.html

GPIO1：

```text
GPIO1 = ADC1_CH1
```

最高 attenuation 档有效测量范围约：

```text
0–2.5V
```

Espressif 的 ADC 测试条件也使用外接：

```text
100nF capacitor
```

因此本设计的：

```text
4.2V battery
→ 100k / 100k divider
→ 2.1V ADC
```

处于可测范围内。

---

# 30. 最终结论

当前推荐固定成：

```text
1S LiPo
   ↓
TP4056 USB-C + DW01A/8205A protection
   ↓
Power Switch
   ↓
TPS61023 5V Boost
   ↓
SS14
   ↓
5V System
   ├── ESP32-C3 SuperMini
   └── MAX98357A

ESP32 3V3
   └── INMP441

Battery after switch
   ↓
100k / 100k divider + 100nF
   ↓
GPIO1 ADC
```

这是当前 MVP 在 **成本、稳定性、模块数量和开发速度** 之间比较合适的方案。
