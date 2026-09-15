param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$source = [IO.Path]::GetFullPath((Join-Path $taskRoot 'data'))
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $taskRoot 'history\pre_variable_spi_20260906'))
$destination = [IO.Path]::GetFullPath((Join-Path $archiveRoot 'data'))
$boundary = $taskRoot.TrimEnd('\') + '\'
foreach ($target in @($source, $archiveRoot, $destination)) {
    if (-not $target.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target is outside the intended data-scalability workspace: $target"
    }
}
if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Source missing: $source" }
if (Test-Path -LiteralPath $archiveRoot) { throw "Archive already exists; will not overwrite: $archiveRoot" }
$sourceItem = Get-Item -LiteralPath $source -Force
if ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source must not be a reparse point.' }
$items = @(Get-ChildItem -LiteralPath $source -Recurse -Force)
if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw 'Source contains a reparse point; archive requires explicit review.'
}
$files = @($items | Where-Object { -not $_.PSIsContainer } | Sort-Object FullName)
if (-not $files.Count) { throw 'Source is empty; refusing to create an empty historical archive.' }
$inventory = @(
    foreach ($item in $files) {
        [pscustomobject]@{
            relative_path = $item.FullName.Substring($source.Length + 1)
            size_bytes = $item.Length
            last_write_utc = $item.LastWriteTimeUtc.ToString('o')
            sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)
$runs = @(
    foreach ($item in $files | Where-Object { $_.Name -eq 'summary.json' }) {
        $summary = Get-Content -LiteralPath $item.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        [pscustomobject]@{
            run_id = $summary.run_id
            started_at = $summary.started_at
            summary_relative_path = $item.FullName.Substring($source.Length + 1)
        }
    }
)
$current = @(Get-ChildItem -LiteralPath $source -File -Recurse -Force | Sort-Object FullName)
if ($current.Count -ne $inventory.Count) { throw 'Source changed during inventory; no files moved.' }
for ($index = 0; $index -lt $current.Count; $index++) {
    $item = $current[$index]
    $entry = $inventory[$index]
    if ($item.FullName.Substring($source.Length + 1) -ne $entry.relative_path -or
        $item.Length -ne $entry.size_bytes -or
        $item.LastWriteTimeUtc.ToString('o') -ne $entry.last_write_utc) {
        throw 'Source changed during inventory; no files moved.'
    }
}
$bytes = ($inventory | Measure-Object size_bytes -Sum).Sum
if (-not $Execute) {
    [pscustomobject]@{ mode='PREVIEW'; source=$source; destination=$destination; files=$files.Count; runs=$runs.Count; bytes=$bytes } | ConvertTo-Json
    return
}

# One native PowerShell move, after absolute-path, content and reparse checks.
New-Item -ItemType Directory -Path $archiveRoot | Out-Null
$pending = [ordered]@{
    status = 'PRE_MOVE_INVENTORY'; source_root=$source; archived_data_root=$destination
    created_at_utc=[DateTime]::UtcNow.ToString('o'); file_count=$inventory.Count
    total_bytes=$bytes; runs=$runs; files=$inventory
}
$pending | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $archiveRoot 'archive_manifest.json') -Encoding UTF8
Move-Item -LiteralPath $source -Destination $destination
New-Item -ItemType Directory -Path $source | Out-Null

$archivedFiles = @(Get-ChildItem -LiteralPath $destination -Recurse -File -Force)
if ($archivedFiles.Count -ne $inventory.Count) { throw 'Archive file count differs; inspect archive_manifest.json.' }
foreach ($entry in $inventory) {
    $archivedPath = Join-Path $destination $entry.relative_path
    $item = Get-Item -LiteralPath $archivedPath
    if ($item.Length -ne $entry.size_bytes -or
        (Get-FileHash -LiteralPath $archivedPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
        throw "Archive verification failed for $($entry.relative_path); originals remain in archive for inspection."
    }
}
$pending.status = 'VERIFIED_SHA256'
$pending['verified_at_utc'] = [DateTime]::UtcNow.ToString('o')
$pending['original_file_contents_modified'] = $false
$pending['active_data_directory'] = $source
$pending | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $archiveRoot 'archive_manifest.json') -Encoding UTF8
$inventory | ForEach-Object {
    [pscustomobject]@{ original_path=(Join-Path $source $_.relative_path); archived_path=(Join-Path $destination $_.relative_path); sha256=$_.sha256 }
} | Export-Csv -LiteralPath (Join-Path $archiveRoot 'path_map.csv') -NoTypeInformation -Encoding UTF8
@'
# Historical Data archive

The original data directory was moved here intact on 2026-09-06 before the new GUI experiment campaign.
All original file bytes were verified against SHA-256 hashes after the move.

Original root: ../../data (the active Data directory, now reserved for new recordings).
Archived data: ./data

Original summary JSON and Markdown may contain old absolute paths. Their contents were deliberately
preserved. Resolve them using path_map.csv; do not rewrite the original files to repair links.
archive_manifest.json records the original relative paths, hashes, sizes and acquisition dates.

This archive contains historical measurements, not evidence of deployment of the new variable-SPI build.
Use an explicit --data-root pointing here when reproducing historical figures. New GUI recordings go
to the active data directory outside history; readers must not recursively combine both roots.
'@ | Set-Content -LiteralPath (Join-Path $archiveRoot 'README.md') -Encoding UTF8
[pscustomobject]@{status='VERIFIED_SHA256';files=$inventory.Count;runs=$runs.Count;bytes=$bytes;archive=$archiveRoot;active_data=$source} | ConvertTo-Json
