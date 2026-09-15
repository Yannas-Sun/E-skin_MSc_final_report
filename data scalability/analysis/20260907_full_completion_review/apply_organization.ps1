$ErrorActionPreference = 'Stop'
$dataReviewDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$dataMovePlan = Get-Content -LiteralPath (Join-Path $dataReviewDirectory 'organization_plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$dataAllowedRoot = [IO.Path]::GetFullPath((Join-Path  '..\..\data'))
if ([IO.Path]::GetFullPath($dataMovePlan.data_root) -ne $dataAllowedRoot) { throw 'Unexpected data root' }
if ($dataMovePlan.total_runs -ne 6 -or $dataMovePlan.total_files -ne 36) { throw 'Unexpected snapshot size' }
$dataRootPrefix = $dataAllowedRoot + [IO.Path]::DirectorySeparatorChar

function Confirm-DataPath([string] $path) {
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($dataRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside authorized data root: $resolved"
    }
    return $resolved
}

# Preflight the entire fixed snapshot before the first move. Refuse live files,
# concurrent changes, extra files, collisions, and any path outside this data root.
foreach ($dataRun in $dataMovePlan.runs) {
    $dataSource = Confirm-DataPath $dataRun.source
    $dataDestination = Confirm-DataPath $dataRun.destination
    if ((Split-Path -Parent $dataSource) -ne $dataAllowedRoot) { throw 'Expected a top-level source capture' }
    if (-not (Test-Path -LiteralPath $dataSource -PathType Container)) { throw "Missing capture: $dataSource" }
    if (Test-Path -LiteralPath $dataDestination) { throw "Destination exists; no overwrite allowed: $dataDestination" }
    $dataSourceItem = Get-Item -LiteralPath $dataSource
    if ($dataSourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source may not be a link' }
    $dataAncestor = Split-Path -Parent $dataDestination
    while ($dataAncestor -ne $dataAllowedRoot) {
        [void](Confirm-DataPath $dataAncestor)
        if (Test-Path -LiteralPath $dataAncestor) {
            if ((Get-Item -LiteralPath $dataAncestor).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Destination ancestor may not be a link' }
        }
        $dataAncestor = Split-Path -Parent $dataAncestor
    }
    $dataEntries = @(Get-ChildItem -LiteralPath $dataSource -Force)
    if ($dataEntries.Count -ne $dataRun.files.Count) { throw 'Capture file list changed' }
    foreach ($dataFile in $dataRun.files) {
        $dataOldFile = Confirm-DataPath $dataFile.old_path
        $dataNewFile = Confirm-DataPath $dataFile.new_path
        if ((Split-Path -Parent $dataOldFile) -ne $dataSource -or (Split-Path -Parent $dataNewFile) -ne $dataDestination) { throw 'File outside planned run directory' }
        $dataItem = Get-Item -LiteralPath $dataOldFile
        if ($dataItem.PSIsContainer -or ($dataItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected a regular file' }
        $dataHandle = [IO.File]::Open($dataOldFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        $dataHandle.Dispose()
        if ($dataItem.Length -ne $dataFile.bytes -or (Get-FileHash -LiteralPath $dataOldFile -Algorithm SHA256).Hash -ne $dataFile.sha256) {
            throw "Capture changed since audit: $dataOldFile"
        }
    }
    $dataSummary = Get-Content -LiteralPath (Join-Path $dataSource 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $dataSummary.completed_requested_duration -or $dataSummary.reason -ne 'capture duration reached') { throw 'Capture not complete' }
}

$dataVerified = @()
foreach ($dataRun in $dataMovePlan.runs) {
    $dataSource = Confirm-DataPath $dataRun.source
    $dataDestination = Confirm-DataPath $dataRun.destination
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $dataDestination))
    if (Test-Path -LiteralPath $dataDestination) { throw 'Concurrent destination creation' }
    Move-Item -LiteralPath $dataSource -Destination $dataDestination
    foreach ($dataFile in $dataRun.files) {
        $dataHash = (Get-FileHash -LiteralPath $dataFile.new_path -Algorithm SHA256).Hash
        if ($dataHash -ne $dataFile.sha256) { throw "Post-move verification failed: $($dataFile.new_path)" }
        $dataVerified += [PSCustomObject]@{run_id=$dataRun.run_id; path=$dataFile.new_path; bytes=$dataFile.bytes; sha256=$dataHash}
    }
    [PSCustomObject]@{run_id=$dataRun.run_id; source=$dataSource; destination=$dataDestination; sha256_verified=$true} |
        ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $dataReviewDirectory 'move_journal.jsonl') -Encoding UTF8
}
[PSCustomObject]@{
    completed_at=(Get-Date).ToString('o')
    status='completed'
    verified_runs=$dataMovePlan.total_runs
    verified_files=$dataVerified.Count
    total_bytes=$dataMovePlan.total_bytes
    original_contents_changed=$false
    files=$dataVerified
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $dataReviewDirectory 'organization_verification.json') -Encoding UTF8
Write-Output "Organized $($dataMovePlan.total_runs) completed runs; verified $($dataVerified.Count) original files, $($dataMovePlan.total_bytes) bytes."
