"""Run the checked read-only timing audit on the fixed rolling batch."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "20260907_delta_followup_review/timing_review.py"
EXPECTED = "5f1b2f1d4ac8d9bf981b322ffa633e3582f30e921910b7360429e8bf94a52130"
IDS = ("20260907_053858_001637", "20260907_053938_027960", "20260907_054018_056649")


def main():
    actual = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if actual != EXPECTED:
        raise RuntimeError("Timing helper changed; review it before reusing this fixed audit")
    spec = importlib.util.spec_from_file_location("prior_checked_timing", SOURCE)
    timing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timing)
    timing.OUT = HERE
    timing.DATA = HERE.parents[1] / "data"
    timing.IDS = IDS
    timing.main()
    path = HERE / "timing_review.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["timing_helper"] = {"path": str(SOURCE), "sha256": actual}
    result["definitions"]["condition"] = "Recorded zero_load; user specified rolling. See condition_correction.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
