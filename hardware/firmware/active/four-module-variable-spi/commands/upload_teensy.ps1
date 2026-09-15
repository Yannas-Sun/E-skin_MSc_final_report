param(
    [string]$Port = 'COM9',
    [ValidateRange(0, 1000)][int]$ScanHz = 200
)

$ErrorActionPreference = 'Stop'
$protocolRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'build.ps1') -Target Teensy -ScanHz $ScanHz
& arduino-cli upload --port $Port --fqbn 'teensy:avr:teensy41' `
    --input-dir (Join-Path $protocolRoot 'build\teensy')
if ($LASTEXITCODE -ne 0) { throw 'Teensy upload failed.' }
Write-Host 'Teensy upload complete. Use matching STM32 firmware on every connected module.'
