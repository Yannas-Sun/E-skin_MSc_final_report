[CmdletBinding()]
param(
    [string]$BuildDirectory = "D:\study\programming\builds\ESKIN_ACC_SCK_SLOW",
    [string]$Target = "stm32g474cetx",
    [string]$ProbeUid = ""
)

$ErrorActionPreference = "Stop"
$ProjectDirectory = $PSScriptRoot
$Toolchain = Join-Path $ProjectDirectory "cmake\gcc-arm-none-eabi.cmake"
$Elf = Join-Path $BuildDirectory "ESKIN_STM32.elf"
$CMake = (Get-Command cmake.exe -ErrorAction Stop).Source
$Ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$PyOcd = (Get-Command pyocd.exe -ErrorAction Stop).Source

Write-Host "Building ACC slow-SCK continuity test" -ForegroundColor Cyan
& $CMake -S $ProjectDirectory -B $BuildDirectory -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$Ninja" -DCMAKE_BUILD_TYPE=Debug `
    --toolchain $Toolchain
if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed: $LASTEXITCODE" }

& $CMake --build $BuildDirectory --parallel
if ($LASTEXITCODE -ne 0) { throw "STM32 build failed: $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $Elf)) { throw "ELF not found: $Elf" }

$flashArguments = @("flash", "-t", $Target, "-f", "10k", "-M", "under-reset", "-e", "sector")
if ($ProbeUid) { $flashArguments += @("-u", $ProbeUid) }
$flashArguments += $Elf

Write-Host "Flashing through DAPLink at 10 kHz" -ForegroundColor Cyan
& $PyOcd @flashArguments
if ($LASTEXITCODE -ne 0) { throw "pyOCD flash failed: $LASTEXITCODE" }

Write-Host "Flash complete: SCK is LOW for 1 s, then HIGH for 1 s" -ForegroundColor Green
