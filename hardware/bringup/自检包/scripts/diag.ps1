# 诊断：收集驱动/端口信息，测试端口能否打开、esptool 能否自动复位进下载模式并读出芯片信息。
# 只测自动复位。镊子短接 TP3(BOOT)/TP2(GND) 的手动下载模式由 1-自检.bat 在自动方式失败后引导。
. (Join-Path $PSScriptRoot 'common.ps1')
New-Log '诊断结果'

Write-Host ''
Write-Host '诊断开始。屏幕上出现黄色文字时，按文字做完再按回车。' -ForegroundColor Cyan
Write-Host '全程大约 1 分钟，中途不要关闭这个窗口。' -ForegroundColor Cyan

Section '电脑信息'
$os = Get-CimInstance Win32_OperatingSystem
Log "系统：$($os.Caption)  版本 $($os.Version)  $($os.OSArchitecture)"
Log "PowerShell：$($PSVersionTable.PSVersion)"

$esptool = Find-Esptool
if (-not $esptool) {
    Log '没有在工具包文件夹里找到 esptool.exe，无法继续。' 'Red'
    Finish '诊断中止：缺少 esptool.exe。'
    exit 1
}
Log "esptool：$esptool"
& $esptool version 2>&1 | ForEach-Object { Log ("  " + "$_") }

Ask @(
    '第 1 步：把板子用 USB 线插到这台电脑上。',
    '  - 不要短接任何焊盘，正常插上就行。',
    '  - 插上后等 5 秒。'
)

Section '乐鑫 USB 设备（VID_303A）'
try {
    $dev = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object InstanceId -match 'VID_303A')
    if ($dev.Count -eq 0) { Log '没有找到任何 VID_303A 设备。' 'Red' }
    foreach ($d in $dev) {
        Log "[$($d.Status)] 类别=$($d.Class)  名称=$($d.FriendlyName)"
        Log "      InstanceId=$($d.InstanceId)"
    }
} catch {
    Log "Get-PnpDevice 不可用：$($_.Exception.Message)" 'Yellow'
}

Section '这些设备用的驱动'
Get-CimInstance Win32_PnPEntity | Where-Object DeviceID -match 'VID_303A' | ForEach-Object {
    Log "$($_.Name)  服务=$($_.Service)  状态=$($_.Status)  错误码=$($_.ConfigManagerErrorCode)"
}
Get-CimInstance Win32_PnPSignedDriver | Where-Object DeviceID -match 'VID_303A' | ForEach-Object {
    Log "$($_.DeviceName)  提供商=$($_.DriverProviderName)  版本=$($_.DriverVersion)  INF=$($_.InfName)"
}

Section '有问题的 USB 设备（设备管理器里带感叹号的）'
$bad = @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.DeviceID -match '^USB' })
if ($bad.Count -eq 0) { Log '无' }
foreach ($b in $bad) { Log "$($b.Name)  错误码=$($b.ConfigManagerErrorCode)  $($b.DeviceID)" }

Section '电脑上所有 COM 口'
Get-CimInstance Win32_PnPEntity | Where-Object Name -match '\(COM\d+\)' | ForEach-Object {
    Log "$($_.Name)  服务=$($_.Service)  $($_.DeviceID)"
}
try {
    $reg = Get-ItemProperty 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM' -ErrorAction Stop
    $reg.PSObject.Properties | Where-Object Name -notmatch '^PS' | ForEach-Object { Log "注册表 SERIALCOMM：$($_.Name) = $($_.Value)" }
} catch { Log '注册表 SERIALCOMM：读不到' }

Section '可能占用串口的程序'
$suspects = 'putty|sscom|xcom|teraterm|ttermpro|mobaxterm|arduino|cura|prusa|flash_download|esptool|serial|uart|idf|vofa|llcom|sscom|串口'
$procs = @(Get-Process | Where-Object { $_.ProcessName -match $suspects } | Select-Object -ExpandProperty ProcessName -Unique)
if ($procs.Count -eq 0) { Log '无' } else { Log ($procs -join ', ') 'Yellow' }

Section '测试 A：正常插入时打开端口'
$port = Select-Port
$openA = Test-PortOpen $port

Section '测试 B：正常插入，esptool 自动进下载模式并读取芯片信息'
$codeB = Invoke-Esptool $esptool @('--chip', 'esp32c3', '-p', $port, 'flash-id')

Section '汇总'
Log ("测试 A 打开端口（正常）：" + $(if ($openA) { '成功' } else { '失败' }))
Log ("测试 B esptool（自动复位）：" + $(if ($codeB -eq 0) { '成功' } else { '失败' }))

Ask @('诊断已结束。请拔掉 USB 线。')
Finish '诊断完成。'
