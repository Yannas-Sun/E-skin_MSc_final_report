param(
    [string]$Port = "COM9",
    [int]$Module = 1,
    [int[]]$MuxUs = @(100, 75, 50, 25, 10, 0),
    [double]$DurationSeconds = 8.0,
    [switch]$SkipTeensyUpload,
    [switch]$LeaveLastProfile
)

$ErrorActionPreference = "Stop"
$firmwareRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$commands = Join-Path $firmwareRoot "shared\commands"
$capture = Join-Path $PSScriptRoot "capture_internal_fifo_dma.py"
$resultsDirectory = Join-Path $firmwareRoot "docs\test_results"

if (-not $SkipTeensyUpload) {
    & (Join-Path $commands "upload_internal_fifo_dma_bridge.cmd") $Port $Module
    if ($LASTEXITCODE -ne 0) { throw "Teensy upload failed" }
}

$results = @()
foreach ($mux in $MuxUs) {
    Write-Output "Testing stable EOC MUX settle $mux us..."
    & (Join-Path $commands "flash_internal_eoc_mux_stm32.cmd") $mux
    if ($LASTEXITCODE -ne 0) {
        $results += [pscustomobject]@{
            mux_us = $mux; readout_status = "FLASH_FAIL"
            legacy_window_gate = "N/A"; output_hz = 0
            fsr_scan_hz = 0; fsr1_raw = ""; fsr2_raw = ""; json = ""
        }
        continue
    }
    Start-Sleep -Seconds 2
    $captureOutput = & python -u $capture --port $Port --module $Module `
        --duration $DurationSeconds --gap-us 0 --mux-us $mux --stable-eoc
    $captureOutput | ForEach-Object { Write-Output $_ }
    $jsonLine = $captureOutput | Where-Object { $_ -like "json_file=*" } |
        Select-Object -Last 1
    if (-not $jsonLine) {
        $results += [pscustomobject]@{
            mux_us = $mux; readout_status = "CAPTURE_FAIL"
            legacy_window_gate = "N/A"; output_hz = 0
            fsr_scan_hz = 0; fsr1_raw = ""; fsr2_raw = ""; json = ""
        }
        continue
    }
    $jsonPath = $jsonLine.Substring("json_file=".Length)
    $data = Get-Content -Raw -LiteralPath $jsonPath | ConvertFrom-Json
    $results += [pscustomobject]@{
        mux_us = $mux
        readout_status = $data.readout_status
        legacy_window_gate = $data.result
        output_hz = [double]$data.measured_output_rate_hz
        fsr_scan_hz = [double]$data.profile_complete_fsr_scan_hz
        fsr1_raw = ($data.fsr1.raw_range -join "..")
        fsr2_raw = ($data.fsr2.raw_range -join "..")
        json = $jsonPath
    }
}

$qualified = @($results | Where-Object {
        $_.readout_status -eq "EOC_QUALIFIED"
    } | Sort-Object mux_us)
$lowest = if ($qualified.Count -gt 0) { $qualified[0] } else { $null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$summaryPath = Join-Path $resultsDirectory "${stamp}_internal_eoc_mux_sweep.md"
$lines = @(
    "# Stable internal-clock + EOC MUX-settle sweep"
    ""
    "Module: $Module; capture per point: $DurationSeconds s."
    "The acquisition path remains the stable EOC-qualified path; only external MUX settle changes."
    ""
    "| MUX settle | Readout status | Legacy 200-frame gate | USB output | Complete FSR scan | FSR1 raw | FSR2 raw |"
    "| ---: | :---: | :---: | ---: | ---: | :--- | :--- |"
)
foreach ($item in $results) {
    $lines += "| $($item.mux_us) us | $($item.readout_status) | $($item.legacy_window_gate) | $([Math]::Round($item.output_hz, 3)) Hz | $([Math]::Round($item.fsr_scan_hz, 3)) Hz | $($item.fsr1_raw) | $($item.fsr2_raw) |"
}
$lines += ""
if ($lowest) {
    $lines += "Lowest tested EOC-qualified MUX settle: **$($lowest.mux_us) us**."
    $lines += "This is a no-load timing sweep; pressure-response and row-to-row crosstalk still decide whether the interval is electrically acceptable."
} else {
    $lines += "No EOC-qualified point was captured."
}
[System.IO.File]::WriteAllLines($summaryPath, $lines)

if ($lowest -and -not $LeaveLastProfile) {
    Write-Output "Reflashing the lowest tested EOC-qualified profile: MUX settle $($lowest.mux_us) us"
    & (Join-Path $commands "flash_internal_eoc_mux_stm32.cmd") $lowest.mux_us
    if ($LASTEXITCODE -ne 0) { throw "Lowest-profile reflash failed" }
}

$results | Format-Table -AutoSize | Out-String | Write-Output
if ($lowest) {
    Write-Output "lowest_eoc_qualified_mux_us=$($lowest.mux_us)"
}
Write-Output "summary_file=$summaryPath"
