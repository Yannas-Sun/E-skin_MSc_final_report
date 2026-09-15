"""Resolve preserved photo references through the audited ZERO-only relocation.

No recursive search or filename-only match is allowed. A fallback must appear
exactly once in the relocation manifest and match the original SHA256.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

RELOCATION_REL = Path("DATA/analysis/provenance/path_relocation_20260907/relocation_manifest.csv")


def resolve_photo(root: Path, reference: str | Path, expected_sha256: str | None = None) -> Path:
    root = root.resolve()
    original = (root / reference).resolve()
    if not original.is_relative_to(root):
        raise ValueError("Photo reference leaves the Power workspace")
    relative = original.relative_to(root).as_posix()
    manifest = root / RELOCATION_REL
    matches = []
    if manifest.is_file():
        with manifest.open(encoding="utf-8-sig", newline="") as stream:
            matches = [row for row in csv.DictReader(stream) if row["original_path"] == relative]
    if len(matches) > 1:
        raise ValueError("Ambiguous photo relocation: " + relative)
    known = matches[0] if matches else None
    if known and expected_sha256 and known["sha256"] != expected_sha256:
        raise ValueError("Supplied and archived photo hashes disagree: " + relative)
    expected = expected_sha256 or (known["sha256"] if known else None)
    if original.is_file():
        resolved = original
    elif known:
        resolved = (root / known["resolved_path"]).resolve()
        permitted = original.parent / "zero_load" / original.name
        if resolved != permitted or not resolved.is_relative_to(root):
            raise ValueError("Relocation is outside the same configuration zero_load folder")
        allowed = {
            "n=2": {"M0-M2", "M0-M3", "M1-M2", "M1-M3"},
            "n=3": {"M0-M1-M3", "M0-M2-M3"},
        }
        if original.parent.name not in allowed.get(original.parent.parent.name, set()):
            raise ValueError("Relocation is outside the audited N=2/N=3 ZERO configurations")
    else:
        raise FileNotFoundError("Unresolved photo; no audited relocation: " + relative)
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError("Photo SHA256 mismatch: " + str(resolved))
    return resolved
