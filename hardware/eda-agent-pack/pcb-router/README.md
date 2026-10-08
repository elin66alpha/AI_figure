# pcb-router：两层板 45° 布线工具（通用）

所有坐标单位为 mil，y 轴向上，与 `easyeda pcb dump` 一致。脚本只做离线计算，不会写 EDA。

| 文件 | 作用 |
|---|---|
| `geom.py` | 精确几何：焊盘/线/过孔形状、距离、8 方向；`board_rect(dump)`、`dump_rules(dump)` 从 dump 读板框和规则 |
| `router.py` | `Board`（障碍物与已布线路的空间索引，支持移件 `move_component`）+ `Router`（2.5 mil 网格 A*，只允许 ±45° 转弯，最短直行段、拐弯/过孔代价、出线预留、软障碍拆线重布）+ `finalize`（精确八方向拉直，最短段 10 mil，精确间距检查） |
| `audit.py` | 独立审计 dump 格式的板子：非 45° 线段、≥90° 拐角、T 形、悬空端、同网重叠、异网间距、板边距离、断路、每条连接的拐弯数 |
| `render.py` | 整板或局部窗口按层渲染成 PNG |
| `plotarea.py` | 局部窗口快速画图（焊盘、线、过孔，带网络名），适合看拥挤区域 |
| `make_apply.py` | 把模型（moves + routes）转成 `easyeda apply` 剧本：移件，或删除全部旧铜后新建线和过孔 |
| `netlist.py` / `shownet.py` | 列出每个网络的焊盘（含形状、旋转）/ 某网络的线段与总长 |

## 用法

```python
import json, router
from router import Board, Router
d = json.load(open('board.json', encoding='utf-8-sig'))     # pcb dump --include-copper
router.configure_from_dump(d)            # 板框 + 间距（规则 + 0.5 mil 余量）+ 过孔尺寸
bd = Board(d, keep_via_ids=[...], moves={'R5': {'pad': '1', 'at': (450, -1461), 'rot': 180}})
R = Router(bd)
res = R.route('VBAT:J2.1>C8.2', 'VBAT', 'J2.1', ['C8.2'], 20, layers=(2,), max_vias=0)
fin = R.finalize('VBAT:J2.1>C8.2', 'VBAT', res, 20)
bd.add_route('VBAT:J2.1>C8.2', 'VBAT', fin['segs'], fin['vias'])
router.export_dump(bd, 'model.json')     # 导出 dump 格式，交给 audit.py
```

```
python audit.py model.json [--board x0,y0,x1,y1]
python render.py model.json out/board            # 输出 out/board-L1.png、out/board-L2.png
python plotarea.py model.json 300 700 -950 -550 crop.png
python make_apply.py copper routes.json --base board.json --project <工程UUID> --doc <PCB UUID>
```

完整的整板流程（手工规划 USB 和出线、自动布线、拆线重布、GND 打孔、增量修复）见 `../examples/ai-figure-reroute`。

## 已知限制

- 只支持两层（TOP=1、BOTTOM=2、多层焊盘=12）。不处理铺铜，铺铜交给 EDA 的 `pour-rebuild`。
- 多边形焊盘不能用 `move_component` 移动。
- 封装里的隐藏非金属化孔要手动加成障碍物（见 LESSONS.md 第 2 节）。
- 板框按矩形处理，四角按圆角半径 `CORNER_R` 避让；异形板要传 `board=` 并自己补充障碍物。
