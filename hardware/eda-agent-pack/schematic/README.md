# schematic：原理图 typed 流程范例（Codex 写）

这些是用 easyeda CLI 搭原理图时写的生成脚本。思路都一样：读一次 EDA 回读的 JSON，算出摆件、连线、属性，生成 `*.playbook.json`，再用 `easyeda apply` 执行，最后用审计脚本核对回读结果。
脚本里写死了 AI_figure 的工程/页面 UUID、位号和文件名，**只能当模板**，不能直接跑。

| 文件 | 作用 |
|---|---|
| `prepare_peripherals.py`、`prepare_power_parts.py` | 从器件库搜索结果（LCSC 编号）生成放置器件的剧本 |
| `prepare_layout.py`、`prepare_power_layout.py` | 按实测器件 bbox 与功能分区计算摆放坐标 |
| `prepare_inductor.py` | 自建器件（电感）规格：封装尺寸、证据来源、哈希 |
| `build-takeover-mcu.ps1` | 从回读 JSON 生成 MCU 分区的布局输入（网络、连接） |
| `build-single-sheet.py`、`wire-single-sheet.py` | 把多页原理图合并成单页，并按引脚生成连线剧本 |
| `audit-single-sheet.py` | 回读后逐引脚核对连接，确认没有悬空、短接或错连 |
| `prepare_h4x_migration.py`、`prepare_h4x_bus.py`、`prepare_h4x_drc_fix.py`、`audit_h4x_migration.py` | 把 ESP32-C3 裸芯片换成 ESP32-C3-MINI-1-H4X 模组：迁移计划、总线连线、DRC 修复、逐脚审计 |
| `bom_prepare_properties.py`、`bom_verify_final.py` | 降成本换料时，批量写入供应商/型号属性，并导出、校验 BOM |
| `dump_pins.py` | 把原理图回读整理成“位号.引脚 → 网络”的文本表，方便前后对比 |
| `wire_attach_check.py` | 检查指定引脚是否真的接在导线上 |

配套的方法论（参数化原理图数据、自动布局 SOP、连线规范）在 `../tools/easyeda-agent-skill/references/`：
- `schematic-data.md`
- `auto-layout-sop.md`
- `schematic-wiring.md`
