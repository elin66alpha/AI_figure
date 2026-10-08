# EDA Agent Pack

从 AI_figure（ESP32-C3 语音板，30×50 mm，两层板）项目里剥离出来的、可以复用的 EasyEDA Pro 自动化工具、脚本和经验记录。
项目在 2026-10-08 结束，本包是给下一块板用的起点，不依赖原项目目录。

> 本包只是从原项目复制出来的，原文件仍留在 `hardware/eda-design`、`hardware/eda-tools` 等位置，没有删。

## 目录

| 目录 | 内容 | 来源 |
|---|---|---|
| [tools/easyeda-cli](tools/easyeda-cli) | `easyeda.exe` v1.8.0（本项目实际使用、与 EDA 内 1.8.0 连接器配套）、action 目录、EDA API 原语清单 | eda-tools |
| [tools/easyeda-agent-skill](tools/easyeda-agent-skill) | `easyeda-agent` Skill 1.8.0 快照（SKILL.md + references + scripts），即 `~/.claude/skills/easyeda-agent` | Skill |
| [pcb-router](pcb-router) | **通用**：45° 八方向布线器、独立审计、渲染、生成 apply 剧本 | Claude 写的，已去掉项目常量 |
| [examples/ai-figure-reroute](examples/ai-figure-reroute) | 用 pcb-router 给 AI_figure 整板重新布线的完整驱动脚本 + 输入/输出数据 | Claude 写的 |
| [pcb-analysis](pcb-analysis) | Freerouting 流程、差分阻抗估算、连通性/地岛分析、热过孔核查等 | Codex 写的 |
| [layout](layout) | 板框分区图、离线摆件规划与器件 0/180° 朝向优化 | Codex 写的 |
| [schematic](schematic) | 原理图 typed 流程范例：生成摆件/连线剧本、合并单页、换型号迁移、BOM 校验 | Codex 写的 |
| [docs/ai-figure-case](docs/ai-figure-case) | 本项目的设计约束、交接文档、DRC/布线/热过孔报告、原理图审查报告 | 两者 |
| [references/datasheets-text](references/datasheets-text) | ESP32-C3、ETA6002、NS4168 等芯片手册的文字提取版，方便检索 | sch-check |
| [LESSONS.md](LESSONS.md) | **先读这个**：EasyEDA CLI 的坑、布线风格规则、SMT/丝印注意事项 | 汇总 |

## 整体工作流（PCB 部分）

```
EasyEDA Pro（浏览器）+ 连接器扩展  ←WebSocket→  easyeda daemon  ←→  easyeda CLI / apply 剧本
                                                                      ↑
                     pcb dump --include-copper  →  board.json  →  离线脚本（布线/审计/渲染）
                                                                      ↓
                                                     *.apply.json（typed 步骤）→ easyeda apply
```

1. `easyeda daemon start`，在 EDA 里启用连接器，`easyeda health` 确认窗口里有目标工程。
2. `easyeda pcb dump --project <工程> --include-copper --out board.json`：所有离线计算都基于这份快照，同时它也是回滚依据。
3. 离线布线、移件，用 `pcb-router/audit.py` 审计到零问题。
4. 生成 `*.apply.json`，然后 `easyeda apply x.apply.json --project <工程> [--yes]`。
5. `doc reload` → `pcb pour-rebuild` → `pcb save` → 重新 dump → 再审计 → `pcb drc --json`。

## 依赖

Python 3.11、numpy、matplotlib；`pcb-analysis/impedance_estimate.py` 还需要 numpy。
Freerouting 2.5.0（约 190 MB，含 JRE）没有放进来：原件在 `hardware/eda-tools/freerouting-2.5.0`，也可以从 GitHub freerouting 发布页下载。
