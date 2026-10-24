# 离线硬件自检固件 · hwtest-1

用来确认一块新焊好的板子硬件正常：LED、喇叭、按键、PDM 麦克风、电池电压和 USB 检测。不连 WiFi，也不需要服务器。Wi-Fi 由生产固件验证。

音频、LED、按键和提示音直接编译 `../ESP32C3_AI_Voice` 里的生产源文件（`audio_io`、`pdm_filter`、`cue`、`led`、`button`），不做修改。所以自检通过，就说明生产驱动在这块板子上能正常工作。引脚全部来自生产的 `config.h`。构建镜像里不含 `secrets.h`。

PC 端由远程自检包 `hardware/bringup/自检包/1-自检.bat` 驱动，准备和现场使用流程见 [`hardware/bringup/README.md`](../../hardware/bringup/README.md)。

## 测试项和判定

| 命令 | 测试 | 板子做什么 | 判定 |
|---|---|---|---|
| `L` | LED | 亮 1 s、灭 1 s，重复 3 次 | 人工：看到 3 次亮灭 |
| `S` | 喇叭 | 依次播 500 / 1000 / 2000 Hz，各 0.6 s | 人工：听到 3 个音。`tx underruns=0` 只说明 I2S 数据送出去了，不能说明喇叭响了 |
| `B` | 按键 | 20 s 内等一次按下和松开，按住时 LED 亮 | 自动：`BTN PASS`；开始前已经是低电平则 `FAIL stuck_low`，超时则 `FAIL no_press` / `no_release` |
| `M` | 麦克风 | 安静 1.5 s →“嘀”→ LED 亮，录 3 s →“嘀”→ 回放 | 自动：见下文；回放听不听得到由人工判定 |
| `P` | 电源 | 每秒采样 1 次，共 5 次：VBAT（GPIO1）和 VBUS 检测（GPIO20） | 自动：5 次都检测到 USB 才算 `USB PASS`；电池电压由脚本判定（接了电池时应在 3000~4300 mV） |

麦克风按顺序判定，命中第一条就 FAIL：

1. `no_data`：任一阶段收到的样本不足一半，说明 I2S RX 没有数据。
2. `flat_signal`：两个阶段的峰峰值都小于 8，说明 CLK 或 DATA 没接通，读到的是常数。
3. `no_level_change`：说话阶段的 RMS 不到安静阶段的 3.16 倍（10 dB）。
4. `too_quiet`：说话阶段的峰值小于 500。

回放前把峰值归一化到约 0.6 FS（`cue.cpp` 验证过的电平），最大只放大 32 倍，避免把底噪放成很响的噪声。

## 串口协议

走 USB-Serial-JTAG（芯片原生 USB，VID 303A）。波特率可以随便设，因为它是虚拟串口。DTR/RTS 保持为 false，否则打开端口时会复位芯片。

- 上电后打印 `[HWTEST] READY hwtest-1 audio=<0|1>`。`audio=0` 表示 I2S 初始化失败，此时 `S` 和 `M` 直接报错。
- 收到 `?` 时重新打印 READY 行。PC 端打开端口后，靠反复发 `?` 来握手。
- 每个命令是一个字母。命令执行完一定会打印 `[DONE] <字母>`。能自动判定的项会在 DONE 之前打印 `[RESULT] <名称> PASS|FAIL [原因]`。
- 其他字符（包括换行）一律忽略，所以用任意串口终端手动输入字母也能测。
- 一次只执行一个命令。命令执行期间收到的字符会在它结束后才被读取。

`selftest.ps1` 等待每项结束的上限：L 15 s、S 15 s、B 30 s、M 40 s、P 20 s。

## 构建

ESP-IDF 6.1.0，目标 esp32c3。本机 IDF 路径为 `C:\esp\v6.1\esp-idf`，工具在 `C:\Espressif\tools`，与生产固件相同。在本目录运行：

```powershell
.\tools\build.ps1
```

仓库路径里有中文，Windows 下的 IDF 工具链处理不了：kconfgen 会按 GBK 解码失败，链接规格文件也会生成失败。所以脚本先把源文件复制到 `%TEMP%\ai-figure-hwtest-<hash>` 这个英文路径下，并设置 `PYTHONUTF8=1` 再构建。复制时只带上复用的驱动和 `config.h`、`platform.h`，`secrets.h` 不会进入临时目录。

产物：

- `build-idf61/hwtest-merged.bin`：引导程序、分区表和应用合成的单个镜像，从 `0x0` 烧录。脚本会同时把它复制到 `hardware/bringup/自检包/固件-自检/`。
- `build-idf61/hwtest.bin` / `.elf` / `.map`：用于调试和查看代码体积。

`idf.py merge-bin` 的输出必须另起名字。用 `-o hwtest.bin` 会把自己的输入文件覆盖掉，生成一个损坏的 128 KB 镜像。

改版本时，`CMakeLists.txt` 里的 `PROJECT_VER` 和 `hwtest_main.cpp` 里的 `HWTEST_VERSION` 要同时改。

## 不用自检包，手动烧录

```powershell
esptool --chip esp32c3 -p COMx -b 460800 --before default-reset --after hard-reset write-flash 0x0 build-idf61\hwtest-merged.bin
```

全新芯片也用这条命令：esptool 默认通过 USB 自动复位进入下载模式。自动复位不成功时，先拔掉 USB，用镊子短接 TP3（BOOT）和 TP2（GND），按住的同时插上 USB，2 秒后松开，再把命令里的 `--before default-reset` 换成 `--before no-reset` 重刷。

自检固件只响应串口命令，不插 PC 时什么也不做。测完后要恢复成产品，重新烧录生产固件即可（见 `../ESP32C3_AI_Voice/README.md`）。

## 增加一项测试

1. 固件：在 `app_main` 的 `switch` 里加一个新字母。测试函数结束后打印 `[DONE] <字母>`；能自动判定的，在 DONE 之前打印 `[RESULT] <名称> PASS|FAIL <原因>`。
2. 脚本：在 `selftest.ps1` 里加一节，用 `Run-Test` 发出该字母并设好超时，用 `Get-Result` 读取判定，或用 `Ask-YesNo` 问工程师，然后把结果写进 `$results`。
3. 重新构建，`build.ps1` 会把新镜像复制进自检包。
