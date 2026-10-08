# H4X 模组版原理图检查与参考资料

AI_figure / P1 已使用 ESP32-C3-MINI-1-H4X 模块。本版根据 2026-10-04 保存并重开后的原理图引脚/器件/导线回读、原生导出图及检查记录更新。模块相关连接审计通过，官方严格 DRC 为 0 致命错误、0 错误、0 警告、0 信息；电源、散热和音频软件配合仍保留为待验证项。

本次更新 sch-check 文档和截图，未再次修改电路。DRC 和连接结论引用随包保存的 H4X 最终检查证据，并非本轮新跑的实时检查。PCB、天线净空、封装焊盘制造验证、实板电源/射频、喇叭/电池规格及固件功能没有在本轮验收。保持 GPIO 对应关系不等于软件兼容性已实测。

检查日期：2026-10-04。页码均说明是 PDF 页码还是手册印刷页码。

## 模组替换记录

- U1：ESP32-C3FH4 / C2858491 → ESP32-C3-MINI-1-H4X / C41349510；封装 WIFIM-SMD_ESP32-C3-MINI-1。
- 移除 Y1、C17、C18、L2、L3、C20、C21、J4 及裸芯片去耦 C9、C10、C11、C12、C14，共 13 件；器件数 70 → 57（包括 6 个测试点）。
- 保留 C13 100nF、C16 10µF、EN RC、启动上拉、RESET/BOOT/REC、LED、I2S、USB/UART 和 SYS_ADC；另外 56 个器件的 154 个引脚连接/NC 与替换前一致。
- 纠正旧检查表的 SYS_ADC 脚号：当前模块焊盘 13 / GPIO1 / ADC1_CH1；GPIO0 / 焊盘 12 未使用。U7 EN 仍接 SYS。
- 供电、EN、信号映射和全部 NC 在网表中逐脚核对；这些结论不代表 PCB 或固件已完成验证。

## 已保存检查证据

| 检查 | 结果 | 证据 |
|---|---|---|
| 官方严格 DRC | 0 致命错误 / 0 错误 / 0 警告 / 0 信息 | [h4x-final-drc.json](evidence/h4x-final-drc.json) |
| 引脚意图审计 | 53 模块引脚全部符合计划；38 连接 / 15 NC / 22 GND | [h4x-pin-intent-audit.json](evidence/h4x-pin-intent-audit.json) |
| 连接检查 | 0 警告/错误；1 条充电区无接点交叉信息（已核对） | [h4x-final-check.json](evidence/h4x-final-check.json) |
| 短接与孤立导线 | 0 bridges / 0 orphans / 0 orphanFlags | [h4x-final-bridge.json](evidence/h4x-final-bridge.json) |
| 原理图布局 | 57 个器件有实测 bbox；0 重叠、偏格、出图纸等；功能框通过 | [h4x-final-layout-lint.json](evidence/h4x-final-layout-lint.json) |

完整回读：[网表](evidence/h4x-final-readback.json)；[替换记录](evidence/H4X_REPLACEMENT_REPORT_20261004.md)；[模块全部引脚 CSV](module_pinmap.csv)；[器件清单](component_inventory.csv)。

## 当前原理图

[H4X 当前原理图 PDF](current_schematic.pdf) · [原生工程](AI_figure-P1-H4X-20261004.epro2)；original_schematic.pdf 为裸芯片历史输入，仅供对照。

### H4X 当前整页原理图
![H4X 当前整页原理图](current_schematic.png)

### H4X 主控与入口去耦
![H4X 主控与入口去耦](reference_circuits/schematic_mcu.png)

### 主 3.3V LDO
![主 3.3V LDO](reference_circuits/schematic_main_ldo.png)

### 充电、电源路径与电池保护
![充电、电源路径与电池保护](reference_circuits/schematic_power.png)

### I²S 麦克风、功放与功放 LDO
![I²S 麦克风、功放与功放 LDO](reference_circuits/schematic_audio.png)

### 复位、启动、录音、LED 与 SYS_ADC
![复位、启动、录音、LED 与 SYS_ADC](reference_circuits/schematic_controls.png)

### USB-C / ESD / 输入电源
![USB-C / ESD / 输入电源](reference_circuits/schematic_usb.png)

### UART 与下载测试点
![UART 与下载测试点](reference_circuits/schematic_testpads.png)

## 下载资料

| 位号 | 型号 | 资料 | 说明 |
|---|---|---|---|
| U1 | ESP32-C3-MINI-1-H4X / C41349510 | [v2.2；46 页](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf) | 板载 PCB 天线、40MHz 晶振与 4MB Flash；本板实际供应商编号已回读 |
| U2 | ETA6002E8A | [V1.5；9 页](datasheets/ETA6002_V1.5.pdf) | 单节锂电开关充电与电源路径 |
| U3 | ETA5060V330S8F | [V2.6；15 页](datasheets/ETA5060_V2.6.pdf) | 固定 3.3V，SOT89-5 |
| U4 | ICS-43434 | [DS-000069 V1.2；21 页](datasheets/ICS-43434_V1.2.pdf) | I²S 数字麦克风；厂商迁移站点原文 |
| U5 | NS4168 | [Apr.2023 V1.2；10 页](datasheets/NS4168_V1.2.pdf) | I²S 功放；纳芯威原文，Kynix 镜像 |
| U6 | PUOLOP(迪浦) DW01A / C351410 | [Fortune V1.2；13 页（异厂参考）](datasheets/DW01A_V1.2.pdf) | 实际厂商手册待补；仅参考保护拓扑，不能据此确认 PUOLOP 阈值 |
| U7 | TLV75733PDBVR | [Rev.C；41 页](datasheets/TLV757P.pdf) | 固定 3.3V，DBV / SOT-23-5 |
| Q1 | FORTUNE(富晶) FS8205A / C16052 | [Fortune V1.2；6 页](datasheets/FS8205A_V1.2.pdf) | 实际厂商身份已由器件回读确认；双 N-MOS 共漏极结构 |
| D1 / D2 | SEUCS2X3V1B | [Rev-1.2；8 页](datasheets/SEUCS2X3V1B_V1.2.pdf) | 补充 ESD 保护器件；ElecSuper 原文，立创镜像 |

另附 [ESP32-C3 硬件设计指南](datasheets/ESP32-C3_hardware_guidelines.pdf)。U1 模组及其余芯片参考资料见下；U6 仅有同名异厂拓扑参考，实际厂商手册待补。另补充 Q1 与 D1/D2。

## 优先核实的问题

### 高 · 电源架构 · U3 / U7：电池低电量时不能保证 3.3V

**观察与依据：** 两个 LDO 都从 SYS 降压。USB 拔掉后，SYS 由电池经电源路径供电，不是固定 3.6V 或固定 5V。只要输入低于 3.3V 加所需压差，就无法维持 3.3V。U3 的 140mV 是 1A 时典型压差；U7 的 425mV 是 1A、3.3V 输出的最大压差，不能直接当成所有负载的压差。

**影响：** 低电量、大音量或 Wi-Fi 发射时，两路电压可能下跌，导致音频削顶、欠压关断或主控复位。U7 先掉压时，主控送入功放的高电平也可能高于功放 VDD，需核查输入引脚额定值。ESP32-C3 推荐供电下限为 3.0V；掉出 3.3V 稳压区并不等同于立即停止运行。

**建议：** 若要求在较宽电池电压范围始终有 3.3V，采用合适的升降压电源；若保留 LDO，按峰值负载和压差确定低电量关机阈值，并在此之前关功放、停止写 Flash。电池保护阈值不能作为整板正常工作下限；U6 实际为 PUOLOP DW01A，同名 Fortune 手册不能确认其具体阈值。

资料：[ETA6002_V1.5.pdf](datasheets/ETA6002_V1.5.pdf)；[ETA5060_V2.6.pdf](datasheets/ETA5060_V2.6.pdf)；[TLV757P.pdf](datasheets/TLV757P.pdf)；[ESP32-C3_datasheet.pdf](datasheets/ESP32-C3_datasheet.pdf)；[ESP32-C3-MINI-1_datasheet_cn.pdf](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf)

### 高 · 热设计待核实 · U7：1A 标称能力不代表这颗封装可以连续输出 1A

**观察与依据：** U7 是无散热焊盘的 DBV / SOT-23-5，EN 直接接 SYS。功放负载电流持续经过它，损耗约为 (SYS − 3.3V) × 电流。以 SYS=4.5V、负载=0.5A 为假设，损耗为 0.6W；这是风险计算，不是实测功耗。

**影响：** 在手册所列不同参考板热阻下，这个假设会造成约 60~139°C 的温升，实际温升取决于铜面积、环境和音频平均功率。大音量连续播放可能热保护、降压或断续。3.3V 供电也不能获得手册在 5V / 4Ω 条件下标出的 2.5W。

**建议：** 先确定喇叭阻抗、目标连续功率及最大环境温度，再计算平均/峰值电流并核实散热；必要时改用更合适的封装或开关电源。不要直接把 NS4168 改接 SYS：其数字输入高电平要求随 VDD 变化，需重新检查 3.3V 主控接口兼容性。

资料：[TLV757P.pdf](datasheets/TLV757P.pdf)；[NS4168_V1.2.pdf](datasheets/NS4168_V1.2.pdf)

### 中 · 软件配合 · U4 / U5：接收左声道，播放右声道

**观察与依据：** U4 的 LR=GND，所以 MIC_SD 输出左声道。U5 的 CTRL 接 AMP_CTRL；GPIO 输出 3.3V 时选择右声道，输出低电平时关断。MIC_SD 与 AMP_DIN 是独立数据线，经主控处理后再发送，不是直接连接。

**影响：** 因此，这不是必然的硬件接错；但如果软件把收到的左声道原样放进发送帧的左声道，右声道功放可能无声。两个从机共用 BCLK / WS 是可行结构，主控需要统一时钟和帧格式。

**建议：** 保留现有硬件时，将左声道采样送至发送帧右声道，或复制至左右两个声道；采用标准 I²S、每帧 64 个 BCLK、每槽 32bit，承载麦克风 24bit 有效数据。48kHz 对应 3.072MHz BCLK。若想硬件选择左声道，CTRL 要落在 0.9~1.15V，不能用普通高/低 GPIO 直接实现。

资料：[ICS-43434_V1.2.pdf](datasheets/ICS-43434_V1.2.pdf)；[NS4168_V1.2.pdf](datasheets/NS4168_V1.2.pdf)

### 中 · 供电兼容性 · J1 / R3 / F1：USB 充电和整板运行电流要一起计算

**观察与依据：** R3=2.49kΩ，按 ETA6002 公式，快速充电电流约 1000/2490=0.402A。这是电池侧充电电流，不能直接等同于 VBUS 输入电流。主控、功放和电源转换损耗还会增加 USB 侧需求。

**影响：** 两个 5.1kΩ 的 CC 下拉连接正确，但图中没有读取电源电流档位的 CC 电路，也没有相应的可控输入限流方案。不能仅凭使用 USB-C 就假定可取 1.5A / 3A。F1 也不是精确的 500mA 或 1A 电流限制器。

**建议：** 明确供电场景：普通电脑 USB、Type-A 转 Type-C，还是有明确电流能力的适配器。若要支持普通 USB 2.0 端口，按该端口允许电流和枚举状态约束总负载；需要较大电流时，识别 CC 电流档位并控制输入限流。仅调低 R3 所设充电电流，不能保证所有运行模式都不过载。

资料：[ETA6002_V1.5.pdf](datasheets/ETA6002_V1.5.pdf)

### 中 · 保护功能取舍 · U2 NTC：接地会关闭电池温度检测

**观察与依据：** U2 的 NTC（3 脚）接 GND；手册给出低于 100mV 时禁用 NTC 检测。因此这种连接有明确定义，不应作为悬空或接错。

**影响：** 实际结果是板子不能按电芯温度停止充电。DW01A 负责电压/电流保护，不能补上温度检测。402mA 是否合适也取决于电池容量和厂商充电要求；手册预充电典型值 100mA 同样要核对。

**建议：** 若电池没有自身的温度保护，按 ETA6002 参考电路加入与电芯接触的 NTC 及偏置电阻，并按温度阈值选值。若项目明确允许禁用温度检测，应把这一取舍写进设计说明。

资料：[ETA6002_V1.5.pdf](datasheets/ETA6002_V1.5.pdf)

### 中 · 测量语义 · R14 / R15：这里测的是 SYS，不是电池电压

**观察与依据：** 两只 1MΩ 构成二分之一分压，接 U1 模块焊盘 13 的 GPIO1 / ADC1_CH1（旧报告脚号已修正）；C19=100nF 对地。若 SYS=4.5V，ADC 节点约 2.25V；需配置适合的衰减和校准。等效源阻抗 500kΩ，RC 时间常数约 50ms，阶跃后等待约 250ms 才接近充分稳定。

**影响：** 在电池供电时，它可近似反映电池经电源路径后的电压；插 USB 后，SYS 是充电电源路径输出，不能据此准确计算电池电量。高阻分压也更易受输入漏电及采样扰动影响。

**建议：** 若只监测系统欠压，可保留；若要电池电量读数，应采样 VBAT，并核实保护断开、主控掉电时是否会经 ADC 反向供电。不要只把标签改名就认为测量节点已变。

资料：[ESP32-C3_datasheet.pdf](datasheets/ESP32-C3_datasheet.pdf)；[ETA6002_V1.5.pdf](datasheets/ETA6002_V1.5.pdf)；[ESP32-C3-MINI-1_datasheet_cn.pdf](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf)

### 中 · 输出电容待核实 · U3：模块入口电容仍属于 3V3 输出负载

**观察与依据：** U3 数据手册建议有效输出电容 1–10µF。3V3 上 C2=1µF、C16=10µF、C13=100nF、C3=100nF，名义总量约 11.2µF；不是只看 U3 旁边的 C2。

**影响：** MLCC 的 DC 偏压、容差及各电容的布局会改变有效电容。仅凭名义总值不能断言稳定，也不能直接判定超过手册范围；仍需实际器件曲线和负载瞬态验证。

**建议：** 保留 H4X 的 10µF + 100nF 入口旁路需求；核算各电容在 3.3V 下的有效值，并验证上电、Wi-Fi 发射和音频负载阶跃。如不满足 U3 稳定范围，调整电源器件或旁路方案。

资料：[ETA5060_V2.6.pdf](datasheets/ETA5060_V2.6.pdf)；[ESP32-C3-MINI-1_datasheet_cn.pdf](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf)

### 中 · PCB 待核实 · H4X 板载天线：仍需母板与外壳避让

**观察与依据：** 模块已集成 40MHz 晶振、RF 匹配与 PCB 天线。母板不再设置 Y1、L2、L3、C17、C18、C20、C21 或 J4；既有外部天线调试条目已退出当前检查清单。

**影响：** 模块天线的效果仍受母板铜、走线、元件、电池、喇叭及外壳影响。原理图 DRC 通过不能证明天线布局合格；本轮没有检查 PCB。

**建议：** 按 MINI-1 封装与硬件指南将天线放到合适板边位置，核对天线区各层铜/走线/元件净空，并考虑外壳各方向建议至少 15mm 避让。靠近模组非天线侧布置去耦和接地回路，完成整机射频测试。

资料：[ESP32-C3-MINI-1_datasheet_cn.pdf](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf)；[ESP32-C3_hardware_guidelines.pdf](datasheets/ESP32-C3_hardware_guidelines.pdf)

USB 电流档位补充依据：[Espressif USB Type-C 硬件指南](https://docs.espressif.com/projects/esp-iot-solution/en/latest/usb/usb_overview/usb_typec_hardware_guide.html)。

## 已核对、未发现明显接反的部分

### U1 H4X 模块

3V3 接焊盘 3，EN 接焊盘 8 / CHIP_EN；GND 焊盘 1、2、11、14、36–53 全部接系统地，共 22 个。53 脚中 38 脚已连接、15 脚明确 NC（包括未使用的 GPIO0 / 焊盘 12）。模块内部已有 Flash、晶振、射频匹配及板载天线；母板无需外置 Flash 或重复这些外围。C13=100nF、C16=10µF 保留作模块入口旁路；PCB 距离与回路尚待验证。

### 复位 / 启动

R9=10kΩ、C15=1µF 和 SW2 接地复位符合常见参考连接。GPIO9 有 R12 上拉和 SW3 下拉下载；GPIO2 有 R10 上拉，GPIO8 有 R11 上拉。D3 由 GPIO8 低电平点亮，未发现把启动脚硬拉低。下载时按住 GPIO9 按键再复位。

### U2 充电

8 脚 IN 接 VBUS_CHG；1 脚 SW 经 2.2µH L1 接 SYS / 7 脚；6 脚 BATT 接 VBAT；C6=10µF、C7=22µF、C8=1µF 分别用于输入、SYS、BAT；PGND 与 EP 接系统地。保存重开后的回读及连接检查确认 IN 与 SYS 未短接，1930/1510 为无接点正交交叉。STAT 不接仅意味着未使用充电状态输出。

### U3 主 LDO

4 脚 IN 与 3 脚 EN 接 SYS，2 脚 GND 接地，5 脚 OUT 接 3V3，1 脚 NC 不接。V330 为固定 3.3V 版本，不需要照抄可调版的反馈电阻。C1 接输入与地，C2 接输出与地，网表确认输入没有直接接地。

### U4 麦克风

WS、SCK、SD、VDD、GND 与对应信号一致；C3=100nF 和 R1=100kΩ SD 下拉符合参考，R1 应保留。LR 接地选择左声道。

### U5 / U7 功放

NS4168 的 VOP8、VON5 分别到 J3 的 SPK_P / SPK_N；扬声器跨接两端，无一端直接接地。GND7 与 EP9 接地，VDD6 接 3V3_AMP。C4=1µF 与 C5=100µF 在电源对地并联，符合功放旁路建议；C5 不是扬声器串联耦合电容。U7 的 1/2/3/4/5 脚定义与 DBV 手册一致。 U7 的 EN3 与 IN1 均接 SYS，OUT5 接 3V3_AMP；AMP_CTRL 控制 U5，而不控制 U7 使能。

### U6 / Q1 电池保护

电芯负极 J2.2 为 BAT_N，系统/USB 地为 GND；U6 GND6 接 BAT_N，VCC5 由 VBAT 经 R16=100Ω 供电，C22 回 BAT_N，VM/CS2 经 R17=1kΩ 接系统地。OD1→G1/4，OC3→G2/5；Q1 S1/2,3 接 BAT_N，S2/6,7 接 GND，方向与共漏极保护结构相符。Fortune FS8205A 的 D12/1,8 在器件内部共用，外部未接不等于两 MOS 断开；Q1 实际供应商身份已确认为 FORTUNE / C16052；U6 为 PUOLOP / C351410，电气阈值仍待该厂商手册确认。不要把 BAT_N 与 GND 直接短接。

### USB / 测试点

J1 的重复 D+ 同网、重复 D− 同网，R6/R7=33Ω 分别进入 GPIO19 / D+ 与 GPIO18 / D−；R4/R5 各自 5.1kΩ 接地，未把 CC1/CC2 并在一起；双向 ESD 保护接在数据线与地之间。UART RX/TX 测试点对应 模块焊盘 30/31，外接串口需使用 3.3V 电平。

## 冗余与可选优化

- **R8=0Ω：** 功能上可去掉并直连；作为断电调试、串接电流表或后期替换器件的位置则有用。
- **U7 第二路 3.3V LDO：** 不是必然冗余：它能分开功放电流扰动。只有在共用电源电流、发热和噪声均满足要求时才考虑合并；目前 EN 接 SYS，无法通过 MCU 单独关闭 U7，自身静态电流一直存在。
- **R10 / R11 / R12 启动上拉：** GPIO9 虽有内部上拉，外部上拉仍有启动可靠性价值；GPIO2 和 GPIO8 的上拉也服务启动状态，不建议为省件直接删除。
- **R1 麦克风 SD 下拉：** 不是冗余，麦克风非有效时隙会三态；参考图明确使用下拉。
- **模块旁路 C13 / C16：** 保留 100nF + 10µF 入口旁路。原裸芯片 C9/C10/C11/C12/C14 已移除，不能继续按独立芯片的供电脚要求添加回去；U3 输出有效电容另列待核实项。
- **U6 / Q1：** 若使用裸电芯，应保留保护；若电池包自带保护，可能形成重复保护，但是否能省必须核对电池包保护规格和产品要求。
- **电源开关功能：** 图中 U3 / U7 的 EN 都接 SYS，按键均用于复位、下载或 GPIO 输入；未看到独立硬件总电源开关。如果需要真正关机，应另外设计，REC_KEY 本身无法断开整板供电。

## 主控信号映射

| 网络 | U1 模块焊盘 | GPIO / 功能 |
|---|---|---|
| SYS_ADC | 13 | GPIO1 / ADC1_CH1 |
| BOOT_GPIO2 | 5 | GPIO2 |
| CHIP_EN | 8 | EN / 复位使能 |
| REC_KEY | 6 | GPIO3 |
| I2S_BCLK | 18 | GPIO4 / MTMS |
| I2S_WS | 19 | GPIO5 / MTDI |
| MIC_SD | 20 | GPIO6 / MTCK，主控输入 |
| AMP_DIN | 21 | GPIO7 / MTDO，主控输出 |
| LED_GPIO8 | 22 | GPIO8，低电平亮 |
| BOOT_GPIO9 | 23 | GPIO9 |
| AMP_CTRL | 16 | GPIO10 |
| USB_DM | 26 | GPIO18 / D− |
| USB_DP | 27 | GPIO19 / D+ |
| UART_RX | 30 | GPIO20 / U0RXD |
| UART_TX | 31 | GPIO21 / U0TXD |

## 参考电路截图

截图保留厂商原图，未重画。FS8205A 和 ESD 手册没有独立完整应用电路，已明确标记为引脚/内部结构图。

### U1 · H4X 模组引脚布局
v2.2 / PDF 第 10 页，图 3-1。53 个焊盘；此图为顶视图，PCB 底视方向需另核对。

![U1 · H4X 模组引脚布局](reference_circuits/01_H4X_pinout.png)

[打开来源 PDF 第 10 页](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf#page=10)

### U1 · 模组内部原理图
v2.2 / PDF 第 32 页，图 8-1。晶振、射频匹配及板载天线属于模组内部，不在母板重复添加。

![U1 · 模组内部原理图](reference_circuits/02_H4X_internal.png)

[打开来源 PDF 第 32 页](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf#page=32)

### U1 · 模组外围设计原理图
v2.2 / PDF 第 34 页，图 9-1。外围保留 3V3 去耦、EN RC 和启动配置；测试接口与可选元件按本板需要采用。

![U1 · 模组外围设计原理图](reference_circuits/03_H4X_external.png)

[打开来源 PDF 第 34 页](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf#page=34)

### U1 · 模组封装与天线区域
v2.2 / PDF 第 38 页，图 11-1。H4X 使用 MINI-1 板载 PCB 天线版；不能套用 MINI-1U 外接天线版封装。

![U1 · 模组封装与天线区域](reference_circuits/14_H4X_footprint.png)

[打开来源 PDF 第 38 页](datasheets/ESP32-C3-MINI-1_datasheet_cn.pdf#page=38)

### U1 · 模组天线布局避让参考
已归档硬件指南 / PDF 第 26 页，Fig. 21。母板铜、走线和元件避让按实际天线朝向核对；整机外壳附近各方向建议至少 15 mm 净空。此图不是本板 PCB 已通过验收的证明。

![U1 · 模组天线布局避让参考](reference_circuits/15_H4X_antenna_keepout.png)

[打开来源 PDF 第 26 页](datasheets/ESP32-C3_hardware_guidelines.pdf#page=26)

### U2 · 充电与电源路径参考电路
PDF 第 1 页，Typical Application。你的 ISET 电阻不同，设置约 402mA。

![U2 · 充电与电源路径参考电路](reference_circuits/04_ETA6002_charger.png)

[打开来源 PDF 第 1 页](datasheets/ETA6002_V1.5.pdf#page=1)

### U3 · 3.3V LDO 参考电路
PDF 第 1 页。图中反馈分压用于可调版本，固定 3.3V 版本无需这些电阻。

![U3 · 3.3V LDO 参考电路](reference_circuits/05_ETA5060_LDO.png)

[打开来源 PDF 第 1 页](datasheets/ETA5060_V2.6.pdf#page=1)

### U4 · I²S 麦克风系统参考电路
PDF 第 13 页，Fig. 8。图含左右两颗麦克风，你的板只采用左侧通道。

![U4 · I²S 麦克风系统参考电路](reference_circuits/06_ICS-43434_system.png)

[打开来源 PDF 第 13 页](datasheets/ICS-43434_V1.2.pdf#page=13)

### U5 · 功放典型应用电路
PDF 第 1 页。100µF 与 1µF 电容均为电源并联旁路。

![U5 · 功放典型应用电路](reference_circuits/07_NS4168_amplifier.png)

[打开来源 PDF 第 1 页](datasheets/NS4168_V1.2.pdf#page=1)

### U5 · 输出 EMI 处理参考电路
PDF 第 9 页，10.6。磁珠与电容用于 EMI 处理，是否需要取决于走线和实际测试。

![U5 · 输出 EMI 处理参考电路](reference_circuits/08_NS4168_EMI.png)

[打开来源 PDF 第 9 页](datasheets/NS4168_V1.2.pdf#page=9)

### U6 · 电池保护拓扑参考（Fortune，同名异厂）
PDF 第 5 页，Section 8。现装 U6 为 PUOLOP(迪浦) DW01A / C351410；本图仅作共漏极保护拓扑类比，电压阈值及电气参数不能替代实际型号手册。图中 BATT− 是受保护端。

![U6 · 电池保护拓扑参考（Fortune，同名异厂）](reference_circuits/09_DW01A_protection.png)

[打开来源 PDF 第 5 页](datasheets/DW01A_V1.2.pdf#page=5)

### Q1 · 双 MOS 管引脚与内部连接
PDF 第 3 页，Section 4。此图为引脚及内部电路，手册未提供独立应用电路。

![Q1 · 双 MOS 管引脚与内部连接](reference_circuits/10_FS8205A_pinout.png)

[打开来源 PDF 第 3 页](datasheets/FS8205A_V1.2.pdf#page=3)

### U7 · 功放 LDO 典型应用电路
PDF 第 19 页，Fig. 7-4。原图示例输出为 1.8V；你的 33 型号固定输出 3.3V。

![U7 · 功放 LDO 典型应用电路](reference_circuits/11_TLV757P_LDO.png)

[打开来源 PDF 第 19 页](datasheets/TLV757P.pdf#page=19)

### U5 · CTRL 声道选择依据
PDF 第 8 页，10.2.4 / 表 3。为检查声道兼容性额外截取。

![U5 · CTRL 声道选择依据](reference_circuits/12_NS4168_channel.png)

[打开来源 PDF 第 8 页](datasheets/NS4168_V1.2.pdf#page=8)

### D1 / D2 · ESD 二极管内部连接
PDF 第 2 页，Section 5。手册未提供完整 USB 应用电路；这里是双向保护结构。

![D1 / D2 · ESD 二极管内部连接](reference_circuits/13_ESD_pinout.png)

[打开来源 PDF 第 2 页](datasheets/SEUCS2X3V1B_V1.2.pdf#page=2)

## 资料来源

- [ESP32-C3_datasheet.pdf](https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf)
- [ESP32-C3_hardware_guidelines.pdf](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/esp-hardware-design-guidelines-en-master-esp32c3.pdf)
- [ETA6002_V1.5.pdf](https://www.eta-semi.com/wp-content/uploads/2022/03/ETA6002_V1.5.pdf)
- [ETA5060_V2.6.pdf](https://www.eta-semi.com/wp-content/uploads/2022/03/ETA5060-V2.6.pdf)
- [ICS-43434_V1.2.pdf](https://admin-uat.invensense.com/sites/default/files/2026-01/DS-000069-ICS-43434-v1.2.pdf)
- [TLV757P.pdf](https://www.ti.com/lit/ds/symlink/tlv757p.pdf)
- [DW01A_V1.2.pdf](https://www.ic-fortune.com/upload/Download/DW01A-DS-12_EN.pdf)
- [FS8205A_V1.2.pdf](https://www.ic-fortune.com/upload/Download/FS8205A-DS-12_EN.pdf)
- [NS4168_V1.2.pdf](https://pdf.data.kynix.com/r/datasheets/04aba3168248e67c38dd0a24fbd44cbd.pdf)
- [SEUCS2X3V1B_V1.2.pdf](https://atta.szlcsc.com/upload/public/pdf/source/20250407/EA40EA94A290EAC09D1BCCC9775D7FD6.pdf)
- [ESP32-C3-MINI-1_datasheet_cn.pdf](https://www.espressif.com/sites/default/files/documentation/esp32-c3-mini-1_datasheet_cn.pdf)