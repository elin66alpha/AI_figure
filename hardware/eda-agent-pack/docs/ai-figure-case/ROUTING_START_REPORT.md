# PCB 布线起步检查点（2026-10-06，美东）

状态：局部铜线 `live-verified`；整板布线 `incomplete`。文件中原有 2026-10-07 标记使用旧交接日期，本检查点采用用户美东日期。

## 工程与环境

- AI_figure，工程 UUID 8c5d0d86032348a0a6c85102fe97607e；PCB1 f39f5125c569691f。
- CLI / daemon / connector 1.8.0；宿主 EasyEDA Pro 4.1.60；不升级工具。
- 本机 PowerShell 7.6.5，按用户要求后续默认 PowerShell 7。
- 原始备份 backup-before-routing.epro2，ZIP 完整性已验证；未另建工程验证恢复。
- 基线 48 元件，2 铜层，0 tracks/arcs/vias/pours，3 regions。

## 已写入并保存重载的局部铜

全部为 BOTTOM，mil、y 向上，12 段；无新增过孔、铺铜或规则变更。

| 连接 | 线宽 | 意图 |
|---|---|---|
| U2.1 → L1.1，SW | 28 mil / 0.711 mm | 短宽开关节点，限制高 dv/dt 铜面积 |
| C6.1 → U2.8，VBUS_CHG | 20 mil / 0.508 mm | 输入电容接 IN |
| L1.2 → C7.1，SYS | 24 mil / 0.610 mm | 电感输出接输出电容 |
| U2.5 → R3.1，ISET | 8 mil / 0.203 mm | 低电流设置节点 |
| U2.2 → U2.9，GND | 20 mil / 0.508 mm | PGND 到 AGND/EP |
| U2.3 → U2.9，GND | 20 mil / 0.508 mm | NTC 关闭监测的地连接 |
| R3.2 → U2.9，GND | 8 mil / 0.203 mm | ISET 小电流参考地，回 EP |

这些连接不构成完整充电回路：C6/C7 地回流、SYS 返回 U2.7、供电主干、VBAT、散热与跨层地仍待完成。

第一性原理依据：输入旁路应形成低电感回路；开关节点同时限制长度与面积；ISET 返回模拟地；所有连接以实际 pad/net/铜接触为准，不以同网名或飞线消失代替。芯片引脚依据 [ETA6002 厂家手册](https://datasheet.lcsc.com/datasheet/pdf/8efad5a1e38bfd1767a78dc3ee3fef7c.pdf?productCode=C7436031) 的 PIN DESCRIPTION：IN 旁路到 PGND、EP AGND 必须在 PCB 接 PGND。

## 已验证事实

- 完成 save → doc reload → fresh dump → native DRC。
- verification-summary.json：48 元件的位置、角度、装配面、器件和逐图元 pad net 均无变化；三个 region 完全保持。
- 七个 path-*.json 均 connected=true，BOTTOM、0 via；其长度读数可能只覆盖被焊盘铜触及的已选子段，不作为整条焊盘中心间线长。
- 原生 DRC 起点：173 Connection Error、1 Netlist Error。
- 最终：167 Connection Error、1 原有 Netlist Error；没有 Clearance Error、短路或区域违规。不得称整板 DRC 通过。
- 首版 SYS 转角距 C7.2(GND) 仅 0.134 mm，低于 0.152 mm；已按 fresh ID 删除仅本轮两段 SYS 线，提前转向并保持 24 mil，重载后间距错误归零。
- pcb check：新铜 dangling、acute-angle、non-orthogonal、duplicate、floating-island、clearance 均 0。
- pcb check 尚有丝印、未铺铜、去耦距离等检查项，留到相应阶段处理。GND 8 mil 告警来自 R3 ISET 参考地，不是系统电源回流主干。
- 插拔走廊检查把立式 J1 按卧式连接器估算，不能据此移动 D1/D2；J3/J4 插头包络使用回退估算，实物接线方式仍待确认。

## 工具边界与图

- dump 将圆角板框返回为 AABB（unexpected-start:R）；离线 route solve 明确拒绝不完整板框。因此没有离线寻路通过声明，也没有伪造精确多边形。
- 局部路线来自 live pad 坐标和参数 JSON，以 typed line.create/apply 写入，再由原生 DRC 验证；所有局部铜位于板内远离圆角处。
- preview/initial-charger-bottom/snapshot.png 是 typed board-fitted viewport PNG；captureKind=board-fitted-viewport-png、objectLevelExport=false。底面仅图层聚焦，不是物理翻板。为突出背面，板框/正面层目前不可见，PNG 不证明完整禁布区域。
- 没有修改元件属性文字；丝印整理尚未进行。

## 待用户答复与后续

更新：用户已确认普通盖油、焊盘外侧过孔；U2/U5 各 4 个孔已完成，见 `../pcb-thermal-vias-20261006/THERMAL_VIA_REPORT.md`。下方询问保留为起步时记录，不再等待同一答复。

已向用户询问：U2/U5 散热是否采用普通工艺（过孔盖油、无填孔电镀），还是填孔电镀焊盘内过孔。推荐普通工艺、焊盘外侧过孔；答复前不创建散热孔。

后续先计算完整电源回流和 SYS 到 U2.7，再做 USB 输入/差分对、3V3 主干、功放、麦克风与其他信号，最后 GND 铜与缝合孔。元件布局已确认，任何必须移动、旋转、换面的情况先向用户说明原因并询问。保留既有网表一致性提示，在原理图/PCB逐脚核对后再定位，不能为清提示盲目重导入。
