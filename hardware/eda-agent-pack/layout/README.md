# layout：离线摆件规划（Codex 写）

| 文件 | 作用 |
|---|---|
| `floorplan.py` | 画板框分区草图：单位 mm，原点在左上；正反两面都按正面视角画，底面用透视，方便对照同一物理位置 |
| `placement.py` | 30×50 摆件计划加离线检查。按功能分区给出每个件的中心坐标和旋转，器件尺寸取自现场 dump，输出 `placement.json` 供 `pcb modify --center` 使用（原 placement13.py，最终版） |
| `orient.py` | 在不改变占位的前提下，为每个件选 0° 或 180°，让关键焊盘对（电源、USB 等）距离最短（原 orient32.py，最终版） |

文件名（如 `board9.json`）和分区坐标都是本项目的值，改成新板的 dump 和分区再用。
skill 自带的 `easyeda pcb layout-plan` / `layout solve` 是更正式的方案，见 `../tools/easyeda-agent-skill/references/pcb-layout.md`。
