# 贡献标准电路块

标准块保存器件角色、固定内部拓扑、可重绑边界和布局约束。先用
`easyeda blocks search <keyword>` 查已有块，`easyeda blocks show <id>` 读取完整 JSON；
`blocks ls --json` 只提供摘要投影，不包含全部连接数据。

## 模板与 1.4 Lib 的边界

| 数据 | 用途与入口 |
|---|---|
| CLI 内嵌 block 模板 | 仓库 `internal/blocks/data/` 一块一文件，经 `go:embed` 编进 CLI，不随 Skill 分发。`sch block-apply <id>` 解析角色、分配位号、放件并连接内部网与边界。 |
| 本地 Lib composition | 已确定的连接核心加已设计、实测的局部几何，经 `sch compose` 计算模块平移、单页 Z 字排版及框标题，再生成受保护 `sch apply` 队列。格式见 [schematic-data.md](schematic-data.md)。 |

公共 Lib 候选、成熟度及来源策略统一登记在
[reusable-module-library.md](reusable-module-library.md) 所述目录。一个候选可以引用现有
Block；只有当它需要参数化生成拓扑时才提升为新 Block，不能为了“收纳数据”重复造模板。

模板的 `parts.<ROLE>` 与实例的稳定 component ID、ref、role 属于不同层，模板 JSON
不能直接作为 composition 输入。`block-apply` 每次创建新实例，并非幂等修复命令；
部分失败后先回读现场，不能直接重跑。两条路径都不等于从任意拓扑自动设计全部外围与布局。

## 贡献数据合同

文件名为 `internal/blocks/data/<id 去掉 block.>.json`。完整字段说明在仓库
`internal/blocks/data/_block.schema.json`，实际校验由 `internal/blocks/validate.go` 执行。

| 字段 | 要求 |
|---|---|
| `id/desc/category/source/author` | `id` 形如 `block.usb_serial`；说明用途、分类、可追溯来源与原作者。来源使用具体型号手册、官方参考设计或有验证证据的开源电路。 |
| `parts` | 非空角色表，值含 `part/qty`，可附 `alt/value_override/note`。`part` 指向 [standard-parts.json](standard-parts.json) 的 key；新器件先补库身份与真实料号。 |
| `internal_nets` | 数组，每个网络是至少两个 `ROLE.PIN` 或 `PORT:<name>` 引用。同一引脚只属一个网。未定拓扑不写成字符串 `"pending"`，草稿也须满足数据格式。 |
| `ports` | 边界表，含 `dir`（`in/out/bidir`）、`at`（`ROLE.PIN`）、`desc`，可附 `default_net`。重绑边界网络不改变内部引脚拓扑。 |
| 可选约束 | `schematic_layout/pcb_layout/placement/signals/silk/keepout` 等按 schema 记录。存在字段不代表转换器已经执行该约束。 |

引脚引用必须与实际所选符号核对，优先使用功能名；需要区分同名脚时使用真实引脚号。
同名多脚确需全部并联时写 `J.VBUS*`，不能省略后缀并让工具猜选一脚。
物理引脚逐脚验证；明确 NC 与缺失连接分开记录。`schematic_notes` 是模板知识说明，
不表示 1.4 要生成独立 Notes 图元。

## 布局提示的执行范围

`schematic_layout` 有两种互斥形式，新模板优先使用关系形式：

```json
{
  "schematic_layout": {
    "anchor": "U",
    "flow": ["J_USB", "D_ESD", "U"],
    "attach": {"C_VCC": "U.VCC"},
    "pair": [["R_CC1", "R_CC2"]],
    "orient": {"C_VCC": "vertical"}
  }
}
```

- `flow` 表示左到右顺序，不要求覆盖全部角色；一个角色不能被多种关系重复定位。
- `attach` 定位到一个真实、唯一的目标引脚，不能带 `*`；该引脚与所附角色必须有
  `internal_nets` 电气依据。`pair` 组内须为相同 part，`orient` 用 `vertical/horizontal`。
- 兼容的 legacy `roles:{ROLE:{dx,dy,rotation}}` 使用相对块原点偏移，y 向上；
  dx/dy 落 5 raw 网格、rotation 为 0/90/180/270，并覆盖全部角色。不能与关系形式混用。

`block-apply` 已有关系求解：先放锚件，读取引脚与边界，再计算其余位置；放件后用真实
bbox 扩展避让，并在接线前检查几何。关系被跳过或约束未执行时，manifest 会列入
`NOT applied`，同时检查 warnings；不能把成功退出解释为所有原理图与 PCB 约束均已落实。
1.4 composition 则消费明确的局部几何，不会自动旋转、缩放符号或迁移分页。

## 验证与成熟度

在开发仓库先运行 `go test ./internal/blocks/` 和 `make blocks-audit`。
安装态可在 Skill 根目录运行 `python3 scripts/blocks-pin-audit.py`：默认离线，
无源码目录时从 CLI 内嵌库逐项取完整模板，不操作编辑器。

新增器件需要测量引脚时，使用专用空白测量页：

```bash
python3 scripts/blocks-pin-audit.py --probe \
  --project <scratch-project> --doc <scratch-page> --allow-clear
```

`--probe` 会清空指定页、放件、读脚、再清页，所有操作固定同一工程和页；它不会自动建页。
必须已获准清空该测量页。清页或保存失败即停止，无待测器件时不清页。
结果写入 `references/symbol-pins.json`，该文件需可写；这不是仅更新本地缓存的只读操作。

验证模板必须实际通过 `sch block-apply` 生成电路，保存 manifest，回读全部 pin→net/NC，
检查几何并运行原理图检查、显式保存。手工接线只能证明电路，不能证明模板引用与转换正确。
DRC fatal、WARN、INFO 分开报告；块级验证不等于从客户需求到 PCB 的完整验收。

新块和修订使用 `verification` 分别记录 `schematic/component_selection/pcb_drc/bringup`。
每项 status 为 `passed/failed/pending/not_tested`，`passed` 必须有 evidence；失败项附 issues。
只有四项均通过才能设 `production_ready:true`。旧 `validated` 是兼容字段，不能据此跳过
独立阶段的证据。未完成验证可以贡献草稿，但不能声称已生产验证。

## 作者、版本与提交

保留原 `author`；修订者追加到 `contributors`。`added` 记录首次版本，`updated` 记录最近
修改版本；使用 `schema_version/revision` 时一并维护。替换器件须核对引脚、封装、参数及
内部网络，不能只换器件库 key。

提交按块组织，说明来源、器件或拓扑差异、自动生成证据、验证结果及未测项目。
缺陷反馈带具体模板 ID、版本、真实引脚与 manifest 摘录；发布 issue/PR 沿用用户已有授权。
未获外发授权时先准备可审阅内容，不阻塞本地修复与验证。
