"""Supplementary N=2 MAX review; never modifies published 2.1 or raw evidence."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
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
SUPP = ROOT / "DATA/raw/canonical/power_experiment_records/current_temperature_supplements/n2_max_20260907.csv"
META = SUPP.with_name("n2_max_20260907_metadata.json")
N3_SUPP = SUPP.with_name("n3_max_20260907.csv")
N3_META = SUPP.with_name("n3_max_20260907_metadata.json")
ZERO = ROOT / "DATA/analysis/current/n2_zero_review_20260907/configuration_summary.csv"
ZERO_ALL = ROOT / "DATA/analysis/current/zero_power_review_20260907/configuration_summary.csv"
OUT = ROOT / "DATA/analysis/current/n2_max_review_20260907"
FROZEN_MANIFEST = ROOT / "DATA/reference/analysis_v2_1/source_manifest.json"
REPORT = ROOT.parent / "main 2.1.pdf"
REPORT_SHA = "d659fbab34fa82366abba88316f49308e95ce8c1459f0c11941f1d369b627f6f"
D = lambda value: Decimal(str(value)) if value not in (None, "") else None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def rel(path):
    return path.relative_to(ROOT).as_posix()


def describe(values, cv=False):
    values = list(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else None
    result = {"n_combinations": len(values), "mean": mean, "sample_SD_between_combinations": sd,
              "minimum": min(values), "maximum": max(values)}
    if cv:
        result["CV_percent"] = sd / mean * 100 if sd is not None else None
    return result


def verify_frozen():
    manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 19
    for item in manifest["sources"]:
        assert sha(ROOT / item["relative_path"]) == item["sha256"], item["relative_path"]
    assert sha(REPORT) == REPORT_SHA, "Published report changed"


def build():
    metadata = json.loads(META.read_text(encoding="utf-8"))
    sources = {SUPP, META, N3_SUPP, N3_META, ZERO, ZERO_ALL, FROZEN_MANIFEST}
    def read_max_supplement(path, meta, n):
        assert meta["load"] == "MAX"
        result = defaultdict(dict)
        for row in read_csv(path):
            combo, module = row["combo"], row["module_id"]
            ids = combo.split("-")
            assert len(ids) == n and ids == sorted(set(ids)) and set(ids) <= {"M0", "M1", "M2", "M3"}
            assert row["load"] == "MAX" and module in ids and module not in result[combo]
            assert all(D(row[field]) is not None for field in (
                "I_main_mA", "I_min_mA", "I_max_mA", "V_module_main_V", "V_module_min_V", "V_module_max_V",
                "V_source_main_V", "V_source_min_V", "V_source_max_V", "T_stm32_C", "T_teensy_C", "T_regulator_C"))
            temps = meta["temperature_message_values"][combo]
            assert len(temps) == n + 2
            assert D(row["T_stm32_C"]) == D(temps[ids.index(module)])
            assert D(row["T_teensy_C"]) == D(temps[n]) and D(row["T_regulator_C"]) == D(temps[n + 1])
            for field in ("current_photo", "module_voltage_photo", "source_voltage_photo"):
                photo = ROOT / row[field]
                assert photo.is_file(), f"MAX coverage photo missing; explicit path repair required: {photo}"
                sources.add(photo)
            result[combo][module] = row
        for combo, rows in result.items():
            assert set(rows) == set(combo.split("-")), "MAX coverage needs every physical module branch"
            assert len({tuple(row[field] for field in ("V_source_main_V", "V_source_min_V", "V_source_max_V", "source_voltage_photo")) for row in rows.values()}) == 1
        return result
    supplements = read_max_supplement(SUPP, metadata, 2)
    assert set(supplements) == {"M0-M2", "M0-M3", "M1-M2", "M1-M3"}
    assert supplements["M1-M2"]["M1"]["I_main_mA"] == "19.99"
    assert supplements["M1-M3"]["M1"]["I_main_mA"] == "20.32"
    assert metadata["load_mass_g"] is None
    configs, branches, source_voltages, qc = [], [], [], []
    for pair in itertools.combinations(("M0", "M1", "M2", "M3"), 2):
        combo = "-".join(pair)
        extra = supplements.get(combo)
        path = SUPP if extra else BASE / f"n=2/{combo}/full_load/PS01_N2_F200_MAX_{combo}_USB_RX_R1.yaml"
        sources.add(path)
        raw = {} if extra else yaml.safe_load(path.read_text(encoding="utf-8"))
        batch = "2026-09-07" if extra else "2026-09-05"
        if extra:
            assert set(extra) == set(pair)
            lower = extra[pair[0]]
            temps = metadata["temperature_message_values"][combo]
            for i, mid in enumerate(pair):
                assert D(extra[mid]["T_stm32_C"]) == D(temps[i])
                assert D(extra[mid]["T_teensy_C"]) == D(temps[2])
                assert D(extra[mid]["T_regulator_C"]) == D(temps[3])
                for key in ("V_source_main_V", "V_source_min_V", "V_source_max_V", "source_voltage_photo"):
                    assert extra[mid][key] == lower[key]
            vs = [D(lower[f"V_source_{kind}_V"]) for kind in ("main", "min", "max")]
            load_mass = None
            source_photo = lower["source_voltage_photo"]
            source_note = metadata["source_voltage_mapping_basis"]
            config_photos = sorted({extra[mid][key] for mid in pair for key in ("current_photo", "module_voltage_photo", "source_voltage_photo")})
            assert len(config_photos) == 5
        else:
            assert (raw["load"], raw["module_count"], raw["protocol_mode"], raw["frequency_hz"]) == ("MAX", 2, "FULL", 200)
            assert raw["module_ids"].replace("Module", "M").split(",") == list(pair)
            vs = [D(raw[f"V_source_{kind}_V"]) for kind in ("avg", "min", "max")]
            load_mass = D(raw["load_mass_g"])
            source_photo = ""
            source_note = "Original YAML fields; all five original configuration photos retained as group evidence. No new individual photo-to-field mapping asserted."
            config_photos = [rel(p) for p in sorted(path.parent.glob("*.jpg"))]
            assert len(config_photos) == 5
        assert vs[1] <= vs[0] <= vs[2]
        for photo in config_photos:
            assert (ROOT / photo).is_file(), photo
            sources.add(ROOT / photo)
        photo_hashes = [sha(ROOT / photo) for photo in config_photos]
        source_voltages.append({"combo": combo, "load": "MAX", "V_source_main_V": vs[0],
                               "V_source_min_V": vs[1], "V_source_max_V": vs[2], "source_record": rel(path),
                               "source_record_sha256": sha(path), "source_voltage_photo": source_photo,
                               "source_voltage_photo_sha256": sha(ROOT / source_photo) if source_photo else "",
                               "source_identity_basis": source_note, "photo_filename_date_batch": batch,
                               "configuration_photo_paths": ";".join(config_photos), "configuration_photo_sha256": ";".join(photo_hashes)})
        pair_branches = []
        for mid in pair:
            row = extra[mid] if extra else {}
            idx = mid[1:]
            currents = [D(row[f"I_{kind}_mA"]) for kind in ("main", "min", "max")] if extra else [D(raw[f"I_module{idx}_{kind}_mA"]) for kind in ("avg", "min", "max")]
            volts = [D(row[f"V_module_{kind}_V"]) for kind in ("main", "min", "max")] if extra else [D(raw[f"V_module{idx}_{kind}_V"]) for kind in ("avg", "min", "max")]
            issues = []
            if not currents[1] <= currents[0] <= currents[2]:
                issues.append("CURRENT_MAIN_OUTSIDE_DISPLAY_MIN_MAX")
            if not volts[1] <= volts[0] <= volts[2]:
                issues.append("VOLTAGE_MAIN_OUTSIDE_DISPLAY_MIN_MAX")
            for issue in issues:
                qc.append({"combo": combo, "module_id": mid, "issue": issue, "action": "retain original readings"})
            branch = {"combo": combo, "module_id": mid, "load": "MAX", "I_main_mA": currents[0],
                      "I_min_mA": currents[1], "I_max_mA": currents[2],
                      "I_main_display_text_mA": row["I_main_mA"] if extra else str(raw[f"I_module{idx}_avg_mA"]),
                      "V_module_main_V": volts[0], "V_module_min_V": volts[1], "V_module_max_V": volts[2],
                      "V_source_main_V": vs[0], "source_minus_module_main_mV": (vs[0] - volts[0]) * 1000,
                      "T_stm32_C": D(row["T_stm32_C"] if extra else raw[f"T_module{idx}_stm32_C"]),
                      "current_photo": row.get("current_photo", ""), "current_photo_sha256": sha(ROOT / row["current_photo"]) if extra else "",
                      "module_voltage_photo": row.get("module_voltage_photo", ""), "module_voltage_photo_sha256": sha(ROOT / row["module_voltage_photo"]) if extra else "",
                      "source_voltage_photo": source_photo, "source_voltage_photo_sha256": sha(ROOT / source_photo) if source_photo else "",
                      "configuration_photo_paths": ";".join(config_photos), "configuration_photo_sha256": ";".join(photo_hashes),
                      "source_record": rel(path), "source_record_sha256": sha(path),
                      "individual_photo_mapping": "supplement_visual_transcription" if extra else "not_reassigned_original_YAML_plus_group_photos",
                      "temperature_source": "user_message_via_metadata" if extra else "original_YAML",
                      "photo_filename_date_batch": batch, "load_mass_g": load_mass,
                      "quality_note": ";".join(issues), "n_records_per_condition": 1, "within_condition_repeat_SD_mA": None}
            branches.append(branch)
            pair_branches.append(branch)
        isum = sum(b["I_main_mA"] for b in pair_branches)
        configs.append({"combo": combo, "module_count": 2, "load": "MAX", "protocol_mode": "FULL",
                        "configured_frequency_Hz": 200, "host_state": "CONTINUOUS_USB_READ",
                        "module_lower": pair[0], "module_upper": pair[1],
                        "I_lower_main_mA": pair_branches[0]["I_main_mA"], "I_upper_main_mA": pair_branches[1]["I_main_mA"],
                        "I_sum_mA": isum, "V_source_main_V": vs[0], "V_source_min_V": vs[1], "V_source_max_V": vs[2],
                        "V_lower_main_V": pair_branches[0]["V_module_main_V"], "V_upper_main_V": pair_branches[1]["V_module_main_V"],
                        "P_source_output_estimate_mW": vs[0] * isum, "T_lower_stm32_C": pair_branches[0]["T_stm32_C"],
                        "T_upper_stm32_C": pair_branches[1]["T_stm32_C"],
                        "T_teensy_C": D(extra[pair[0]]["T_teensy_C"] if extra else raw["T_teensy_C"]),
                        "T_regulator_C": D(extra[pair[0]]["T_regulator_C"] if extra else raw["T_regulator_C"]),
                        "load_mass_g": load_mass, "load_area_mm2": None, "load_application": None,
                        "voltage_current_simultaneity_verified": False, "simultaneous_branch_sum_measured": False,
                        "photo_filename_date_batch": batch, "n_records_per_configuration": 1, "within_condition_repeat_SD_mA": None})
    zero = {row["combo"]: row for row in read_csv(ZERO)}
    assert set(zero) == {c["combo"] for c in configs}
    pairs = []
    for c in configs:
        z = zero[c["combo"]]
        delta = c["I_sum_mA"] - D(z["I_sum_mA"])
        pdelta = c["P_source_output_estimate_mW"] - D(z["P_source_output_estimate_mW"])
        pairs.append({"combo": c["combo"], "I_ZERO_sum_mA": D(z["I_sum_mA"]), "I_MAX_sum_mA": c["I_sum_mA"],
                      "MAX_minus_ZERO_mA": delta, "MAX_minus_ZERO_percent_of_ZERO": delta / D(z["I_sum_mA"]) * 100,
                      "P_ZERO_estimate_mW": D(z["P_source_output_estimate_mW"]), "P_MAX_estimate_mW": c["P_source_output_estimate_mW"],
                      "MAX_minus_ZERO_power_estimate_mW": pdelta, "V_source_ZERO_V": D(z["V_source_main_V"]), "V_source_MAX_V": c["V_source_main_V"],
                      "T_lower_MAX_minus_ZERO_C": c["T_lower_stm32_C"] - D(z["T_lower_stm32_C"]),
                      "T_upper_MAX_minus_ZERO_C": c["T_upper_stm32_C"] - D(z["T_upper_stm32_C"]),
                      "T_teensy_MAX_minus_ZERO_C": c["T_teensy_C"] - D(z["T_teensy_C"]),
                      "T_regulator_MAX_minus_ZERO_C": c["T_regulator_C"] - D(z["T_regulator_C"]),
                      "ZERO_current_filename_date_batch": z["current_filename_date_batch"], "MAX_filename_date_batch": c["photo_filename_date_batch"],
                      "ZERO_power_uses_cross_record_voltage": z["power_uses_cross_record_voltage"],
                      "MAX_load_mass_g": c["load_mass_g"], "n_ZERO_records": 1, "n_MAX_records": 1, "repeat_SD_available": False,
                      "comparison_basis": "descriptive_matching_physical_combo;not_repeated_paired_trials"})
    zero_all = {row["combo"] for row in read_csv(ZERO_ALL)}
    assert len(zero_all) == 15
    max_all = {}
    for path in sorted(BASE.rglob("*_MAX_*_USB_RX_R1.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids = raw["module_ids"].replace("Module", "M").split(",")
        n = raw["module_count"]
        assert raw["load"] == "MAX" and 1 <= n <= 4 and len(ids) == n and ids == sorted(set(ids))
        assert set(ids) <= {"M0", "M1", "M2", "M3"}
        required = [f"V_source_{kind}_V" for kind in ("avg", "min", "max")] + ["T_teensy_C", "T_regulator_C"]
        for i in (["0"] if n == 1 else [m[1:] for m in ids]):
            required.extend(f"{quantity}_module{i}_{kind}_{unit}" for quantity, unit in (("I", "mA"), ("V", "V")) for kind in ("avg", "min", "max"))
            required.append("T_stm32_stable_C" if n == 1 else f"T_module{i}_stm32_C")
        assert all(D(raw.get(field)) is not None for field in required), path
        combo = "-".join(ids)
        assert combo not in max_all
        max_all[combo] = rel(path)
        sources.add(path)
    assert len(max_all) == 9
    assert not set(max_all) & set(supplements)
    max_all.update({combo: rel(SUPP) for combo in supplements})
    # N=3 additions affect overall coverage only; all measurements/statistics above stay N=2.
    n3_metadata = json.loads(N3_META.read_text(encoding="utf-8"))
    n3_supplements = read_max_supplement(N3_SUPP, n3_metadata, 3)
    assert set(n3_supplements) == {"M0-M1-M3", "M0-M2-M3"}
    assert not set(max_all) & set(n3_supplements)
    max_all.update({combo: rel(N3_SUPP) for combo in n3_supplements})
    assert set(max_all) == zero_all and len(max_all) == 15
    coverage = []
    for n in range(1, 5):
        for group in itertools.combinations(("M0", "M1", "M2", "M3"), n):
            combo = "-".join(group)
            coverage.append({"module_count": n, "combo": combo, "ZERO_voltage_current_temperature_recorded": combo in zero_all,
                             "MAX_voltage_current_temperature_recorded": combo in max_all, "MAX_source": max_all.get(combo, ""),
                             "MAX_load_mass_status": "unspecified_new_supplement" if combo in supplements or combo in n3_supplements else ("2000_g_recorded_area_distribution_unspecified" if combo in max_all else "missing"),
                             "n_records_per_available_configuration_condition": 1, "within_condition_repeat_SD_available": False})
    metrics = ("I_sum_mA", "P_source_output_estimate_mW", "V_source_main_V", "T_teensy_C", "T_regulator_C")
    summary = {"scope": metadata["scope"], "n_combinations": 6, "n_records_per_configuration_condition": 1,
               "SD_meaning": "Sample SD across different configurations; not within-condition repeatability. Combinations share modules and are confounded with acquisition batch.",
               "aggregate_MAX": {key: describe((c[key] for c in configs), key in metrics[:2]) for key in metrics},
               "aggregate_ZERO": {key: describe((D(z[key]) for z in zero.values()), key in metrics[:2]) for key in metrics},
               "by_MAX_photo_filename_date_batch": {batch: {key: describe((c[key] for c in configs if c["photo_filename_date_batch"] == batch), key in metrics[:2]) for key in metrics} for batch in ("2026-09-05", "2026-09-07")},
               "by_ZERO_current_filename_date_batch": {batch: {key: describe((D(z[key]) for z in zero.values() if z["current_filename_date_batch"] == batch), key in metrics[:2]) for key in metrics} for batch in ("2026-09-05", "2026-09-07")},
               "descriptive_MAX_minus_ZERO": {key: describe((p[key] for p in pairs)) for key in ("MAX_minus_ZERO_mA", "MAX_minus_ZERO_percent_of_ZERO", "MAX_minus_ZERO_power_estimate_mW")},
               "module_voltage_main_range_V": [min(b["V_module_main_V"] for b in branches), max(b["V_module_main_V"] for b in branches)],
               "module_temperature_range_C": [min(b["T_stm32_C"] for b in branches), max(b["T_stm32_C"] for b in branches)],
               "source_minus_module_main_range_mV": [min(b["source_minus_module_main_mV"] for b in branches), max(b["source_minus_module_main_mV"] for b in branches)],
               "new_photos": 20, "new_current_photos": 8, "new_voltage_photos": 12,
               "N2_MAX_branch_main_MIN_MAX_coverage": "12/12 current and module voltage; 6/6 source voltage",
               "overall_coverage": {"ZERO": "15/15", "MAX": "15/15", "MAX_missing": [r["combo"] for r in coverage if not r["MAX_voltage_current_temperature_recorded"]]},
               "QC_reading_consistency_issues": qc,
               "QC_scope": "Checks numeric MIN <= main <= MAX only; no hardware fault absence or session integrity inferred.",
               "limitations": metadata["known_limitations"]}
    assert summary["overall_coverage"]["MAX_missing"] == []
    assert len(branches) == 12 and len(configs) == 6
    return configs, branches, source_voltages, pairs, coverage, summary, sources


def write_readme(configs, pairs, summary):
    lines = ["# N=2 满负载电压、电流与温度补充统计（2026-09-07）", "",
             "新增四组按用户确认记为满负载 MAX。与原有 M0-M1、M2-M3 合并后，N=2 的 ZERO 和 MAX 均覆盖全部 6 种组合。补入两组 N=3 MAX 后，整体 N=1–4 的 ZERO 和 MAX 现均为 15/15。覆盖完成表示这些测点已有记录，不表示全部试验条件或故障监测已完整。", "",
             "本目录的测量统计仍只包含 N=2；N=3 MAX 只用于更新整体覆盖度。全部组合汇总见[完整 Power 统计总结](../all_power_review_20260907/README_CN.md)。", "",
             "FULL、配置 200 Hz、持续 USB 接收沿用本次 Power 实验系列；照片本身不能验证固件、实际帧率或运行完整性。", "",
             "## MAX 主读数", "", "| 组合 | 较小编号模块电流 / mA | 较大编号模块电流 / mA | 分支合计 / mA | 源端 / V | 较小编号模块 / V | 较大编号模块 / V | 输出侧功率估计 / mW |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for c in configs:
        lines.append(f"| {c['combo']} | {c['I_lower_main_mA']} | {c['I_upper_main_mA']} | {c['I_sum_mA']:.3f} | {c['V_source_main_V']:.3f} | {c['V_lower_main_V']:.3f} | {c['V_upper_main_V']:.3f} | {c['P_source_output_estimate_mW']:.3f} |")
    lines += ["", "新数据中 19.99 mA 和 20.32 mA 保留照片显示精度；合计与功率的小数位只表示算术结果，不是新增测量精度。", "",
              "I_sum 为顺序测量的两支路 DMM 主读数之和；P_est = V_source × I_sum。电压、电流也按照片顺序分次记录，不能解释为同步总电流或同步功率测量。主读数不是经验证的时间平均值。功率不包括 USB 供电的 Teensy 和稳压器损耗。源端至模块压降也是主读数之差，不是动态最坏压降。", "",
              "## 温度 / °C", "", "| 组合 | 较小编号模块 STM32 | 较大编号模块 STM32 | Teensy | Regulator |", "|---|---:|---:|---:|---:|"]
    for c in configs:
        lines.append(f"| {c['combo']} | {c['T_lower_stm32_C']:.1f} | {c['T_upper_stm32_C']:.1f} | {c['T_teensy_C']:.1f} | {c['T_regulator_C']:.1f} |")
    lines += ["", "## ZERO / MAX 描述性比较", "", "| 组合 | ZERO 合计 / mA | MAX 合计 / mA | 增量 / mA | 相对 ZERO / % |", "|---|---:|---:|---:|---:|"]
    for p in pairs:
        lines.append(f"| {p['combo']} | {p['I_ZERO_sum_mA']:.3f} | {p['I_MAX_sum_mA']:.3f} | {p['MAX_minus_ZERO_mA']:.3f} | {p['MAX_minus_ZERO_percent_of_ZERO']:.3f} |")
    lines += ["", "## 汇总和证据范围", ""]
    for condition in ("ZERO", "MAX"):
        for key, title, unit in (("I_sum_mA", "合计电流", "mA"), ("P_source_output_estimate_mW", "输出侧功率估计", "mW")):
            s = summary[f"aggregate_{condition}"][key]
            lines.append(f"- {condition} {title}：{s['mean']:.3f} ± {s['sample_SD_between_combinations']:.3f} {unit}；n_combination = 6。")
    lines += ["", "上述 SD 是 6 种组合之间的样本 SD（n−1），不是同条件重复误差。每组合每负载条件 n_record = 1，无独立重复 SD；DMM 的 MIN/MAX 也不是 SD。各组合共享模块，不能当作 6 组独立硬件重复。", "",
              "原有两组 MAX 来自文件名日期 2026-09-05，新四组来自 2026-09-07；summary.json 保留各批次独立统计。文件名日期不等同于已验证的测量起止时间。组合与日期混杂，ZERO/MAX 差异只作同一物理组合的描述性对比，不能把所有差异单独归因于负载。", "",
              "比较表中的 ZERO 沿用已保存的空载汇总。M0-M2、M0-M3、M1-M2、M1-M3 的 ZERO 功率估计使用 9 月 6 日电压照片和 9 月 7 日电流照片，属于跨记录配置估计；load_pairs.csv 保留该标记。新增 MAX 电压/电流来自各组合本次 9 月 7 日照片，也仍是顺序测量。", "",
              "新四组 MAX 由用户确认，但未提供质量、接触面积或分布；这些字段保留为空，不能复制旧两组的 2000 g。旧 2000 g 也未明确面积与施力分布。", "",
              "新增照片中的 SOURCE 按既有记录习惯分配给每组合第一张电压照片；探针端点不可见，此身份属于记录顺序推定。模块电压与电流分别按升序模块编号映射。旧两组沿用原 YAML，照片保留为整组证据，本次没有重新断言每张旧照片的测点身份。", "",
              "12 个电流支路、12 个模块电压及 6 个源端电压均保留主读数/MIN/MAX；本次检查未发现 MAX 主读数落在 MIN/MAX 之外。该检查不能代表没有硬件故障、掉帧或供电动态问题。", "",
              "温度是点读数，不具备已验证的热稳态与环境温度依据。启动峰值、纹波、负载切换波形、持续温升曲线按用户决定保留为未来工作。", "",
              "## 文件与复现", "", "- `configuration_summary.csv`：6 组 MAX 的电压、电流、功率估计和温度。",
              "- `branch_readings.csv`：12 支路及全部 MIN/MAX、原始显示精度、照片路径和 SHA256。",
              "- `source_voltage_readings.csv`：6 组 SOURCE 的主读数/MIN/MAX 与来源。",
              "- `load_pairs.csv`：6 个相同物理组合的 ZERO/MAX 描述性差异。",
              "- `coverage.csv`：15 种可能组合的 ZERO/MAX 测点覆盖。",
              "- `summary.json`：总体与分批统计、QC 和限制；`source_manifest.json`：输入来源与哈希。",
              "- 从 Power 目录运行 `python script/Main/intake/summarize_n2_max_20260907.py`。",
              "- 原始 YAML、照片、ZERO 数据、冻结 analysis_v2_1 与 main 2.1.pdf 均不改写。", ""]
    (OUT / "README_CN.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    verify_frozen()
    protected = list(BASE.rglob("*.yaml")) + list(BASE.rglob("*.jpg")) + list((ROOT / "DATA/reference/analysis_v2_1").rglob("*"))
    protected += [REPORT, ROOT / "DATA/raw/canonical/power_raw.csv", SUPP, META, N3_SUPP, N3_META]
    before = {p: sha(p) for p in protected if p.is_file()}
    configs, branches, source_voltages, pairs, coverage, summary, sources = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("configuration_summary.csv", configs), ("branch_readings.csv", branches),
                       ("source_voltage_readings.csv", source_voltages), ("load_pairs.csv", pairs), ("coverage.csv", coverage)):
        write_csv(OUT / name, rows)
    write_json(OUT / "summary.json", summary)
    write_readme(configs, pairs, summary)
    write_json(OUT / "source_manifest.json", {"schema_version": 1, "analysis_script": {"path": rel(Path(__file__)), "sha256": sha(Path(__file__))},
               "sources": [{"path": rel(p), "sha256": sha(p)} for p in sorted(sources)],
               "protected_existing_file_count": len(before), "frozen_v2_1_sources_verified": 19, "published_main_2_1_sha256": sha(REPORT)})
    assert all(sha(p) == digest for p, digest in before.items()), "Protected inputs changed"
    verify_frozen()
    print(json.dumps({"configurations": len(configs), "branches": len(branches), "aggregate_MAX": summary["aggregate_MAX"],
                      "coverage": summary["overall_coverage"], "QC": summary["QC_reading_consistency_issues"],
                      "protected_unchanged": len(before)}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
