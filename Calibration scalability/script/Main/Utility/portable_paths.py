"""Portable path helpers for calibration records and manifests.

Filesystem operations still use resolved :class:`~pathlib.Path` objects, but
paths written into JSON/CSV metadata are relative to the calibration project
root.  This keeps records usable after the project is copied to another
machine or relocated as a complete ``Calibration scalability`` package.
"""

from __future__ import annotations

import os
from pathlib import Path


def calibration_root(anchor: Path | None = None) -> Path:
    """Return the folder containing ``DATA`` and ``script``.

    The default works from the current ``Calibration scalability`` checkout
    and from a complete copy of that package.  An explicit anchor is useful
    for tests or callers operating on a copied tree.
    """

    current = Path(anchor or __file__).resolve()
    for parent in (current, *current.parents):
        if (parent / "DATA").is_dir() and (parent / "script").is_dir():
            return parent
    # The utility is normally inside ``script/Main/Utility``; this fallback
    # keeps a newly created empty tree usable before DATA is populated.
    return current.parents[3]


def portable_path(path: Path | str, root: Path | None = None) -> str:
    """Serialize *path* as a POSIX relative path below *root*.

    Files inside the project become relative POSIX paths.  Windows cannot
    express a relative path across different drive letters; for that rare
    external-fixture case the normalized absolute path is retained so
    provenance serialization remains lossless.
    """

    base = Path(root or calibration_root()).resolve()
    target = Path(path).resolve()
    try:
        relative = os.path.relpath(target, base)
    except ValueError:  # Windows: target and base are on different drives.
        return str(target)
    return Path(relative).as_posix()


def resolve_recorded_path(value: Path | str, anchor: Path, root: Path | None = None) -> Path:
    """Resolve an old absolute or new project-relative recorded path.

    Existing absolute paths remain supported for legacy records.  If an old
    absolute path no longer exists after relocation, its suffix after the
    former calibration-folder name is mapped into the current project root.
    Relative paths are first interpreted beside the record, then relative to
    the calibration root.
    """

    raw = Path(value)
    project_root = Path(root or calibration_root(anchor)).resolve()
    if raw.is_absolute():
        parts = list(raw.parts)
        markers = {"Calibration scalability", "Calibration_scalability"}
        marker_index = next((i for i, part in enumerate(parts) if part in markers), None)
        if marker_index is not None:
            candidate = project_root.joinpath(*parts[marker_index + 1:])
            if candidate.exists():
                return candidate.resolve()
        if raw.exists():
            return raw.resolve()
        return raw.resolve()

    beside = (Path(anchor).parent / raw).resolve()
    if beside.exists():
        return beside
    return (project_root / raw).resolve()
