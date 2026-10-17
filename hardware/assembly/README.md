# AI_figure 主板手工装配

**给装配的人：** 直接用浏览器打开 [`AI_figure_装配指南.html`](AI_figure_装配指南.html)（单文件，断网可用，横屏为主）。点中间 2D 板图上任意元件就显示它的信息；左边小窗是焊好后的 3D 样子（只看，可旋转）；右边是建议顺序。

工作流和工具在本地的 `hardware/eda-agent-pack/assembly-guide/`（含完整工作流文档 README.md）。这个工具包只留在本地、已加入 `.gitignore`，不在 GitHub 上。重新生成（需要本地有工具包）：

```bash
pwsh hardware/eda-agent-pack/assembly-guide/run_all.ps1 -Config hardware/assembly/assembly.config.json
```

## 本板情况（2026-10-17）

- PCB：`ProPrj_AI_figure_2026-10-08.epro2`，与 EasyEDA live 版本逐焊盘对账一致（50 个位号、所有焊盘偏差 ≤0.07 mil）。用户确认手上的光板就是这一版。
- 3D：`../../mechanic/export/PCB.step`（EasyEDA 2026-10-10 导出），44 个贴片件全部在内，坐标与 PCB 逐件对齐。
- 位号丝印全部隐藏（`valueVisible=false`），封装丝印框保留。
- 工艺：锡膏 + 热风枪，烙铁补焊。**建议顺序（用户定）**：先焊正面、第一个焊 ESP32 模组 U1；再焊背面，USB-C 座 J1 是最后一个贴片件；最后焊电池/喇叭/按键线。
- 贴片 44 个，27 个料袋；不贴片 6 个：J2/J3/J4 直接焊电池/喇叭/按键线（用户确认，不装排针座），TP1–TP3 是测试焊盘。

## 采购清单 vs 设计 BOM

[`purchase.csv`](purchase.csv) 由 [`../BOM/c3bfd9e86d0bf8306d8e2dab7f3f90c9.png`](../BOM/c3bfd9e86d0bf8306d8e2dab7f3f90c9.png)（立创下单截图）转录，27 行与设计 BOM 27 行一一对应，单套用量全部相同，购买数量都够。4 处换料，均按立创官方参数核对等效：

| 位号 | 设计 | 实购 | 核对结果 |
|---|---|---|---|
| C2, C15 | CL05A105KA5NQNC (C52923) | 村田 GRM155R61E105KA12D (C77009) | 1 µF ±10% 25 V X5R 0402，一致 |
| R3 | 0402WGF3001TCE (C25784) | 富捷 FRC0402F3001TS (C2909355) | 3 kΩ ±1% 62.5 mW 0402，一致 |
| R8 | 0402WGF0000TCE (C17168) | 富捷 FRC0402F0000TS (C2906858) | 0 Ω 62.5 mW 0402，一致 |
| R9–R12 | 0402WGF1002TCE (C25744) | 富捷 FRC0402F1002TS (C2906861) | 10 kΩ ±1% 62.5 mW 0402，一致 |

U4 麦克风（C5373237）立创国际站查不到参数，型号与设计 BOM 相同，已按本地手册 `../datasheets/U4_LMD2718T261-OA1_LinkMems.pdf` 核对。

## 有方向的器件（第一性原理核对）

| 位号 | 依据 | 结论 |
|---|---|---|
| D3 LED | 原理图 pin1=A 经 R13(330Ω) 接 3V3，pin2=K 接 GPIO8（低电平点亮）；亿光 19-217 手册 ①=+、②=− | 阴极 = 焊盘 2（LED_GPIO8）。板上丝印框切角端=阴极；封装“标记层”圆点在阳极侧但不印在板上 |
| D4 TVS | 单向 SMF5.0A，pin1=C 接 VBUS_CHG，pin2=A 接 GND | 色带(阴极) = 焊盘 1，板上二极管丝印竖杠同侧 |
| D1/D2 | 双向 ESD（引脚名 IO/IO，手册 bi-directional） | 无极性 |
| U4 麦克风 | 手册：顶部进声孔，盖子无 1 脚标记，底面切角焊盘 = 1 脚；1/2/3=GND/L-R/GND，4/5/6=VDD/DATA/CLK；封装焊盘号与手册一致无镜像 | 1 脚在正面视图右下角，进声孔在下端；最后焊、焊后不清洗 |
| U1/U2/U3/U5/U7 | 焊盘 1 坐标取自 live 板 | 指南按视图给出 1 脚方位（已逐个按坐标手算核对） |
| J1 USB-C | 立式，A/B 两排旋转 180° 后网络完全对应 | 正反都对，不画方向标记 |
| J2 电池 | 方焊盘 pin1=VBAT，丝印“+”压在 pin1 上 | 电池线最后焊，接反会烧 U2 |

## 复核结果

见 [`VERIFY_REPORT.md`](VERIFY_REPORT.md)：50 个位号全部通过（含 3D 对齐）；复核器变异自测 7/7 抓到。

页面按用户要求（2026-10-16/17）：横屏三栏，左 3D 小窗（只看）、中间 2D 主图（点选元件）、右建议顺序；芯片显示完整型号 + 中文名，阻容显示参数；型号/品牌/C 编号小灰字；不含工艺说明、焊接技巧提示、复核勾选、进度记录。

## 文件

| 文件 | 说明 |
|---|---|
| `AI_figure_装配指南.html` | 交付物 |
| `assembly.config.json` | 本板的人工判断（工艺、方向说明、注意事项、不贴件、上电检查） |
| `purchase.csv` | 采购截图转录 |
| `VERIFY_REPORT.md` | 独立复核报告 |
| `data/board.json` | live `pcb dump` 快照 |
| `data/extract.json` | `.epro2` 提取结果 |
| `data/reconcile_report.json` | 工程文件 vs live 对账 |
| `data/lcsc_parts.json` | 立创官方参数 |
| `data/mesh3d.json` | STEP 转出的 3D 网格（按位号分组） |
| `data/guide_data.json` | 指南嵌入的数据 |
