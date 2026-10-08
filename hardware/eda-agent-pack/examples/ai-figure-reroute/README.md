# 范例：AI_figure 整板重新布线（2026-10-08）

这块板原来由 Codex 用 Freerouting 布线，有斜 GND 线、T 形、半截直角等问题。这里用 `../../pcb-router` 把旧线全部删掉后重布。
- 结果：278 段线、121 个过孔，没有圆弧；原生 DRC 0 错误。
- USB 两对差分对的长度差约 0。
- 最终板子截图：`final-board-snapshot.png`。

这些脚本是**项目专用的驱动**：里面写着位号、坐标和网络名。下一块板拿来当模板改。

| 文件 | 作用 |
|---|---|
| `design.py` | 手工规划部分：小件挪位（`moves`）和固定路线（J1 出线、USB 差分对、CC、VBUS、MCU 侧 USB、内向逃逸过孔、上拉短线、左侧 3V3 竖线、麦克风过孔等） |
| `check_design.py` | 校验 design.py 的固定路线与挪件（精确间距、USB 长度差） |
| `check_bodies.py` | 挪动后的元件本体是否压到同面其他元件 |
| `main.py` | 自动布线：按 HOPS 列表逐条布线，含出线预留和拆线重布队列，输出 `routedN.json` 与 `routedN-routes.json` |
| `post.py` | 后处理：重布难看的连接；GND 阶段（顶排母线、EP 互连、横平竖直的接地短线加过孔、150 mil 间距缝合孔） |
| `fix1.py` | 第一次写入后按 DRC 做的增量修复：J1 隐藏定位孔加成障碍物后重布 VBAT；R2 掉头；U5 散热焊盘接地 |
| `spread.py` | 第二轮增量修改：把过密的阻容拉开到约 0.8 mm 以上，只拆、只重连受影响的 16 段线，用户改过的丝印不动 |
| `t_one.py` | 单独试布一条连接，用来调参数 |
| `fpslot.py` | 从 .epro2 里找封装隐藏的非金属化孔 |

## 跑法

```
cd data
python ../check_design.py
python ../main.py routed.json              # 自动布线，慢，几分钟
python ../post.py routed-routes.json post.json
python ../../../pcb-router/audit.py post.json
python ../../../pcb-router/make_apply.py copper post-routes.json --base before.json --project <工程> --doc <PCB>
```

`data/` 里的文件：
- `before.json`：重布前的完整 dump，也是这些脚本的输入。
- `post16-routes.json` / `fix1-routes.json`：最终布线模型。
- `after-spread.json`：项目结束时从 EDA 读回的最终状态。

`fix1.py` 和 `spread.py` 读的是当时从 EDA 现场 dump 下来的 `after1.json` / `now.json`，这两个文件没有收进来。拿来当增量修改的模板时，先对当前板子 dump 一份。

板子规格：30×50 mm（1181.1 × 1968.5 mil），两层。规则：线到线 4 mil，其他 6 mil；铜到板边 11.8 mil；过孔 24/12 mil。
