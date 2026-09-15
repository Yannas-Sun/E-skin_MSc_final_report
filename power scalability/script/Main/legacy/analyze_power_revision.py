"""Historical Power 2.1 reproduction; never writes raw CSV, YAML or photographs.

The 13-row legacy CSV supplies blocked-standby comparators. The 18 continuous
USB-read voltage-and-current YAML files supply the new analysis. Explicitly
marked VOLTAGE_ONLY supplements are excluded from this combined-demand dataset;
they must be analysed separately and never given invented branch currents.
Standby YAMLs duplicate part of the
CSV and are deliberately excluded. Labels M0..M3 are experiment-record labels,
not independently verified hardware UIDs. Requires PyYAML; otherwise stdlib.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
CONTINUOUS = "CONTINUOUS_USB_READ"
BLOCKED = "BLOCKED_STANDBY_NO_CONTINUOUS_USB_READ"
FAULT_FIELDS = ("reset_count", "current_limit_count", "brownout_count", "data_stop_count", "data_gap_count")
LIMITATIONS = [
    "Every exact continuous-state/mode/frequency/load/module-combination condition has one recording (R1); repeat SD is unavailable. Different modules/combinations are not repeats.",
    "Fields named avg are treated as recorded representative instrument readings, not verified time averages. DMM MIN/MAX are not repeat SD or verified high-speed transient extrema.",
    "Currents were measured sequentially by branch; their sum is a module-supply demand estimate, not a simultaneously measured total-current waveform or peak.",
    "Teensy USB power is excluded. V_source times the branch-current sum estimates module-supply output power, not converter input power, efficiency or whole-system power.",
    "MAX records state 2000 g but omit area and application: per-module versus whole-system mass, position and layer are unresolved. Loaded prediction comparisons are conditional on equivalent module loading.",
    "Continuous YAML dates, start times and operator are absent; nominal 30 s warm-up and 10 s measurement fields are prefilled and not independently confirmed.",
    "Fault counters are template-default zero without confirmed observation; they do not establish fault-free operation.",
    "M0..M3 identify modules as written in experiment records; consistent physical identity across combinations has not been independently verified by hardware UID.",
    "Temperature readings do not establish thermal equilibrium. Startup, fast transients, full supply-board capacity, maximum module count and 20% headroom are unverified.",
    "Blocked and continuous results come from separate records, not a randomized paired intervention; state differences are descriptive, not an isolated causal estimate.",
]


def number(value: Any) -> float | None:
    if value is None or str(value).strip().upper() in {"", "N/A", "NA", "NOT_AVAILABLE", "NONE"}:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite numerical field: {value!r}")
    return result


def num(row: dict, key: str) -> float | None:
    return number(row.get(key))


def first_number(row: dict, *keys: str) -> float | None:
    return next((num(row, key) for key in keys if num(row, key) is not None), None)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def defined(values):
    return [x for x in values if x is not None]


def extreme(values, function):
    values = defined(values)
    return function(values) if values else None


def load_sources(root: Path) -> tuple[list[dict], list[dict]]:
    legacy = root / "DATA" / "raw" / "canonical" / "power_raw.csv"
    yamls = sorted((root / "DATA" / "raw" / "canonical" / "power_experiment_records" / "transmission").rglob("*.yaml"))
    if not yamls:
        raise ValueError("No continuous-read YAML records found")
    sources = []
    rows = []
    for path in [legacy, *yamls]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle)) if path == legacy else [yaml.safe_load(handle)]
        if path != legacy and len(records) == 1 and isinstance(records[0], dict) and records[0].get("measurement_scope") == "VOLTAGE_ONLY":
            continue
        sources.append({"relative_path": path.relative_to(root).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
        for row in records:
            if not isinstance(row, dict) or not row.get("run_id"):
                raise ValueError(f"Invalid record in {path}")
            row = dict(row)
            row["_source_path"] = path.relative_to(root).as_posix()
            row["_source_kind"] = "legacy_csv" if path == legacy else "continuous_yaml"
            expected_state = BLOCKED if path == legacy else CONTINUOUS
            if row.get("host_usb_polling_state") != expected_state:
                raise ValueError(f"Unexpected state for {row['run_id']}")
            rows.append(row)
    ids = [r["run_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate run IDs across canonical inputs")
    return rows, sources


def derive(row: dict) -> tuple[dict, list[dict], list[dict]]:
    module_ids = [s.strip() for s in str(row["module_ids"]).split(",")]
    modules = []
    for item in module_ids:
        match = re.fullmatch(r"Module([0-3])", item)
        if not match:
            raise ValueError(f"Unknown module label {item}")
        modules.append("M" + match[1])
    n = int(row["module_count"])
    if len(modules) != n or len(set(modules)) != n:
        raise ValueError(f"Module count/list disagreement: {row['run_id']}")
    rep = re.search(r"_R(\d+)$", row["run_id"])
    if not rep:
        raise ValueError(f"Missing repeat identifier: {row['run_id']}")
    context = {
        "run_id": row["run_id"], "state": row["host_usb_polling_state"],
        "frequency_hz": int(row["frequency_hz"]), "protocol_mode": row["protocol_mode"],
        "load": row["load"], "N": n, "combo": "+".join(modules), "repeat": int(rep[1]),
        "source_path": row["_source_path"], "source_kind": row["_source_kind"],
    }
    source_v = num(row, "V_source_avg_V")
    issues = []

    def issue(code, field, detail, module_id=""):
        issues.append({**context, "module_id": module_id, "code": code, "field": field, "detail": detail, "raw_values_preserved": True})

    branches = []
    for module in modules:
        # N=1 stores the selected labelled module in module0 columns.
        column = 0 if n == 1 else int(module[1:])
        prefix_i = f"I_module{column}"
        prefix_v = f"V_module{column}"
        i = num(row, prefix_i + "_avg_mA")
        i_min, i_max = num(row, prefix_i + "_min_mA"), num(row, prefix_i + "_max_mA")
        current_source = prefix_i + "_avg_mA"
        if i is None and n == 1:
            i = num(row, "I_source_avg_mA")
            i_min, i_max = num(row, "I_source_min_mA"), num(row, "I_source_max_mA")
            current_source = "I_source_avg_mA (N=1 fallback)"
        if i is None:
            raise ValueError(f"Missing current for {row['run_id']} {module}")
        v, v_min, v_max = num(row, prefix_v + "_avg_V"), num(row, prefix_v + "_min_V"), num(row, prefix_v + "_max_V")
        t = first_number(row, "T_stm32_stable_C", "T_module0_stm32_C") if n == 1 else num(row, f"T_module{column}_stm32_C")
        branch = {
            **context, "module_id": module, "source_column": column, "current_source_field": current_source,
            "identity_verification": "experiment_label_not_hardware_UID_verified",
            "I_recorded_mA": i, "I_min_recorded_mA": i_min, "I_max_recorded_mA": i_max,
            "V_recorded_V": v, "V_min_recorded_V": v_min, "V_max_recorded_V": v_max,
            "V_source_recorded_V": source_v,
            "drop_recorded_mV": None if v is None or source_v is None else (source_v - v) * 1000,
            "P_branch_est_mW": None if v is None else v * i,
            "T_STM32_recorded_C": t,
            "T_regulator_recorded_C": first_number(row, "T_regulator_C", "T_regulator_stable_C"),
            "T_Teensy_recorded_C": first_number(row, "T_teensy_C", "T_teensy_stable_C"),
        }
        branches.append(branch)
        if i_min is not None and i_max is not None and (i < i_min - 1e-10 or i > i_max + 1e-10):
            outside = max(i_min - i, i - i_max, 0)
            issue("CURRENT_REPRESENTATIVE_OUTSIDE_MINMAX", current_source,
                  f"Representative={i:g} mA; MIN={i_min:g}; MAX={i_max:g}; outside by {outside:.6f} mA. Check instrument display/rounding; do not replace values.", module)
    total = sum(b["I_recorded_mA"] for b in branches)
    original_total = num(row, "I_total_avg_mA")
    if original_total is not None and abs(original_total - total) > 1e-6:
        issue("TOTAL_DIFFERS_FROM_BRANCH_SUM", "I_total_avg_mA", f"Recorded total {original_total:g}; branch sum {total:g} mA")
    is_new = row["_source_kind"] == "continuous_yaml"
    for field in ("date", "measurement_start_time", "operator"):
        if is_new and not row.get(field):
            issue("MISSING_ACQUISITION_METADATA", field, "Not recorded; photograph filename is not accepted as a confirmed acquisition timestamp.")
    if is_new:
        issue("FAULT_DEFAULTS_UNVERIFIED", ",".join(FAULT_FIELDS), "Template-default counters are not independently confirmed observations.")
        issue("DURATION_FIELDS_UNVERIFIED", "warmup_duration_s,measurement_duration_s", "30 s and 10 s are prefilled nominal metadata, not independently verified elapsed durations.")
        if row["load"] == "MAX":
            issue("LOAD_APPLICATION_UNSPECIFIED", "load_mass_g,load_area_mm2,load_application", "2000 g is recorded but per-module/system distribution, contact area, position and layer are unresolved.")
    run = {
        **context, "modules": modules, "I_sum_mA": total,
        "I_total_original_field_mA": original_total,
        "I_sum_min_est_mA": sum(b["I_min_recorded_mA"] for b in branches) if all(b["I_min_recorded_mA"] is not None for b in branches) else None,
        "I_sum_max_est_mA": sum(b["I_max_recorded_mA"] for b in branches) if all(b["I_max_recorded_mA"] is not None for b in branches) else None,
        "V_source_recorded_V": source_v,
        "V_source_min_recorded_V": num(row, "V_source_min_V"),
        "V_source_max_recorded_V": num(row, "V_source_max_V"),
        "P_output_est_mW": None if source_v is None else source_v * total,
        "V_module_recorded_min_V": extreme((b["V_recorded_V"] for b in branches), min),
        "V_module_recorded_max_V": extreme((b["V_recorded_V"] for b in branches), max),
        "V_module_min_recorded_V": extreme((b["V_min_recorded_V"] for b in branches), min),
        "V_module_max_recorded_V": extreme((b["V_max_recorded_V"] for b in branches), max),
        "max_drop_recorded_mV": extreme((b["drop_recorded_mV"] for b in branches), max),
        "T_STM32_max_recorded_C": extreme((b["T_STM32_recorded_C"] for b in branches), max),
        "T_regulator_recorded_C": branches[0]["T_regulator_recorded_C"],
        "T_Teensy_recorded_C": branches[0]["T_Teensy_recorded_C"],
        "n_repeat": 1, "SD_repeat_mA": None,
        "source_quality_label": row.get("data_quality"), "date_recorded": row.get("date") or None,
        "measurement_start_recorded": row.get("measurement_start_time") or None,
        "operator_recorded": row.get("operator") or None,
        "load_mass_recorded_g": num(row, "load_mass_g"), "load_area_recorded_mm2": num(row, "load_area_mm2"),
        "load_application_recorded": row.get("load_application") or None,
        "load_equivalence_verified": False,
        "warmup_duration_nominal_s": num(row, "warmup_duration_s"),
        "measurement_duration_nominal_s": num(row, "measurement_duration_s"),
        "duration_verified": False, "fault_zero_observation_verified": False,
        "fault_counts_as_recorded": {key: row.get(key) for key in FAULT_FIELDS},
        "temperature_equilibrium_verified": False,
        "reading_semantics": "recorded_representative_not_verified_time_average",
    }
    return run, branches, issues


def aggregate(runs: list[dict]) -> list[dict]:
    exact = defaultdict(list)
    groups = defaultdict(list)
    for r in runs:
        key = (r["state"], r["protocol_mode"], r["frequency_hz"], r["load"], r["N"])
        groups[key].append(r)
        exact[(*key, r["combo"])].append(r)
    for values in exact.values():
        for r in values:
            r["n_repeat"] = len(values)
            r["SD_repeat_mA"] = statistics.stdev(v["I_sum_mA"] for v in values) if len(values) >= 2 else None
    result = []
    for key, values in sorted(groups.items()):
        combo_means = [statistics.mean(v["I_sum_mA"] for v in exact[(*key, combo)]) for combo in sorted({r["combo"] for r in values})]
        result.append(dict(zip(("state", "protocol_mode", "frequency_hz", "load", "N"), key)) | {
            "n_recordings": len(values), "n_combinations": len(combo_means),
            "n_repeat_min": min(r["n_repeat"] for r in values), "n_repeat_max": max(r["n_repeat"] for r in values),
            "I_combo_mean_mA": statistics.mean(combo_means),
            "SD_between_combinations_mA": statistics.stdev(combo_means) if len(combo_means) >= 2 else None,
            "SD_repeat_mA": None if all(r["n_repeat"] == 1 for r in values) else "see exact-combination run metrics",
            "I_recording_min_mA": min(r["I_sum_mA"] for r in values), "I_recording_max_mA": max(r["I_sum_mA"] for r in values),
            "combinations": sorted({r["combo"] for r in values}),
            "run_ids": [r["run_id"] for r in values],
            "dispersion_interpretation": "between recorded labelled modules/combinations; not repeatability",
        })
    return result


def comparisons(runs: list[dict]) -> tuple[list[dict], list[dict]]:
    solo = defaultdict(list)
    pairs = defaultdict(dict)
    for r in runs:
        key = (r["state"], r["protocol_mode"], r["frequency_hz"], r["load"])
        if r["N"] == 1:
            solo[(*key, r["modules"][0])].append(r)
        pairs[(r["state"], r["protocol_mode"], r["frequency_hz"], r["combo"], r["repeat"])][r["load"]] = r
    predictions = []
    for r in runs:
        if r["N"] < 2:
            continue
        key = (r["state"], r["protocol_mode"], r["frequency_hz"], r["load"])
        refs = [solo.get((*key, module), []) for module in r["modules"]]
        if not all(refs):
            continue
        prediction = sum(statistics.mean(v["I_sum_mA"] for v in rr) for rr in refs)
        predictions.append({k: r[k] for k in ("run_id", "state", "protocol_mode", "frequency_hz", "load", "N", "combo", "repeat")} | {
            "observed_I_mA": r["I_sum_mA"], "predicted_I_mA": prediction,
            "residual_mA": r["I_sum_mA"] - prediction,
            "residual_percent": 100 * (r["I_sum_mA"] - prediction) / prediction,
            "reference_run_ids": [v["run_id"] for rr in refs for v in rr],
            "comparability": "zero_load" if r["load"] == "ZERO" else "conditional_load_equivalence",
            "identity_assumption": "recorded_module_labels_consistent_across_runs_not_UID_verified",
        })
    loading = []
    for records in pairs.values():
        if not {"ZERO", "MAX"}.issubset(records):
            continue
        zero, loaded = records["ZERO"], records["MAX"]
        loading.append({k: zero[k] for k in ("state", "protocol_mode", "frequency_hz", "N", "combo", "repeat")} | {
            "zero_run_id": zero["run_id"], "loaded_run_id": loaded["run_id"],
            "I_zero_mA": zero["I_sum_mA"], "I_loaded_mA": loaded["I_sum_mA"],
            "delta_I_mA": loaded["I_sum_mA"] - zero["I_sum_mA"],
            "delta_I_percent": 100 * (loaded["I_sum_mA"] - zero["I_sum_mA"]) / zero["I_sum_mA"],
            "P_zero_est_mW": zero["P_output_est_mW"], "P_loaded_est_mW": loaded["P_output_est_mW"],
            "load_protocol_complete": False, "n_paired_recordings": 1,
        })
    return predictions, loading


def descriptive_fits(runs: list[dict]) -> list[dict]:
    """OLS on four equally weighted N means, not on unequal record counts."""
    conditions = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in runs:
        if r["protocol_mode"] == "FULL" and r["frequency_hz"] == 200:
            conditions[(r["state"], r["load"])][r["N"]][r["combo"]].append(r)
    output = []
    for (state, load), by_n in sorted(conditions.items()):
        if len(by_n) < 2:
            continue
        for metric in ("I_sum_mA", "P_output_est_mW"):
            points = []
            for n, by_combo in sorted(by_n.items()):
                combo_values = [statistics.mean(r[metric] for r in rr) for rr in by_combo.values()]
                points.append({"N": n, "mean_across_combinations": statistics.mean(combo_values), "n_combinations": len(combo_values)})
            xs = [p["N"] for p in points]
            ys = [p["mean_across_combinations"] for p in points]
            xbar, ybar = statistics.mean(xs), statistics.mean(ys)
            slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sum((x - xbar)**2 for x in xs)
            intercept = ybar - slope * xbar
            for point in points:
                point["fitted"] = intercept + slope * point["N"]
                point["residual"] = point["mean_across_combinations"] - point["fitted"]
            sse = sum(p["residual"]**2 for p in points)
            sst = sum((y - ybar)**2 for y in ys)
            output.append({"state": state, "load": load, "protocol_mode": "FULL", "frequency_hz": 200,
                           "metric": metric, "slope_per_module": slope, "intercept": intercept,
                           "R_squared_descriptive": 1-sse/sst if sst else None, "points": points,
                           "weighting": "equal weight per N; equal combination means within N",
                           "inference": "descriptive only; R_squared does not independently validate scalability; no repeat-derived CI"})
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def facts(summary: dict) -> str:
    new = [r for r in summary["runs"] if r["state"] == CONTINUOUS]
    lines = ["# Power report 2.1: reproducible recorded-data facts", "",
             "18 continuous USB-read YAML records (9 ZERO, 9 MAX), FULL at 200 Hz; 13 separate legacy blocked-standby CSV records. Standby YAML duplicates are excluded.", "",
             "Every exact continuous condition has R1 only. N=1: four labelled modules; N=2: two combinations; N=3: two combinations; N=4: one combination. Different combinations are not repeat recordings.", "",
             "## Continuous USB-read results", "",
             "| Load | N | Combination | Current sum (mA) | Output power estimate (mW) | Lowest module representative (V) | Lowest module MIN field (V) |",
             "|---|---:|---|---:|---:|---:|---:|"]
    if summary.get("quality_events"):
        lines[2:2] = ["> Historical reproduction only: the user identified a connector fault at M0 in the N=3 M0-M1-M2 ZERO record, while confirming SOURCE/M1/M2 voltages unchanged and valid. The original M0 3.224 V remains below for traceability. The voltage review uses 3.241 V from the separate M0 retest with per-point provenance, retaining the other voltage points. This is a user-confirmed correction, not a new simultaneous run or independent repeat.", ""]
    for r in sorted(new, key=lambda x: (x["load"], x["N"], x["combo"])):
        lines.append(f"| {r['load']} | {r['N']} | {r['combo']} | {r['I_sum_mA']:.3f} | {r['P_output_est_mW']:.3f} | {r['V_module_recorded_min_V']:.3f} | {r['V_module_min_recorded_V']:.3f} |")
    lines += ["", "## Independent N=1 prediction", "", "Residual = 100 × (observed branch sum − sum of separately recorded N=1 currents) / predicted sum. MAX results require equivalent loading; module labels are assumed consistent across runs.", "", "| Load | Combination | Predicted (mA) | Observed (mA) | Residual (%) |", "|---|---|---:|---:|---:|"]
    for p in summary["predictions"]:
        if p["state"] == CONTINUOUS:
            lines.append(f"| {p['load']} | {p['combo']} | {p['predicted_I_mA']:.3f} | {p['observed_I_mA']:.3f} | {p['residual_percent']:.4f} |")
    lines += ["", "## Matched load comparisons", "", "| Combination | ZERO (mA) | MAX (mA) | Increase (mA) | Increase (%) |", "|---|---:|---:|---:|---:|"]
    for p in summary["load_pairs"]:
        if p["state"] == CONTINUOUS:
            lines.append(f"| {p['combo']} | {p['I_zero_mA']:.3f} | {p['I_loaded_mA']:.3f} | {p['delta_I_mA']:.3f} | {p['delta_I_percent']:.4f} |")
    lines += ["", "## Limits on interpretation", ""] + [f"- {x}" for x in LIMITATIONS]
    rounding = [q for q in summary["qc_issues"] if q["code"] == "CURRENT_REPRESENTATIVE_OUTSIDE_MINMAX" and q["state"] == CONTINUOUS]
    lines += ["", f"{len(rounding)} continuous current representative readings fall outside their recorded MIN/MAX range by at most 0.005 mA. Original readings are retained.", ""]
    for q in rounding:
        lines.append(f"- {q['run_id']} / {q['module_id']}: {q['detail']}")
    lowest = min((b for b in summary["branches"] if b["state"] == CONTINUOUS), key=lambda b: b["V_min_recorded_V"])
    lines += ["", f"Lowest continuous module MIN field: {lowest['V_min_recorded_V']:.3f} V, {lowest['run_id']}, {lowest['module_id']}; margin above 3.135 V: {(lowest['V_min_recorded_V']-3.135)*1000:.1f} mV. This is a recorded DMM value, not a high-speed transient guarantee.", ""]
    return "\n".join(lines)


def analyze(root: Path = ROOT, output: Path | None = None) -> dict:
    root = root.resolve()
    output = (output or root / "DATA" / "reference" / "analysis_v2_1").resolve()
    forbidden = [root / "DATA" / "raw", root / "DATA" / "analysis"]
    if any(output == path or path in output.parents for path in forbidden) or output == root / "DATA":
        raise ValueError("Output must not overwrite raw records or legacy analysis")
    rows, sources = load_sources(root)
    runs, branches, issues = [], [], []
    for row in rows:
        run, branch, issue = derive(row)
        runs.append(run)
        branches.extend(branch)
        issues.extend(issue)
    groups = aggregate(runs)
    predictions, loading = comparisons(runs)
    timestamp = datetime.now(timezone.utc).isoformat()
    quality_event_paths = sorted((root / "DATA/raw/canonical/power_experiment_records/quality_events").glob("*.json"))
    quality_events = [json.loads(p.read_text(encoding="utf-8")) for p in quality_event_paths]
    if quality_events:
        import warnings
        warnings.warn("Historical report 2.1 reproduction retains the original M0 connector-fault voltage point (3.224 V). SOURCE/M1/M2 were confirmed unchanged and valid. Consult quality_events and summarize_voltage_review.py for the pointwise-corrected voltage configuration.", RuntimeWarning)
    excluded = sorted((root / "DATA" / "raw" / "canonical" / "power_experiment_records" / "no_transmission").rglob("*.yaml"))
    voltage_only = [p for p in sorted((root / "DATA/raw/canonical/power_experiment_records/transmission").rglob("*.yaml"))
                    if (yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}).get("measurement_scope") == "VOLTAGE_ONLY"]
    manifest = {"schema_version": 1, "created_utc": timestamp, "analysis_version": "2.1", "sources": sources,
                "quality_event_sources": [{"relative_path": p.relative_to(root).as_posix(), "sha256": digest(p)} for p in quality_event_paths],
                "interpretation": "Historical report 2.1 numeric reproduction; registered contact faults are retained, not filtered from legacy fits or tables.",
                "excluded_voltage_only_yaml_count": len(voltage_only),
                "excluded_voltage_only_reason": "Supplementary voltage records have no branch currents; excluded from the report 2.1 combined-demand dataset.",
                "excluded_voltage_only_yaml_paths": [p.relative_to(root).as_posix() for p in voltage_only],
                "excluded_standby_yaml_count": len(excluded), "excluded_reason": "Legacy CSV is the canonical standby input; standby YAML duplicates are not counted again.",
                "excluded_standby_yaml_paths": [p.relative_to(root).as_posix() for p in excluded],
                "analysis_script_sha256": digest(Path(__file__)), "source_files_verified_unchanged": False}
    summary = {"schema_version": 1, "analysis_version": "2.1", "created_utc": timestamp,
               "runs": runs, "branches": branches, "groups": groups, "predictions": predictions,
               "quality_events": quality_events,
               "load_pairs": loading, "qc_issues": issues, "limitations": LIMITATIONS,
               "descriptive_fits": descriptive_fits(runs),
               "counts": {"total_runs": len(runs), "continuous_runs": sum(r["state"] == CONTINUOUS for r in runs),
                          "blocked_runs": sum(r["state"] == BLOCKED for r in runs), "branches": len(branches)},
               "provenance": manifest}
    output.mkdir(parents=True, exist_ok=True)
    for filename, values in (("run_metrics.csv", runs), ("branch_metrics.csv", branches), ("group_summary.csv", groups),
                             ("prediction_checks.csv", predictions), ("load_pairs.csv", loading), ("qc_issues.csv", issues)):
        write_csv(output / filename, values)
    for source in sources:
        if digest(root / source["relative_path"]) != source["sha256"]:
            raise RuntimeError(f"Source changed during analysis: {source['relative_path']}")
    manifest["source_files_verified_unchanged"] = True
    (output / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "analysis_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (output / "REPORT_FACTS.md").write_text(facts(summary), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = analyze(args.root, args.output)
    print(json.dumps({"counts": summary["counts"], "source_files_verified_unchanged": summary["provenance"]["source_files_verified_unchanged"],
                      "output": str((args.output or args.root / "DATA" / "reference" / "analysis_v2_1").resolve())}, indent=2))


if __name__ == "__main__":
    main()
