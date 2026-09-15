"""Auditable voltage-only review with an explicit pointwise correction layer.

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

from photo_source_paths import RELOCATION_REL, resolve_photo

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
OUTPUT_REL = Path("DATA/analysis/current/voltage_review_20260907")
EVENT_REL = Path("DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json")
FAULT = "SUPPLY_CONTACT_FAULT"
UNREPORTED = "no_reported_supply_contact_fault"
POINT_FAULT_RUN = "CONTAINS_POINT_SPECIFIC_SUPPLY_CONTACT_FAULT"
CORRECTION = "USER_CONFIRMED_POINTWISE_CORRECTION"


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
    affected = raw["run_id"] == event["affected_run_id"]
    fault_points = set(event["affected_voltage_points"]) if affected else set()
    quality = POINT_FAULT_RUN if fault_points else UNREPORTED
    is_repair = raw["run_id"] == event["replacement_run_id"]
    run = {
        "run_id": raw["run_id"], "combo": "+".join(connected), "module_count": len(connected),
        "connected_module_ids": ",".join(connected), "load": raw["load"],
        "record_kind": raw.get("record_kind", "ORIGINAL_FULL_RECORD"),
        "measurement_scope": raw.get("measurement_scope", "ORIGINAL_MULTIMODAL_RECORD"),
        "quality_class": quality,
        "contains_known_fault_voltage_point": bool(fault_points),
        "affected_voltage_points": ",".join(sorted(fault_points)),
        "source_quality_class": FAULT if "SOURCE" in fault_points else UNREPORTED,
        "included_no_reported_supply_contact_fault": "SOURCE" not in fault_points or bool(set(declared_measured) - fault_points),
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
            "quality_class": FAULT if module in fault_points else UNREPORTED,
            "included_no_reported_supply_contact_fault": module not in fault_points,
            **{"module_" + key: decimal_text(value) for key, value in values.items()},
            "source_to_module_drop_mV": decimal_text(drop),
            "drop_basis": "source_and_module_main_in_same_record" if drop is not None else "unavailable_no_source_in_this_record",
        })
    complete = len(rows) == len(connected) and all(value is not None for value in source.values()) and all(
        row[key] is not None for row in rows for key in ("module_main_V", "module_min_V", "module_max_V")
    )
    accepted_complete = complete and not fault_points
    run.update(measured_module_ids=",".join(row["module_id"] for row in rows),
               measured_module_count=len(rows), complete_voltage_record=complete,
               accepted_complete_voltage_record=accepted_complete)
    for row in rows:
        row["measured_module_ids"] = run["measured_module_ids"]
        row["measured_module_count"] = len(rows)
        row["complete_voltage_record"] = complete
        row["accepted_complete_voltage_record"] = accepted_complete
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
        "accepted_complete_same_record_voltage_run_count": sum(run["accepted_complete_voltage_record"] for run in runs),
        "partial_voltage_run_count": sum(not run["complete_voltage_record"] for run in runs),
        "post_repair_record_count": sum(run["post_repair_record"] for run in runs),
        "minimum_module_main_V": extremum(rows, "module_main_V"),
        "minimum_module_recorded_min_V": extremum(rows, "module_min_V"),
        "minimum_source_main_V": extremum(runs, "source_main_V"),
        "minimum_source_recorded_min_V": extremum(runs, "source_min_V"),
        "maximum_same_record_source_to_module_drop_mV": extremum(rows, "source_to_module_drop_mV", True),
        "module_points_with_same_record_drop": sum(row["source_to_module_drop_mV"] is not None for row in rows),
    }


def photo_provenance(root: Path, raw: dict, run: dict, point: str) -> dict:
    evidence = [item for item in raw.get("voltage_photo_evidence", []) if item["role"] == point]
    paths, hashes, original_paths = [], [], []
    for item in evidence:
        reference = ((root / run["source_path"]).parent / item["file"]).resolve()
        path = resolve_photo(root, reference, item["sha256"])
        digest = sha(path)
        if digest != item["sha256"]:
            raise ValueError("Voltage photo hash no longer matches its record")
        paths.append(path.relative_to(root).as_posix())
        hashes.append(digest)
        original_paths.append(reference.relative_to(root).as_posix())
    return {"photo_paths": ";".join(paths), "photo_sha256": ";".join(hashes),
            "photo_original_references": ";".join(original_paths),
            "photo_mapping_basis": "record_voltage_photo_evidence" if paths else "not_mapped_in_original_record"}


def build_accepted_configurations(root: Path, runs: list[dict], rows: list[dict], raws: dict, event: dict) -> tuple[list[dict], list[dict]]:
    """Select accepted voltage points without creating or modifying acquisitions."""
    by_run = {run["run_id"]: run for run in runs}
    by_point = {(row["run_id"], row["module_id"]): row for row in rows}
    corrected = event["accepted_voltage_configuration"]
    mapping = corrected["point_source_run_ids"]
    required = {"SOURCE", *corrected["combo"].split("+")}
    if set(mapping) != required or corrected["kind"] != CORRECTION:
        raise ValueError("Correction mapping does not cover exactly the connected voltage points")
    if not event["retained_voltage_values_user_confirmed_unchanged"] or not event["drop_recalculation_allowed_with_user_confirmed_unchanged_source"]:
        raise ValueError("Pointwise correction requires explicit unchanged-point confirmation")
    if corrected["counts_as_additional_independent_run"] or corrected["simultaneous_new_acquisition_claimed"] or event["repeatability_pooling_allowed"]:
        raise ValueError("Pointwise correction must not create a new acquisition or repeat")
    unaffected = set(event["confirmed_unaffected_voltage_points"])
    affected = set(event["affected_voltage_points"])
    if affected & unaffected or affected | unaffected != required:
        raise ValueError("Fault and unaffected scopes must partition the correction points")
    for point, run_id in mapping.items():
        expected = event["affected_run_id"] if point in unaffected else event["replacement_run_id"]
        if run_id != expected:
            raise ValueError("Correction point provenance conflicts with confirmed event scope")
    configs, accepted = [], []
    keys = sorted({(run["load"], run["combo"]) for run in runs})
    for load, combo in keys:
        complete = [run for run in runs if (run["load"], run["combo"]) == (load, combo) and run["accepted_complete_voltage_record"]]
        is_corrected = (load, combo) == (corrected["load"], corrected["combo"])
        if not complete and not is_corrected:
            continue
        if len(complete) > 1:
            raise ValueError("Multiple complete acquisitions require an explicit selection policy")
        point_sources = mapping if is_corrected else {point: complete[0]["run_id"] for point in ("SOURCE", *combo.split("+"))}
        config = {"configuration_id": load + ":" + combo, "load": load, "combo": combo,
                  "module_count": len(combo.split("+")),
                  "configuration_kind": CORRECTION if is_corrected else "SAME_RECORD_VOLTAGE_CONFIGURATION",
                  "accepted_complete": True, "same_record_complete": not is_corrected,
                  "counts_as_additional_independent_run": False, "simultaneous_new_acquisition_claimed": False,
                  "point_source_run_ids": dict(point_sources)}
        configs.append(config)
        source_run = by_run[point_sources["SOURCE"]]
        if source_run["source_quality_class"] == FAULT:
            raise ValueError("Accepted source point is flagged as faulty")
        for point in ("SOURCE", *combo.split("+")):
            run = by_run[point_sources[point]]
            if (run["load"], run["combo"]) != (load, combo):
                raise ValueError("Correction combines different loads or module configurations")
            point_row = run if point == "SOURCE" else by_point[(run["run_id"], point)]
            if point_row["source_quality_class" if point == "SOURCE" else "quality_class"] == FAULT:
                raise ValueError("Accepted voltage point is flagged as faulty")
            prefix = "source_" if point == "SOURCE" else "module_"
            values = {key: point_row[prefix + key] for key in ("main_V", "min_V", "max_V")}
            if any(value is None for value in values.values()):
                raise ValueError("Accepted complete configuration has an unavailable voltage")
            same_record_drop = point != "SOURCE" and run["run_id"] == source_run["run_id"]
            drop = None if point == "SOURCE" else (number(source_run["source_main_V"]) - number(values["main_V"])) * Decimal(1000)
            accepted.append({
                **{key: value for key, value in config.items() if key != "point_source_run_ids"},
                "point_id": point, **values, "point_source_run_id": run["run_id"],
                "point_source_path": run["source_path"], "point_source_sha256": run["source_sha256"],
                "point_source_fields": ";".join(("V_source" if point == "SOURCE" else "V_module" + str(point_row["source_column"])) + suffix for suffix in ("_avg_V", "_min_V", "_max_V")),
                **photo_provenance(root, raws[run["run_id"]], run, point),
                "point_acceptance_basis": "user_confirmed_unchanged" if is_corrected and point in unaffected else "post_connector_repair_retest" if is_corrected else UNREPORTED,
                "source_reference_run_id": None if point == "SOURCE" else source_run["run_id"],
                "source_reference_main_V": None if point == "SOURCE" else source_run["source_main_V"],
                "source_to_point_drop_mV": decimal_text(drop),
                "drop_uses_same_record": same_record_drop if point != "SOURCE" else None,
                "drop_basis": "not_applicable_source_point" if point == "SOURCE" else "source_and_module_main_in_same_record" if same_record_drop else "user_confirmed_unchanged_source_minus_retested_module_estimate_not_same_record",
                "quality_event_id": event["event_id"] if is_corrected else None,
            })
    return configs, accepted


def build_coverage(runs: list[dict], configurations: list[dict]) -> list[dict]:
    coverage = []
    for load in ("ZERO", "MAX"):
        for count in range(1, 5):
            for modules in itertools.combinations(("M0", "M1", "M2", "M3"), count):
                combo = "+".join(modules)
                historical = [run for run in runs if run["load"] == load and run["combo"] == combo]
                included = [run for run in historical if run["included_no_reported_supply_contact_fault"]]
                complete = [run for run in included if run["accepted_complete_voltage_record"]]
                partial = [run for run in included if not run["accepted_complete_voltage_record"]]
                accepted = [config for config in configurations if (config["load"], config["combo"]) == (load, combo)]
                coverage.append({
                    "load": load, "module_count": count, "combo": combo,
                    "historical_run_count": len(historical),
                    "historical_complete_voltage_record_count": sum(run["complete_voltage_record"] for run in historical),
                    "known_supply_contact_fault_run_count": sum(run["contains_known_fault_voltage_point"] for run in historical),
                    "no_reported_supply_contact_fault_complete_record_count": len(complete),
                    "no_reported_supply_contact_fault_partial_record_count": len(partial),
                    "no_reported_supply_contact_fault_coverage": "COMPLETE" if complete else "PARTIAL" if partial else "MISSING",
                    "accepted_configuration_coverage": "COMPLETE" if accepted else "PARTIAL" if partial else "MISSING",
                    "accepted_configuration_kind": accepted[0]["configuration_kind"] if accepted else None,
                    "user_confirmed_pointwise_correction_count": sum(config["configuration_kind"] == CORRECTION for config in accepted),
                    "post_repair_record_count": sum(run["post_repair_record"] for run in included),
                    "repair_records_counted_as_same_condition_repeats": 0,
                    "complete_run_ids": ";".join(run["run_id"] for run in complete),
                    "partial_run_ids": ";".join(run["run_id"] for run in partial),
                    "known_fault_run_ids": ";".join(run["run_id"] for run in historical if run["contains_known_fault_voltage_point"]),
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
    runs, rows, raws = [], [], {}
    for path in paths:
        raw = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=DecimalLoader)
        if raw.get("host_usb_polling_state") != "CONTINUOUS_USB_READ" or raw.get("protocol_mode") != "FULL" or raw.get("frequency_hz") != 200:
            raise ValueError("Unexpected condition in continuous FULL/200 Hz source folder")
        if raw.get("load") not in ("ZERO", "MAX"):
            raise ValueError("Unexpected load")
        run, points = derive_run(raw, path.relative_to(root).as_posix(), before[path], event)
        runs.append(run)
        rows.extend(points)
        raws[run["run_id"]] = raw
    ids = [run["run_id"] for run in runs]
    if len(ids) != len(set(ids)) or any(ids.count(event[key]) != 1 for key in ("affected_run_id", "replacement_run_id")):
        raise ValueError("Duplicate or missing event-linked run")
    configurations, accepted_points = build_accepted_configurations(root, runs, rows, raws, event)
    coverage = build_coverage(runs, configurations)
    cohorts = {}
    for cohort in ("raw_historical_including_known_fault", UNREPORTED):
        cohort_runs = [run for run in runs if cohort != UNREPORTED or run["included_no_reported_supply_contact_fault"]]
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
                **{status.lower() + "_subsets": sum(row["accepted_configuration_coverage"] == status for row in selected) for status in ("COMPLETE", "PARTIAL", "MISSING")},
                "same_record_complete_subsets": sum(row["no_reported_supply_contact_fault_coverage"] == "COMPLETE" for row in selected),
                "user_confirmed_pointwise_corrected_subsets": sum(row["user_confirmed_pointwise_correction_count"] for row in selected),
                "known_supply_contact_fault_run_count": sum(row["known_supply_contact_fault_run_count"] for row in selected),
            }
    verify_unchanged(before)
    summary = {
        "review_id": "voltage_review_20260907",
        "scope": "FULL, configured 200 Hz, continuous USB read, voltage only",
        "definitions": {
            "raw_historical_including_known_fault": "All supplied continuous-read records, including additions, original fault condition, and separate repaired M0 record.",
            UNREPORTED: "Point-level filter: only the affected original M0 voltage is excluded. SOURCE/M1/M2 are user-confirmed unaffected and retained. This does not establish verified fault-free operation.",
            "complete_voltage_record": "Same record contains main/MIN/MAX source voltage and main/MIN/MAX voltage for every connected module.",
            "accepted_complete_voltage_record": "A complete raw voltage record whose voltage points have no reported supply-contact fault.",
            "accepted_configuration_coverage": "Configuration has accepted source and all module main/MIN/MAX readings, either in one record or via the explicitly user-confirmed pointwise correction. Coverage counts configurations, not new runs or independent repeats.",
            "same_record_coverage": "Accepted complete records remain separately counted; original M0 fault plus partial retest does not become a same-record acquisition.",
            "main_reading": "Existing avg fields retained as main/representative readings; not verified time averages.",
            "recorded_min": "Meter MIN field, not a statistical lower confidence bound or an independently repeated run.",
            "drop": "Raw module_voltages.csv uses decimal (source main - module main) * 1000 from the same record only; sequential readings are not guaranteed simultaneous. The raw M0 retest has no source or drop.",
            "corrected_drop": "accepted_configuration_voltage.csv permits the explicit user-confirmed unchanged source minus retested M0 estimate (35 mV), flagged as not same-record. It is excluded from same-record drop summaries.",
            "numeric_encoding": "Voltage and voltage-drop quantities are exact decimal strings; CSV blank and JSON null mean unavailable.",
            "repair": "M0-only measurement after connector repair. Its voltage replaces only the faulty M0 point in the accepted configuration; original SOURCE/M1/M2 are retained under user confirmation. No new full acquisition or independent repeat is created.",
        },
        "counts": {"input_runs": len(runs), "module_voltage_points": len(rows),
                   "known_supply_contact_fault_runs": sum(run["contains_known_fault_voltage_point"] for run in runs),
                   "excluded_fault_condition_module_points": sum(row["quality_class"] == FAULT for row in rows),
                   "no_reported_supply_contact_fault_module_points": sum(row["quality_class"] != FAULT for row in rows),
                   "accepted_complete_voltage_configurations": len(configurations),
                   "user_confirmed_pointwise_corrected_configurations": sum(config["configuration_kind"] == CORRECTION for config in configurations),
                   "additional_independent_runs_from_correction": 0},
        "quality_event": event,
        "summaries": cohorts,
        "coverage": coverage_summary,
        "runs": runs,
        "accepted_configurations": configurations,
        "provenance": {
            "source_files_verified_unchanged": True,
            "sources": [{"path": path.relative_to(root).as_posix(), "sha256": digest} for path, digest in before.items()],
            "photo_sources": [{"path": path, "sha256": digest} for path, digest in sorted({
                (path, digest) for row in accepted_points
                for path, digest in zip(row["photo_paths"].split(";"), row["photo_sha256"].split(";")) if path
            })],
            "photo_relocation_manifest": {"path": RELOCATION_REL.as_posix(), "sha256": sha(root / RELOCATION_REL)} if (root / RELOCATION_REL).is_file() else None,
            "old_analysis_or_report_written": False,
        },
    }
    content = {"module_voltages.csv": csv_text(rows), "coverage.csv": csv_text(coverage),
               "accepted_configuration_voltage.csv": csv_text(accepted_points),
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
