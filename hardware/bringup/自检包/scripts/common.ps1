# 公共函数：日志、找 esptool、找 COM 口、打开端口测试。由 diag.ps1 / selftest.ps1 引用。
# 必须兼容 Windows PowerShell 5.1（Win10 自带），文件需存为 UTF-8 带 BOM。

$ErrorActionPreference = 'Continue'
$KitRoot = Split-Path -Parent $PSScriptRoot
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = 'utf-8'

function New-Log([string]$prefix) {
    $script:LogFile = Join-Path $KitRoot ("{0}_{1}.txt" -f $prefix, (Get-Date -Format 'yyyyMMdd_HHmmss'))
    Set-Content -Path $script:LogFile -Value "# $prefix  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8
}

function Log([string]$text, [string]$color = '') {
    if ($color) { Write-Host $text -ForegroundColor $color } else { Write-Host $text }
    Add-Content -Path $script:LogFile -Value $text -Encoding UTF8
}

function Section([string]$title) {
    Log ''
    Log ('=' * 60)
    Log "== $title"
    Log ('=' * 60)
}

# 给现场工程师看的操作提示：只显示，不进日志
function Ask([string[]]$lines) {
    Write-Host ''
    Write-Host ('-' * 60) -ForegroundColor Yellow
    foreach ($l in $lines) { Write-Host $l -ForegroundColor Yellow }
    Write-Host ('-' * 60) -ForegroundColor Yellow
    [void](Read-Host '做完以后按 回车键 继续')
}

function Find-Esptool {
    $exe = Get-ChildItem -Path $KitRoot -Filter 'esptool.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) { return $exe.FullName }
    return $null
}

# 返回 ESP32 原生 USB（VID 303A）对应的 COM 口列表，例如 @('COM6')
function Get-EspPorts {
    $ports = @()
    Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -match 'VID_303A' -and $_.Name -match '\((COM\d+)\)' } |
        ForEach-Object { if ($_.Name -match '\((COM\d+)\)') { $ports += $Matches[1] } }
    return $ports
}

# 自动找 COM 口；找不到或有多个时让工程师输入
function Select-Port([int]$waitSeconds = 10) {
    $ports = @()
    for ($i = 0; $i -lt $waitSeconds; $i++) {
        $ports = @(Get-EspPorts)
        if ($ports.Count -gt 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($ports.Count -eq 1) {
        Log "自动识别到板子的端口：$($ports[0])"
        return $ports[0]
    }
    if ($ports.Count -gt 1) {
        Log "识别到多个乐鑫端口：$($ports -join ', ')" 'Yellow'
    } else {
        Log '没有自动识别到板子的端口（VID_303A）。' 'Yellow'
    }
    # 空输入 = 工程师刚插好线，重新自动查找；只有输入了数字才当作手动指定的端口
    while ($true) {
        Write-Host '请确认 USB 线已经插好。' -ForegroundColor Yellow
        Write-Host '  - 插好了就直接按回车，程序会重新查找；' -ForegroundColor Yellow
        Write-Host '  - 或者打开“设备管理器”→“端口(COM 和 LPT)”，看板子是 COM 几，只输入数字（COM6 就输入 6）再按回车。' -ForegroundColor Yellow
        $n = (Read-Host '请操作') -replace '\D', ''
        if ($n) {
            $port = 'COM' + $n
            Log "工程师手动输入的端口：$port"
            return $port
        }
        $ports = @(Get-EspPorts)
        if ($ports.Count -ge 1) {
            Log "重新查找到板子的端口：$($ports[0])"
            return $ports[0]
        }
        Log '仍然没有找到板子的端口。' 'Yellow'
    }
}

# 用 .NET 直接打开端口再关闭，和烧录工具无关，用来判断端口本身能不能打开
function Test-PortOpen([string]$port) {
    $p = New-Object System.IO.Ports.SerialPort $port, 115200
    $p.DtrEnable = $false
    $p.RtsEnable = $false
    try {
        $p.Open()
        $p.Close()
        Log "打开 $port ：成功" 'Green'
        return $true
    } catch {
        $msg = $_.Exception.Message
        if ($_.Exception.InnerException) { $msg += ' | ' + $_.Exception.InnerException.Message }
        Log "打开 $port ：失败 —— $msg" 'Red'
        return $false
    } finally {
        $p.Dispose()
    }
}

# 运行 esptool，输出同时显示并写进日志，返回退出码
function Invoke-Esptool([string]$exe, [string[]]$arguments) {
    Log ("> esptool " + ($arguments -join ' '))
    & $exe @arguments 2>&1 | ForEach-Object { Log ("  " + "$_") }
    $code = $LASTEXITCODE
    Log "esptool 退出码：$code"
    return $code
}

# 手动下载模式：BOOT(TP3) 接 GND(TP2) 的同时上电，芯片停在下载模式。自动复位刷不进去时才用。
function Show-DownloadModeSteps {
    Ask @(
        '现在要用镊子让芯片进入“下载模式”，请严格按顺序做：',
        '',
        '  1. 拔掉 USB 线。如果板子接了电池，把电池插头也拔掉（板子要完全断电）。',
        '  2. 用镊子把 TP3（BOOT）和 TP2（GND）两个焊盘连在一起，一直按住不要松。',
        '     位置：板子背面（有 USB-C 口的一面），天线那头朝上，',
        '     左边缘靠上有竖排 3 个小方焊盘，从上往下是 TP1、TP2、TP3。',
        '     要连的是 中间(TP2) 和 最下面(TP3)。',
        '  3. 镊子按住不松的同时，插上 USB 线（可以请同事帮忙插）。',
        '  4. 插上后再等 2 秒，然后松开镊子。',
        '',
        '  注意：不要碰最上面的 TP1。'
    )
}

function Finish([string]$message) {
    Log ''
    Log $message 'Cyan'
    Write-Host ''
    Write-Host "结果文件：$script:LogFile" -ForegroundColor Cyan
    Write-Host '请把这个文件原样发回给我们（文件夹会自动打开，文件已选中）。' -ForegroundColor Cyan
    Start-Process explorer.exe -ArgumentList "/select,`"$script:LogFile`""
}
