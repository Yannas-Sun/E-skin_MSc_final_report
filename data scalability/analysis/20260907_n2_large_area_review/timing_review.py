"""Read-only dual-module timing audit; sync intervals are kept per slot."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data"
SOURCE = HERE.parent / "20260907_delta_followup_review/timing_review.py"
EXPECTED = "5f1b2f1d4ac8d9bf981b322ffa633e3582f30e921910b7360429e8bf94a52130"
IDS = ("20260907_054752_155421", "20260907_054832_183609", "20260907_054912_204552")


def main():
    actual = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if actual != EXPECTED:
        raise RuntimeError("Timing helper changed; review before reusing")
    spec = importlib.util.spec_from_file_location("prior_checked_timing", SOURCE)
    timing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timing)
    timing.OUT, timing.DATA, timing.IDS = HERE, DATA, IDS
    timing.main()
    path = HERE / "timing_review.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["timing_helper"] = {"path": str(SOURCE), "sha256": actual}
    result["definitions"]["condition"] = "Recorded zero_load; user confirmed N=2 large-area coverage with simultaneous coverage and loading of M1 and M3. Equal force/area is not established. See condition_correction.json"
    result["definitions"]["ESKF"] = "Per-slot logged DELTA_SYNC events; any_ESKF_packet intervals are an interleaved union and are not a module's refresh period. No trigger causes are inferred."
    for record in result["records"]:
        directory = DATA / record["run_id"]
        with (directory / "packet_log.csv").open(encoding="utf-8-sig", newline="") as stream:
            packets = [r for r in csv.DictReader(stream) if r["outer_crc_ok"] == "True"
                       and int(r["received_bytes"]) == int(r["declared_length"]) > 0]
        record["any_ESKF_packet_host_interval_ms"] = record.pop("ESKF_host_interval_ms")
        record["any_ESKF_packet_interval_counts"] = record.pop("ESKF_interval_counts")
        record["ESKF_per_slot"] = {}
        for slot in record["metadata"]["target_modules"]:
            sync = [r for r in packets if r["algorithms"].split(",")[slot].strip() == "DELTA_SYNC"]
            gaps = [(int(b["host_ms"])-int(a["host_ms"])) & 0xffffffff for a,b in zip(sync,sync[1:])]
            record["ESKF_per_slot"][str(slot)] = {"full_count":len(sync),
                "main_count":sum(r["main_window"] == "True" for r in sync),
                "host_interval_ms":timing.profile(gaps),
                "events":[{"time_s":float(r["elapsed_s"]),"host_ms":int(r["host_ms"]),
                           "outer_sequence":int(r["packet_sequence"]),"main_window":r["main_window"] == "True"}
                          for r in sync]}
        record["packet_sync_combinations"] = {}
        for scope in ("full_run", "initial_prefix", "main"):
            selected = packets if scope == "full_run" else [r for r in packets if (r["main_window"] == "True") == (scope == "main")]
            counts = {}
            for p in selected:
                algorithms = p["algorithms"].split(",")
                names = [f"M{slot}:{algorithms[slot]}" for slot in record["metadata"]["target_modules"]]
                key = "+".join(names)
                counts[key] = counts.get(key,0)+1
            record["packet_sync_combinations"][scope] = counts
        assert all(hashlib.sha256((directory/name).read_bytes()).hexdigest() == meta["sha256"]
                   for name,meta in record["sources"].items())
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"run_id":r["run_id"],"main_combinations":r["packet_sync_combinations"]["main"],
                       "per_slot_sync":[{"slot":slot,"full":s["full_count"],"main":s["main_count"],
                                         "min_ms":s["host_interval_ms"].get("min"),"max_ms":s["host_interval_ms"].get("max")}
                                        for slot,s in r["ESKF_per_slot"].items()]}
                      for r in result["records"]], indent=2))


if __name__ == "__main__":
    main()
