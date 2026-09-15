"""Current ZERO power view with dated supplements and per-point voltage provenance.

Writes only DATA/analysis/current/zero_power_review_20260907. Original acquisitions and the
published 2.1 reproduction remain untouched. No within-condition SD is inferred.
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

from photo_source_paths import RELOCATION_REL, resolve_photo

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "DATA/raw/canonical/power_experiment_records/transmission"
SUPPS = ROOT / "DATA/raw/canonical/power_experiment_records/current_temperature_supplements"
MAX_SUPP = SUPPS / "n2_max_20260907.csv"
MAX_META = SUPPS / "n2_max_20260907_metadata.json"
VOLTAGES = ROOT / "DATA/analysis/current/voltage_review_20260907/accepted_configuration_voltage.csv"
EVENT = ROOT / "DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json"
FROZEN_MANIFEST = ROOT / "DATA/reference/analysis_v2_1/source_manifest.json"
PDF = ROOT.parent / "main 2.1.pdf"
PDF_SHA = "d659fbab34fa82366abba88316f49308e95ce8c1459f0c11941f1d369b627f6f"
OUT = ROOT / "DATA/analysis/current/zero_power_review_20260907"
MODULES = ("M0", "M1", "M2", "M3")


def number(value):
    return None if value in (None, "", "N/A", "NOT_AVAILABLE") else Decimal(str(value))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    def encode(item):
        if isinstance(item, Decimal):
            return float(item)
        raise TypeError(type(item))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n", encoding="utf-8")


def describe(values, cv=False):
    values = list(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else None
    return {"n_configurations": len(values), "mean": mean, "sample_SD_across_configurations": sd,
            "minimum": min(values), "maximum": max(values),
            "CV_percent": sd / mean * 100 if cv and sd is not None else None}


def date_from_filenames(directory):
    dates = sorted({m[1] for path in directory.glob("*.jpg")
                    if (m := re.search(r"IMG_(\d{8})_", path.name))})
    return ";".join(f"{day[:4]}-{day[4:6]}-{day[6:8]}" for day in dates)


def build():
    sources = {VOLTAGES, EVENT, FROZEN_MANIFEST, ROOT / RELOCATION_REL, Path(__file__).with_name("photo_source_paths.py"), MAX_SUPP, MAX_META}
    raw_cache = {}
    def raw(path):
        path = path.resolve()
        sources.add(path)
        if path not in raw_cache:
            raw_cache[path] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return raw_cache[path]

    # Verify accepted voltage provenance and values before joining to currents.
    volts = defaultdict(dict)
    for row in read_csv(VOLTAGES):
        path = ROOT / row["point_source_path"]
        assert sha(path) == row["point_source_sha256"], f"Voltage source changed: {path}"
        data = raw(path)
        for value_key, field in zip(("main_V", "min_V", "max_V"), row["point_source_fields"].split(";")):
            assert number(row[value_key]) == number(data[field]), f"Voltage value mismatch: {path} {field}"
        photos = row["photo_paths"].split(";") if row["photo_paths"] else []
        photo_hashes = row["photo_sha256"].split(";") if row["photo_sha256"] else []
        assert len(photos) == len(photo_hashes)
        resolved_photos = []
        for photo, digest in zip(photos, photo_hashes):
            photo_path = resolve_photo(ROOT, photo, digest)
            assert sha(photo_path) == digest, f"Voltage photo changed: {photo_path}"
            sources.add(photo_path)
            resolved_photos.append(relative(photo_path))
        row["photo_original_references"] = row.get("photo_original_references", row["photo_paths"])
        row["photo_paths"] = ";".join(resolved_photos)
        if row["load"] == "ZERO":
            combo = row["combo"].replace("+", "-")
            assert row["point_id"] not in volts[combo]
            volts[combo][row["point_id"]] = row

    supplement = defaultdict(dict)
    metadata = {}
    for n in (2, 3):
        path = SUPPS / f"n{n}_zero_20260907.csv"
        meta_path = SUPPS / f"n{n}_zero_20260907_metadata.json"
        sources.update((path, meta_path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        metadata[n] = meta
        for row in read_csv(path):
            combo, module = row["combo"], row["module_id"]
            assert module not in supplement[combo]
            supplement[combo][module] = (row, path, meta)
            assert module in combo.split("-") and len(combo.split("-")) == n
            temperatures = meta["temperature_message_values"][combo]
            index = combo.split("-").index(module)
            assert number(row["T_stm32_C"]) == number(temperatures[index])
            assert number(row["T_teensy_C"]) == number(temperatures[n])
            assert number(row["T_regulator_C"]) == number(temperatures[n + 1])
            sources.add(resolve_photo(ROOT, row["current_photo"]))
    assert set(supplement) == {"M0-M2", "M0-M3", "M1-M2", "M1-M3", "M0-M1-M3", "M0-M2-M3"}

    # The MAX supplement contributes coverage only, never ZERO measurements.
    max_metadata = json.loads(MAX_META.read_text(encoding="utf-8"))
    assert max_metadata["load"] == "MAX", "MAX coverage metadata has another load"
    max_supplement = defaultdict(dict)
    for row in read_csv(MAX_SUPP):
        combo, module = row["combo"], row["module_id"]
        assert row["load"] == "MAX" and len(combo.split("-")) == 2
        assert module in combo.split("-") and module not in max_supplement[combo]
        assert all(number(row[field]) is not None for field in (
            "I_main_mA", "I_min_mA", "I_max_mA", "V_module_main_V", "V_module_min_V", "V_module_max_V",
            "V_source_main_V", "V_source_min_V", "V_source_max_V", "T_stm32_C", "T_teensy_C", "T_regulator_C"))
        max_supplement[combo][module] = row
    assert set(max_supplement) == {"M0-M2", "M0-M3", "M1-M2", "M1-M3"}
    for combo, rows in max_supplement.items():
        assert set(rows) == set(combo.split("-")), "MAX coverage needs both physical module branches"

    refs = {}
    for module in MODULES:
        path = BASE / f"n=1/{module}/zero_load/PS01_N1_F200_ZERO_{module}_USB_RX_R1.yaml"
        data = raw(path)
        assert data["module_ids"] == module.replace("M", "Module")
        refs[module] = number(data["I_module0_avg_mA"])

    configurations, branches, qc = [], [], []
    for n in range(1, 5):
        for members in itertools.combinations(MODULES, n):
            combo = "-".join(members)
            extra = supplement.get(combo)
            suffix = "VOLTAGE_R1" if extra else "R1"
            path = BASE / f"n={n}/{combo}/zero_load/PS01_N{n}_F200_ZERO_{combo}_USB_RX_{suffix}.yaml"
            data = raw(path)
            assert (data["load"], data["protocol_mode"], data["frequency_hz"], data["module_count"]) == ("ZERO", "FULL", 200, n)
            assert data["module_ids"].replace("Module", "M").split(",") == list(members)
            assert set(volts[combo]) == {"SOURCE", *members}
            assert all(row["accepted_complete"] == "True" for row in volts[combo].values())
            if extra:
                assert set(extra) == set(members)
            batch = extra[members[0]][2]["current_photo_filename_date"] if extra else date_from_filenames(path.parent)
            source = volts[combo]["SOURCE"]
            corrected = source["configuration_kind"] == "USER_CONFIRMED_POINTWISE_CORRECTION"
            current_branches = []
            for module in members:
                field_index = "0" if n == 1 else module[1:]
                row, current_path, meta = extra[module] if extra else ({}, path, {})
                main = number(row["I_main_mA"] if extra else data[f"I_module{field_index}_avg_mA"])
                minimum = number(row["I_min_mA"] if extra else data[f"I_module{field_index}_min_mA"])
                maximum = number(row["I_max_mA"] if extra else data[f"I_module{field_index}_max_mA"])
                temp = number(row["T_stm32_C"] if extra else data["T_stm32_stable_C" if n == 1 else f"T_module{field_index}_stm32_C"])
                assert main is not None and temp is not None
                issues = []
                if minimum is None:
                    issues.append("CURRENT_MIN_UNAVAILABLE")
                if maximum is None:
                    issues.append("CURRENT_MAX_UNAVAILABLE")
                if (minimum is not None and main < minimum) or (maximum is not None and main > maximum):
                    issues.append("MAIN_OUTSIDE_DISPLAY_MIN_MAX")
                if minimum is not None and maximum is not None:
                    assert minimum <= maximum
                for issue in issues:
                    qc.append({"combo": combo, "module_id": module, "issue": issue, "main_mA": main,
                               "min_mA": minimum, "max_mA": maximum, "action": "Retain source values; missing field remains null."})
                voltage = volts[combo][module]
                original_photo = row.get("current_photo", "")
                photo = relative(resolve_photo(ROOT, original_photo)) if original_photo else ""
                current_note = row.get("current_min_note", "")
                branch = {"combo": combo, "module_count": n, "module_id": module, "load": "ZERO",
                          "I_main_mA": main, "I_min_mA": minimum, "I_max_mA": maximum, "T_stm32_C": temp,
                          "current_source_path": relative(current_path), "current_source_sha256": sha(current_path),
                          "current_field_mapping": "supplement CSV physical module_id" if extra else f"I_module{field_index}_*_mA",
                          "current_photo": photo, "current_photo_sha256": sha(ROOT / photo) if photo else "",
                          "current_photo_original_reference": original_photo,
                          "I_min_source": "user_confirmation" if current_note.startswith("MIN confirmed by user") else ("unavailable" if minimum is None else "photo" if photo else "original_YAML"),
                          "I_min_note": current_note, "current_filename_date_batch": batch,
                          "temperature_source": "user_message_via_supplement" if extra else "original_YAML_point_reading",
                          "V_module_main_V": number(voltage["main_V"]), "V_module_min_V": number(voltage["min_V"]),
                          "V_module_max_V": number(voltage["max_V"]), "voltage_source_run_id": voltage["point_source_run_id"],
                          "voltage_source_path": voltage["point_source_path"], "voltage_source_sha256": voltage["point_source_sha256"],
                          "voltage_source_fields": voltage["point_source_fields"], "voltage_photo_paths": voltage["photo_paths"],
                          "voltage_photo_original_references": voltage["photo_original_references"],
                          "voltage_photo_sha256": voltage["photo_sha256"], "voltage_acceptance_basis": voltage["point_acceptance_basis"],
                          "V_source_reference_V": number(voltage["source_reference_main_V"]),
                          "source_to_module_drop_mV": number(voltage["source_to_point_drop_mV"]),
                          "drop_uses_same_record": voltage["drop_uses_same_record"], "drop_basis": voltage["drop_basis"],
                          "voltage_quality_event_id": voltage["quality_event_id"],
                          "current_temperature_are_post_connector_repair_measurements": False if corrected else None,
                          "original_observation": data.get("observation") or "", "quality_note": ";".join(issues),
                          "n_current_records_in_this_condition": 1, "within_condition_repeat_SD_mA": None}
                branches.append(branch)
                current_branches.append(branch)
            summed = sum(b["I_main_mA"] for b in current_branches)
            prediction = sum(refs[m] for m in members) if n > 1 else None
            config = {"combo": combo, "module_count": n, "load": "ZERO", "protocol_mode": "FULL",
                      "configured_frequency_Hz": 200, "current_filename_date_batch": batch}
            by_module = {b["module_id"]: b for b in current_branches}
            config.update({f"I_{m}_main_mA": by_module[m]["I_main_mA"] if m in by_module else None for m in MODULES})
            config.update({"I_sum_mA": summed, "V_source_main_V": number(source["main_V"]),
                           "V_source_min_V": number(source["min_V"]), "V_source_max_V": number(source["max_V"]),
                           "P_source_output_estimate_mW": number(source["main_V"]) * summed,
                           "power_uses_cross_record_voltage": bool(extra),
                           "power_is_simultaneous_measurement": False, "branch_sum_is_simultaneous_measurement": False,
                           "source_voltage_path": source["point_source_path"], "source_voltage_sha256": source["point_source_sha256"],
                           "source_voltage_run_id": source["point_source_run_id"], "source_voltage_photo_paths": source["photo_paths"],
                           "source_voltage_photo_original_references": source["photo_original_references"],
                           "source_voltage_photo_sha256": source["photo_sha256"],
                           "voltage_configuration_kind": source["configuration_kind"],
                           "current_temperature_remeasured_after_connector_repair": False if corrected else None,
                           "voltage_quality_event_id": source["quality_event_id"]})
            config.update({f"T_{m}_stm32_C": by_module[m]["T_stm32_C"] if m in by_module else None for m in MODULES})
            config.update({"T_teensy_C": number(extra[members[0]][0]["T_teensy_C"] if extra else data["T_teensy_C"]),
                           "T_regulator_C": number(extra[members[0]][0]["T_regulator_C"] if extra else data["T_regulator_C"]),
                           "I_N1_prediction_mA": prediction,
                           "prediction_residual_mA": summed - prediction if prediction is not None else None,
                           "prediction_residual_percent": (summed - prediction) / prediction * 100 if prediction is not None else None,
                           "n_current_records_in_this_condition": 1, "within_condition_repeat_SD_mA": None,
                           "current_MIN_MAX_complete_branches": sum(b["I_min_mA"] is not None and b["I_max_mA"] is not None for b in current_branches),
                           "source_record_run_id": data["run_id"], "current_source": relative(extra[members[0]][1] if extra else path)})
            assert config["T_teensy_C"] is not None and config["T_regulator_C"] is not None
            configurations.append(config)

    assert len(configurations) == 15 and len(branches) == 32
    by_combo = {c["combo"]: c for c in configurations}
    for combo, expected in {"M0-M1-M3": "54.159", "M0-M2-M3": "54.130", "M0-M1-M2": "54.481", "M1-M2-M3": "54.851", "M0-M1-M2-M3": "72.513"}.items():
        assert by_combo[combo]["I_sum_mA"] == number(expected), (combo, by_combo[combo]["I_sum_mA"])
    fixed = next(b for b in branches if (b["combo"], b["module_id"]) == ("M0-M1-M2", "M0"))
    assert fixed["V_module_main_V"] == number("3.241") and fixed["I_main_mA"] == number("17.968")
    assert fixed["T_stm32_C"] == number("27.5") and fixed["source_to_module_drop_mV"] == number("35")
    confirmed = next(b for b in branches if (b["combo"], b["module_id"]) == ("M0-M3", "M3"))
    assert confirmed["I_min_mA"] == number("17.89") and confirmed["I_min_source"] == "user_confirmation"

    groups, coverage = [], []
    for n in range(1, 5):
        configs = [c for c in configurations if c["module_count"] == n]
        for batch in ["ALL", *sorted({c["current_filename_date_batch"] for c in configs})]:
            selected = configs if batch == "ALL" else [c for c in configs if c["current_filename_date_batch"] == batch]
            for field in ("I_sum_mA", "P_source_output_estimate_mW", "T_teensy_C", "T_regulator_C", "prediction_residual_percent"):
                if n == 1 and field == "prediction_residual_percent":
                    continue
                groups.append({"module_count": n, "current_filename_date_batch": batch, "metric": field,
                               **describe((c[field] for c in selected), cv=field in ("I_sum_mA", "P_source_output_estimate_mW")),
                               "SD_meaning": "Across different configurations; not repeatability; modules shared; batch/configuration confounded"})
        max_combos = []
        for path in (BASE / f"n={n}").rglob("*.yaml"):
            data = raw(path)
            if data.get("load") == "MAX":
                ids = data["module_ids"].replace("Module", "M").split(",")
                fields = ["0"] if n == 1 else [m[1:] for m in ids]
                if all(number(data.get(f"I_module{i}_avg_mA")) is not None for i in fields):
                    max_combos.append("-".join(ids))
        assert len(set(max_combos)) == len(max_combos)
        if n == 2:
            assert not set(max_combos) & set(max_supplement), "Duplicate MAX condition needs an explicit selection policy"
            max_combos.extend(max_supplement)
        members = [b for b in branches if b["module_count"] == n]
        coverage.append({"module_count": n, "possible_combinations": len(configs),
                         "ZERO_voltage_configurations": len(configs), "ZERO_current_main_configurations": len(configs),
                         "ZERO_temperature_configurations": len(configs), "ZERO_current_main_branches": len(members),
                         "ZERO_current_MIN_MAX_branches": sum(b["I_min_mA"] is not None and b["I_max_mA"] is not None for b in members),
                         "MAX_current_configurations": len(max_combos), "MAX_available_combos": ";".join(sorted(max_combos)),
                         "MAX_missing_combos": ";".join(c["combo"] for c in configs if c["combo"] not in max_combos),
                         "current_records_per_configuration_condition": 1, "independent_repeat_SD_available": False})
    assert sum(c["MAX_current_configurations"] for c in coverage) == 13
    summary = {"scope": "ZERO FULL configured 200 Hz continuous USB read; all 15 configurations of the existing four modules",
               "configuration_count": 15, "branch_count": 32, "voltage_current_temperature_main_coverage": "15/15",
               "current_MIN_MAX_coverage": f"{sum(b['I_min_mA'] is not None and b['I_max_mA'] is not None for b in branches)}/32",
               "MAX_current_configuration_coverage": "13/15", "current_records_per_configuration_condition": 1,
               "MAX_coverage_basis": "Nine original MAX YAML configurations plus four N=2 MAX supplement configurations. Coverage only; MAX statistics are in DATA/analysis/current/n2_max_review_20260907.",
               "N1_reference_main_mA": refs, "groups": groups, "coverage": coverage, "quality_issues": qc,
               "known_contact_event": json.loads(EVENT.read_text(encoding="utf-8")),
               "user_confirmed_current_values": [item for meta in metadata.values() for item in meta.get("user_confirmed_current_values", [])],
               "supplement_limitations": {str(n): metadata[n]["known_limitations"] for n in metadata},
               "inference_limits": ["Configuration SD is descriptive, not independent repeat SD.",
                   "Current branches were measured sequentially; representative DMM readings are not verified time averages.",
                   "Six supplemented configurations combine different voltage/current records; contemporaneous source voltage is unverified.",
                   "M0-M1-M2 retains original current and temperature observations while only its M0 voltage uses the accepted repair retest.",
                   "P_est = source voltage times branch-current sum; excludes USB Teensy and regulator losses.",
                   "Filename dates are acquisition-batch indicators, not verified start times. Dates and configuration selection are confounded.",
                   "Temperature point readings are not established thermal equilibrium or temperature rise.",
                   "Startup peaks, ripple, load-switching waveforms and continuous thermal curves remain future work.",
                   "Published main 2.1 and frozen analysis_v2_1 are unchanged."]}
    return configurations, branches, groups, coverage, summary, sources


def write_readme(configs, branches, groups, summary):
    n3 = [c for c in configs if c["module_count"] == 3]
    missing = [b for b in branches if b["I_min_mA"] is None or b["I_max_mA"] is None]
    lines = ["# 空载电流、温度与功率配置汇总（2026-09-07）", "",
             "当前四模块的全部15种非空组合，均有ZERO电压、电流主读数和温度。FULL、配置200 Hz、持续USB接收；照片不能独立验证固件和实际帧率。",
             "两组新增N=3温度按模块编号升序、Teensy、regulator录入；6张电流照片与已有对应电压逐组合关联。原始YAML及已发布main 2.1 PDF未改动。", "",
             "## N=3 各组合电流与功率", "",
             "| 组合 | M0 / mA | M1 / mA | M2 / mA | M3 / mA | 合计 / mA | 源端 / V | 输出侧功率估计 / mW | 相对N=1预测偏差 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value, digits=3):
        return "—" if value is None else f"{value:.{digits}f}"
    for c in n3:
        lines.append("| " + " | ".join([c["combo"], *(fmt(c[f"I_{m}_main_mA"]) for m in MODULES), fmt(c["I_sum_mA"]), fmt(c["V_source_main_V"]), fmt(c["P_source_output_estimate_mW"]), fmt(c["prediction_residual_percent"]) + "%"]) + " |")
    lines += ["", "## N=3 温度 / °C", "", "| 组合 | M0 STM32 | M1 STM32 | M2 STM32 | M3 STM32 | Teensy | Regulator |", "|---|---:|---:|---:|---:|---:|---:|"]
    for c in n3:
        lines.append("| " + " | ".join([c["combo"], *(fmt(c[f"T_{m}_stm32_C"], 1) for m in MODULES), fmt(c["T_teensy_C"], 1), fmt(c["T_regulator_C"], 1)]) + " |")
    lines += ["", "## N=1–4 描述性汇总", "", "| N | 组合数 | 合计电流均值 ± SD / mA | 输出侧功率估计均值 ± SD / mW | 每组合电流记录数 |", "|---|---:|---:|---:|---:|"]
    for n in range(1, 5):
        stats = {g["metric"]: g for g in groups if g["module_count"] == n and g["current_filename_date_batch"] == "ALL"}
        i, p = stats["I_sum_mA"], stats["P_source_output_estimate_mW"]
        lines.append(f"| {n} | {i['n_configurations']} | {fmt(i['mean'])} ± {fmt(i['sample_SD_across_configurations'])} | {fmt(p['mean'])} ± {fmt(p['sample_SD_across_configurations'])} | 1 |")
    lines += ["", "SD为同一N下不同组合之间的样本SD（分母n−1），不是同条件重复测量SD。N=4仅一个组合，SD留空。组合共享同一批模块，不能作为独立硬件重复；原有与新增组合日期不同，日期与组合效应混杂。group_summary.csv同时保留按照片文件名日期分批的结果。", "",
              "N=1的四条记录对应四个不同物理模块；原始文件将其均存入module0测量字段，分析已按module_ids映射回M0–M3。", "",
              "## 数据含义与已知限制", "",
              "- I_sum为顺序测得的各模块DMM主读数之和，不是同步总电流，也不是经过验证的时间平均电流。MIN/MAX保留仪表显示数值，不是SD或启动峰值。",
              "- P_est = V_source × I_sum。新增4个N=2及2个N=3组合使用不同记录的电压和电流；N=3即使照片日期相同，也不代表同一时刻。功率为输出侧配置估计，不包括USB供电Teensy和稳压器损耗。",
              "- 相对N=1预测偏差=(实测支路合计−对应物理模块的N=1电流之和)/预测值。仅N>1计算；属于所测条件下的描述性可加性检查，不能证明最大供电容量或普遍线性。",
              "- M0-M1-M2：仅原M0电压3.224 V受connector接触不良影响，现接受M0复测3.241 V；SOURCE/M1/M2保留用户确认的原电压。原电流及温度全部保留，不声称在修复后重测。M0压降35 mV为用户确认源端未变情况下的跨记录估计，逐点来源见branch_readings.csv及电压接受表。",
              "- M0-M3的M3电流MIN=17.89 mA来自用户确认；照片仍因反光无法独立验证该字段。",
              f"- 电流主读数32/32支路齐全；MIN/MAX齐全程度为{summary['current_MIN_MAX_coverage']}。"]
    for item in summary["user_confirmed_current_values"]:
        if item["combo"] != "M0-M3":
            lines.append(f"- {item['combo']}的{item['module_id']}电流{item['field']}={number(item['value']):.2f} mA来自用户确认，已单独标明来源；照片中该字段仍无法独立读出，主读数和MAX保持不变。")
    for b in missing:
        lines.append(f"- 待补字段：{b['combo']} {b['module_id']}，MIN={fmt(b['I_min_mA'])} mA、MAX={fmt(b['I_max_mA'])} mA；说明：{b['I_min_note']}。主读数{fmt(b['I_main_mA'])} mA可用于上述合计。")
    lines += ["- 个别历史记录的主读数略超显示MIN/MAX范围，按原值保留并在summary.json标记；不静默修正。",
              "- 温度为点读数。环境温度、实际预热和观察时长尚未核实，不声称热稳态；启动峰值、纹波、负载切换波形和持续温升曲线按用户决定列为未来工作。",
              "- 模板故障计数0不能作为完成监测的证明；未建立对应会话的观测依据时保留未知，且不能抹去已有M0接头故障。",
              "- MAX现覆盖13/15组合：仅缺M0-M1-M3、M0-M2-M3两组N=3加载记录。这里仅合并原9组YAML与新增4组N=2 MAX补充表的覆盖度，不在ZERO统计中混入MAX数值；同条件独立重复仍未增加。",
              "- 最新N=2加载电压、电流、温度及与空载的对照，见[满负载统计说明](../../../../../../DATA/analysis/current/n2_max_review_20260907/README_CN.md)。", "",
              "## 文件与复现", "", "- `configuration_summary.csv`：全部15组合；`n3_configuration_summary.csv`：4个N=3组合。",
              "- `branch_readings.csv`：32个支路的电流/温度、接受电压及逐字段来源。",
              "- `group_summary.csv`：按N及日期批次的描述性统计；`coverage.csv`：ZERO/MAX覆盖。",
              "- `summary.json`：统计、质量标记及限制；`source_manifest.json`：原始输入/照片哈希和保护性检查。",
              "- Power目录执行：`python script/Main/summarize_zero_power_20260907.py`。本脚本只写本汇总目录，不修改原始记录或报告。", ""]
    (OUT / "README_CN.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    frozen = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    assert len(frozen["sources"]) == 19
    for item in frozen["sources"]:
        assert sha(ROOT / item["relative_path"]) == item["sha256"], item["relative_path"]
    assert sha(PDF) == PDF_SHA, "Published PDF differs from the protected 2.1 snapshot"
    protected = [p for p in (ROOT / "DATA/reference/analysis_v2_1").rglob("*") if p.is_file()]
    protected += list(BASE.rglob("*.yaml")) + list(BASE.rglob("*.jpg")) + [ROOT / "DATA/raw/canonical/power_raw.csv", PDF]
    protected += list(SUPPS.glob("*.csv")) + list(SUPPS.glob("*.json")) + [VOLTAGES, EVENT]
    before = {p: sha(p) for p in protected}
    configs, branches, groups, coverage, summary, sources = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, rows in [("configuration_summary.csv", configs), ("branch_readings.csv", branches),
                           ("group_summary.csv", groups), ("coverage.csv", coverage),
                           ("n3_configuration_summary.csv", [c for c in configs if c["module_count"] == 3])]:
        write_csv(OUT / filename, rows)
    write_json(OUT / "summary.json", summary)
    write_readme(configs, branches, groups, summary)
    assert all(sha(path) == digest for path, digest in before.items()), "Protected input changed during analysis"
    sources.update(ROOT / item["relative_path"] for item in frozen["sources"])
    manifest = {"schema_version": 1, "scope": "Current ZERO review; published 2.1 historical analysis not rewritten",
                "script": {"path": relative(Path(__file__)), "sha256": sha(Path(__file__))},
                "sources": [{"path": relative(path), "sha256": sha(path)} for path in sorted(sources)],
                "published_main_2_1_sha256": sha(PDF), "original_19_inputs_match_frozen_manifest": True,
                "protected_files_unchanged": len(before), "accepted_voltage_sources_and_photo_hashes_verified": True,
                "configuration_count": len(configs), "branch_count": len(branches)}
    write_json(OUT / "source_manifest.json", manifest)
    print(json.dumps({"configurations": len(configs), "branches": len(branches),
                      "MIN_MAX_coverage": summary["current_MIN_MAX_coverage"], "MAX_coverage": summary["MAX_current_configuration_coverage"],
                      "n3_sums_mA": {c["combo"]: str(c["I_sum_mA"]) for c in configs if c["module_count"] == 3},
                      "protected_unchanged": len(before), "QC_count": len(summary["quality_issues"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
