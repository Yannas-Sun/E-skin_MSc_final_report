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
