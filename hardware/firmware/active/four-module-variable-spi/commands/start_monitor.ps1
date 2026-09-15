param(
    [string]$Port = 'COM9',
    [string]$OutputDirectory = '',
    [string]$Schedule = '',
    [switch]$Demo
)

$ErrorActionPreference = 'Stop'
$protocolRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Required tool 'python' was not found on PATH. Install Python and add it to PATH."
}
$monitorArguments = @('-B', '-u', (Join-Path $protocolRoot 'pc\four-module-fsr-monitor.py'), '--port', $Port)
if ($OutputDirectory) { $monitorArguments += @('--output-dir', $OutputDirectory) }
if ($Schedule) { $monitorArguments += @('--schedule', $Schedule) }
if ($Demo) { $monitorArguments += '--demo' }
& python @monitorArguments
if ($LASTEXITCODE -ne 0) { throw 'Monitor exited with an error.' }
