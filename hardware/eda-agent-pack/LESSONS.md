# 经验与坑（AI_figure 项目，2026-09-29 ~ 10-08）

## 1. EasyEDA CLI / 连接器

- 版本要配套：CLI、daemon、EDA 里的连接器扩展主次版本一致（本项目全是 1.8.0）。宿主 EasyEDA Pro 4.1.60。
- `easyeda daemon start` 会一直挂在前台，要放后台跑；断开用 `easyeda daemon stop`。
- 用 `--project <UUID>` 定位窗口，不要用 `--window`：浏览器刷新或重连后 windowId 会变。
- 删除类步骤（`pcb.route.delete` 等）必须加 `easyeda apply ... --yes`。
- 写入后的读取会带 `staleRisk` 警告，而且警告文字会**加在 JSON 输出前面**。脚本解析时先找第一个 `{`，或者先 `doc reload` 再读。
- 权威验证顺序：`pcb save` → `doc reload` → `pcb pour-rebuild` → `pcb dump` → 审计 → `pcb drc --json`。
- `project export`（导出 .epro2）这次多次超时。不要指望它做备份，**改动前的 `pcb dump --include-copper` JSON 就是回滚依据**（里面有所有线和过孔的坐标与 primitiveId）。
- 下面这些 typed 接口**做不到**，按约定也不能用 GUI 或 exec_js 绕过，只能让人在 EDA 里手动改：
  - 丝印文字的“镜像”属性：`pcb.silk.set` 不接受 mirror。
  - 元件位号显示/隐藏：`pcb.component.modify` 的可用字段里没有。
  - 画布过滤器的设置：只有读取接口。
- `pcb silk-align` 会把**底层位号强制改成镜像=是**。所以先自动摆位号，人工改镜像或隐藏位号放到最后。

## 2. `pcb dump` 数据的坑

- 焊盘的 `width`/`height` 是**旋转后**的外形尺寸；做精确几何要用 `shape` = [类型, w, h] 加 `rotation`。
- 焊盘坐标取整到 0.1 mil，同一行两个焊盘的 y 可能差 0.1，直接连线会出现非 0/45/90° 的线段。连线前把端点吸附到同一条轴上。
- 板框 `outline.bbox` 含 10 mil 线宽，真实板边要往里缩 5 mil（`geom.board_rect` 已处理）。
- **封装里隐藏的非金属化孔不在 dump 的焊盘里**（本项目 Type-C 座 J1 有两个定位孔），只能靠 DRC 报错才发现。办法：解压 .epro2，在 `*.epru` 里找 `"layerId":12` 的 FILL/POLY（见 `examples/ai-figure-reroute/fpslot.py`），把孔加成障碍物。
- 过孔压在焊盘上，EasyEDA 不算连接，要用导线连。
- live 规则里的 `copperToEdgeMil` 是 10，但嘉立创要求铜到板边不小于 0.3 mm（11.8 mil）。审计按两者取大。

## 3. 用户认可的走线风格（下一块板照此执行）

- 线段只能是 0°/45°/90°（含 135°），**每个拐角只能转 45°**：不要直角，也不要锐角。
- **不要 T 形分支**：分支只能出现在焊盘或过孔上，不能从线身中间引出。
- 不要因网格产生的碎折线；点到点尽量直，最多拐 1–3 个弯；最短线段不小于 10 mil。
- GND 短线横平竖直接过孔，不要斜着拉过去。粗电源线同样守这些规则。
- 间距留余量：本项目信号 6 mil 目标（规则线到线 4、其他 6），布完线到线最小 7.65 mil。
- USB 差分对用**元件摆放和过孔错位**补长度，不用蛇形线；本板两对差分对的长度差约 0.004 mil。
- Freerouting 的结果达不到上面的风格（会出现斜 GND 线、T 形、半截直角），最后改用 `pcb-router` 自研布线器重布。

## 4. 布局与 SMT

- 0402 阻容之间焊盘间距起码 **0.8 mm（约 30 mil）**。10 mil（0.25 mm）用户认为太挤，担心贴片出问题。
- 主要器件（Type-C、芯片、模组、麦克风）不能动；挪小件要同时重连相关走线：增量修改，不推翻重来（见 `examples/ai-figure-reroute/spread.py`）。
- 位号丝印对 SMT 没用，可以隐藏；但**位号本身必须保留**，BOM 和坐标文件靠它对应。
- 只在 PCB 里改位号（本项目 J2/J3/J4 改成 batt/spk/key）会导致 DRC 报“网表不一致”，BOM 和坐标文件也可能对不上。要么原理图同步改，要么改用普通丝印文字标注。此时**不要**在 PCB 里点“从原理图导入变更”，否则手改的内容会被覆盖。
- 底层丝印镜像：用户确认在 EasyEDA 里底层文字应设“镜像=否”，否则做出来是反的（Skill 文档对此记录不一，以 Gerber 预览为准）。

## 5. 脚本层面

- PowerShell 变量**不区分大小写**：`$F` 和循环变量 `$f` 是同一个变量，会互相覆盖。
- `from router import CLR` 会在导入时把值拷贝过来；要用 `router.configure()` 改过的值，代码里写 `router.CLR`。
