# 远程自检包

新焊好的板子在远处的工程师手里，双方只能用文字和文件联系：没有远程桌面，现场也没有网络和服务器。这个包让现场工程师只需要双击、按回车、回答 y/n，然后把生成的 txt 发回来。所有判读都在我们这边做。

固件侧（测试项、判定规则、串口协议、构建方法）见 [`firmware/ESP32C3_HwTest/README.md`](../../firmware/ESP32C3_HwTest/README.md)。

## 目录

```
bringup/
└─ 自检包/
   ├─ 先看我-操作说明.txt     给现场工程师看的操作说明
   ├─ 1-自检.bat              刷入自检固件，逐项测试，生成 自检结果_<时间>.txt
   ├─ 2-诊断.bat              连不上板子时用：收集驱动和端口信息，测试 esptool 能否连接
   ├─ scripts/                common.ps1（公共函数）、diag.ps1、selftest.ps1
   ├─ 固件-自检/hwtest-merged.bin   由 build.ps1 复制进来（*.bin 不进 git）
   └─ esptool-windows-amd64/  esptool v5.6.0 官方 Windows 版（不进 git）
```

## 准备

1. 第一次使用时，从 <https://github.com/espressif/esptool/releases/tag/v5.6.0> 下载 `esptool-v5.6.0-windows-amd64.zip`，解压到 `自检包/esptool-windows-amd64/`，确保 `esptool.exe` 直接放在这个目录下。脚本用的是 v5 的命令写法（`write-flash`、`--before default-reset`），所以版本要对上。
2. 构建自检固件：`firmware/ESP32C3_HwTest/tools/build.ps1`。它会把 `hwtest-merged.bin` 复制进 `自检包/固件-自检/`。
3. 把整个 `自检包/` 文件夹发给现场；发之前删掉本地测试留下的 `诊断结果_*.txt` 和 `自检结果_*.txt`。现场先看《先看我-操作说明.txt》。

## 现场流程

- **1-自检.bat**：大约 3 分钟。
  - 刷机时先用 esptool 自动复位。失败后会让工程师重插 USB，最多一共尝试 3 次。
  - 3 次都失败时，引导工程师用镊子短接 TP3（BOOT）和 TP2（GND）后插上 USB，让芯片停在下载模式，再用 `--before no-reset` 刷，最多尝试 2 次。焊盘位置和步骤写在《先看我-操作说明.txt》和 `common.ps1` 的 `Show-DownloadModeSteps` 里。
  - 刷完后发 `?` 握手，然后依次测 L、S、B、M、P 五项，最后在结果文件末尾写一份汇总。
  - 人工判定的项（LED、喇叭、回放）会在结果里写成“FAIL（工程师未看到/未听到）”。
- **2-诊断.bat**：只在 1-自检.bat 连不上板子、刷不进去时使用，大约 1 分钟。
  - 收集系统版本、VID_303A 设备和驱动、带感叹号的 USB 设备、所有 COM 口及其注册表项，以及可能占用串口的程序。
  - 然后测试两项：A 用 .NET 打开端口；B 用 esptool 自动复位后执行 `flash-id`。
- 每个结果文件都会写到包的根目录。脚本结束时会打开资源管理器并选中该文件，方便工程师直接发回。

## 读结果

| 结果 | 处理 |
|---|---|
| 设备管理器里有 COM 口，但端口打不开（错误 31） | 芯片还是空的，这是正常现象。用 esptool 自动复位烧录；不要用 flash_download_tool |
| 刷机失败（自动方式和镊子方式都失败） | 换 USB 线，或者关掉占用串口的软件后再试一次；还不行就跑 2-诊断.bat |
| `audio=0` | I2S 初始化失败，属于固件问题 |
| 喇叭不响或按键没反应 | 把结果文件发回给硬件负责人 |

## 写脚本时的约束

- 现场电脑是 Windows 11，脚本按系统自带的 Windows PowerShell 5.1 来写。
- `.ps1` 文件必须保存为 UTF-8 带 BOM，否则 5.1 会按 ANSI 读取，中文会乱码。
- `.bat` 只用 ASCII 字符，只负责调用 `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\xxx.ps1"`，然后 `pause`。
- 输出用 `Log` 函数，会同时写到屏幕和结果文件；给工程师的操作提示用 `Ask`，只显示，不写进日志。
- 端口按 VID_303A 自动识别。工程师直接按回车会重新扫描；只有输入数字时，才当作手动指定的端口。
- 回答 y/n 时先做 NFKC 归一化，所以中文输入法打出的全角 ｙ/ｎ 也能识别。
