"""Validate the complete local review output; writes only validation.json here."""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

from analyze_records import histogram_stats, repeat_sd

HERE = Path(__file__).resolve().parent


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9), (a, b)


def main():
    runs = json.loads((HERE / "runs.json").read_text(encoding="utf-8"))
    inventory = json.loads((HERE / "inventory.json").read_text(encoding="utf-8"))
    assert len(runs) == 88
    assert Counter(r["date"] for r in runs) == {"2026-09-01": 56, "2026-09-05": 32}
    assert sum(r["raw_bytes"] for r in runs) == 417176802
    assert sum(r["raw_packets"] for r in runs) == 497729
    assert len(set(r["raw_sha256"] for r in runs)) == 88
    assert inventory["script_sha256"] == hashlib.sha256((HERE / "analyze_records.py").read_bytes()).hexdigest()
    allowed_notices = {"requested_vs_observed_algorithm", "experiment_log_run_id_missing", "stale_metadata_file_path"}
    for run in runs:
        assert not set(run["audit_issue_counts"]) - allowed_notices
        assert run["raw_packets"] == run["complete_outer_packets"] == run["valid_inner_packets"]
        assert run["valid_module_frames"] + run["unupdated_expected_module_frames"] == run["N"] * run["raw_packets"]
        close(run["Lmean_B"], run["Lmodel_mean_B"])
        close(run["Mbit_per_s"], 8 * run["Lmean_B"] * run["f_packet_Hz"] / 1e6)
        detail = json.loads((HERE / "per_run" / (run["run_id"] + ".json")).read_text(encoding="utf-8"))
        assert sum(m["ESKF_count"] for m in detail["modules"]) == run["ESKF_count"]
        assert sum(m["ESKD_count"] for m in detail["modules"]) == run["ESKD_count"]
        close(run["q_ESKF_module_frames"], run["ESKF_count"] / run["valid_module_frames"])
        for module in detail["modules"]:
            hist = detail["K_histograms_by_module"][module["module_id"]]
            assert sum(hist.values()) == module["ESKD_count"]
            if hist:
                close(module["K_mean"], sum(int(k) * v for k, v in hist.items()) / sum(hist.values()))
        if run["mode"] == "DELTA":
            mixture = (1-run["q_ESKF_module_frames"]) * run["K_ESKD_mean"] + 480*run["q_ESKF_module_frames"]
            close(run["K_effective_present_module_frames"], mixture)
            close(run["Lmean_B"], 40 + run["valid_module_frames"] / run["raw_packets"] * (84 + 2*mixture)
                  + run["diagnostic_payload_bytes"] / run["raw_packets"])
            if run["fixed_N_mixture_applicable"]:
                close(run["K_effective_all_frames"], mixture)
    with (HERE / "modules.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 162
    with (HERE / "groups.csv").open(encoding="utf-8-sig", newline="") as handle:
        groups = list(csv.DictReader(handle))
    assert sum(int(g["n_runs"]) for g in groups) == 88
    for group in groups:
        if int(group["n_runs"]) == 1:
            assert all(not v for k, v in group.items() if k.endswith("_sd_between_runs"))
    assert sum(r["raw_base_break_events_after_anchor"] for r in runs) == 0
    assert sum(r["raw_unapplied_after_anchor"] for r in runs) == 0
    assert sum(r["raw_initial_unanchored_delta_frames"] for r in runs) == 13305
    reference = next(r for r in runs if r["run_id"] == "20260901_205141")
    assert (reference["ESKF_count"], reference["ESKD_count"]) == (119, 23845)
    close(reference["K_ESKD_mean"], 74.2191235059761)
    partial = [r for r in runs if r["unupdated_expected_module_frames"]]
    assert len(partial) == 1 and partial[0]["run_id"] == "20260905_184520"
    assert partial[0]["unupdated_expected_module_frames"] == 6
    assert partial[0]["diagnostic_payload_bytes"] == 80
    assert partial[0]["unupdated_module_status_counts"] == {"M0:0x80": 1, "M3:0x87": 3, "M3:0x81": 2}
    sample = [0, 0, 1, 3, 4, 4, 7, 9, 10]
    stats = histogram_stats(Counter(sample))
    close(stats["mean"], statistics.mean(sample))
    close(stats["sd_population"], statistics.pstdev(sample))
    close(stats["median"], statistics.median(sample))
    close(stats["p05"], 0)
    close(stats["p95"], 9.6)
    assert repeat_sd([7]) is None and histogram_stats(Counter())["mean"] is None
    result = {"status": "PASS", "run_count": len(runs), "checks": [
        "acquisition date grouping and exhaustive inventory counts",
        "unique raw hashes and current analysis script hash",
        "whole-stream outer/inner CRC, layout, CSV and metadata hard audits",
        "per-module histogram and frame-count aggregation",
        "recorded byte/packet/frequency/rate identities",
        "general mixture identity including absent updates and diagnostic bytes",
        "fixed-N mixture identity when complete-update assumption holds",
        "88 runs retained in condition groups; singleton SD unavailable",
        "offline in-file baseline chain counts and known N4 reference",
        "target-module update coverage and explicit partial-update sample",
        "histogram moments and quantiles against independent reference"
    ], "limitations": ["No device or firmware deployment validation", "No attribution of ESKF trigger causes",
                         "Validation does not establish independence or causal comparability of experiment conditions"]}
    (HERE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
