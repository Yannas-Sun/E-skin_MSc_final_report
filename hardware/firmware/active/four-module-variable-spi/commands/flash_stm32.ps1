param(
    [Parameter(Mandatory = $true)][string]$ProbeUid,
    [string]$SwdSpeed = '1M'
)

$ErrorActionPreference = 'Stop'
$protocolRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command pyocd -ErrorAction SilentlyContinue)) {
    throw "Required tool 'pyocd' was not found on PATH. Install pyOCD and add its executable directory to PATH."
}
& (Join-Path $PSScriptRoot 'build.ps1') -Target STM32
$firmwareFile = Join-Path $protocolRoot 'stm32\combined-system\build\Release\ESKIN_STM32.elf'
& pyocd flash -W -u $ProbeUid -t stm32g474cetx -f $SwdSpeed `
    -M under-reset -e sector $firmwareFile
if ($LASTEXITCODE -ne 0) { throw 'STM32 flash failed.' }
Write-Host 'STM32 flash complete. Reset this module. Deploy the matching bridge before testing.'
