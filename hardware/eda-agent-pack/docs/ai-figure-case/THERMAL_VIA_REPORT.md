# U2 / U5 焊盘外侧盖油散热过孔检查点

用户于 2026-10-06（美东）确认：普通双层工艺、两面盖油、焊盘外侧过孔，无填孔电镀。继续使用本机 PowerShell 7.6.5 和 easyeda v1.8.0。

## 完成范围

- U2 ETA6002 和 U5 NS4168 各 4 个 GND 普通贯通孔，共 8 个。
- 各孔的孔壁和铜环均在 EP 焊盘外，不设置焊盘内孔。原生工程钻孔 12.01 mil（0.305 mm）、外径 24.02 mil（0.610 mm）。dump 的 12 / 24 mil 是读取时圆整，尺寸以原生工程为准。
- 8 根背面 30 mil 短铜连接 EP 与过孔，正面 10 段 30 / 40 mil 铜连接局部过孔；新增 U5.7 → U5.9 的背面 20 mil 铜。
- 全板现在 31 段铜线、8 个过孔；本轮新增 19 段铜线。
- 48 个元件的 x/y、角度、装配面、器件、逐焊盘网络均保持；3 个 region 完全保持；原有 12 段铜逐图元状态保持。

## 保存与核查

完成 typed apply → save → doc reload → fresh dump → 原生 DRC。

`local-thermal-verification.json` 对每个孔分别核对：原生 normal via 与 GND 归属、钻孔/外径、孔壁与铜环都在 EP 外、TOP/BOTTOM 均触及实际导线，局部铜图存在到 EP 的路径。未用“同名 GND”代替连接。

原生存档各孔 topSolderExpansion / bottomSolderExpansion 为 null、ruleName 为空，继承默认规则；新鲜 config 的两面 via mask expansion 均为 -25.4 mm，关闭阻焊开窗。规则未改动。尚未检查 Gerber，制造输出时仍需核对最终阻焊文件。

原生 DRC：0 间距、短路、区域违规；168 未连接、1 原有 Netlist Error，全板未通过。全板 GND 尚未统一，原生未连接包括 GND 岛及过孔条目；本轮仅证明两个模块局部 EP/过孔铜连通，不能称全板接地完成。

pcb check：0 dangling、acute angle、non-orthogonal、重复铜、漂浮铜岛、重叠孔、via-in-pad、板边铜错误。既有丝印、未铺铜、去耦距离等告警保留。U5.7 到 EP 的 typed net-path 为 connected=true。

## 存档和预览

- `backup-before-thermal.epro2`：改前备份。
- `with-thermal-vias.epro2`：改后原生工程，ZIP 完整性通过；未另建工程验证恢复。
- `before.json` / `after.json`：实际铜快照；`thermal-plan.json` / `thermal.apply.json` / journal：参数与执行。
- `drc.json`：保存重载后的成功原生 DRC。
- `preview/thermal-bottom/snapshot.png`：typed board-fitted viewport PNG，objectLevelExport=false，非物理翻板。此 stage 再次采集 DRC 时发生超时，stage 未包含有效 DRC；未重复轮询/刷新。正式 DRC 依据前述 `drc.json`，不能把 stage 的 drcPassed=false 当新检查结果。该情况不构成两轮整板验收。

## 后续

继续电源回流、SYS 返回 U2.7 和主干，随后 USB 差分对、功放/麦克风等信号和全板 GND 铜。已确认的普通盖油/焊盘外侧孔方案无需重复询问。任何需要调整已确认的元件布局时，先说明受阻路径与改动范围再问用户。
