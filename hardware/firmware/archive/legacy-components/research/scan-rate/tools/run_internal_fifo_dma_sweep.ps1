param(
    [string]$Port = "COM9",
    [int]$Module = 1,
    [int[]]$GapUs = @(0, 20, 40, 50, 60, 70, 80),
    [int]$MuxUs = 0,
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
foreach ($gap in $GapUs) {
    Write-Output "Testing command-to-FIFO gap ${gap} us..."
    & (Join-Path $commands "flash_internal_fifo_dma_stm32.cmd") $gap $MuxUs
    if ($LASTEXITCODE -ne 0) {
        $results += [pscustomobject]@{
            gap_us = $gap; readout_status = "FLASH_FAIL"
            legacy_window_gate = "N/A"; output_hz = 0
            fsr_scan_hz = 0; json = ""
        }
        continue
    }
    Start-Sleep -Seconds 2
    $captureOutput = & python -u $capture --port $Port --module $Module `
        --duration $DurationSeconds --gap-us $gap --mux-us $MuxUs
    $captureOutput | ForEach-Object { Write-Output $_ }
    $jsonLine = $captureOutput | Where-Object { $_ -like "json_file=*" } |
        Select-Object -Last 1
    if (-not $jsonLine) {
        $results += [pscustomobject]@{
            gap_us = $gap; readout_status = "CAPTURE_FAIL"
            legacy_window_gate = "N/A"; output_hz = 0
            fsr_scan_hz = 0; json = ""
        }
        continue
    }
    $jsonPath = $jsonLine.Substring("json_file=".Length)
    $data = Get-Content -Raw -LiteralPath $jsonPath | ConvertFrom-Json
    $results += [pscustomobject]@{
        gap_us = $gap
        readout_status = $data.readout_status
        legacy_window_gate = $data.result
        output_hz = [double]$data.measured_output_rate_hz
        fsr_scan_hz = [double]$data.profile_complete_fsr_scan_hz
        json = $jsonPath
    }
}

$passing = @($results | Where-Object {
        $_.readout_status -eq "DIGITALLY_CREDIBLE_UNLOADED"
    } |
    Sort-Object fsr_scan_hz -Descending)
$best = if ($passing.Count -gt 0) { $passing[0] } else { $null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$summaryPath = Join-Path $resultsDirectory "${stamp}_internal_fifo_dma_sweep.md"
$lines = @(
    "# Internal-clock FIFO-DMA sweep"
    ""
    "Module: $Module; MUX settle: $MuxUs us; capture per point: $DurationSeconds s."
    ""
    "| Command-to-read gap | Readout status | Legacy 200-frame gate | USB output | Complete FSR scan profile |"
    "| ---: | :---: | :---: | ---: | ---: |"
)
foreach ($item in $results) {
    $lines += "| $($item.gap_us) us | $($item.readout_status) | $($item.legacy_window_gate) | $([Math]::Round($item.output_hz, 3)) Hz | $([Math]::Round($item.fsr_scan_hz, 3)) Hz |"
}
$lines += ""
if ($best) {
    $lines += "Fastest unloaded point without the >=3072 early-read signature: **$($best.fsr_scan_hz.ToString('0.000')) Hz** at **$($best.gap_us) us** command-to-read gap."
} else {
    $lines += "No point had both valid transport and an unloaded readout free of the >=3072 early-read signature."
}
$lines += ""
$lines += "This is an unloaded short-run validity test, not a controlled-pressure qualification."
[System.IO.File]::WriteAllLines($summaryPath, $lines)

if ($best -and -not $LeaveLastProfile) {
    Write-Output "Reflashing the fastest digitally credible unloaded profile: gap $($best.gap_us) us"
    & (Join-Path $commands "flash_internal_fifo_dma_stm32.cmd") `
        $best.gap_us $MuxUs
    if ($LASTEXITCODE -ne 0) { throw "Best-profile reflash failed" }
}

$results | Format-Table -AutoSize | Out-String | Write-Output
if ($best) {
    Write-Output "best_gap_us=$($best.gap_us)"
    Write-Output "best_complete_fsr_scan_hz=$($best.fsr_scan_hz)"
}
Write-Output "summary_file=$summaryPath"
