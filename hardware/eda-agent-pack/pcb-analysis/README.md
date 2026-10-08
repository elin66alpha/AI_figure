# pcb-analysis：Codex 阶段的 PCB 分析与 Freerouting 工具

这些是 2026-10-06~07 Codex 用 Freerouting 布线时写的脚本。大多数把文件名写成了默认参数（例如 `dsn-corner-verified.json`），复用时要改输入参数。坐标单位 mil、y 轴向上。

| 文件 | 作用 | 复用价值 |
|---|---|---|
| `impedance_estimate.py` | 二维有限差分（Laplace）估算共面差分对的奇模/差分阻抗；线宽、间距、到地间隙、介电常数是 `solve()` 的参数，板厚等在函数里改；`quick` 参数为粗网格 | 高，与项目无关 |
| `verify_corner_connectivity.py` | 独立的铜皮接触连通性检查：圆弧按扫掠采样，焊盘形状取自 DSN | 中，其他脚本的基础 |
| `ground_island_graph.py` | 用铺铜实际轮廓（含挖孔）构建 GND 连通图，找孤岛 | 中 |
| `ground_path_search.py` | 8 方向 A*，给孤立的 GND 焊盘找到主地过孔的路径 | 中 |
| `audit_angles.py` | 角度审计（含端点和线中间的 T/交叉） | 中，`pcb-router/audit.py` 更完整 |
| `chamfer_corners.py` | 把 90° 拐角改成参数化的 45° 斜切 | 中 |
| `preflight_tracks.py` | 新增走线计划的保守间距预检 | 中 |
| `prepare_router.py` | 整理 `pcb export-dsn` 导出的 DSN：去掉重复的过孔图元，设置布线参数 | Freerouting 流程用 |
| `ses_candidate.py` | 解析 Freerouting 输出的 SES，转成可审查的 typed 布线计划 | Freerouting 流程用 |
| `screen_plan.py` | 用精确焊盘几何筛查布线计划（含挪件） | Freerouting 流程用 |
| `plan_to_apply.py` | 把计划（deleteIds/componentMoves/vias/routes）转成 apply 剧本。只允许挪 R/C/D1/D2，这是项目限制 | Freerouting 流程用 |
| `verify_local_thermal.py` | 核对散热焊盘热过孔（数量、位置、与铺铜连接） | 中 |

Freerouting 流程：`pcb export-dsn` → `prepare_router.py` → `freerouting-cli` → `ses_candidate.py` → `screen_plan.py` → `plan_to_apply.py` → `easyeda apply`。
它的布线风格达不到用户要求（见 `../LESSONS.md` 第 3 节），所以本项目最后改用 `../pcb-router` 重布。
