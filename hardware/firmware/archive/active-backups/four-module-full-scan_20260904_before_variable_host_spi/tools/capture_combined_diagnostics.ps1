param(
    [string]$Port = "COM9",
    [int]$Baud = 2000000,
    [int]$DurationSeconds = 20,
    [string]$Label = "host_spi"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$outputDirectory = Join-Path $root "docs\test_results"
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$baseName = "${stamp}_${Label}"
$rawPath = Join-Path $outputDirectory "${baseName}.bin"
$textPath = Join-Path $outputDirectory "${baseName}.txt"

$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.DtrEnable = $true
$serial.RtsEnable = $true
$serial.ReadTimeout = 250
$stream = [System.IO.MemoryStream]::new()

try {
    $serial.Open()
    $buffer = New-Object byte[] 4096
    # Actively drain the connection/startup period. Merely sleeping here lets
    # the Teensy USB queue fill before Windows begins consuming endpoints and
    # makes startup-only drops look like steady-state failures.
    $warmupDeadline = [DateTime]::UtcNow.AddMilliseconds(2500)
    while ([DateTime]::UtcNow -lt $warmupDeadline) {
        try {
            [void]$serial.BaseStream.Read($buffer, 0, $buffer.Length)
        }
        catch [System.TimeoutException] {
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($DurationSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $count = $serial.BaseStream.Read($buffer, 0, $buffer.Length)
            if ($count -gt 0) {
                $stream.Write($buffer, 0, $count)
            }
        }
        catch [System.TimeoutException] {
        }
    }
}
finally {
    if ($serial.IsOpen) { $serial.Close() }
}

$raw = $stream.ToArray()
[System.IO.File]::WriteAllBytes($rawPath, $raw)
$ascii = [System.Text.Encoding]::ASCII.GetString($raw)
$matches = [regex]::Matches(
    $ascii, '#ESK(?:DBG|FIRST|CRC|ALIGN)[^\r\n]*')
$lines = @($matches | ForEach-Object { $_.Value })
$dbgLines = @($lines | Where-Object { $_ -like '#ESKDBG*' })

function Convert-DebugLine([string]$Line) {
    $values = @{}
    foreach ($match in [regex]::Matches($Line, '(\w+)=(\d+)')) {
        $values[$match.Groups[1].Value] = [uint64]$match.Groups[2].Value
    }
    return $values
}

$summary = @(
    "port=$Port"
    "baud=$Baud"
    "duration_seconds=$DurationSeconds"
    "raw_bytes=$($raw.Length)"
)

if ($dbgLines.Count -ge 2) {
    $first = Convert-DebugLine $dbgLines[0]
    $last = Convert-DebugLine $dbgLines[-1]
    $irq = $last.irq - $first.irq
    $ok = $last.ok - $first.ok
    $crc = $last.crc - $first.crc
    $magic = $last.magic - $first.magic
    $header = $last.header - $first.header
    $sequence = if ($first.ContainsKey("sequence") -and $last.ContainsKey("sequence")) {
        $last.sequence - $first.sequence
    } else { 0 }
    $crcChecked = if ($first.ContainsKey("crc_checked") -and $last.ContainsKey("crc_checked")) {
        $last.crc_checked - $first.crc_checked
    } else { $irq }
    $crcSkipped = if ($first.ContainsKey("crc_skipped") -and $last.ContainsKey("crc_skipped")) {
        $last.crc_skipped - $first.crc_skipped
    } else { 0 }
    $usbOff = $last.usb_off - $first.usb_off
    $usbShort = $last.usb_short - $first.usb_short
    $release = $last.release_timeout - $first.release_timeout
    $summary += "delta_irq=$irq"
    $summary += "delta_ok=$ok"
    $summary += "delta_crc=$crc"
    $summary += "delta_magic=$magic"
    $summary += "delta_header=$header"
    $summary += "delta_sequence=$sequence"
    $summary += "delta_crc_checked=$crcChecked"
    $summary += "delta_crc_skipped=$crcSkipped"
    $summary += "delta_usb_off=$usbOff"
    $summary += "delta_usb_short=$usbShort"
    $summary += "delta_release_timeout=$release"
    $measuredSeconds = [double]$DurationSeconds
    if ($first.ContainsKey("ms") -and $last.ContainsKey("ms")) {
        $elapsedMs = $last.ms - $first.ms
        if ($elapsedMs -gt 0) {
            $measuredSeconds = $elapsedMs / 1000.0
            $summary += "diagnostic_interval_seconds=$([Math]::Round($measuredSeconds, 3))"
        }
    }
    if ($irq -gt 0) {
        $summary += "acceptance_percent=$([Math]::Round(100.0 * $ok / $irq, 3))"
        if ($crcChecked -gt 0) {
            $summary += "crc_error_percent=$([Math]::Round(100.0 * $crc / $crcChecked, 3))"
        }
        $crcObserved = $crcChecked + $crcSkipped
        if ($crcObserved -gt 0) {
            $summary += "crc_coverage_percent=$([Math]::Round(100.0 * $crcChecked / $crcObserved, 3))"
        }
        $summary += "transfer_rate_hz=$([Math]::Round($irq / $measuredSeconds, 3))"
        $readyAttempts = $irq - $usbOff
        if ($readyAttempts -gt 0) {
            $summary += "usb_ready_acceptance_percent=$([Math]::Round(100.0 * $ok / $readyAttempts, 3))"
            $summary += "usb_output_rate_hz=$([Math]::Round($ok / $measuredSeconds, 3))"
        }
    }
}
else {
    $summary += "result=insufficient_diagnostic_lines"
}

[System.IO.File]::WriteAllLines($textPath, $summary + "" + $lines)
$summary | ForEach-Object { Write-Output $_ }
Write-Output "raw_file=$rawPath"
Write-Output "diagnostic_file=$textPath"
