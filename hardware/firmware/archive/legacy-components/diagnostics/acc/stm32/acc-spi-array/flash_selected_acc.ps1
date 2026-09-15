[CmdletBinding()]
param(
    [ValidateRange(0, 9)]
    [int]$Acc = 0,

    [string]$BuildDirectory = "D:\study\programming\builds\ESKIN_ACC_SINGLE",

    [string]$Target = "stm32g474cetx",

    [string]$ProbeUid = ""
)

$ErrorActionPreference = "Stop"

if (-not $PSBoundParameters.ContainsKey("Acc")) {
    $answer = Read-Host "Select ACC (1-9), or 0 for the complete nine-device scan"
    $parsed = 0
    if (-not [int]::TryParse($answer, [ref]$parsed) -or $parsed -lt 0 -or $parsed -gt 9) {
        throw "Invalid ACC selection '$answer'. Enter an integer from 0 to 9."
    }
    $Acc = $parsed
}

$ProjectDirectory = $PSScriptRoot
$Toolchain = Join-Path $ProjectDirectory "cmake\gcc-arm-none-eabi.cmake"
$Elf = Join-Path $BuildDirectory "ESKIN_STM32.elf"
$CMake = (Get-Command cmake.exe -ErrorAction Stop).Source
$Ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$PyOcd = (Get-Command pyocd.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $Toolchain)) {
    throw "STM32 CMake toolchain file not found: $Toolchain"
}

$selectionText = if ($Acc -eq 0) { "all ACCs (A1-A9)" } else { "ACC$Acc only" }
Write-Host "Building $selectionText" -ForegroundColor Cyan
Write-Host "Project: $ProjectDirectory"
Write-Host "Build:   $BuildDirectory"

& $CMake `
    -S $ProjectDirectory `
    -B $BuildDirectory `
    -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$Ninja" `
    -DCMAKE_BUILD_TYPE=Debug `
    "-DACC_SELECTED=$Acc" `
    --toolchain $Toolchain
if ($LASTEXITCODE -ne 0) {
    throw "CMake configuration failed with exit code $LASTEXITCODE."
}

& $CMake --build $BuildDirectory --parallel
if ($LASTEXITCODE -ne 0) {
    throw "STM32 build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $Elf)) {
    throw "Build completed but the ELF image was not found: $Elf"
}

Write-Host "Flashing $selectionText through DAPLink at 10 kHz" -ForegroundColor Cyan
$flashArguments = @(
    "flash",
    "-t", $Target,
    "-f", "10k",
    "-M", "under-reset",
    "-e", "sector"
)
if ($ProbeUid) {
    $flashArguments += @("-u", $ProbeUid)
}
$flashArguments += $Elf

& $PyOcd @flashArguments
if ($LASTEXITCODE -ne 0) {
    throw "pyOCD flash failed with exit code $LASTEXITCODE."
}

Write-Host "Flash complete: $selectionText" -ForegroundColor Green
if ($Acc -gt 0) {
    Write-Host "PC check: read_acc_array.py --port COM9 --sensor $Acc --frames 100"
}
