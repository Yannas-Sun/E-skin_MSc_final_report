"""Auditable voltage-only review; never merge repaired and original sessions.

Outputs are isolated from the frozen power analysis. Voltage/drop numbers in JSON
are decimal strings; CSV preserves the same decimal representation. ``avg`` input
fields are described as main/representative readings, not verified time averages.
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_REL = Path("DATA/analysis/current/voltage_review_20260907")
EVENT_REL = Path("DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json")
FAULT = "SUPPLY_CONTACT_FAULT"
UNREPORTED = "no_reported_supply_contact_fault"


class DecimalLoader(yaml.SafeLoader):
    """Keep source decimal literals exact, without a binary-float round trip."""


DecimalLoader.add_constructor(
    "tag:yaml.org,2002:float", lambda loader, node: Decimal(loader.construct_scalar(node))
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_unchanged(before: dict[Path, str]) -> None:
    changed = [str(path) for path, digest in before.items() if not path.is_file() or sha(path) != digest]
    if changed:
        raise RuntimeError("Protected input changed: " + ", ".join(changed))


def number(value) -> Decimal | None:
    if value is None or str(value).strip() in ("", "N/A", "NOT_AVAILABLE"):
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite voltage")
    return result


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def module_ids(value: str) -> list[str]:
    labels = [label.strip().replace("Module", "M") for label in value.split(",")]
    if not labels or len(labels) != len(set(labels)) or any(label not in ("M0", "M1", "M2", "M3") for label in labels):
        raise ValueError(f"Invalid module identifiers: {value!r}")
    return sorted(labels)


def voltage_triplet(raw: dict, prefix: str) -> dict:
    readings = {label: number(raw.get(prefix + suffix)) for label, suffix in (
        ("main_V", "_avg_V"), ("min_V", "_min_V"), ("max_V", "_max_V")
    )}
    if all(value is not None for value in readings.values()):
        if not readings["min_V"] <= readings["main_V"] <= readings["max_V"]:
            raise ValueError(f"MIN/main/MAX order invalid: {raw['run_id']} {prefix}")
    return readings


def derive_run(raw: dict, source_path: str, source_hash: str, event: dict) -> tuple[dict, list[dict]]:
    connected = module_ids(raw["module_ids"])
    if len(connected) != raw["module_count"]:
        raise ValueError("module_count differs from connected module IDs")
    declared_measured = module_ids(raw.get("measured_module_ids", raw["module_ids"]))
    if not set(declared_measured) <= set(connected):
        raise ValueError("Measured module is not connected")
    source = voltage_triplet(raw, "V_source")
    quality = FAULT if raw["run_id"] == event["affected_run_id"] else UNREPORTED
    is_repair = raw["run_id"] == event["replacement_run_id"]
    run = {
        "run_id": raw["run_id"], "combo": "+".join(connected), "module_count": len(connected),
        "connected_module_ids": ",".join(connected), "load": raw["load"],
        "record_kind": raw.get("record_kind", "ORIGINAL_FULL_RECORD"),
        "measurement_scope": raw.get("measurement_scope", "ORIGINAL_MULTIMODAL_RECORD"),
        "quality_class": quality, "included_no_reported_supply_contact_fault": quality != FAULT,
        "post_repair_record": is_repair,
        "independent_repeat_of_original_condition": False if is_repair else None,
        "retest_of_run_id": raw.get("retest_of_run_id"),
        "source_path": source_path, "source_sha256": source_hash,
        **{"source_" + key: decimal_text(value) for key, value in source.items()},
    }
    rows = []
    for module in connected:
        column = "0" if len(connected) == 1 else module[1:]
        values = voltage_triplet(raw, "V_module" + column)
        if module not in declared_measured:
            if any(value is not None for value in values.values()):
                raise ValueError("Undeclared measured-module voltage exists")
            continue
        if values["main_V"] is None:
            raise ValueError(f"Declared measured module lacks main reading: {raw['run_id']} {module}")
        drop = None if source["main_V"] is None else (source["main_V"] - values["main_V"]) * Decimal(1000)
        rows.append({
            **run, "module_id": module, "source_column": int(column),
            **{"module_" + key: decimal_text(value) for key, value in values.items()},
            "source_to_module_drop_mV": decimal_text(drop),
            "drop_basis": "source_and_module_main_in_same_record" if drop is not None else "unavailable_no_source_in_this_record",
        })
    complete = len(rows) == len(connected) and all(value is not None for value in source.values()) and all(
        row[key] is not None for row in rows for key in ("module_main_V", "module_min_V", "module_max_V")
    )
    run.update(measured_module_ids=",".join(row["module_id"] for row in rows),
               measured_module_count=len(rows), complete_voltage_record=complete)
    for row in rows:
        row["measured_module_ids"] = run["measured_module_ids"]
        row["measured_module_count"] = len(rows)
        row["complete_voltage_record"] = complete
    return run, rows


def extremum(rows: list[dict], field: str, maximum: bool = False) -> dict | None:
    available = [(number(row[field]), row) for row in rows if row.get(field) is not None]
    if not available:
        return None
    value = (max if maximum else min)(value for value, _ in available)
    return {"value": decimal_text(value), "points": [
        {key: row[key] for key in ("run_id", "combo", "load", "module_id", "quality_class") if key in row}
        for candidate, row in available if candidate == value
    ]}


def scoped_summary(runs: list[dict], rows: list[dict]) -> dict:
    return {
        "run_count": len(runs), "module_voltage_point_count": len(rows),
        "complete_voltage_run_count": sum(run["complete_voltage_record"] for run in runs),
        "partial_voltage_run_count": sum(not run["complete_voltage_record"] for run in runs),
        "post_repair_record_count": sum(run["post_repair_record"] for run in runs),
        "minimum_module_main_V": extremum(rows, "module_main_V"),
        "minimum_module_recorded_min_V": extremum(rows, "module_min_V"),
        "minimum_source_main_V": extremum(runs, "source_main_V"),
        "minimum_source_recorded_min_V": extremum(runs, "source_min_V"),
        "maximum_same_record_source_to_module_drop_mV": extremum(rows, "source_to_module_drop_mV", True),
        "module_points_with_same_record_drop": sum(row["source_to_module_drop_mV"] is not None for row in rows),
    }


def build_coverage(runs: list[dict]) -> list[dict]:
    coverage = []
    for load in ("ZERO", "MAX"):
        for count in range(1, 5):
            for modules in itertools.combinations(("M0", "M1", "M2", "M3"), count):
                combo = "+".join(modules)
                historical = [run for run in runs if run["load"] == load and run["combo"] == combo]
                included = [run for run in historical if run["quality_class"] != FAULT]
                complete = [run for run in included if run["complete_voltage_record"]]
                partial = [run for run in included if not run["complete_voltage_record"]]
                coverage.append({
                    "load": load, "module_count": count, "combo": combo,
                    "historical_run_count": len(historical),
                    "historical_complete_voltage_record_count": sum(run["complete_voltage_record"] for run in historical),
                    "known_supply_contact_fault_run_count": len(historical) - len(included),
                    "no_reported_supply_contact_fault_complete_record_count": len(complete),
                    "no_reported_supply_contact_fault_partial_record_count": len(partial),
                    "no_reported_supply_contact_fault_coverage": "COMPLETE" if complete else "PARTIAL" if partial else "MISSING",
                    "post_repair_record_count": sum(run["post_repair_record"] for run in included),
                    "repair_records_counted_as_same_condition_repeats": 0,
                    "complete_run_ids": ";".join(run["run_id"] for run in complete),
                    "partial_run_ids": ";".join(run["run_id"] for run in partial),
                    "known_fault_run_ids": ";".join(run["run_id"] for run in historical if run["quality_class"] == FAULT),
                })
    return coverage


def csv_text(rows: list[dict]) -> str:
    result = io.StringIO(newline="")
    writer = csv.DictWriter(result, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return result.getvalue()


def review(root: Path = ROOT, output: Path | None = None) -> dict:
    root = root.resolve()
    output = (output or root / OUTPUT_REL).resolve()
    # The one production output folder is deliberate; temporary external output is
    # permitted for tests, but neither raw records nor old analysis can be targeted.
    if output.is_relative_to(root) and output != root / OUTPUT_REL:
        raise ValueError("Within this project, output must be DATA/analysis/current/voltage_review_20260907")
    paths = sorted((root / "DATA/raw/canonical/power_experiment_records/transmission").rglob("*.yaml"))
    event_path = root / EVENT_REL
    before = {path: sha(path) for path in [*paths, event_path]}
    event = json.loads(event_path.read_text(encoding="utf-8-sig"))
    affected_path = root / event["affected_record_path"]
    if before.get(affected_path) != event["affected_record_sha256"]:
        raise ValueError("Fault event no longer matches the preserved original record hash")
    runs, rows = [], []
    for path in paths:
        raw = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=DecimalLoader)
        if raw.get("host_usb_polling_state") != "CONTINUOUS_USB_READ" or raw.get("protocol_mode") != "FULL" or raw.get("frequency_hz") != 200:
            raise ValueError("Unexpected condition in continuous FULL/200 Hz source folder")
        if raw.get("load") not in ("ZERO", "MAX"):
            raise ValueError("Unexpected load")
        run, points = derive_run(raw, path.relative_to(root).as_posix(), before[path], event)
        runs.append(run)
        rows.extend(points)
    ids = [run["run_id"] for run in runs]
    if len(ids) != len(set(ids)) or any(ids.count(event[key]) != 1 for key in ("affected_run_id", "replacement_run_id")):
        raise ValueError("Duplicate or missing event-linked run")
    coverage = build_coverage(runs)
    cohorts = {}
    for cohort in ("raw_historical_including_known_fault", UNREPORTED):
        cohort_runs = [run for run in runs if cohort != UNREPORTED or run["quality_class"] != FAULT]
        cohort_rows = [row for row in rows if cohort != UNREPORTED or row["quality_class"] != FAULT]
        cohorts[cohort] = {
            load: scoped_summary(
                [run for run in cohort_runs if load == "ALL" or run["load"] == load],
                [row for row in cohort_rows if load == "ALL" or row["load"] == load],
            ) for load in ("ALL", "ZERO", "MAX")
        }
    coverage_summary = {}
    for load in ("ZERO", "MAX"):
        coverage_summary[load] = {}
        for count in ("ALL", 1, 2, 3, 4):
            selected = [row for row in coverage if row["load"] == load and (count == "ALL" or row["module_count"] == count)]
            coverage_summary[load][str(count)] = {
                "nominal_subsets": len(selected),
                **{status.lower() + "_subsets": sum(row["no_reported_supply_contact_fault_coverage"] == status for row in selected) for status in ("COMPLETE", "PARTIAL", "MISSING")},
                "known_supply_contact_fault_run_count": sum(row["known_supply_contact_fault_run_count"] for row in selected),
            }
    verify_unchanged(before)
    summary = {
        "review_id": "voltage_review_20260907",
        "scope": "FULL, configured 200 Hz, continuous USB read, voltage only",
        "definitions": {
            "raw_historical_including_known_fault": "All supplied continuous-read records, including additions, original fault condition, and separate repaired M0 record.",
            UNREPORTED: "No supply-contact fault has been reported for this record; this does not establish verified fault-free operation.",
            "complete_voltage_record": "Same record contains main/MIN/MAX source voltage and main/MIN/MAX voltage for every connected module.",
            "main_reading": "Existing avg fields retained as main/representative readings; not verified time averages.",
            "recorded_min": "Meter MIN field, not a statistical lower confidence bound or an independently repeated run.",
            "drop": "Decimal (source main - module main) * 1000 using values from the same record only; sequential readings are not guaranteed simultaneous.",
            "numeric_encoding": "Voltage and voltage-drop quantities are exact decimal strings; CSV blank and JSON null mean unavailable.",
            "repair": "M0-only measurement after a changed supply-contact condition; not pooled as an independent repeat of the original condition.",
        },
        "counts": {"input_runs": len(runs), "module_voltage_points": len(rows),
                   "known_supply_contact_fault_runs": sum(run["quality_class"] == FAULT for run in runs),
                   "excluded_fault_condition_module_points": sum(row["quality_class"] == FAULT for row in rows),
                   "no_reported_supply_contact_fault_module_points": sum(row["quality_class"] != FAULT for row in rows)},
        "quality_event": event,
        "summaries": cohorts,
        "coverage": coverage_summary,
        "runs": runs,
        "provenance": {
            "source_files_verified_unchanged": True,
            "sources": [{"path": path.relative_to(root).as_posix(), "sha256": digest} for path, digest in before.items()],
            "old_analysis_or_report_written": False,
        },
    }
    content = {"module_voltages.csv": csv_text(rows), "coverage.csv": csv_text(coverage),
               "summary.json": json.dumps(summary, indent=2, ensure_ascii=False) + "\n"}
    verify_unchanged(before)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in content.items():
        (output / name).write_text(value, encoding="utf-8", newline="")
    verify_unchanged(before)
    return summary


if __name__ == "__main__":
    result = review()
    print(json.dumps({"counts": result["counts"], "coverage": result["coverage"]}, indent=2))
