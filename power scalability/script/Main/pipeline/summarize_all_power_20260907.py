"""Evidence-preserving ZERO/MAX review of all 15 configurations of four modules.

Writes only DATA/analysis/current/all_power_review_20260907. Supplement files are separate from
the immutable 2.1 acquisition and analysis inputs. Main readings are not claimed
to be time averages; one configuration-condition is not an independent repeat.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import re
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
BASE = ROOT / "DATA/raw/canonical/power_experiment_records/transmission"
SUPPS = ROOT / "DATA/raw/canonical/power_experiment_records/current_temperature_supplements"
ZERO = ROOT / "DATA/analysis/current/zero_power_review_20260907"
VOLTAGES = ROOT / "DATA/analysis/current/voltage_review_20260907/accepted_configuration_voltage.csv"
EVENT = ROOT / "DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json"
FROZEN = ROOT / "DATA/reference/analysis_v2_1/source_manifest.json"
REPORT = ROOT.parent / "main 2.1.pdf"
REPORT_SHA = "d659fbab34fa82366abba88316f49308e95ce8c1459f0c11941f1d369b627f6f"
OUT = ROOT / "DATA/analysis/current/all_power_review_20260907"
MODULES = ("M0", "M1", "M2", "M3")
METRICS = ("I_sum_mA", "P_source_output_estimate_mW", "V_source_main_V", "T_teensy_C", "T_regulator_C")


def d(value):
    return None if value in (None, "", "N/A", "NOT_AVAILABLE") else Decimal(str(value))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return path.resolve().relative_to(ROOT).as_posix()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value))


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def photo_batch(photos):
    dates = sorted({m[1] for p in photos if (m := re.search(r"IMG_(\d{8})_", str(p)))})
    return ";".join(f"{v[:4]}-{v[4:6]}-{v[6:]}" for v in dates)


def describe(values):
    values = list(values)
    return {"n_configurations": len(values), "mean": statistics.mean(values),
            "sample_SD_across_configurations": statistics.stdev(values) if len(values) > 1 else None,
            "minimum": min(values), "maximum": max(values)}


def protect():
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert len(frozen["sources"]) == 19
    for row in frozen["sources"]:
        assert sha(ROOT / row["relative_path"]) == row["sha256"], row["relative_path"]
    assert sha(REPORT) == REPORT_SHA
    paths = {p for p in (ROOT / "DATA/raw/canonical/power_experiment_records").rglob("*") if p.is_file()}
    paths |= {p for p in (ROOT / "DATA/reference/analysis_v2_1").rglob("*") if p.is_file()}
    paths |= {ROOT / "DATA/raw/canonical/power_raw.csv", REPORT}
    return {p: sha(p) for p in paths}


def build():
    sources = {Path(__file__), FROZEN, EVENT, VOLTAGES,
               ZERO / "configuration_summary.csv", ZERO / "branch_readings.csv", ZERO / "source_manifest.json"}
    issues = []

    def add_source(path, expected=None):
        path = path if isinstance(path, Path) else ROOT / path
        assert path.is_file(), path
        if expected:
            assert sha(path) == expected, path
        sources.add(path.resolve())
        return sha(path)

    def validate_pairs(paths, hashes):
        ps = paths.split(";") if paths else []
        hs = hashes.split(";") if hashes else []
        assert len(ps) == len(hs), (ps, hs)
        for p, digest in zip(ps, hs):
            add_source(p, digest)

    # Carry through the ZERO derivation's complete evidence chain, including
    # user-confirmed minima/temperature metadata and relocated-photo hashes.
    zero_manifest = json.loads((ZERO / "source_manifest.json").read_text(encoding="utf-8"))
    for row in zero_manifest["sources"]:
        add_source(row["path"], row["sha256"])
    add_source(zero_manifest["script"]["path"], zero_manifest["script"]["sha256"])

    voltage_points = {}
    for row in read_csv(VOLTAGES):
        add_source(row["point_source_path"], row["point_source_sha256"])
        raw = yaml.safe_load((ROOT / row["point_source_path"]).read_text(encoding="utf-8"))
        for key, field in zip(("main_V", "min_V", "max_V"), row["point_source_fields"].split(";")):
            assert d(row[key]) == d(raw[field]), (row["point_source_path"], field)
        validate_pairs(row["photo_paths"], row["photo_sha256"])
        voltage_points[(row["load"], row["combo"].replace("+", "-"), row["point_id"])] = row

    configs, branches, source_points = [], [], []

    def add_config(combo, load, branch_rows, vs, teensy, regulator, batch, load_mass, provenance):
        assert len(branch_rows) == len(combo.split("-"))
        isum = sum(row["I_main_mA"] for row in branch_rows)
        row = {"combo": combo, "module_count": len(branch_rows), "load": load, "protocol_mode": "FULL",
               "configured_frequency_Hz": 200, "host_state": "CONTINUOUS_USB_READ",
               "photo_filename_date_batch": batch, "I_sum_mA": isum,
               "V_source_main_V": vs[0], "V_source_min_V": vs[1], "V_source_max_V": vs[2],
               "P_source_output_estimate_mW": vs[0] * isum, "T_teensy_C": teensy, "T_regulator_C": regulator,
               "load_mass_g_recorded": load_mass, "load_area_mm2": None, "load_application": None,
               "n_records_per_configuration_condition": 1, "within_condition_repeat_SD_mA": None,
               "simultaneous_branch_sum_measured": False, "simultaneous_voltage_current_measurement_verified": False,
               "provenance_json": json.dumps(provenance, ensure_ascii=False, default=json_default)}
        for mid in MODULES:
            found = [b for b in branch_rows if b["module_id"] == mid]
            for dest, field in ((f"I_{mid}_main_mA", "I_main_mA"), (f"V_{mid}_main_V", "V_module_main_V"),
                                (f"T_{mid}_stm32_C", "T_stm32_C")):
                row[dest] = found[0][field] if found else None
        configs.append(row)
        if vs[1] is None or vs[2] is None:
            issues.append({"load": load, "combo": combo, "module_id": "SOURCE", "issue": "SOURCE_VOLTAGE_DISPLAY_EXTREMUM_UNAVAILABLE", "action": "retain null; do not infer"})
        elif not vs[1] <= vs[0] <= vs[2]:
            issues.append({"load": load, "combo": combo, "module_id": "SOURCE", "issue": "SOURCE_VOLTAGE_MAIN_OUTSIDE_DISPLAY_MIN_MAX", "action": "retain original readings"})

    def branch_record(combo, mid, load, values, temperature, vs, provenance, batch, retained_note=""):
        row = {"combo": combo, "module_count": len(combo.split("-")), "module_id": mid, "load": load,
               **{key: d(values[key]) for key in ("I_main_mA", "I_min_mA", "I_max_mA", "V_module_main_V", "V_module_min_V", "V_module_max_V")},
               "I_main_display_text_mA": str(values["I_main_mA"]), "T_stm32_C": d(temperature),
               "V_source_main_V": vs, "source_minus_module_main_mV": (vs - d(values["V_module_main_V"])) * 1000,
               "photo_filename_date_batch": batch, "retained_quality_note": retained_note,
               "n_records_per_configuration_condition": 1, "within_condition_repeat_SD_mA": None,
               "provenance_json": json.dumps(provenance, ensure_ascii=False, default=json_default)}
        for prefix in ("I", "V_module"):
            unit = "mA" if prefix == "I" else "V"
            main, low, high = (row[f"{prefix}_{k}_{unit}"] for k in ("main", "min", "max"))
            if low is None or high is None:
                issues.append({"load": load, "combo": combo, "module_id": mid, "issue": f"{prefix}_DISPLAY_EXTREMUM_UNAVAILABLE", "action": "retain null; do not infer"})
            elif not low <= main <= high:
                issues.append({"load": load, "combo": combo, "module_id": mid, "issue": f"{prefix}_MAIN_OUTSIDE_DISPLAY_MIN_MAX", "action": "retain original readings; not a hardware fault conclusion"})
        branches.append(row)
        return row

    zero_configs = read_csv(ZERO / "configuration_summary.csv")
    zero_branches = read_csv(ZERO / "branch_readings.csv")
    assert len(zero_configs) == 15 and len(zero_branches) == 32
    for c in zero_configs:
        combo = c["combo"]
        pv = voltage_points[("ZERO", combo, "SOURCE")]
        vs = [d(pv[key]) for key in ("main_V", "min_V", "max_V")]
        assert vs == [d(c[f"V_source_{key}_V"]) for key in ("main", "min", "max")]
        group = []
        for b in zero_branches:
            if b["combo"] != combo:
                continue
            add_source(b["current_source_path"], b["current_source_sha256"])
            add_source(b["voltage_source_path"], b["voltage_source_sha256"])
            validate_pairs(b["current_photo"], b["current_photo_sha256"])
            validate_pairs(b["voltage_photo_paths"], b["voltage_photo_sha256"])
            v = voltage_points[("ZERO", combo, b["module_id"])]
            for key in ("main", "min", "max"):
                assert d(b[f"V_module_{key}_V"]) == d(v[f"{key}_V"])
            group.append(branch_record(combo, b["module_id"], "ZERO", b, b["T_stm32_C"], vs[0], b,
                                       b["current_filename_date_batch"], b["quality_note"]))
        add_config(combo, "ZERO", group, vs, d(c["T_teensy_C"]), d(c["T_regulator_C"]), c["current_filename_date_batch"], Decimal(0), c)
        assert configs[-1]["I_sum_mA"] == d(c["I_sum_mA"])
        assert configs[-1]["P_source_output_estimate_mW"] == d(c["P_source_output_estimate_mW"])
        source_points.append({"load": "ZERO", "combo": combo, "V_source_main_V": vs[0], "V_source_min_V": vs[1],
                              "V_source_max_V": vs[2], "provenance_json": json.dumps(pv, ensure_ascii=False)})

    for path in sorted(BASE.rglob("*_MAX_*_USB_RX_R1.yaml")):
        add_source(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert (raw["protocol_mode"], raw["load"], raw["frequency_hz"]) == ("FULL", "MAX", 200)
        combo = raw["module_ids"].replace("Module", "M").replace(",", "-")
        mids = combo.split("-")
        assert len(mids) == raw["module_count"]
        photos = sorted(path.parent.glob("*.jpg"))
        photo_paths, photo_hashes = [rel(p) for p in photos], [add_source(p) for p in photos]
        batch = photo_batch(photos)
        vs = [d(raw[f"V_source_{key}_V"]) for key in ("avg", "min", "max")]
        provenance = {"source_record": rel(path), "source_record_sha256": sha(path),
                      "configuration_photo_paths": photo_paths, "configuration_photo_sha256": photo_hashes,
                      "individual_photo_mapping": "not_reassigned_original_YAML_plus_group_photos",
                      "firmware_actual_rate_verified_by_photos": False,
                      "fault_counts": "original YAML zeros are template defaults, not verified fault-monitoring outcomes"}
        group = []
        for mid in mids:
            index = "0" if len(mids) == 1 else mid[1:]
            values = {f"{prefix}_{kind}_{unit}": raw[f"{raw_prefix}{index}_{original}_{unit}"]
                      for prefix, raw_prefix, unit in (("I", "I_module", "mA"), ("V_module", "V_module", "V"))
                      for kind, original in (("main", "avg"), ("min", "min"), ("max", "max"))}
            temp = raw["T_stm32_stable_C"] if len(mids) == 1 else raw[f"T_module{index}_stm32_C"]
            group.append(branch_record(combo, mid, "MAX", values, temp, vs[0],
                                       {**provenance, "current_fields": f"I_module{index}_*_mA", "voltage_fields": f"V_module{index}_*_V"}, batch))
        add_config(combo, "MAX", group, vs, d(raw["T_teensy_C"]), d(raw["T_regulator_C"]), batch, d(raw["load_mass_g"]), provenance)
        source_points.append({"load": "MAX", "combo": combo, "V_source_main_V": vs[0], "V_source_min_V": vs[1],
                              "V_source_max_V": vs[2], "provenance_json": json.dumps(provenance, ensure_ascii=False)})
    assert len([c for c in configs if c["load"] == "MAX"]) == 9

    for n in (2, 3):
        path = SUPPS / f"n{n}_max_20260907.csv"
        meta_path = SUPPS / f"n{n}_max_20260907_metadata.json"
        add_source(path)
        add_source(meta_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["load"] == "MAX" and meta["load_mass_g"] is None
        by_combo = defaultdict(dict)
        for b in read_csv(path):
            assert b["load"] == "MAX" and b["module_id"] not in by_combo[b["combo"]]
            by_combo[b["combo"]][b["module_id"]] = b
        assert len(by_combo) == (4 if n == 2 else 2)
        for combo, rows in sorted(by_combo.items()):
            mids = combo.split("-")
            assert len(mids) == n and set(rows) == set(mids)
            assert not any(c["combo"] == combo and c["load"] == "MAX" for c in configs)
            first = rows[mids[0]]
            vs = [d(first[f"V_source_{key}_V"]) for key in ("main", "min", "max")]
            config_photos = sorted({b[key] for b in rows.values() for key in ("current_photo", "module_voltage_photo", "source_voltage_photo")})
            assert len(config_photos) == 2 * n + 1
            photo_hashes = [add_source(p) for p in config_photos]
            batch = photo_batch(config_photos)
            temperatures = meta["temperature_message_values"][combo]
            provenance = {"source_record": rel(path), "source_record_sha256": sha(path), "metadata": rel(meta_path), "metadata_sha256": sha(meta_path),
                          "configuration_photo_paths": config_photos, "configuration_photo_sha256": photo_hashes,
                          "source_voltage_mapping_basis": meta["source_voltage_mapping_basis"], "temperature_source": "user_message_via_metadata",
                          "load_mass_area_distribution": "not supplied", "fault_counts": None}
            group = []
            for i, mid in enumerate(mids):
                b = rows[mid]
                for key in ("V_source_main_V", "V_source_min_V", "V_source_max_V", "source_voltage_photo", "T_teensy_C", "T_regulator_C"):
                    assert b[key] == first[key]
                assert d(b["T_stm32_C"]) == d(temperatures[i])
                assert d(b["T_teensy_C"]) == d(temperatures[n]) and d(b["T_regulator_C"]) == d(temperatures[n + 1])
                branch_prov = {**provenance, "row_values": b,
                               **{key + "_sha256": sha(ROOT / b[key]) for key in ("current_photo", "module_voltage_photo", "source_voltage_photo")}}
                group.append(branch_record(combo, mid, "MAX", b, b["T_stm32_C"], vs[0], branch_prov, batch))
            add_config(combo, "MAX", group, vs, d(first["T_teensy_C"]), d(first["T_regulator_C"]), batch, None, provenance)
            source_points.append({"load": "MAX", "combo": combo, "V_source_main_V": vs[0], "V_source_min_V": vs[1],
                                  "V_source_max_V": vs[2], "provenance_json": json.dumps({**provenance, "source_voltage_photo": first["source_voltage_photo"]}, ensure_ascii=False)})

    configs.sort(key=lambda c: (c["module_count"], c["combo"], c["load"] == "MAX"))
    branches.sort(key=lambda b: (b["module_count"], b["combo"], b["load"] == "MAX", b["module_id"]))
    assert len(configs) == 30 and len(branches) == 64 and len(source_points) == 30
    index = {(c["load"], c["combo"]): c for c in configs}
    assert len(index) == 30
    expected = {"-".join(m) for n in range(1, 5) for m in itertools.combinations(MODULES, n)}
    for load in ("ZERO", "MAX"):
        assert {c["combo"] for c in configs if c["load"] == load} == expected

    groups, pairs, predictions, coverage = [], [], [], []
    for load in ("ZERO", "MAX"):
        for n in range(1, 5):
            selected = [c for c in configs if c["load"] == load and c["module_count"] == n]
            batches = ["ALL"] + sorted({c["photo_filename_date_batch"] for c in selected})
            for batch in batches:
                sub = selected if batch == "ALL" else [c for c in selected if c["photo_filename_date_batch"] == batch]
                for metric in METRICS:
                    groups.append({"load": load, "module_count": n, "photo_filename_date_batch": batch, "metric": metric,
                                   **describe(c[metric] for c in sub), "SD_meaning": "Across configurations; shared modules and batch confounding; not repeatability"})
        refs = {mid: index[(load, mid)]["I_sum_mA"] for mid in MODULES}
        for c in configs:
            if c["load"] != load or c["module_count"] == 1:
                continue
            prediction = sum(refs[mid] for mid in c["combo"].split("-"))
            residual = c["I_sum_mA"] - prediction
            predictions.append({"load": load, "combo": c["combo"], "module_count": c["module_count"], "I_observed_sum_mA": c["I_sum_mA"],
                                "I_prediction_from_same_load_N1_physical_modules_mA": prediction, "residual_mA": residual,
                                "residual_percent_of_prediction": residual / prediction * 100, "N1_references_mA_json": json.dumps(refs, default=json_default),
                                "additional_independent_same_condition_repeats": 0, "interpretation": "descriptive additivity; no causal or significance claim"})
    assert len(predictions) == 22
    for combo in sorted(expected, key=lambda x: (len(x.split("-")), x)):
        z, m = index[("ZERO", combo)], index[("MAX", combo)]
        delta = m["I_sum_mA"] - z["I_sum_mA"]
        row = {"combo": combo, "module_count": z["module_count"], "I_ZERO_sum_mA": z["I_sum_mA"], "I_MAX_sum_mA": m["I_sum_mA"],
               "MAX_minus_ZERO_mA": delta, "MAX_minus_ZERO_percent_of_ZERO": delta / z["I_sum_mA"] * 100,
               "P_ZERO_estimate_mW": z["P_source_output_estimate_mW"], "P_MAX_estimate_mW": m["P_source_output_estimate_mW"],
               "MAX_minus_ZERO_power_estimate_mW": m["P_source_output_estimate_mW"] - z["P_source_output_estimate_mW"],
               "ZERO_photo_filename_date_batch": z["photo_filename_date_batch"], "MAX_photo_filename_date_batch": m["photo_filename_date_batch"],
               "MAX_load_mass_g_recorded": m["load_mass_g_recorded"], "n_ZERO_records": 1, "n_MAX_records": 1,
               "within_condition_repeat_SD_available": False, "comparison_basis": "same physical combo descriptive comparison; not repeated paired trials"}
        for mid in MODULES:
            key = f"T_{mid}_stm32_C"
            row[f"T_{mid}_MAX_minus_ZERO_C"] = m[key] - z[key] if z[key] is not None else None
        for device in ("teensy", "regulator"):
            row[f"T_{device}_MAX_minus_ZERO_C"] = m[f"T_{device}_C"] - z[f"T_{device}_C"]
        pairs.append(row)
        coverage.append({"module_count": z["module_count"], "combo": combo, "ZERO_voltage_current_temperature_main_recorded": True,
                         "MAX_voltage_current_temperature_main_recorded": True, "n_records_per_configuration_condition": 1,
                         "same_condition_repeats_available": False, "MAX_load_mass_g_recorded": m["load_mass_g_recorded"],
                         "MAX_area_distribution_recorded": False})

    ranges = {}
    for load in ("ZERO", "MAX"):
        bs = [b for b in branches if b["load"] == load]
        cs = [c for c in configs if c["load"] == load]
        ranges[load] = {}
        for key, rows in (("V_module_main_V", bs), ("V_module_min_V", bs), ("V_module_max_V", bs), ("T_stm32_C", bs),
                          ("source_minus_module_main_mV", bs), ("V_source_main_V", cs), ("T_teensy_C", cs), ("T_regulator_C", cs)):
            values = [r[key] for r in rows if r[key] is not None]
            ranges[load][key] = [min(values), max(values)]
    event = json.loads(EVENT.read_text(encoding="utf-8"))
    summary = {"scope": "Existing four modules, every nonempty physical combination, ZERO and user-labelled MAX; FULL configured 200 Hz; continuous USB read",
               "legacy_blocked_scope": "13 blocked-standby rows in power_raw.csv are a separate historical comparison; 11 no_transmission YAMLs duplicate legacy records and are not additional samples. No new matched blocked-state measurements are included.",
               "configurations_by_load": {load: 15 for load in ("ZERO", "MAX")}, "configuration_conditions": 30, "branches": 64,
               "n_configurations_per_load_by_N": {"1": 4, "2": 6, "3": 4, "4": 1}, "same_condition_records_per_configuration": 1,
               "within_condition_repeat_SD_available": False, "range_values": ranges,
               "groups_ALL": [r for r in groups if r["photo_filename_date_batch"] == "ALL"],
               "descriptive_additivity_residual_percent": {load: describe(p["residual_percent_of_prediction"] for p in predictions if p["load"] == load) for load in ("ZERO", "MAX")},
               "descriptive_MAX_minus_ZERO_percent": describe(p["MAX_minus_ZERO_percent_of_ZERO"] for p in pairs),
               "N4_ZERO_MAX": {load: index[(load, "M0-M1-M2-M3")] for load in ("ZERO", "MAX")},
               "current_extrema_complete_branches": sum(b["I_min_mA"] is not None and b["I_max_mA"] is not None for b in branches),
               "module_voltage_extrema_complete_branches": sum(b["V_module_min_V"] is not None and b["V_module_max_V"] is not None for b in branches),
               "source_voltage_extrema_complete_configurations": sum(c["V_source_min_V"] is not None and c["V_source_max_V"] is not None for c in configs),
               "numeric_display_consistency_issues": issues, "accepted_voltage_correction": event,
               "power_estimate_definition": "V_source_main_V times sum of separately measured branch main currents in mA; excludes USB-powered Teensy and regulator losses",
               "date_definition": "Filename-date sets, not independently verified start times; mixed dates retained",
               "fault_monitoring": "No zero hardware-fault rate inferred. Old template-zero counters are not independent monitoring evidence; new supplement counters unspecified.",
               "published_main_2_1_pdf_modified": False, "published_main_2_1_sha256": REPORT_SHA}
    return configs, branches, source_points, groups, pairs, predictions, coverage, summary, sources


def write_readme(configs, groups, pairs, summary):
    def show(value, digits=3):
        return "未记录" if value is None else f"{value:.{digits}f}"
    def stat(load, n, metric):
        row = next(r for r in groups if r["load"] == load and r["module_count"] == n and r["metric"] == metric and r["photo_filename_date_batch"] == "ALL")
        return f"{row['mean']:.3f} ± {row['sample_SD_across_configurations']:.3f}" if row["sample_SD_across_configurations"] is not None else f"{row['mean']:.3f}（SD 不可估计）"
    lines = ["# Power scalability 全部组合数据总结（2026-09-07）", "",
             "现有 M0–M3 的全部 15 种非空组合均已记录 ZERO 和 MAX 条件下的模块电压、电流及温度：共 30 个配置条件、64 个模块支路观测。这里的完成指测点与组合覆盖，并不代表独立重复、动态稳定性或故障监测全部完成。", "",
             "本总结按持续 USB 接收、FULL、配置 200 Hz 的 Power 实验系列整理；照片本身不能验证固件版本、实际扫描频率或会话完整性。仅汇总 Power 数据，main 2.1.pdf 和 analysis_v2_1 原版复现数据没有修改。", "",
             "power_raw.csv 中的 13 条阻塞待机记录仍作为独立历史对照保留，11 个 no_transmission YAML 是已有待机记录的重复映射，不计作新增样本，也不合并进本次 30 条持续接收矩阵。本次没有补测阻塞工况；不同运行状态间的因果比较仍受批次和试验条件不匹配的限制。", "",
             "## 最新两组 MAX", "", "| 组合 | 支路电流 / mA（模块升序） | 支路合计 / mA | 源端 / V | 模块电压 / V（升序） | 源端输出功率估计 / mW |", "|---|---|---:|---:|---|---:|"]
    for c in configs:
        if c["load"] == "MAX" and c["combo"] in ("M0-M1-M3", "M0-M2-M3"):
            mids = c["combo"].split("-")
            currents = " / ".join(str(c[f"I_{mid}_main_mA"]) for mid in mids)
            volts = " / ".join(show(c[f"V_{mid}_main_V"]) for mid in mids)
            lines.append(f"| {c['combo']} | {currents} | {c['I_sum_mA']:.3f} | {c['V_source_main_V']:.3f} | {volts} | {c['P_source_output_estimate_mW']:.3f} |")
    lines += ["", "| 组合 | STM32 温度 / °C（模块升序） | Teensy / °C | Regulator / °C |", "|---|---|---:|---:|"]
    for c in configs:
        if c["load"] == "MAX" and c["combo"] in ("M0-M1-M3", "M0-M2-M3"):
            temps = " / ".join(show(c[f"T_{mid}_stm32_C"], 1) for mid in c["combo"].split("-"))
            lines.append(f"| {c['combo']} | {temps} | {c['T_teensy_C']:.1f} | {c['T_regulator_C']:.1f} |")
    lines += ["", "温度顺序为模块编号升序、Teensy、稳压器；用户输入的 `30\\` 记为 30.0 °C。MAX 条件沿用本次补充实验上下文。新增 N=2/N=3 记录的具体载荷质量、接触面积和模块间分配未提供，不将旧记录的 2000 g 自动套入新增数据。", "",
              "## 按模块数量汇总", "", "| N | 每种负载的组合数 n | ZERO 总电流 / mA | MAX 总电流 / mA | ZERO 输出功率估计 / mW | MAX 输出功率估计 / mW |", "|---:|---:|---:|---:|---:|---:|"]
    for n, count in ((1, 4), (2, 6), (3, 4), (4, 1)):
        lines.append(f"| {n} | {count} | {stat('ZERO', n, 'I_sum_mA')} | {stat('MAX', n, 'I_sum_mA')} | {stat('ZERO', n, 'P_source_output_estimate_mW')} | {stat('MAX', n, 'P_source_output_estimate_mW')} |")
    lines += ["", "表中为 mean ± 样本 SD，SD 描述同一 N 下不同物理组合的离散，不能用作同一条件重复试验的误差棒。每个组合、每种负载仅有一组记录，N=4 的 SD 留空。不同组合共享物理模块，组合效果又与测量批次混杂，因此并非独立随机样本。MIN/MAX 是仪表显示极值，不能当作 SD、经过验证的瞬时峰值或电流时间均值的置信区间。", "",
              "## 全部 15 个组合的 ZERO/MAX 对照", "", "| 组合 | ZERO 合计 / mA | MAX 合计 / mA | 增量 / mA | 相对 ZERO / % | ZERO 功率估计 / mW | MAX 功率估计 / mW |", "|---|---:|---:|---:|---:|---:|---:|"]
    for p in pairs:
        lines.append(f"| {p['combo']} | {p['I_ZERO_sum_mA']:.3f} | {p['I_MAX_sum_mA']:.3f} | {p['MAX_minus_ZERO_mA']:.3f} | {p['MAX_minus_ZERO_percent_of_ZERO']:.2f} | {p['P_ZERO_estimate_mW']:.3f} | {p['P_MAX_estimate_mW']:.3f} |")
    lines += ["", "电流合计为顺序测量的支路主读数之和；功率估计 P = V_source × ΣI。电压、电流以及不同支路不是同步采样，这不是直接测得的同步总功率。估计值只覆盖模块供电侧，不包含 USB 供电的 Teensy 和稳压器损耗。ZERO/MAX 差值可描述同一物理组合的观测差异；缺少匹配重复、受控温度与统一载荷定义时，不能将全部差异严格归因于加载。", "",
              "## 电压和温度范围", "", "| 测点／量 | ZERO | MAX |", "|---|---|---|"]
    for key, label, digits in (("V_source_main_V", "源端电压主读数 / V", 3), ("V_module_main_V", "模块电压主读数 / V", 3),
                               ("V_module_min_V", "各模块仪表 MIN 读数范围 / V", 3), ("source_minus_module_main_mV", "源端−模块主读数差 / mV", 1),
                               ("T_stm32_C", "STM32 温度点读数 / °C", 1), ("T_teensy_C", "Teensy 温度点读数 / °C", 1), ("T_regulator_C", "稳压器温度点读数 / °C", 1)):
        values = ["–".join(show(v, digits) for v in summary["range_values"][load][key]) for load in ("ZERO", "MAX")]
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines += ["", "源端−模块差值为代表性主读数之差，不是动态最坏压降。温度是点读数，没有统一环境温度、充分稳定时间或连续记录，不能换算为环境温升或证明热稳态。", "",
              "M0-M1-M2 ZERO 的原 M0 电压 3.224 V 归为用户确认的供电连接器接触故障，作为历史事件保留。接受配置视图仅将该 M0 电压替换为 3.241 V 复测；源端、M1、M2 原电压按用户确认保留。原电流和温度也保留，但不宣称它们已在修复后重测。逐点来源及跨记录修正标记保存在支路表的 provenance_json 中。", "",
              "## 电流可加性的描述性检查", "",
              "按相同负载标签（ZERO 或 MAX）使用各物理模块的 N=1 记录作为参考，预测 N>1 的支路合计，而非把同一次支路求和作为可加性验证。每种负载标签共有 11 个多模块组合；MAX 标签相同不表示实际载荷质量及其分配已核实一致。", ""]
    for load in ("ZERO", "MAX"):
        x = summary["descriptive_additivity_residual_percent"][load]
        lines.append(f"- {load}：观测合计相对 N=1 同模块参考和的残差为 {x['minimum']:.3f}% 至 {x['maximum']:.3f}%。")
    lines += ["", "上述结果支持现有四个模块、当前供电和传输条件下的近似可加描述。由于共享模块、单次观测与批次差异，不作因果、统计显著性或任意更大 N 的验证结论。", "",
              "## 批次与证据", "",
              "保留照片文件名推定的日期集合。N=1 的原始照片包括 2026-09-04 和跨 09-04/09-05 的配置，不能统一称为 09-05；其余原始多模块记录多为 09-05，新增支路记录为 09-07。ZERO 部分新增电流与此前电压来自不同采集记录。group_summary.csv 同时给出 ALL 和日期集合分组，日期集合不是已核实的实际试验开始时间。", "",
              "新照片按用户约定的模块编号升序分别映射电流和模块电压；每组第一张电压照片按既定记录顺序推定为 SOURCE。照片不显示探头端点，SOURCE 身份并非图像独立证实。既有 YAML 保留原字段与组照片，不重新猜测单张照片对应关系。source_manifest.json 为引用来源保存 SHA-256，逐点数字与已有受接受电压记录核对。", "",
              f"本视图记录的电流 MIN/MAX 完整支路数为 {summary['current_extrema_complete_branches']}/64；模块电压 MIN/MAX 为 {summary['module_voltage_extrema_complete_branches']}/64；源端电压 MIN/MAX 为 {summary['source_voltage_extrema_complete_configurations']}/30。缺失极值保持空值，不用主读数补齐。", "",
              "ZERO 中 M0-M3 的 M3 MIN = 17.89 mA，以及 M0-M1-M3 的 M0 MIN = 18.00 mA，均来自用户确认；照片本身未能独立读出这两个极值。相应来源标记已保留，因此记录完整不等于所有字段均由照片独立确认。", "",
              f"主读数与显示 MIN/MAX 的数值一致性检查共保留 {len(summary['numeric_display_consistency_issues'])} 条问题，详见 quality_issues.csv；旧数据出现的范围不一致不作静默修正。此检查仅审计记录，不能据此推定有或没有硬件故障。原 YAML 中模板默认的故障计数 0 不作为独立故障监测结果；新增照片也不能证明无复位、无欠压或无丢帧。", "",
              "## 已完成、限制与未来工作", "",
              "- [x] 四个现有模块的 N=1–4 全部 15 组合，ZERO/MAX 均有电压、电流、模块/Teensy/稳压器温度记录。",
              "- [x] 汇总 30 配置条件、64 支路的主读数与已记录的 MIN/MAX，保存原始读数精度、来源和哈希。",
              "- [x] 分清组合数 n 与重复数，按 N 和文件名日期集合提供 mean ± 组合间样本 SD。",
              "- [x] 同组合 ZERO/MAX 描述性对照、同负载 N=1 参考预测、多模块覆盖表和接触故障范围保留。",
              "- [ ] 同一条件的独立重复仍缺，N=4 各负载仅 n=1，不能给出重复性 SD。",
              "- [ ] 新 MAX 的载荷质量、面积、分配，以及逐运行环境温度、稳定时间、同步供电/数据故障监测仍未完整记录。",
              "- [ ] 本次持续接收数据不能替代同条件主动阻塞/持续接收的配对试验；历史阻塞数据不得据此冒充当前配对结果。",
              "- [ ] 更大 N、其它模块批次、不同供电拓扑与导线/连接器条件的泛化尚未验证。",
              "- [ ] 启动峰值、纹波、负载切换波形及连续温升曲线按用户决定列为未来工作。这些点读数尚不能单独确定电源容量和动态裕量。",
              "- [ ] 将新增结果写入论文正文、图表和 discussion，并生成新报告 PDF 属于后续报告修订；本次没有修改 main 2.1.pdf。", "",
              "## 文件", "",
              "- configuration_summary.csv：30 条配置条件，包含模块电流、电压、温度、源端极值、功率估计和来源。",
              "- branch_readings.csv：64 条支路，包含电流/模块电压主读数及 MIN/MAX、温度与逐点来源。",
              "- source_voltage_readings.csv：30 条配置条件的源端电压与出处。",
              "- group_summary.csv：负载 × N × 照片日期集合的均值、样本 SD、范围及 n。",
              "- load_pairs.csv：15 种组合的 ZERO/MAX 电流、功率和温度描述性差值。",
              "- additivity_checks.csv：22 条多模块观测与同负载 N=1 物理模块参考和的比较。",
              "- coverage.csv、quality_issues.csv、summary.json、source_manifest.json：覆盖、记录问题、机器可读统计与来源哈希。", "",
              "## 顺序复现", "",
              "在 `power scalability` 目录依次执行以下命令。脚本保留原始输入与 main 2.1；先更新电压和 ZERO 派生视图，再生成本全量总结，以保持来源哈希一致。", "",
              "```powershell", "python .\\script\\Main\\summarize_voltage_review.py",
              "python .\\script\\Main\\summarize_n2_zero_20260907.py",
              "python .\\script\\Main\\summarize_zero_power_20260907.py",
              "python .\\script\\Main\\summarize_all_power_20260907.py", "```", ""]
    (OUT / "README_CN.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    protected = protect()
    result = build()
    configs, branches, source_points, groups, pairs, predictions, coverage, summary, sources = result
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("configuration_summary.csv", configs), ("branch_readings.csv", branches),
                           ("source_voltage_readings.csv", source_points), ("group_summary.csv", groups),
                           ("load_pairs.csv", pairs), ("additivity_checks.csv", predictions),
                           ("coverage.csv", coverage), ("quality_issues.csv", summary["numeric_display_consistency_issues"])):
        write_csv(OUT / filename, rows)
    write_json(OUT / "summary.json", summary)
    write_readme(configs, groups, pairs, summary)
    write_json(OUT / "source_manifest.json", {"sources": [{"relative_path": rel(p), "sha256": sha(p)} for p in sorted(sources)],
                                            "protected_file_count": len(protected), "published_main_2_1_sha256": REPORT_SHA})
    for p, digest in protected.items():
        assert sha(p) == digest, f"Protected input changed during review: {p}"
    for row in read_csv(OUT / "configuration_summary.csv"):
        currents = [d(row[f"I_{mid}_main_mA"]) for mid in row["combo"].split("-")]
        assert sum(currents) == d(row["I_sum_mA"])
        assert d(row["V_source_main_V"]) * sum(currents) == d(row["P_source_output_estimate_mW"])
    print(json.dumps({"written_to": rel(OUT), "configs": len(configs), "branches": len(branches),
                      "sources": len(sources), "protected_files_unchanged": len(protected),
                      "numeric_issues": len(summary["numeric_display_consistency_issues"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
