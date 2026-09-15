"""Evaluate completed shared-endpoint captures in a new timestamped directory.

Default input: current DATA/module_*/FSR*. This command does not rebuild models,
move RAW data, or generate area-derived pressure/resistance outputs. For model
rebuilding, use the explicit offline commands in the calibration README.
Each module/layer batch must have one protocol, range, endpoint/FIT model pair,
and gamma. Split different conditions into separate evaluation directories.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from new_protocol_evaluation import (
    PROTOCOL_ID, CAPTURE_NAME, analyze_batch, analyze_capture,
    batch_protocol, load_matched_batch, partition_completed,
)

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from portable_paths import portable_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(fsr_dir: Path) -> dict[str, Any] | None:
    """Read and validate a whole module/layer batch before creating outputs."""
    fsr_dir = fsr_dir.resolve()
    evaluation = fsr_dir / "evaluation"
    captures = sorted(evaluation.rglob(CAPTURE_NAME))
    if not captures:
        return None
    protocol, low, upper = batch_protocol(captures)
    if protocol != PROTOCOL_ID:
        raise ValueError(f"{fsr_dir}: legacy captures are not accepted by the current refresh command; use the archived tools for legacy reproduction")
    completed, incomplete = partition_completed(captures)
    if not completed:
        return None
    records = load_matched_batch(captures)
    return {"fsr_dir": fsr_dir, "evaluation_dir": evaluation,
            "completed_captures": completed, "all_captures": captures,
            "excluded_incomplete_captures": incomplete,
            "load_range_g": [low, upper],
            "comparison_condition": records[0]["provenance"]["comparison_condition"],
            "capture_sha256": {str(path): digest(path) for path in captures}}


def refresh(plan: dict[str, Any], *, include_shared_lut: bool = True) -> dict[str, Any]:
    """Render only after the caller has preflighted every selected batch."""
    current = sorted(plan["evaluation_dir"].rglob(CAPTURE_NAME))
    if current != plan["all_captures"] or any(digest(path) != plan["capture_sha256"][str(path)] for path in current):
        raise ValueError("Capture set changed after preflight; finish acquisition and run refresh again")
    output = plan["evaluation_dir"] / "analysis" / ("refresh_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
    output.mkdir(parents=True, exist_ok=False)
    distributions = []
    for index, capture in enumerate(plan["completed_captures"], start=1):
        destination = output / "distributions" / f"{index:04d}_{capture.parent.name}"
        distributions.append({key: portable_path(value) for key, value in analyze_capture(capture, destination).items()})
    accuracy = analyze_batch(plan["evaluation_dir"], output / "accuracy", kind="accuracy", include_shared_lut=include_shared_lut)
    dispersion = analyze_batch(plan["evaluation_dir"], output / "dispersion", kind="dispersion")
    unchanged = all(digest(Path(path)) == sha for path, sha in plan["capture_sha256"].items())
    if not unchanged:
        raise RuntimeError("A source capture changed during evaluation; generated results require review")
    result = {"format": "e-skin-shared-endpoint-evaluation-refresh", "version": 1,
              "protocol_id": PROTOCOL_ID, "source_fsr_dir": portable_path(plan["fsr_dir"]),
              "created_at": datetime.now(timezone.utc).isoformat(),
              "load_range_g": plan["load_range_g"],
              "comparison_condition": plan["comparison_condition"],
              "completed_capture_count": len(plan["completed_captures"]),
              "excluded_incomplete_captures": plan["excluded_incomplete_captures"],
              "source_capture_sha256": {portable_path(Path(path)): sha for path, sha in plan["capture_sha256"].items()},
              "source_captures_unchanged": unchanged,
              "model_rebuilt": False, "shared_lut_error_comparison": include_shared_lut, "output_directory": portable_path(output),
              "distributions": distributions,
              "accuracy": {key: portable_path(value) for key, value in accuracy.items()},
              "dispersion": {key: portable_path(value) for key, value in dispersion.items()}}
    with (output / "refresh_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return result


def run(fsr_dir: Path | None = None, *, check_only: bool = False, include_shared_lut: bool = True) -> list[dict[str, Any]]:
    targets = [fsr_dir.resolve()] if fsr_dir is not None else sorted((ROOT / "DATA").glob("module_*/FSR*"))
    # Preflight every target before any target is allowed to write outputs.
    plans = [plan for target in targets if (plan := preflight(target)) is not None]
    if not plans:
        print("No new captures: no complete shared-endpoint captures to evaluate.")
        return []
    if check_only:
        for plan in plans:
            print(f"Ready: {plan['fsr_dir']} | {len(plan['completed_captures'])} complete captures | range {plan['load_range_g']} g")
        return plans
    results = [refresh(plan, include_shared_lut=include_shared_lut) for plan in plans]
    for result in results:
        print(f"Evaluation saved: {result['output_directory']}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fsr-dir", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Validate captures and conditions without creating outputs")
    parser.add_argument("--no-shared-lut", action="store_true", help="Compatibility for old exports without a frozen mean-cell inverse LUT")
    args = parser.parse_args()
    try:
        run(args.fsr_dir, check_only=args.check_only, include_shared_lut=not args.no_shared_lut)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Refresh refused: {error}\nGroup captures by protocol, range, endpoint model, FIT model and gamma before analysis.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
