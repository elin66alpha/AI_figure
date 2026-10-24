param(
    [string]$IdfPath = 'C:\esp\v6.1\esp-idf',
    [string]$ToolsPath = 'C:\Espressif\tools'
)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$appDir = [IO.Path]::GetFullPath((Join-Path $project '..\ESP32C3_AI_Voice'))
# Windows GCC/IDF cannot reliably handle non-ASCII project paths: build an ASCII mirror.
# The mirror keeps the ../ESP32C3_AI_Voice layout main/CMakeLists.txt expects, but holds only
# the reused drivers, so secrets.h can never reach the self-test image.
$hashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($project))
$suffix = ([BitConverter]::ToString($hashBytes) -replace '-', '').Substring(0,12)
$root = Join-Path $env:TEMP "ai-figure-hwtest-$suffix"
if ($root -match '[^\x00-\x7f]') { throw 'TEMP must be an ASCII path for the ESP-IDF Windows toolchain.' }
$mirror = Join-Path $root 'ESP32C3_HwTest'
$appMirror = Join-Path $root 'ESP32C3_AI_Voice'
New-Item -ItemType Directory -Path $mirror, $appMirror -Force | Out-Null
foreach ($name in @('CMakeLists.txt', 'sdkconfig.defaults', 'hwtest_main.cpp')) {
    Copy-Item -LiteralPath (Join-Path $project $name) -Destination $mirror -Force
}
Copy-Item -LiteralPath (Join-Path $project 'main') -Destination $mirror -Recurse -Force
Get-ChildItem -LiteralPath $appMirror -File | Remove-Item -Force
foreach ($name in @('audio_io.cpp','audio_io.h','pdm_filter.cpp','pdm_filter.h','cue.cpp','cue.h',
                    'led.cpp','led.h','button.cpp','button.h','config.h','platform.h')) {
    Copy-Item -LiteralPath (Join-Path $appDir $name) -Destination $appMirror -Force
}
$env:IDF_PATH = $IdfPath
$env:IDF_TOOLS_PATH = $ToolsPath
$env:IDF_PYTHON_ENV_PATH = Join-Path $ToolsPath 'python\v6.1\venv'
$env:IDF_COMPONENT_LOCAL_STORAGE_URL = "file://$ToolsPath"
$env:ESP_ROM_ELF_DIR = Join-Path $ToolsPath 'esp-rom-elfs\20241011'
$env:ESP_IDF_VERSION = '6.1'
$env:IDF_VERSION = '6.1.0'
$env:PYTHONUTF8 = '1'
$env:PATH = @(
    "$env:IDF_PYTHON_ENV_PATH\Scripts",
    (Join-Path $ToolsPath 'cmake\4.0.3\bin'),
    (Join-Path $ToolsPath 'ninja\1.12.1'),
    (Join-Path $ToolsPath 'riscv32-esp-elf\esp-15.2.0_20251204\riscv32-esp-elf\bin'),
    $env:PATH
) -join ';'
$python = "$env:IDF_PYTHON_ENV_PATH\Scripts\python.exe"
Push-Location -LiteralPath $mirror
try {
    & $python "$IdfPath\tools\idf.py" -DIDF_TARGET=esp32c3 build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    # One image from 0x0 (bootloader + partition table + app) so the remote kit flashes a single file.
    # It needs its own name: merge-bin reads build\hwtest.bin and must not overwrite it.
    & $python "$IdfPath\tools\idf.py" merge-bin -o hwtest-merged.bin
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $output = Join-Path $project 'build-idf61'
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    foreach ($name in @('hwtest-merged.bin', 'hwtest.bin', 'hwtest.elf', 'hwtest.map')) {
        Copy-Item -LiteralPath (Join-Path $mirror "build\$name") -Destination $output -Force
    }
    # selftest.ps1 flashes 自检包\固件-自检\hwtest-merged.bin, so the kit always carries this build.
    $kitFw = [IO.Path]::GetFullPath((Join-Path $project '..\..\hardware\bringup\自检包\固件-自检'))
    New-Item -ItemType Directory -Path $kitFw -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $output 'hwtest-merged.bin') -Destination $kitFw -Force
    Write-Host "Build verified with ESP-IDF 6.1.0. Merged image: $output\hwtest-merged.bin (flash at 0x0), copied to $kitFw"
} finally { Pop-Location }
