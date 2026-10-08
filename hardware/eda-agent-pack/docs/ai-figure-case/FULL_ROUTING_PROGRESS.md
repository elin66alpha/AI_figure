# 当前整板布线检查点（2026-10-07，美东）

整板已布线，连续两轮回读验收均得到原生 DRC 通过。用户也在现场确认 0 错误。材料化地铜无孤立铜岛，走线中心线直角为 0。目标暂保留 active：Hardware 主文档要求 USB 按 90Ω 设计，当前阻抗和实际支路匹配未证明符合，已向用户询问是否继续优化或留作样板验证。

## 已验证的事实

- 当前权威快照 `final-round2.json`：48 元件、586 直线、18 圆弧、135 过孔、2 个 GND 铺铜边界、3 个 region。
- 第一轮 `drc-final-round1.json`：passed=true、total=0；第一轮 stage bundle 同样通过。
- 第二轮 `final-review/final-round2/drc.json`：passed=true、violations=[]。原先独立 DRC 命令后台超时留下的空 `drc-final-round2.json` 不可作证；用户前台重算并确认 0 后，新的 stage bundle 得到上述原生通过结果。
- 两轮 stage.json 均非空、非 stale、drcPassKnown=true。两幅整板视口图已检查。captureKind=board-fitted-viewport-png、objectLevelExport=false，不是菜单对象级导出。
- 第二轮遵循 save→真实关闭重开 PCB1→pour rebuild→save→fresh dump→fresh DSN→fresh render。`final-round2-reload.json` 证明保存/重开；器件、直线、圆弧、过孔、region 与第一轮一致。
- 两轮 angle-audit 均为中心线直角 0、圆弧端点直角/锐角 0。全铜边缘、圆弧中部和间距由原生 DRC 覆盖。
- `final-round2-ground-graph.json`：实际材料化 GND 全部只有一个连通分量（497 节点、34 个填充连通块、81 个接地过孔 ID），没有悬浮地铜岛。模型包含轮廓、孔洞、分层接触和过孔跨层，圆弧采样 ≤1°；原生 DRC 仍为规则检查依据。
- `final-round2-critical-proof.json` passed：7 组关键网络连通；U2/U5 各 4 个焊盘外普通散热过孔与 EP 相连且双面有真实铜接触；授权范围外的器件绑定/姿态及 3 个机械区域保持。
- 丝印 helper 已对齐 47 个位号，U4 位号移至声学区域外；`final-silk-persistence.json` 确认重载后 48 个位号方向、所在层与底面镜像正确，两轮一致。
- 原理图同步及逐引脚网络对账已清除旧 Netlist Error；48 个器件及电路绑定保持。没有通过降低 DRC 阈值或忽略错误获取通过。

## 授权范围内的小器件调整

ESP32、麦克风、插排和其他大器件固定。实际仅改变以下 6 件的布局，均在 BOTTOM，PCB 坐标 mil、y 向上：

| 器件 | 当前 x,y | 旋转 | 理由 |
|---|---|---|---|
| C13 | 1004.57,-310 | 180° | 缩短麦克风去耦与供电/地路径 |
| R2 | 375,-631 | 0° | AMP_CTRL 更直接，地端接入 MCU 地 |
| R6 | 650,-590 | 90° | 串阻靠 MCU，减少 USB 绕行 |
| R7 | 710,-558.6 | 90° | 串阻与实际逃线协调 |
| D1 | 618.82,-1049.49 | 135° | D+ 直接流经 ESD 信号焊盘 |
| D2 | 672.12,-1089.49 | 45° | D− 直接流经 ESD 信号焊盘 |

已拉直 AMP_CTRL 插排附近及 TOP SYS/VBAT，去除无必要小折弯；其余信号、电源、喇叭和地网已连通。C13 地铜追加跨层连接以消除最后孤立填充块。曾清理 SYS 过孔造成两处断路，已恢复，并在以上两轮原生验收中通过。

## USB：连通已验证，阻抗及实际支路匹配待确认

用户确认双层 FR-4、1.6 mm 板厚、1 oz 铜厚，普通过孔两面盖油。原生两组差分长度规则通过，但并不证明 USB-C 各插向的实际支路等长。

独立有序路径确认 4 条支路均真实经过相应 ESD 到串阻：

| 支路 | 中心线长度 mil | 证据 |
|---|---:|---|
| J1.A6 → D1.1 → R6.1 | 703.8275 | usb-ordered-a6-esd.json |
| J1.B6 → D1.1 → R6.1 | 864.8875 | usb-ordered-b6-esd.json |
| J1.A7 → D2.1 → R7.1 | 849.8247 | usb-ordered-a7-esd.json |
| J1.B7 → D2.1 → R7.1 | 910.2847 | usb-ordered-b7-esd.json |

A 插向输入支路长度差约 3.708 mm，B 插向约 1.153 mm；不宣称有序支路满足 0.254 mm 差值。

长直段线宽 10 mil、线间距 6.2 mil。实际材料化地铜抽样间距常为约 14.52 mil，局部更大；部分截面正面回流地铜不连续，见 `final-round1-usb-return-coverage.json`。

0.5 mil 网格静态截面估算约 101.37Ω，0.25 mil 网格细化后约 99.94Ω，见 `impedance-estimate-0.25mil-quick-gap14.52.json`。模型假设同层地铜均匀、对面完整地平面；实际布局并非全程均匀，不能作为整板 90Ω 证明。此前约 92Ω 使用地铜间距 6.02 mil 的假设，不适用于当前实际地铜。板厂实际介质、阻焊与 USB 实物性能未测。

已向用户询问是否继续优化 USB 以争取 90Ω 与实际支路匹配，或本轮以 DRC 全过、无铜岛验收并后续样板验证。该问题尚无明确回答；用户“DRC 我看了，0 错误”仅作为 DRC 现场确认，不擅自解释为放弃 90Ω 要求。

## 原生备份

`AI_figure_routed_DRC0_checkpoint_20261007.epro2` 已原生导出，381672 字节，ZIP CRC 无错误；PCB1 和 P1 UUID 均在工程内容中。SHA256：

`92643641f131121fd6afd18fad1c8a0899cb05dde1dd7f34242c40c0d2524c51`

导出记录 `final-checkpoint-export.json`；独立核验 `AI_figure_routed_DRC0_checkpoint_20261007.verification.json`。尚未重新导入恢复测试，restoreVerified=false。

dump 将圆角板框降为 AABB（partial 记录 unexpected-start:R），离线板边距离仅为近似值。现场圆角板框没有被替换，原生 DRC 检查实际几何。
