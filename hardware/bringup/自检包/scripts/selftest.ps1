# 自检：刷入离线自检固件（firmware/ESP32C3_HwTest），逐项测 LED、喇叭、按键、麦克风、电池/USB。
# 板子每收到一个命令字母跑一项，结束时打印 "[DONE] <字母>"；能自己判定的项打印 "[RESULT] ..."。
. (Join-Path $PSScriptRoot 'common.ps1')
New-Log '自检结果'

$bin = Join-Path $KitRoot '固件-自检\hwtest-merged.bin'
$results = [ordered]@{}

function Ask-YesNo([string]$question) {
    while ($true) {
        # NFKC 把中文输入法打出的全角 ｙ／ｎ 变成半角
        $a = (Read-Host "$question  请输入 y（是）或 n（否），然后按回车").Normalize([Text.NormalizationForm]::FormKC).Trim().ToLower()
        if ($a -in @('y', 'yes', '是', '有', '对')) { Log "问：$question  答：是"; return $true }
        if ($a -in @('n', 'no', '否', '没有', '不是', '没')) { Log "问：$question  答：否"; return $false }
        Write-Host '只能输入 y 或 n。' -ForegroundColor Yellow
    }
}

function Open-Board([string]$port) {
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        $sp = New-Object System.IO.Ports.SerialPort $port, 115200
        $sp.DtrEnable = $false
        $sp.RtsEnable = $false
        $sp.ReadTimeout = 500
        $sp.NewLine = "`n"
        $sp.Encoding = [Text.Encoding]::UTF8
        try { $sp.Open(); return $sp } catch { $sp.Dispose(); Start-Sleep -Milliseconds 500 }
    }
    return $null
}

# 读板子输出直到出现 pattern 或超时；每行都写进日志。返回读到的所有行。
function Read-Until($sp, [string]$pattern, [int]$timeoutSec) {
    $lines = @()
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $l = $sp.ReadLine().TrimEnd("`r")
        } catch [TimeoutException] {
            continue
        } catch {
            Log "  串口断开：$($_.Exception.Message)" 'Red'
            break
        }
        if ($l -eq '') { continue }
        Log "  板子> $l"
        $lines += $l
        if ($l -match $pattern) { break }
    }
    return $lines
}

function Run-Test($sp, [string]$letter, [int]$timeoutSec) {
    $sp.DiscardInBuffer()
    $sp.Write($letter)
    $lines = @(Read-Until $sp "^\[DONE\] $letter" $timeoutSec)
    if (-not ($lines | Where-Object { $_ -match "^\[DONE\] $letter" })) {
        Log "  第 $letter 项没有在 $timeoutSec 秒内结束。" 'Red'
    }
    return $lines
}

function Get-Result([string[]]$lines, [string]$name) {
    foreach ($l in $lines) {
        if ($l -match "^\[RESULT\] $name (PASS|FAIL)(.*)$") { return @($Matches[1], $Matches[2].Trim()) }
    }
    return @('无响应', '')
}

Section '检查文件'
$esptool = Find-Esptool
if (-not $esptool) { Log '没有在工具包文件夹里找到 esptool.exe，无法继续。' 'Red'; Finish '自检中止：缺少 esptool.exe。'; exit 1 }
Log "esptool：$esptool"
if (-not (Test-Path $bin)) { Log '缺少文件：固件-自检\hwtest-merged.bin' 'Red'; Finish '自检中止：缺少自检固件。'; exit 1 }
$fi = Get-Item $bin
Log "自检固件：$($fi.Name)  $($fi.Length) 字节  $($fi.LastWriteTime)"

Ask @(
    '第 1 步：把板子用 USB 线插到这台电脑上。',
    '  - 不要短接任何焊盘，正常插上就行。插上后等 5 秒。'
)

Section '刷入自检固件'
$port = Select-Port
$flashArgs = @('write-flash', '0x0', $bin)
$code = Invoke-Esptool $esptool (@('--chip', 'esp32c3', '-p', $port, '-b', '460800', '--before', 'default-reset', '--after', 'hard-reset') + $flashArgs)
# 失败后重插 USB 再自动重试，一共 3 次。
for ($attempt = 2; $code -ne 0 -and $attempt -le 3; $attempt++) {
    Log "第 $($attempt - 1) 次没有成功，重插 USB 线后再试。" 'Yellow'
    Ask @('请拔掉 USB 线，等 3 秒，再插上，然后等 5 秒。', '（不要短接任何焊盘。）')
    $port = Select-Port
    $code = Invoke-Esptool $esptool (@('--chip', 'esp32c3', '-p', $port, '-b', '460800', '--before', 'default-reset', '--after', 'hard-reset') + $flashArgs)
}
# 3 次都失败：用镊子短接 BOOT/GND 进手动下载模式，芯片已经停在下载模式，所以 esptool 不再复位它。
for ($attempt = 1; $code -ne 0 -and $attempt -le 2; $attempt++) {
    Log "自动方式刷不进去，改用镊子进入下载模式（第 $attempt 次）。" 'Yellow'
    Show-DownloadModeSteps
    Start-Sleep -Seconds 2
    $port = Select-Port
    $code = Invoke-Esptool $esptool (@('--chip', 'esp32c3', '-p', $port, '-b', '460800', '--before', 'no-reset', '--after', 'hard-reset') + $flashArgs)
}
if ($code -ne 0) { Finish '自检中止：自检固件刷不进去（自动方式和镊子方式都失败）。'; exit 1 }
Log '自检固件刷入成功。' 'Green'

Section '连接板子'
Start-Sleep -Seconds 3
$port = Select-Port
$sp = Open-Board $port
if (-not $sp) { Log "打不开 $port。" 'Red'; Finish '自检中止：连不上板子。'; exit 1 }
$ready = $false
for ($i = 0; $i -lt 15 -and -not $ready; $i++) {
    $sp.Write('?')
    $ready = [bool](@(Read-Until $sp '^\[HWTEST\] READY' 1) | Where-Object { $_ -match '^\[HWTEST\] READY' })
}
if (-not $ready) { $sp.Close(); Log '板子没有回应 READY。' 'Red'; Finish '自检中止：自检固件没有响应。'; exit 1 }
Log '板子已就绪。' 'Green'

Section '测试 1：LED'
Ask @('眼睛看着板子正面的红色 LED。', '按回车后，LED 会“亮 1 秒、灭 1 秒”，一共 3 次。')
[void](Run-Test $sp 'L' 15)
$results['LED'] = if (Ask-YesNo 'LED 是否亮灭了 3 次？') { 'PASS' } else { 'FAIL（工程师未看到）' }

Section '测试 2：喇叭'
Ask @('耳朵靠近喇叭。', '按回车后，喇叭会依次响 3 个音：低、中、高，每个约半秒。')
[void](Run-Test $sp 'S' 15)
$results['喇叭'] = if (Ask-YesNo '是否听到了 3 个由低到高的音？') { 'PASS' } else { 'FAIL（工程师未听到）' }

Section '测试 3：按键'
Ask @('按回车后，在 20 秒之内：按一下按键，再松开。', '（按住时 LED 会亮，松开后灭。）')
$r = Get-Result (Run-Test $sp 'B' 30) 'BTN'
$results['按键'] = ($r[0] + ' ' + $r[1]).Trim()

Section '测试 4：麦克风（录音后回放）'
Ask @(
    '按回车后，按下面的顺序做：',
    '  1. 先保持安静，不要说话（约 2 秒）。',
    '  2. 听到“嘀”一声、同时 LED 亮起后，对着麦克风大声说话或拍手，持续 3 秒。',
    '  3. 再听到“嘀”一声（LED 灭）就停下。',
    '  4. 接着喇叭会把刚才录到的声音放出来。',
    '  （如果喇叭不响，就看 LED：LED 亮的那 3 秒就是该说话的时候。）'
)
$micLines = Run-Test $sp 'M' 40
$r = Get-Result $micLines 'MIC'
$results['麦克风（自动判定）'] = ($r[0] + ' ' + $r[1]).Trim()
$results['麦克风回放（人工）'] = if (Ask-YesNo '回放时是否听到了刚才说的话或拍手声？') { 'PASS' } else { 'FAIL（工程师未听到）' }

Section '测试 5：电池电压和 USB 检测'
$hasBattery = Ask-YesNo '现在板子接了电池吗？'
$pwrLines = Run-Test $sp 'P' 20
$r = Get-Result $pwrLines 'USB'
$results['USB 插入检测'] = ($r[0] + ' ' + $r[1]).Trim()
$vbat = $pwrLines | Where-Object { $_ -match '^\[RESULT\] VBAT min=(-?\d+) max=(-?\d+)' } | Select-Object -First 1
if ($vbat -and ($vbat -match 'min=(-?\d+) max=(-?\d+)')) {
    $vmin = [int]$Matches[1]; $vmax = [int]$Matches[2]
    if ($hasBattery) {
        $ok = $vmin -ge 3000 -and $vmax -le 4300
        $results['电池电压'] = $(if ($ok) { 'PASS' } else { 'FAIL' }) + " （$vmin~$vmax mV，正常范围 3000~4300）"
    } else {
        $results['电池电压'] = "不判定（没接电池，读数 $vmin~$vmax mV 没有意义）"
    }
} else {
    $results['电池电压'] = '无响应'
}
$sp.Close()
$sp.Dispose()

Section '汇总'
foreach ($k in $results.Keys) {
    $v = $results[$k]
    $c = if ($v -like 'PASS*') { 'Green' } elseif ($v -like '不判定*') { 'Yellow' } else { 'Red' }
    Log ("{0}：{1}" -f $k, $v) $c
}

Ask @(
    '自检结束，可以拔掉 USB 线。',
    '板子里现在是自检程序，下次运行 1-自检.bat 会重新刷一遍，不用管它。'
)
Finish '自检完成。'
