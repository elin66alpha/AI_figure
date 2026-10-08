# H4X 原理图替换记录

状态：live-verified。2026-10-04 本地日期，使用用户指定的嘉立创 EDA 桌面版 4.1.60，通过 EasyEDA typed 连接器修改 AI_figure / P1。CLI / daemon v1.8.1，Connector 1.8.0。

## 修改结果

- U1：ESP32-C3FH4 / C2858491 → ESP32-C3-MINI-1-H4X / C41349510。
- U1 保留位号、位置和 sch↔PCB 关联 `uniqueId=gge1`；新实例 ID 为 `82e405d617046e35`。模块封装绑定为 `WIFIM-SMD_ESP32-C3-MINI-1`。
- 删除模块已集成的外围：Y1、C17、C18、L2、L3、C20、C21、J4。
- 删除裸芯片专属或多余去耦：C9、C10、C11、C12、C14。保留 C13 100 nF 和 C16 10 µF 作为模块入口去耦，收短原电容母线。
- 保留 EN 的 RC 和复位键、GPIO2/8/9 启动配置、录音键及上拉、LED、USB/UART、I2S 和 SYS_ADC 滤波。
- 删除空的外部晶振框及功能组，更新 MCU 与控制区标题。
- 器件数由 70 减为 57。本轮仅修改原理图；未修改 PCB 或固件。

## 模块引脚与既有软件保持对应

| 用途 | GPIO | 模块焊盘 | 网络 |
|---|---:|---:|---|
| 电池采样 | 1 | 13 | SYS_ADC |
| 启动配置 | 2 | 5 | BOOT_GPIO2 |
| 录音键 | 3 | 6 | REC_KEY |
| I2S 时钟 | 4 | 18 | I2S_BCLK |
| I2S 字选择 | 5 | 19 | I2S_WS |
| 麦克风数据 | 6 | 20 | MIC_SD |
| 功放数据 | 7 | 21 | AMP_DIN |
| LED / 启动配置 | 8 | 22 | LED_GPIO8 |
| BOOT | 9 | 23 | BOOT_GPIO9 |
| 功放控制 | 10 | 16 | AMP_CTRL |
| USB D− | 18 | 26 | USB_DM |
| USB D+ | 19 | 27 | USB_DP |
| UART RX | 20 | 30 | UART_RX |
| UART TX | 21 | 31 | UART_TX |

3V3 接焊盘 3，EN 接焊盘 8 / CHIP_EN。22 个接地焊盘 1、2、11、14、36–53 全部接 GND；右侧 36–53 使用一条接地母线。14 个内部 NC 焊盘及未使用的 GPIO0（焊盘 12）明确标 NC。

引脚和集成外围依据：[乐鑫模组技术规格书 v2.2](https://documentation.espressif.com/esp32-c3-mini-1_datasheet_cn.html)。库身份来源：`h4x-library-20261004.json`、`h4x-device-20261004.json`。

## 保存后的检查

已完成显式保存 → typed 关闭并重开 P1 → fresh 引脚/器件/导线回读，并在重开后核对：

- 官方严格 DRC：致命错误、错误、警告、信息均为 0。证据 `h4x-final-drc.json`。
- `sch check`：无警告/错误；只有原电池充电区的一处已验证无接点交叉信息。证据 `h4x-final-check.json`。
- `bridge-check`：0 短接、0 孤立线树、0 悬空标记。证据 `h4x-final-bridge.json`。
- 严格布局检查：57 个器件全部有实测 bbox / pins，0 重叠、0 偏格、0 引脚重合、0 出图纸。功能框回读通过。
- 逐引脚意图审计：模块 53 脚（38 连接、15 NC、其中 22 GND）全部符合计划；其余 56 个器件的身份、属性、位姿及 154 个引脚连接/NC 保持不变。证据 `h4x-pin-intent-audit.json`。

最初出现的 4 条官方警告已修复：三条源于分支导线重复写入同名 Name 属性，现由每棵线树的单一电源/地符号命名；一条源于 U1 的 Name 与供应商库默认值不符，已恢复库值。

## 交付文件

- 修改前备份：`backup-before-H4X-20261004.epro2`，ZIP 完整性已核验。
- 整页原生预览：`P1-H4X-schematic-20261004.png`。
- 原生工程导出：`AI_figure-P1-H4X-20261004.epro2`，229,777 字节，ZIP 完整性已核验；SHA-256 `7983540ed684ee64ad47a883d4e9edd1c04d4744f93f592af11cd6e3f0ca5cd7`。未另行导入此归档进行恢复测试，当前 P1 的保存重开回读已通过。
- 可追踪参数：`h4x-migration-plan-20261004.json`、`h4x-cleanup.playbook.json`、`h4x-buses.playbook.json`、`h4x-signal-connections.json`、`h4x-drc-fix.playbook.json`、`h4x-frames.json`。

规划和中途失败的读取文件保留为过程证据；完整图元属性快照曾因原生属性导出超时失败，未用于最终判断。最终判断使用成功的 fresh 回读、原生工程导出和上述专项检查。以上检查验证原理图与保存状态，不替代实板射频、电源和天线布局验证。
