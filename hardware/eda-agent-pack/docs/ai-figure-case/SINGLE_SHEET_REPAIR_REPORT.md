# P1 单页原理图修复记录

完成时间：2026-09-29（本地）。工程 AI_figure；P1 UUID `98cfe13509bc1f5c`。

- 用户将纸张扩大为横向 A2，实测 2338×1652 raw。仅剩一张 P1；原 Power and USB 页已迁移并删除。
- 57 个原有有效器件全部保留其电路功能，删除重叠重复电感 L4。电源页迁入器件保留原 uniqueId。
- 重新布局和接线，消除导线重复网名、反向电源标记、标签重叠、交叉导线与悬空引脚。射频 CLC 与 U.FL 已接通。
- 增加 6 个标准测试焊盘：UART_RX、UART_TX、GND、CHIP_EN、BOOT_GPIO9、3V3。焊盘不进入采购 BOM。
- 根据用户选择，L1 从自建 DH0618H-2R2M 更换为标准库 FXL0618-2R2-M / C524593；保留 L1 与 uniqueId gge16。

## L1 手册核查

归档 `FXL0618-datasheet.pdf` 为长江微电 FXL 系列手册，第 6 页（印刷页 43）：2.20µH ±20%、DCR 典型 28mΩ/最大 35mΩ、额定电流典型 7A、饱和电流典型 8A。第 2 页（印刷页 39）给出 7.0×6.6×1.6mm 本体及推荐焊盘。FXL0618 与 FXL0630 使用同一推荐平面焊盘尺寸，因此标准库封装名称包含 FXL0630；器件实际高度以 FXL0618 手册为准，PCB 阶段还需检查库中的 3D 高度。

源手册：https://img.allchips.com/online/fileBatchImport/2023321/pXTsMFTzfTjGZyBN3hnZHSkmYxyJ5kZQ.pdf

## 最终验证

| 检查 | 结果 | 证据 |
|---|---|---|
| 官方严格 DRC | 0 fatal / 0 error / 0 warn / 0 info | single-sheet-final-drc.json |
| 连线与文字检查 | 0 项问题 | single-sheet-final-check.json |
| 实际短接、孤立线/标记 | 0 项 | single-sheet-final-bridge.txt |
| 设计意图逐引脚对账 | 63 器件、190 引脚，通过 | single-sheet-pin-audit.json |
| 页面库存 | 仅 P1 | single-sheet-final-pages.json |
| 保存 | saved:true | single-sheet-final-save.json |
| 原生工程导出 | ZIP 完整性通过 | single-sheet-project-export-final.json |

额外布局检查无本体重叠、无近距碰撞、无引脚重合、无出纸张。该检查按器件 anchor 判断格点，保留 SW1 anchor=2190,1249 的一项提示：这是为补偿原库引脚相对原点 -14 的偏移，三个实际引脚与导线均在 5 raw 格点；官方 DRC 为零。不能把此 anchor 提示误当原生电气 DRC 遗留警告。

保存后的首次自动重开失败并引起连接器断连，用户恢复连接后重新读到了 63 个器件。最终 L1 替换后已再次保存、完整回读、逐引脚审计并原生导出；未再次自动重开，以避免重复触发已知宿主故障。备份恢复未实测。

## 交付

- `P1-A2-schematic-final.png`：最新原生整页导出，已人工视检。
- `AI_figure-P1-A2-DRC0.epro2`：最新原生工程备份。
- 本轮未打开或编辑 PCB。既有功能/实物风险不因 DRC 清零而自动关闭。
