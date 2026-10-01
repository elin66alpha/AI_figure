# 原理图进度与待完成项

## 最新有效检查点：P1 单页 / DRC 清零（2026-09-29 20:46 本地）

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
