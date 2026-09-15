"""Read-only PC/bridge timing and metadata audit of the fixed three new runs."""
from pathlib import Path
import csv
import hashlib
import json
import statistics

OUT = Path(__file__).resolve().parent
DATA = OUT.parents[1] / "data"
IDS = ("20260907_050453_154588", "20260907_050533_183636", "20260907_050613_222506")
FILES = ("summary.json", "packet_log.csv", "module_log.csv", "events.jsonl", "experiment_log.md", "mul1_raw.bin")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    def pct(q):
        idx = q * (len(values) - 1)
        i = int(idx)
        return values[i] + (values[min(i+1, len(values)-1)]-values[i])*(idx-i)
    return {"n": len(values), "min": values[0], "median": pct(.5),
            "mean": statistics.mean(values), "p95": pct(.95),
            "p99": pct(.99), "max": values[-1],
            "count_zero": sum(v == 0 for v in values),
            "count_negative": sum(v < 0 for v in values),
            "count_gt_20": sum(v > 20 for v in values),
            "count_gt_100": sum(v > 100 for v in values)}


def scope_timing(packets):
    intervals = []
    for a, b in zip(packets, packets[1:]):
        intervals.append({"before_outer_seq": int(a["packet_sequence"]),
                          "after_outer_seq": int(b["packet_sequence"]),
                          "outer_seq_step": (int(b["packet_sequence"])-int(a["packet_sequence"])) & 0xffffffff,
                          "time_s": float(b["elapsed_s"]),
                          "pc_dt_ms": (float(b["elapsed_s"])-float(a["elapsed_s"])) * 1000,
                          "host_dt_ms": (int(b["host_ms"])-int(a["host_ms"])) & 0xffffffff,
                          "after_algorithms": b["algorithms"]})
    pc_span = (float(packets[-1]["elapsed_s"])-float(packets[0]["elapsed_s"])) * 1000
    host_span = (int(packets[-1]["host_ms"])-int(packets[0]["host_ms"])) & 0xffffffff
    return {"packets": len(packets), "pc_completion_dt_ms": profile([r["pc_dt_ms"] for r in intervals]),
            "host_enqueue_dt_ms": profile([r["host_dt_ms"] for r in intervals]),
            "outer_seq_nonunit_steps": sum(r["outer_seq_step"] != 1 for r in intervals),
            "pc_packet_span_rate_Hz": (len(packets)-1) * 1000/pc_span,
            "host_packet_span_rate_Hz": (len(packets)-1) * 1000/host_span,
            "largest_pc_gaps": sorted(intervals, key=lambda r: r["pc_dt_ms"], reverse=True)[:5],
            "largest_host_gaps": sorted(intervals, key=lambda r: r["host_dt_ms"], reverse=True)[:5],
            "host_gaps_over_10_ms": [r for r in intervals if r["host_dt_ms"] > 10]}


def main():
    records = []
    for run_id in IDS:
        directory = DATA / run_id
        source_hashes = {name: {"sha256": digest(directory/name), "bytes": (directory/name).stat().st_size} for name in FILES}
        s = json.loads((directory/"summary.json").read_text(encoding="utf-8"))
        assert s["run_id"] == run_id and s["completed_requested_duration"]
        m = s["metadata"]
        with (directory/"packet_log.csv").open(encoding="utf-8-sig", newline="") as stream:
            packets = [r for r in csv.DictReader(stream) if r["outer_crc_ok"] == "True"
                       and int(r["received_bytes"]) == int(r["declared_length"]) > 0]
        timing = {}
        for scope, selected in (("full_run", packets),
                                ("initial_prefix", [r for r in packets if r["main_window"] != "True"]),
                                ("main", [r for r in packets if r["main_window"] == "True"])):
            timing[scope] = scope_timing(selected)
        assert timing["main"]["packets"] == s["scopes"]["main"]["counts"]["valid_outer_packets"]
        sync = [r for r in packets if "DELTA_SYNC" in r["algorithms"].split(",")]
        intervals = [((int(b["host_ms"])-int(a["host_ms"])) & 0xffffffff)
                     for a,b in zip(sync,sync[1:])]
        row = {"run_id": run_id, "started_at": s["started_at"],
               "metadata": {key:m.get(key) for key in (
                   "target_modules", "target_mode", "target_hz", "delta_threshold", "spi_setting_hz",
                   "condition", "load_layers", "load_notes", "notes", "block", "repeat", "batch_id",
                   "batch_recording_method", "deployment_confirmed", "physical_modules_to_slots")},
               "local_file_hashes": {k:v.get("sha256") for k,v in m.get("local_provenance", {}).get("files", {}).items()},
               "duration_s":s["duration_seconds"], "settle_s":s["settle_seconds"],
               "GUI_status":{key:s["scopes"][key]["status"] for key in ("main", "full_run")},
               "review_reasons":{key:s["scopes"][key]["review_reasons"] for key in ("main", "full_run")},
               "timing":timing, "ESKF_host_interval_ms":profile(intervals),
               "ESKF_interval_counts":{"less_than_900ms":sum(v < 900 for v in intervals),
                                       "900_to_1100ms":sum(900 <= v <= 1100 for v in intervals),
                                       "above_1100ms":sum(v > 1100 for v in intervals)},
               "sources":source_hashes}
        row["sources_unchanged"] = all(digest(directory/name) == meta["sha256"]
                                        and (directory/name).stat().st_size == meta["bytes"]
                                        for name,meta in source_hashes.items())
        assert row["sources_unchanged"]
        records.append(row)
    result = {"records":records, "input_run_count":3,
              "batch_count":len({r["metadata"]["batch_id"] for r in records}),
              "observational_unit":"Three consecutive time windows in one setup; no independent reassembly recorded",
              "definitions":{
                  "PC":"Packet-completion elapsed time on PC; buffering and scheduling may repeat timestamps",
                  "host_ms":"Teensy MUL1 construction/enqueue millis timestamp, not direct SPI or physical scan timing",
                  "ESKF":"All logged DELTA_SYNC; host interval categories are descriptive, not classified trigger causes",
                  "condition":"File metadata zero_load retained; user confirmed large_area, see condition_correction.json",
                  "provenance":"Local file hashes only; no device flash readback"},
              "source_file_count":18, "all_sources_unchanged":all(r["sources_unchanged"] for r in records)}
    (OUT/"timing_review.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    for row in records:
        t = row["timing"]["main"]
        print(json.dumps({"run_id":row["run_id"], "GUI_status":row["GUI_status"],
                         "main_packets":t["packets"], "PC_max_ms":t["pc_completion_dt_ms"]["max"],
                         "host_max_ms":t["host_enqueue_dt_ms"]["max"],
                         "host_span_rate_Hz":t["host_packet_span_rate_Hz"],
                         "outer_seq_nonunit_steps":t["outer_seq_nonunit_steps"],
                         "ESKF_intervals":row["ESKF_interval_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
