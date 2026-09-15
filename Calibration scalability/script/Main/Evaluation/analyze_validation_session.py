"""Manually update comparisons for the frozen models of one saved capture.

Select completed validation captures of the same module, layer, range, model
pair and gamma. Read the recorded gram predictions; never refit on validation.
Each invocation saves a new analysis beside its anchor capture and publishes
the derived results at the original script locations for convenient access.
The GUI only generates single-capture distributions automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from new_protocol_evaluation import (
    CAPTURE_NAME, PROTOCOL_ID, analyze_batch, analyze_capture,
    completion_issue, load_matched_batch, prepare_matched,
)

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from portable_paths import portable_path  # noqa: E402


def _read(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _condition(record: dict[str, Any]) -> dict[str, Any]:
    return {"protocol_id": PROTOCOL_ID,
            "load_range_g": record["load_range_g"],
            "module_id": record["module_id"], "fsr": record["fsr"],
            **record["provenance"]["comparison_condition"]}


def _assert_unchanged(hashes: dict[str, str]) -> None:
    for source, expected in hashes.items():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source capture changed during analysis: {source}")


def build_plan(capture_path: Path) -> dict[str, Any]:
    """Validate the anchor and select a fixed source list before writing."""
    anchor = capture_path.resolve()
    capture_root = anchor.parent.parent
    if anchor.name != CAPTURE_NAME or capture_root.name != "view_distribution":
        raise ValueError("Expected evaluation/view_distribution/<run>/view_distribution_capture.json")
    data, anchor_hash = _read(anchor)
    record = prepare_matched(data, anchor)
    if not record["included"]:
        raise ValueError("Anchor actual load is outside its calibration range")
    if not record["mask"].any():
        raise ValueError("Anchor has no common valid cells for the three methods")
    condition = _condition(record)
    canonical = json.dumps(condition, sort_keys=True, separators=(",", ":"), allow_nan=False)
    condition_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    paths, hashes, excluded = [anchor], {str(anchor): anchor_hash}, []
    for path in sorted(capture_root.rglob(CAPTURE_NAME)):
        path = path.resolve()
        if path == anchor:
            continue
        reason = None
        try:
            candidate, sha = _read(path)
            issue = completion_issue(candidate)
            if issue:
                reason = issue
            else:
                candidate_record = prepare_matched(candidate, path)
                if _condition(candidate_record) != condition:
                    reason = "different_module_layer_range_models_or_gamma"
                elif not candidate_record["included"]:
                    reason = "outside_actual_load_range"
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = "invalid_capture: " + str(error)
        if reason:
            excluded.append({"source": portable_path(path), "reason": reason})
        else:
            paths.append(path)
            hashes[str(path)] = sha
    paths.sort()
    records = load_matched_batch(paths)
    if not records[0]["mask"].any():
        raise ValueError("Same-condition captures have no common valid cells across the batch")
    _assert_unchanged(hashes)
    return {"anchor": anchor, "evaluation_dir": capture_root.parent,
            "capture_paths": paths, "excluded": excluded,
            "condition": condition, "condition_id": condition_id,
            "source_sha256": hashes}


def publish_outputs(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Copy only completed derived artifacts; captures and model files stay put."""
    anchor = Path(result["anchor"])
    evaluation = anchor.parent.parent.parent
    destinations = {"capture": anchor.parent,
                    "error": evaluation / "analysis" / "error",
                    "dispersion": evaluation / "analysis" / "dispersion"}
    snapshot = Path(result["output_dir"]).resolve()
    planned = []
    for section, outputs in result["outputs"].items():
        for key, source in outputs.items():
            source = Path(source).resolve()
            if not source.is_relative_to(snapshot) or not source.is_file():
                raise ValueError(f"Cannot publish missing or non-generated analysis output: {source}")
            target = destinations[section] / source.name
            if target.resolve() == anchor.resolve() or target.suffix not in {".png", ".pdf", ".csv", ".json"}:
                raise ValueError(f"Unexpected analysis destination: {target}")
            planned.append((section, key, source, target))
    published = {section: {} for section in destinations}
    copied = set()
    for section, key, source, target in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target not in copied:
            # Replace a completed copy instead of truncating a displayed image.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".analysis_", suffix=".tmp", delete=False) as handle:
                staged = Path(handle.name)
            try:
                shutil.copyfile(source, staged)
                os.replace(staged, target)
            finally:
                if staged.exists():
                    staged.unlink()
            copied.add(target)
        published[section][key] = portable_path(target)
    pointer = {"format": "e-skin-latest-validation-analysis", "version": 1,
               "created_at": result["created_at"], "condition": result["condition"],
               "condition_id": result["condition_id"], "capture_count": result["capture_count"],
               "source_captures": [portable_path(Path(path)) for path in result["source_captures"]],
               "snapshot_manifest": portable_path(Path(result["manifest"])), "outputs": published,
               "scope": "Latest successful analysis of the current paper validation condition; superseded snapshots are not retained"}
    pointer_path = evaluation / "analysis" / "latest_analysis.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    result["latest_manifest"] = portable_path(pointer_path)
    return published


def run(capture_path: Path, *, publish: bool = True, include_shared_lut: bool = True) -> dict[str, Any]:
    plan = build_plan(capture_path)
    output = plan["anchor"].parent / "analysis" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    _assert_unchanged(plan["source_sha256"])
    output.mkdir(parents=True, exist_ok=False)
    single = analyze_capture(plan["anchor"], output / "capture")
    error = analyze_batch(plan["evaluation_dir"], output / "error", kind="accuracy",
                          capture_paths=plan["capture_paths"], include_shared_lut=include_shared_lut)
    dispersion = analyze_batch(plan["evaluation_dir"], output / "dispersion", kind="dispersion",
                               capture_paths=plan["capture_paths"])
    _assert_unchanged(plan["source_sha256"])
    result = {"format": "e-skin-validation-session-analysis", "version": 2,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "anchor": str(plan["anchor"]), "output_dir": str(output),
              "condition": plan["condition"], "condition_id": plan["condition_id"],
              "source_captures": [str(path) for path in plan["capture_paths"]],
              "capture_count": len(plan["capture_paths"]),
              "excluded": plan["excluded"], "source_sha256": plan["source_sha256"],
              "source_captures_unchanged": True, "model_rebuilt": False,
              "shared_lut_error_comparison": include_shared_lut,
              "comparison_units": "g; variance in g squared; CV in percent from unnormalized g values",
              "outputs": {section: {key: str(value) for key, value in values.items()}
                          for section, values in (("capture", single), ("error", error), ("dispersion", dispersion))},
              "manifest": str(output / "analysis_manifest.json")}
    with Path(result["manifest"]).open("x", encoding="utf-8") as handle:
        stored = dict(result)
        stored.update(
            anchor=portable_path(plan["anchor"]),
            output_dir=portable_path(output),
            source_captures=[portable_path(path) for path in plan["capture_paths"]],
            outputs={section: {key: portable_path(Path(value)) for key, value in values.items()}
                     for section, values in result["outputs"].items()},
            manifest=portable_path(output / "analysis_manifest.json"),
        )
        json.dump(stored, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    if publish:
        result["published_outputs"] = publish_outputs(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--no-shared-lut", action="store_true", help="Compatibility for old exports without a frozen mean-cell inverse LUT")
    args = parser.parse_args()
    try:
        result = run(args.capture, include_shared_lut=not args.no_shared_lut)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Validation analysis failed: {error}\nThe saved capture has been retained.\n")
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
