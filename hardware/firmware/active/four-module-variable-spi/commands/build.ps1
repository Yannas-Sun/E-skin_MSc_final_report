param(
    [ValidateSet('All', 'STM32', 'Teensy')][string]$Target = 'All',
    [ValidateRange(0, 1000)][int]$ScanHz = 200
)

$ErrorActionPreference = 'Stop'
$protocolRoot = Split-Path -Parent $PSScriptRoot
function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool '$Name' was not found on PATH. Install it and add its executable directory to PATH."
    }
}

if ($Target -in @('All', 'STM32')) {
    Assert-Command 'cmake'
    Assert-Command 'ninja'
    Assert-Command 'arm-none-eabi-gcc'
}

if ($Target -in @('All', 'Teensy')) {
    Assert-Command 'arduino-cli'
}

if ($Target -in @('All', 'STM32')) {
    $sourceDirectory = Join-Path $protocolRoot 'stm32\combined-system'
    $buildDirectory = Join-Path $sourceDirectory 'build\Release'
    & cmake --fresh -S $sourceDirectory -B $buildDirectory -G Ninja `
        '-DCMAKE_BUILD_TYPE=Release' `
        "-DCMAKE_TOOLCHAIN_FILE=$sourceDirectory\cmake\gcc-arm-none-eabi.cmake"
    if ($LASTEXITCODE -ne 0) { throw 'STM32 configure failed.' }
    & cmake --build $buildDirectory -j 4
    if ($LASTEXITCODE -ne 0) { throw 'STM32 build failed.' }
}

if ($Target -in @('All', 'Teensy')) {
    & arduino-cli compile --fqbn 'teensy:avr:teensy41' `
        --build-path (Join-Path $protocolRoot 'build\teensy') `
        --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 -DESKIN_DEFAULT_SCAN_HZ=$ScanHz" `
        (Join-Path $protocolRoot 'teensy\four_module')
    if ($LASTEXITCODE -ne 0) { throw 'Teensy build failed.' }
}
Write-Host 'Build complete. No device was flashed.'
