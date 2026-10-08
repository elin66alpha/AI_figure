# easyeda CLI

- `easyeda.exe`：easyeda-agent **v1.8.0**，Windows x64。本项目全程用它，配合 EasyEDA Pro 4.1.60 里的 1.8.0 连接器扩展。
  - 原安装位置 `C:\Users\liupp\.local\bin\easyeda.exe`，不在 PATH 里。
  - `hardware/eda-tools/easyeda.exe` 是另一个 v1.8.1 的二进制，`checksums-v1.8.1-release.txt` 是那个版本的发布校验和，对应的是 v1.8.1，不是这里的 exe。
- `actions-catalog-v1.8.0.txt`：`easyeda actions` 的完整输出，列出所有 typed action 的输入、输出和说明。查某个功能有没有接口，先搜这个文件。
- `eda-api-primitives.txt`：EasyEDA Pro `eda.*` API 原语清单。
- `transport-v1.8.0.ts`：连接器与 daemon 之间的传输协议源码，供参考。

常用命令（PowerShell）：

```powershell
$e = "C:\path\to\easyeda.exe"
& $e daemon start                       # 前台阻塞，放后台跑
& $e health                             # 看 windows[] 里是否有目标工程/文档
& $e pcb dump --project <UUID> --include-copper --out board.json
& $e apply x.apply.json --project <UUID> --yes
& $e doc reload --project <UUID>; & $e pcb pour-rebuild --project <UUID>; & $e pcb save --project <UUID>
& $e pcb drc --project <UUID> --json
& $e call <action> --project <UUID> --payload '{...}'
& $e daemon stop
```

连接器扩展的安装和启用（“允许外部交互”）见 `../easyeda-agent-skill/references/environment-setup.md`。
