param(
    [string]$IdfPath = 'C:\esp\v6.1\esp-idf',
    [string]$ToolsPath = 'C:\Espressif\tools'
)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
# Windows GCC/IDF cannot reliably handle non-ASCII project paths.
# Build an ASCII mirror; keep generated files and secrets out of Git.
$hashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($project))
$suffix = ([BitConverter]::ToString($hashBytes) -replace '-', '').Substring(0,12)
$mirror = Join-Path $env:TEMP "ai-figure-idf61-$suffix"
if ($mirror -match '[^\x00-\x7f]') { throw 'TEMP must be an ASCII path for the ESP-IDF Windows toolchain.' }
New-Item -ItemType Directory -Path $mirror -Force | Out-Null
Get-ChildItem -LiteralPath $project -File | Where-Object {
    $_.Name -notin @('sdkconfig', 'sdkconfig.old') -and $_.Extension -in @('.cpp','.h','.txt','.csv','.defaults','.lock')
} | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $mirror -Force }
Copy-Item -LiteralPath (Join-Path $project 'main') -Destination $mirror -Recurse -Force
# Do not leave deleted source files in the build: CMake lists sources explicitly.
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
Push-Location -LiteralPath $mirror
try {
    & "$env:IDF_PYTHON_ENV_PATH\Scripts\python.exe" "$IdfPath\tools\idf.py" -DIDF_TARGET=esp32c3 build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $output = Join-Path $project 'build-idf61'
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    foreach ($name in @('ai_figure.bin','ai_figure.elf','ai_figure.map','ota_data_initial.bin','flasher_args.json','flash_args')) {
        Copy-Item -LiteralPath (Join-Path $mirror "build\$name") -Destination $output -Force
    }
    foreach ($folder in @('bootloader','partition_table')) {
        New-Item -ItemType Directory -Path (Join-Path $output $folder) -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $mirror "build\$folder") -Filter '*.bin' |
            ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $output $folder) -Force }
    }
    Copy-Item -LiteralPath (Join-Path $mirror 'dependencies.lock') -Destination $project -Force
    Write-Host "Build verified with ESP-IDF 6.1.0. Flash files: $output"
    Write-Host "Full build directory: $mirror\build"
} finally { Pop-Location }
