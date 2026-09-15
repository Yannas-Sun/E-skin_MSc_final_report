"""Combine the dated N=2 current/temperature supplement with voltage provenance.

Produces a current six-pair view; never changes raw YAML, photos or analysis_v2_1.
Main DMM readings are not relabelled as time averages. SD is across configurations.
"""
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

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "DATA/raw/canonical/power_experiment_records/transmission"
SUPP = ROOT / "DATA/raw/canonical/power_experiment_records/current_temperature_supplements/n2_zero_20260907.csv"
META = SUPP.with_name("n2_zero_20260907_metadata.json")
OUT = ROOT / "DATA/analysis/current/n2_zero_review_20260907"
D = lambda value: Decimal(str(value)) if value not in (None, "") else None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def dump_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def describe(values, include_cv=False):
    values = list(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else None
    result = {"n": len(values), "mean": mean, "sample_SD": sd,
              "minimum": min(values), "maximum": max(values)}
    if include_cv:
        result["CV_percent"] = sd / mean * 100 if sd is not None else None
    return result


def build():
    sources = {SUPP, META}
    metadata = json.loads(META.read_text(encoding="utf-8"))
    supplements = defaultdict(dict)
    with SUPP.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            combo, mid = row["combo"], row["module_id"]
            if mid in supplements[combo]:
                raise ValueError(f"Duplicate supplement: {combo} {mid}")
            supplements[combo][mid] = row
    if set(supplements) != {"M0-M2", "M0-M3", "M1-M2", "M1-M3"}:
        raise ValueError("Expected exactly the four newly supplemented configurations")

    references = {}
    for mid in ("M0", "M1", "M2", "M3"):
        path = BASE / f"n=1/{mid}/zero_load/PS01_N1_F200_ZERO_{mid}_USB_RX_R1.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw["module_ids"] != "Module" + mid[1:]:
            raise ValueError("N=1 physical module mapping mismatch")
        # N=1 records store the selected physical module in module0 fields.
        references[mid] = D(raw["I_module0_avg_mA"])
        sources.add(path)

    configs, branches, qc = [], [], []
    for pair in itertools.combinations(("M0", "M1", "M2", "M3"), 2):
        combo = "-".join(pair)
        extra = supplements.get(combo)
        suffix = "VOLTAGE_R1" if extra else "R1"
        path = BASE / f"n=2/{combo}/zero_load/PS01_N2_F200_ZERO_{combo}_USB_RX_{suffix}.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        sources.add(path)
        for evidence in raw.get("voltage_photo_evidence", []):
            photo_path = (path.parent / evidence["file"]).resolve()
            if sha(photo_path) != evidence["sha256"]:
                raise ValueError(f"Voltage photo hash mismatch: {photo_path}")
            sources.add(photo_path)
        if (raw["load"], raw["module_count"], raw["protocol_mode"], raw["frequency_hz"]) != ("ZERO", 2, "FULL", 200):
            raise ValueError("Unexpected condition")
        if raw["module_ids"].replace("Module", "M").split(",") != list(pair):
            raise ValueError("N=2 module mapping mismatch")
        if extra and set(extra) != set(pair):
            raise ValueError("Missing or extra branch in current supplement")
        if extra:
            temperatures = metadata["temperature_message_values"][combo]
            for index, mid in enumerate(pair):
                assert D(extra[mid]["T_stm32_C"]) == D(temperatures[index])
                assert D(extra[mid]["T_teensy_C"]) == D(temperatures[2])
                assert D(extra[mid]["T_regulator_C"]) == D(temperatures[3])
        batch = "2026-09-07" if extra else "2026-09-05"
        pair_branches = []
        for mid in pair:
            index = mid[1:]
            row = extra[mid] if extra else {}
            main = D(row["I_main_mA"] if extra else raw[f"I_module{index}_avg_mA"])
            minimum = D(row["I_min_mA"] if extra else raw[f"I_module{index}_min_mA"])
            maximum = D(row["I_max_mA"] if extra else raw[f"I_module{index}_max_mA"])
            temperature = D(row["T_stm32_C"] if extra else raw[f"T_module{index}_stm32_C"])
            photo = row.get("current_photo", "")
            if photo:
                sources.add(ROOT / photo)
            issues = []
            if minimum is None:
                issues.append("MIN_UNREADABLE_GLARE")
            elif not minimum <= main <= maximum:
                issues.append("MAIN_OUTSIDE_DISPLAY_MIN_MAX")
            for issue in issues:
                qc.append({"combo": combo, "module_id": mid, "issue": issue,
                           "main_mA": main, "min_mA": minimum, "max_mA": maximum,
                           "action": "Retain source readings; no inferred or corrected value"})
            branch = {"combo": combo, "module_id": mid, "I_main_mA": main,
                      "I_min_mA": minimum, "I_max_mA": maximum,
                      "T_stm32_C": temperature, "V_module_main_V": D(raw[f"V_module{index}_avg_V"]),
                      "current_source": str((SUPP if extra else path).relative_to(ROOT)).replace("\\", "/"),
                      "current_photo": photo, "current_photo_sha256": sha(ROOT / photo) if photo else "",
                      "I_min_source": "user_confirmation" if row.get("current_min_note", "").startswith("MIN confirmed by user") else ("photo" if photo else "original_YAML"),
                      "I_min_note": row.get("current_min_note", ""),
                      "current_filename_date_batch": batch,
                      "temperature_source": "user_message_via_supplement" if extra else "original_YAML",
                      "voltage_source": path.relative_to(ROOT).as_posix(),
                      "voltage_source_run_id": raw["run_id"],
                      "quality_note": ";".join(issues), "n_records_in_this_condition": 1,
                      "within_condition_repeat_SD_mA": None}
            pair_branches.append(branch)
            branches.append(branch)
        current_sum = sum(b["I_main_mA"] for b in pair_branches)
        prediction = sum(references[mid] for mid in pair)
        source_voltage = D(raw["V_source_avg_V"])
        configs.append({"combo": combo, "module_count": 2, "load": "ZERO", "protocol_mode": "FULL",
                        "configured_frequency_Hz": 200, "module_lower": pair[0], "module_upper": pair[1],
                        "I_lower_main_mA": pair_branches[0]["I_main_mA"],
                        "I_upper_main_mA": pair_branches[1]["I_main_mA"], "I_sum_mA": current_sum,
                        "V_source_main_V": source_voltage, "P_source_output_estimate_mW": source_voltage * current_sum,
                        "power_uses_cross_record_voltage": bool(extra),
                        "simultaneous_branch_sum_measured": False,
                        "T_lower_stm32_C": pair_branches[0]["T_stm32_C"],
                        "T_upper_stm32_C": pair_branches[1]["T_stm32_C"],
                        "T_teensy_C": D(extra[pair[0]]["T_teensy_C"] if extra else raw["T_teensy_C"]),
                        "T_regulator_C": D(extra[pair[0]]["T_regulator_C"] if extra else raw["T_regulator_C"]),
                        "I_N1_prediction_mA": prediction, "prediction_residual_mA": current_sum - prediction,
                        "prediction_residual_percent": (current_sum - prediction) / prediction * 100,
                        "current_filename_date_batch": batch, "n_records_per_configuration": 1,
                        "within_condition_repeat_SD_mA": None})

    metrics = ("I_sum_mA", "P_source_output_estimate_mW", "T_teensy_C", "T_regulator_C", "prediction_residual_percent")
    summary = {"scope": metadata["scope"], "n_combinations": 6, "n_current_records_per_combination": 1,
               "SD_meaning": "Descriptive sample SD across six different configurations, not repeatability SD. Pairs share modules; acquisition batch and configuration effects are confounded.",
               "aggregate": {field: describe((c[field] for c in configs), include_cv=field in metrics[:2]) for field in metrics},
               "by_current_filename_date_batch": {
                   batch: {field: describe((c[field] for c in configs if c["current_filename_date_batch"] == batch), include_cv=field in metrics[:2]) for field in metrics}
                   for batch in ("2026-09-05", "2026-09-07")},
               "N1_ZERO_reference_main_mA": references,
               "module_branch_ranges_mA": {
                   mid: {"minimum": min(b["I_main_mA"] for b in branches if b["module_id"] == mid),
                         "maximum": max(b["I_main_mA"] for b in branches if b["module_id"] == mid),
                         "n_partner_configurations": 3}
                   for mid in references},
               "module_temperature_range_C": [min(b["T_stm32_C"] for b in branches), max(b["T_stm32_C"] for b in branches)],
               "current_main_coverage": "6/6 combinations; 12/12 branches",
               "current_MIN_MAX_coverage": f"{sum(b['I_min_mA'] is not None and b['I_max_mA'] is not None for b in branches)}/{len(branches)} branches; includes user-confirmed values where documented",
               "user_confirmed_current_values": metadata.get("user_confirmed_current_values", []),
               "quality_issues": qc,
               "limitations": metadata["known_limitations"]}
    return configs, branches, summary, sources


def write_readme(configs, summary):
    lines = ["# N=2 空载电流与温度补充统计（2026-09-07）", "",
             "FULL、配置200 Hz、持续USB接收。按模块编号升序读取新增8张电流照片，并采用用户最新温度数值。",
             "原有M0+M1、M2+M3与新增四组合合计覆盖6/6。每组合一组电流记录，电压/电流分次补测不计为重复实验。", "",
             "## 各组合结果", "",
             "| 组合 | 较小编号模块 / mA | 较大编号模块 / mA | 分支合计 / mA | 源端电压 / V | 输出侧功率估计 / mW | 相对N=1预测偏差 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for c in configs:
        lines.append(f"| {c['combo']} | {c['I_lower_main_mA']:.3f} | {c['I_upper_main_mA']:.3f} | {c['I_sum_mA']:.3f} | {c['V_source_main_V']:.3f} | {c['P_source_output_estimate_mW']:.3f} | {c['prediction_residual_percent']:.3f}% |")
    lines += ["", "I_sum为两条顺序测量支路的DMM主读数之和；不是同步测得的总电流或经过时间平均的电流。",
              "P_est = V_source × I_sum。四个新增组合使用9月6日照片中的对应源端电压和9月7日电流照片，属于跨记录配置估计，当前测电流时的源端电压未经确认。其余两组合的电压/电流来自同一YAML，也不代表同步采集。功率不含USB供电的Teensy和稳压器损耗。", "",
              "## 温度 / °C", "", "| 组合 | 较小编号模块STM32 | 较大编号模块STM32 | Teensy | Regulator |", "|---|---:|---:|---:|---:|"]
    for c in configs:
        lines.append(f"| {c['combo']} | {c['T_lower_stm32_C']:.1f} | {c['T_upper_stm32_C']:.1f} | {c['T_teensy_C']:.1f} | {c['T_regulator_C']:.1f} |")
    a = summary["aggregate"]
    lines += ["", "## 描述性汇总", ""]
    for key, name, unit in [("I_sum_mA", "分支合计电流", "mA"), ("P_source_output_estimate_mW", "输出侧功率估计", "mW"), ("T_teensy_C", "Teensy温度", "°C"), ("T_regulator_C", "Regulator温度", "°C")]:
        s = a[key]
        lines.append(f"- {name}：{s['mean']:.3f} ± {s['sample_SD']:.3f} {unit}；范围{s['minimum']:.3f}–{s['maximum']:.3f} {unit}。")
    lines += [f"- 合计电流CV：{a['I_sum_mA']['CV_percent']:.3f}%。", "",
              "上述±是6种不同组合之间的样本SD（分母n−1），n_combination=6；每组合n_record=1，重复测量SD仍不可计算。模块被多个组合共享，不是6次独立硬件重复。两批采集日期与组合选择混杂，不能把全部差异归因于模块组合。summary.json同时保留9月5日两组合与9月7日四组合的分批统计；日期仅来自照片文件名，不当作正式测量起止时间。", "",
              "## 对P-H1的意义", "",
              "预测为对应模块在N=1 ZERO下独立记录的支路电流之和；偏差=(N=2合计−N=1预测)/N=1预测。",
              f"六组合偏差范围为{a['prediction_residual_percent']['minimum']:.3f}%至{a['prediction_residual_percent']['maximum']:.3f}%。这扩大了两模块组合覆盖，支持所测条件下近似可加的描述性核验；不能由此证明普遍线性、重复性或最大供电容量。", "",
              "## 质量记录与范围", "",
              "- M0-M3的M3：用户于2026-09-07补充确认MIN为17.89 mA；主读数17.922 mA、MAX 18.05 mA不变。照片中的MIN仍被反光遮挡，因此该字段来源标为用户确认。至此12/12支路均有主读数/MIN/MAX数值；电流合计和功率估计不受此次MIN补录影响。",
              "- 旧M0-M1的M1：主读数18.055 mA低于显示MIN 18.06 mA，差0.005 mA。按原记录保留并标记，不修正或视为SD。",
              "- 温度为点读数；没有环境温度、温升曲线或经过核实的稳定时间，不能据此声称达到热稳态。",
              "- 这次补齐的是N=2 ZERO的电流主读数、温度和配置功率估计。新增四组合MAX记录及同条件独立重复并未增加。",
              "- 原始照片、25条连续传输YAML、已发布main 2.1及其冻结分析均保留；新增数据通过独立补充表按组合关联，避免把早期电压记录改写成同时测得的完整记录。", "",
              "## 文件与复现", "",
              "- 原始转录：`../../../../../../raw/canonical/power_experiment_records/current_temperature_supplements/n2_zero_20260907.csv`；同目录metadata说明温度来源、模块对应及缺失信息。",
              "- `configuration_summary.csv`：6个组合；`branch_readings.csv`：12个支路及照片来源。",
              "- `summary.json`：总体/分批统计与QC；`source_manifest.json`：全部分析来源SHA256。",
              "- 从Power目录执行：`python script/Main/summarize_n2_zero_20260907.py`。", ""]
    (OUT / "README_CN.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    protected = list(BASE.rglob("*.yaml")) + list(BASE.rglob("*.jpg")) + list((ROOT / "DATA/reference/analysis_v2_1").rglob("*"))
    protected += [ROOT.parent / "main 2.1.pdf", ROOT / "DATA/raw/canonical/power_raw.csv"]
    before = {p: sha(p) for p in protected if p.is_file()}
    configs, branches, summary, sources = build()
    OUT.mkdir(parents=True, exist_ok=True)
    dump_csv(OUT / "configuration_summary.csv", configs)
    dump_csv(OUT / "branch_readings.csv", branches)
    dump_json(OUT / "summary.json", summary)
    dump_json(OUT / "source_manifest.json", {"schema_version": 1,
              "analysis_script": {"path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": sha(Path(__file__))},
              "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in sorted(sources)],
              "protected_existing_file_count": len(before),
              "published_main_2_1_sha256": sha(ROOT.parent / "main 2.1.pdf")})
    write_readme(configs, summary)
    if any(sha(p) != digest for p, digest in before.items()):
        raise RuntimeError("Protected input unexpectedly changed")
    print(json.dumps({"configurations": len(configs), "branches": len(branches),
                      "aggregate": summary["aggregate"], "QC": summary["quality_issues"],
                      "protected_unchanged": len(before)}, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
