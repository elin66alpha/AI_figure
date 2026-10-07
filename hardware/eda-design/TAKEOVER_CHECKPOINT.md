# 原理图进度与待完成项

## 最新有效检查点：30×50 PCB 布局定稿，待布线（2026-10-07）

原理图按 PCB 尺寸收紧做了一轮改动，PCB 布局完成。尚未布线和铺铜。布线交接见 `PCB_ROUTING_HANDOFF_2026-10-07.md`。

**原理图改动**（相对 10-06 检查点，均已逐脚对比网表，只有计划内变化）
- **J1：** TYPE-C-31-M-12 卧式改为 SHOU HAN TYPE-C 16PLT-H6.5 立贴（C3151748）。新符号 A/B 面引脚分开，SHELL 为单独引脚，已全部重连。SBU1/SBU2 NC。
- **L1：** FXL0618 改为 FXL0420-2R2-M（C167206）。
- **C5：** 100 µF 电解改为 CL31A107MQHNNNE 1206 MLCC（C15008）。符号引脚长度不同，已旋转并重连。
- **电池保护：** 删除 U6/Q1/R16/R17/C22 及其网络（BAT_N、BP_OD、BP_OC、$1N347、$1N349），J2.2 改接 GND。顺带清掉了 (1425,1430) 处重复的 GND 旗。
- **按键：** SW2/SW3 改为 TP1（CHIP_EN）、TP2（GND）、TP3（BOOT_GPIO9）。器件为系统库 `T-1.6x1.6x0.5`，2 mm 方焊盘，`addIntoBom=false`。本条取代 10-06"用户不需要任何测试焊盘"。
- **R3：** 2.49 kΩ 改为 3.0 kΩ（C25784），用于 500 mAh 电池。
- **用户自行删除：** H1（UART 排针）、SCREW1–5，并将 U1 焊盘 30/31（TXD0/RXD0）标 NC。之后试加的 3 颗 M2 螺丝也已按用户要求从原理图和 PCB 删除。
- **当前状态：** 48 个器件。sch check 只剩 J4 两条出脚方向错误（历史遗留，不影响连接）；bridge-check 0，原生 DRC 0。

**PCB 布局**
- **板子：** 30×50 mm，两层。
  - 正面 10 个：U1（天线朝上，左上角）、U4 麦克风、D3、C2/C3/C15/R9、J2/J3/J4。
  - 背面 38 个：J1 居中 (15, 34)、充电、两个 LDO、功放、USB 保护、上下拉电阻、TP1–TP3。
- **禁布区：** 天线（所有层）、麦克风 Ø10 圈（正面）、电池 30×30.5（正面）三个 region 已建好。
- **器件朝向：** 每个元件都按"连接焊盘朝向目标引脚"做了 0°/180° 优化。
  - 电感到充电芯片 SW/SYS 脚 3.7 / 5.0 mm，输入电容到 IN 脚 2.4 mm。
  - USB 串联电阻到模块约 2 mm，ESD 在 J1 上方的 D+/D− 直线通道上。
- **检查：** 保存、重新加载后回读，48/48 器件位置一致；无重叠、无出板、无区域违规。
- **DRC：** 除 173 个未连接外，只剩 1 条原因不明的"原理图/PCB 网表不一致"提示（逐焊盘对比 0 差异）。

**文件**
- 定稿存档 `AI_figure_30x50_placed_2026-10-07.epro2`（ZIP 已核验）。
- 布局图 `AI_figure_30x50_placed_top/bottom_2026-10-07.png`。
- BOM `../BOM/BOM_30x50_2026-10-07.csv`（原生导出，26 行）。
- 过程数据和逐步备份在 `pcb-30x50-20261007/`（`backup-before-*.epro2`）。

**未关闭风险**
- 电池离天线约 14 mm，需实测 WiFi。
- J1 定位脚会从电池下方冒出，装配需剪平并绝缘。
- 2.54 排针约 8.5 mm 高，高于电池。
- R3 = 3.0 kΩ 对应的充电电流需实测。
- 充电芯片电感离麦克风较远，但仍建议实测录音底噪。

## 历史检查点：麦克风改 PDM（2026-10-06）

用户确认把 I2S 麦克风换成 PDM 数字麦克风，芯片仍用 ESP32-C3（ESP-IDF ≥5.5 支持 C3 PDM RX 原始格式，PDM→PCM 需软件抽取滤波；生产固件改用 ESP-IDF 6.1）。

- U4 由 ICS-43434（C5656610）换为 LinkMems LMD2718T261-OA1（C5373237，顶部进声 2.8×1.9 mm，-26 dBFS / 58 dBA，1.62–3.6 V，标准模式时钟 1.3–4.8 MHz）。用户选择顶部进声：PCB 不开声孔，声孔开在外壳上，需要密封垫。
- 引脚（手册 p.7）：1/3 GND、2 L/R → GND（左声道）、4 VDD → 3V3（C3 100 nF 实线就近）、5 DATA → MIC_DATA、6 CLK → MIC_CLK。
- MIC_CLK = GPIO6（焊盘 20，原 MIC_SD）；MIC_DATA = GPIO0（焊盘 12，原 NC）+ R1 100 kΩ 下拉。I2S_BCLK/I2S_WS 只剩 U1 与 NS4168。PCB 时 MIC_DATA 与焊盘 13 的 SYS_ADC 相邻，注意隔离。
- U1 焊盘 11 的 GND 旗左移，为 MIC_DATA 端口让位；C3 的 GND 旗上移，避免文字压在 MIC_DATA 线上。
- 回读：48 个器件；逐脚网表与改前对比只有上述计划内变化。bridge-check 0；原生 DRC 0 fatal / 0 error / 2 warn（无明细）；sch check 剩 6 条均为本次改动前已存在（C1 两条出脚方向、VBAT/GND 两面旗方向、两处 GND 与 SPK_P 视觉重叠）。
- 同日第二轮（用户要求）：
  - 加回 GPIO8 状态灯：3V3 → R13 330 Ω（C25104）→ D3 红灯（C2986060）→ LED_GPIO8 = IO8，R11 10 kΩ（C25744）上拉，低电平点亮。GPIO8 的启动电平因此确定为高。
  - 新增 D4 SMF5.0A（JSMSEMI C2857263，SOD-123FL）：负极接 VBUS_CHG（保险丝 F1 之后），正极接 GND。注意：ETA6002 的 IN 脚绝对最大 6 V，而 TVS 击穿电压 ≥6.4 V，所以它只防浪涌/ESD，不能把电压精确限在 6 V 以下。
  - 刷写和日志都走 USB-Serial-JTAG，所以删除 UART_RX/UART_TX 标签，U1 焊盘 30/31 标 NC。用户不需要任何测试焊盘。
  - 修图面：C1 改为上下出线；U5 GND/EP 合并成一面向下的 GND 旗；VBAT 旗、Q1 的 GND 旗方向改正；删除 U1 焊盘 11 一面延迟落地的重复 GND 旗。
- 最终结果：52 个器件；sch check 0、bridge-check 0、原生 DRC 0（含警告）、layout-lint 0。clusters --strict 仍有 5 条间距告警（R4↔R5、J1↔R7、R17/R16/C22 与 U6），都是本次改动前就有的。网表与第一轮相比只有上述计划内变化。
- 待手动：功能框标题 "I2S Microphone / Amplifier / Speaker" 改为 PDM，"Battery Charger / Power Switch" 改为 Protection（无 typed 文字修改接口）。固件需改 PDM RX + 软件抽取。
- 改前备份 `pdm-20261006/backup-before-PDM-20261006.epro2`；最终 `AI_figure_PDM_2026-10-06.epro2`（ZIP 完整性已核验），预览 `AI_figure_PDM_2026-10-06.png`，BOM `../BOM/BOM_PDM_2026-10-06.csv`（原生导出）；过程数据在 `pdm-20261006/`。

## 历史检查点：现货替换与 0402（2026-10-05）

用户要求低成本、外围少、现货，大多数电阻电容用 0402；容量、耐压等需要时允许 0603/0805 或更大。按用户选择暂留现用 ICS-43434，低价 Knowles 候选无现货，未替换麦克风。

- Q1 改为台舟 8205A / C7419210。共漏极双 N-MOS、TSSOP-8；2/3→BAT_N，4→BP_OD，5→BP_OC，6/7→GND，1/8 不外接。RDS(on) 不同可能改变实际过流触发电流，须样机验证。
- 18 个电阻全部换成 0402，阻值保持；缺货的 33Ω、100Ω、1kΩ 厚声候选改用现货国巨 C138002、C106232、C106235。
- C3/C13/C19/C22：100nF/16V/X7R/0402 C1525；C2/C15：1µF/25V/X5R/0402 C52923；C4/C8/C23：2.2µF/25V/X5R/0402 C307418，为直流偏压造成的容量下降留余量。
- C1/C6/C16：10µF/25V/X5R/0805 C19103847，原 C15850 无现货；C7 22µF/0805 和 C5 100µF 铝电解沿用。共 27/32 个电阻电容为 0402。
- 保存、关闭重开、回读核对通过：57 个器件、51 个采购实例、31 个实例更换料号；逐器件网络对账通过。原生 BOM 与采购 CSV 的每个位号、料号、型号、封装、数值和数量一致。
- 最终 gate PASS；布局/分组/bridge 检查 0 错误，原生 DRC 0 fatal、0 error、2 warning（接口无告警详情）。连接检查含 C13/C16 无极性 MLCC 引脚方向提示和一处已验证无接点交叉信息，未声称全零告警。
- 原生工程 `AI_figure_0402_2026-10-05.epro2` 已导出并核验 ZIP 完整性（未另建工程验证恢复），预览为同名 PNG。采购表 `../BOM/BOM_0402_2026-10-05.csv`；选型、价格、数据手册和限制见 `../BOM/Cost_Reduction_2026-10-05.md`；证据目录 `cost-reduction-20261004/`。
- 未开始 PCB；下一步先由用户确认原理图，再进入 PCB。实物保护阈值、电源稳定性和温升尚未验证。

## 历史检查点：H4X 模块替换（2026-10-04）

用户明确要求使用已打开的 EasyEDA 桌面版；通过 typed CLI / Connector 完成 AI_figure / P1 修改，未操作 PCB 或固件。

- U1 改为 ESP32-C3-MINI-1-H4X / C41349510，封装 WIFIM-SMD_ESP32-C3-MINI-1；保留 gge1 关联，新 primitiveId `82e405d617046e35`。
- 删除 Y1、C17、C18、L2、L3、C20、C21、J4，以及 C9–C12、C14。保留 C13 100 nF + C16 10 µF 模块入口去耦、EN RC、全部 GPIO 和外部接口。
- 57 个器件；保存并重开后，53 个模块引脚按官方表核对（38 连接、15 NC、22 GND）；其余 56 个器件和 154 个引脚保持原样。
- 官方严格 DRC 全部 0；bridge-check 全部 0；sch check 仅有原充电区一条已验证无接点交叉信息。严格器件布局检查和功能框回读通过。
- 更新 MCU / 控制区标题，移除空的外部晶振框及旧晶振功能组。电源架构仍以 10-01 检查点为准。
- 改前备份 `backup-before-H4X-20261004.epro2`；最终工程 `AI_figure-P1-H4X-20261004.epro2`（ZIP 完整性已核验）；预览 `P1-H4X-schematic-20261004.png`；详情见 `H4X_REPLACEMENT_REPORT_20261004.md`。
- 后续 PCB 须用模块封装和板载天线布局约束；本轮未开始 PCB。

## 电源架构检查点：返修（2026-10-01）

用户确认后按数据手册返修电源，取代下方 09-29 检查点中的电源部分。仍未进入 PCB。

- 去掉拨动开关 SW1（SYS_SW 并入 SYS）。整机常通电，靠 ESP32 深睡 + REC_KEY（GPIO3，可做深睡唤醒）开关机。
- 新增电池保护：U6 DW01A（C351410）+ Q1 FS8205A（C16052）。R16 100Ω/C22 100nF 接 VCC，R17 1kΩ 接 VM。J2 负极改为 BAT_N；Q1 的 D12 和 U6 的 TD 标 NC。
- 功放独立供电：U7 TLV75733PDBVR（C485517，Cout 1–200µF，Iq 25µA），SYS → 3V3_AMP，接 C23 1µF 输入、C4 1µF + C5 100µF 输出和 NS4168 VDD。
- ESP32 3V3（U3 ETA5060，手册 Cout 1–10µF）：C2 改为 1µF，网络上标称约 11.6µF，DC 偏压后有效值在范围内。
- 新增 R18 100k 作 REC_KEY 上拉；R14/R15 改为 1MΩ（分压静态电流约 2µA）。
- 检查结果：官方 DRC 0；sch check 只有 1 条已验证的 info 级无接点交叉；bridge-check 0。逐引脚网表对账只有计划内改动，共 70 个器件。
- 证据：`P1-A2-power-rework-20261001.png`、`AI_figure-P1-power-rework-20261001.epro2`；改前备份 `backup-before-power-rework-20261001.epro2`。
- 未完成：电池区标题仍是 "Battery Charger / Power Switch"，没有可用的类型化文字修改接口，需手动改为 "Battery Charger / Protection"。
- 本轮未做：VDD3P3 的 LC 滤波、VBUS 过压保护；固件端的深睡唤醒、醒来先录音缓冲、睡眠前把 GPIO4/5 拉低。
- 注意：EasyEDA 窗口最小化时 `sch wire` 会返回 "create failed!"，需先把窗口恢复到前台。

## 检查点：P1 单页 / DRC 清零（2026-09-29 20:46 本地）

本节取代下方历史状态。具体证据见 `SINGLE_SHEET_REPAIR_REPORT.md`。

- 仅一张 P1，用户已扩为横向 A2；Power and USB 全部迁入，旧第二页删除。
- 已完成模块重排、全部连线重建、RF 接线、标签整理和功能框。
- 63 个器件、190 个引脚对账通过；官方严格 DRC 为 0 错误/0 警告/0 信息；sch check 全部 0；bridge-check 全部 0。
- TP1–TP6 为 UART_RX、UART_TX、GND、CHIP_EN、BOOT_GPIO9、3V3 实体测试焊盘（不计采购 BOM）。
- 用户已授权采用标准库等效电感，L1 现为 FXL0618-2R2-M / C524593，保留 gge16 关联。旧自建 L1 和重复 L4 均不在图中。
- 最新保存已确认，原生备份 `AI_figure-P1-A2-DRC0.epro2`，整页预览 `P1-A2-schematic-final.png`。
- 自动重开曾失败；用户恢复连接后成功回读，随后换 L1 并再次保存/核对/导出。不要反复自动重开诱发宿主断连。
- 本轮未操作 PCB。PCB 前仍需用户确认。历史功能风险（共享 LDO 电容/热、麦克风保证电平、USB 功率预算、电池插头极性、RF 实测调谐）仍未以实物关闭；DRC 清零不是生产定版。
- SW1 库原点不在其引脚网格上，anchor 2190,1249 是有意补偿；实际引脚均落在 5 raw 格点。不要按通用 anchor lint 把它移回 y1250，否则会重引入原生 DRC 的偏格警告。

## 以下为历史过程，不代表最新工程

2026-09-29 当前仅原理图，未操作 PCB。

## 已实际写入
- ESP32 供电脚、CPU 100nF、VDD_SPI 1uF、其余去耦组。
- EN 10k + 1uF + RESET；GPIO2/8/9 上拉；BOOT 按键。
- GPIO8 LED 330Ω 串联电阻与独立 10k 上拉。
- GPIO3 录音键到地。
- 40MHz 晶振、2×15pF 初始负载电容、XTAL_P 串联 24nH。负载电容与电感为调试起点。
- ETA6002 的 SW→2.2uH→SYS，输入10uF、SYS22uF、电池1uF、2.49k ISET、NTC接地、PGND/AGND接地。
- 电池插座、SYS 电源开关、USB-C 两独立 CC 下拉、D+/D-、ESD、33Ω 串阻、保险丝与0Ω充电连接位。
- SYS_SW 的2×100k分压与100nF滤波，SYS_ADC连接GPIO1。
- 喇叭J3接口及ESP32 USB/UART端口。

## 已核查
- U3 ETA5060、U4 ICS43434、U5 NS4168 所有功能引脚回读与当前设计一致。
- 充电页 bridge-check：0跨网短接、0悬空线树/标记（ADC加入后、后续未再修改该页）。
- working-main-with-crystal.json：晶振所有功能端与地端网络确认。
- working-charger-verified.json：ETA6002及其所有外围网络确认。

## 必须继续完成，不能称为生产定版
- RF匹配及U.FL：初始选型LQP03TN2N4B02D 2.4nH、GRM0335C1H1R5BA01D 1.5pF、U.FL-R-SMT-1(01)，尚未完成连线。
- L3放置接口出现partial，返回两个零长度线ID 91847556658a18b0、50549fe80de0f5bb；先检查working-rf-read2.json结果再进行任何重试/清理。
- VDD3P3模拟供电LC、实体测试点、最终布局/文字去重/功能框。
- 两页全量ERC、bridge-check、网络对账、保存持久化与最终PNG。
- 既有风险仍未闭合：共享LDO大电容稳定性与热耗散、麦克风保证电平、USB输入限制、电池插头实际极性、L1自定义封装、外置天线线缆及RF调谐。

## 手册依据
- https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/schematic-checklist.html
- https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf
- https://datasheet.lcsc.com/datasheet/pdf/8efad5a1e38bfd1767a78dc3ee3fef7c.pdf?productCode=C7436031
- https://docs.rs-online.com/6b57/0900766b814fc195.pdf （Murata厂家PDF镜像，LQP03TN2N4B02D）
- https://www.hirose.com/product/download/?distributor=all&lang=en&series=U.FL&type=catalogue

## 最后状态（23:57 UTC）
- L3、C20、C21、J4 已放置，尚未接 RF 网络。L3 两段零长度异常线已删除并继续放置成功。
- 最新主图保存返回 saved:true，时间 2026-09-29T23:56:43Z，证据 working-latest-save.json。
- working-rf-pins2.json 虽 ok:true，但全部器件 netlistAvailable:false，netlistError="netlist export returned no file"；不得将 null 网络当未连接或据此删除重建。
- 原理图PNG导出随后 connector did not respond；working-main.png 是19:43检查点预览，不含后续USB/ADC/喇叭/RF改动，不能称最终图。
- 依 EasyEDA skill 的持续回读失败规则停止现场写入，保留原始对象。恢复连接/网表读取之后，从引脚快照核对继续；不要整份重跑已完成playbook。
