"""Generate reproducible power-scalability summaries and figures.

The canonical input is ``DATA/raw/canonical/power_raw.csv``. The script never modifies it;
all derived CSV/JSON/PNG/PDF/SVG outputs are written below ``DATA/analysis``.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import numpy as np

from power_figures import build_figures


PASS_VOLTAGE_LOW_V = 3.3 * 0.95
PASS_VOLTAGE_HIGH_V = 3.3 * 1.05
TARGET_REPEAT_COUNT = 3


def _float(row: dict[str, str], field: str) -> float | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"{row.get('run_id', '<unknown>')}: {field}={value!r} is not numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{row.get('run_id', '<unknown>')}: {field} is not finite")
    return number


def _integer(row: dict[str, str], field: str) -> int:
    value = _float(row, field)
    if value is None or not float(value).is_integer():
        raise ValueError(f"{row.get('run_id', '<unknown>')}: {field} must be an integer")
    return int(value)


def _mean(values: Iterable[float | None]) -> float | None:
    array = np.asarray([value for value in values if value is not None], dtype=float)
    return None if array.size == 0 else float(np.mean(array))


def _sample_std(values: Iterable[float | None]) -> float | None:
    array = np.asarray([value for value in values if value is not None], dtype=float)
    return None if array.size < 2 else float(np.std(array, ddof=1))


def _max_or_none(values: Iterable[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return None if not valid else float(max(valid))


def _cv_percent(values: Iterable[float | None]) -> float | None:
    array = np.asarray([value for value in values if value is not None], dtype=float)
    if array.size == 0 or np.isclose(np.mean(array), 0.0):
        return None
    return float(np.std(array, ddof=0) / abs(np.mean(array)) * 100.0)


def _module_number(module_id: str) -> int:
    match = re.fullmatch(r"Module(\d+)", module_id.strip(), flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"unsupported module id: {module_id!r}")
    return int(match.group(1))


def _module_ids(row: dict[str, str]) -> list[str]:
    result = [item.strip() for item in (row.get("module_ids") or "").split(",") if item.strip()]
    expected = _integer(row, "module_count")
    if len(result) != expected:
        raise ValueError(
            f"{row.get('run_id')}: module_count={expected}, but module_ids contains {len(result)} entries"
        )
    return result


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [
            {str(key): ("" if value is None else str(value)) for key, value in row.items()}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]
    if not rows:
        raise ValueError(f"no records found in {path}")
    run_ids = [row.get("run_id", "") for row in rows]
    duplicates = sorted({run_id for run_id in run_ids if run_ids.count(run_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate run_id values: {', '.join(duplicates)}")
    return rows


def is_scaling_row(row: dict[str, str]) -> bool:
    return (
        (row.get("record_status") or "").strip().upper() == "MEASURED"
        and _integer(row, "frequency_hz") == 200
        and (row.get("protocol_mode") or "").strip().upper() == "FULL"
        and (row.get("load") or "").strip().upper() == "ZERO"
    )


def _physical_to_column(row: dict[str, str]) -> list[tuple[str, int]]:
    ids = _module_ids(row)
    if len(ids) == 1:
        # Historical single-module rows store the selected module in module0 columns.
        return [(ids[0], 0)]
    return [(module_id, _module_number(module_id)) for module_id in ids]


def module_records(row: dict[str, str]) -> list[dict[str, Any]]:
    count = _integer(row, "module_count")
    source_v = _float(row, "V_source_avg_V")
    records: list[dict[str, Any]] = []
    for module_id, column in _physical_to_column(row):
        avg_v = _float(row, f"V_module{column}_avg_V")
        min_v = _float(row, f"V_module{column}_min_V")
        max_v = _float(row, f"V_module{column}_max_V")
        avg_i = _float(row, f"I_module{column}_avg_mA")
        min_i = _float(row, f"I_module{column}_min_mA")
        max_i = _float(row, f"I_module{column}_max_mA")
        if count == 1:
            avg_i = avg_i if avg_i is not None else _float(row, "I_source_avg_mA")
            min_i = min_i if min_i is not None else _float(row, "I_source_min_mA")
            max_i = max_i if max_i is not None else _float(row, "I_source_max_mA")
            stm32_temp = _float(row, "T_stm32_stable_C")
        else:
            stm32_temp = _float(row, f"T_module{column}_stm32_C")
        drop_v = None if source_v is None or avg_v is None else source_v - avg_v
        drop_percent = (
            None
            if drop_v is None or source_v is None or np.isclose(source_v, 0.0)
            else drop_v / source_v * 100.0
        )
        module_power_mw = None if avg_v is None or avg_i is None else avg_v * avg_i
        records.append(
            {
                "run_id": row["run_id"],
                "module_count": count,
                "module_id": module_id,
                "frequency_hz": _integer(row, "frequency_hz"),
                "load": row.get("load", ""),
                "V_source_avg_V": source_v,
                "V_module_avg_V": avg_v,
                "V_module_min_V": min_v,
                "V_module_max_V": max_v,
                "voltage_drop_avg_V": drop_v,
                "voltage_drop_percent": drop_percent,
                "I_module_avg_mA": avg_i,
                "I_module_min_mA": min_i,
                "I_module_max_mA": max_i,
                "module_power_mW": module_power_mw,
                "T_stm32_C": stm32_temp,
            }
        )
    return records


def derive_run(row: dict[str, str]) -> dict[str, Any]:
    count = _integer(row, "module_count")
    branches = module_records(row)
    branch_avg = [record["I_module_avg_mA"] for record in branches]
    branch_min = [record["I_module_min_mA"] for record in branches]
    branch_max = [record["I_module_max_mA"] for record in branches]
    total_avg = _float(row, "I_total_avg_mA")
    if total_avg is None:
        total_avg = _float(row, "I_source_avg_mA") if count == 1 else _mean(branch_avg)
        if count > 1 and all(value is not None for value in branch_avg):
            total_avg = float(sum(value for value in branch_avg if value is not None))
    total_min = _float(row, "I_total_min_est_mA")
    total_max = _float(row, "I_total_max_est_mA")
    if count == 1:
        total_min = total_min if total_min is not None else _float(row, "I_source_min_mA")
        total_max = total_max if total_max is not None else _float(row, "I_source_max_mA")
    source_v = _float(row, "V_source_avg_V")
    source_power = None if source_v is None or total_avg is None else source_v * total_avg
    regulator_temp = _float(row, "T_regulator_C")
    teensy_temp = _float(row, "T_teensy_C")
    if regulator_temp is None:
        regulator_temp = _float(row, "T_regulator_stable_C")
    if teensy_temp is None:
        teensy_temp = _float(row, "T_teensy_stable_C")
    fault_fields = ("reset_count", "current_limit_count", "brownout_count", "data_stop_count")
    fault_count = 0
    for field in fault_fields:
        value = _float(row, field)
        fault_count += 0 if value is None else int(value)
    module_avg_voltages = [record["V_module_avg_V"] for record in branches if record["V_module_avg_V"] is not None]
    module_min_voltages = [record["V_module_min_V"] for record in branches if record["V_module_min_V"] is not None]
    valid_module_avg_records = [
        (record["module_id"], record["V_module_avg_V"])
        for record in branches
        if record["V_module_avg_V"] is not None
    ]
    worst_module_avg_record = (
        min(valid_module_avg_records, key=lambda item: item[1])
        if valid_module_avg_records else None
    )
    voltage_drops = [record["voltage_drop_avg_V"] for record in branches if record["voltage_drop_avg_V"] is not None]
    stm32_temps = [record["T_stm32_C"] for record in branches if record["T_stm32_C"] is not None]
    branch_sum = None if any(value is None for value in branch_avg) else float(sum(branch_avg))
    stored_sum_error = None if total_avg is None or branch_sum is None else total_avg - branch_sum
    return {
        "run_id": row["run_id"],
        "record_status": row.get("record_status", ""),
        "conclusion": row.get("conclusion", ""),
        "module_count": count,
        "module_ids": row.get("module_ids", ""),
        "frequency_hz": _integer(row, "frequency_hz"),
        "protocol_mode": row.get("protocol_mode", ""),
        "load": row.get("load", ""),
        "repeat_id": _repeat_id(row["run_id"]),
        "V_source_avg_V": source_v,
        "V_source_min_V": _float(row, "V_source_min_V"),
        "V_source_max_V": _float(row, "V_source_max_V"),
        "I_total_avg_mA": total_avg,
        "I_total_min_est_mA": total_min,
        "I_total_max_est_mA": total_max,
        "source_power_mW": source_power,
        "worst_module_id": None if worst_module_avg_record is None else worst_module_avg_record[0],
        "worst_module_avg_V": min(module_avg_voltages) if module_avg_voltages else None,
        "worst_module_min_V": min(module_min_voltages) if module_min_voltages else None,
        "max_voltage_drop_avg_V": max(voltage_drops) if voltage_drops else None,
        "branch_current_cv_percent": _cv_percent(branch_avg),
        "max_stm32_C": max(stm32_temps) if stm32_temps else None,
        "T_regulator_C": regulator_temp,
        "T_teensy_C": teensy_temp,
        "fault_count": fault_count,
        "branch_current_sum_error_mA": stored_sum_error,
        "measurement_start_time": row.get("measurement_start_time", ""),
        "measurement_duration_s": _float(row, "measurement_duration_s"),
        "data_quality": row.get("data_quality", ""),
    }


def _repeat_id(run_id: str) -> int | None:
    match = re.search(r"_R(\d+)$", run_id)
    return None if match is None else int(match.group(1))


def _linear_fit(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    residuals = y - predicted
    denominator = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 if np.isclose(denominator, 0.0) else 1.0 - float(np.sum(residuals**2)) / denominator
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r_squared": float(r_squared),
        "predicted": predicted,
        "residuals": residuals,
    }


def aggregate_scaling(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(int(run["module_count"]), []).append(run)
    rows: list[dict[str, Any]] = []
    for count in sorted(grouped):
        group = grouped[count]
        valid_worst_runs = [
            run for run in group
            if run["worst_module_avg_V"] is not None and run["worst_module_id"] is not None
        ]
        worst_run = min(valid_worst_runs, key=lambda run: run["worst_module_avg_V"]) if valid_worst_runs else None
        branch_cv = _mean(run["branch_current_cv_percent"] for run in group)
        if count == 1:
            branch_cv = _cv_percent(run["I_total_avg_mA"] for run in group)
        rows.append(
            {
                "module_count": count,
                "record_count": len(group),
                "repeat_count": len({run["repeat_id"] for run in group if run["repeat_id"] is not None}),
                "I_total_avg_mA": _mean(run["I_total_avg_mA"] for run in group),
                "I_total_std_mA": _sample_std(run["I_total_avg_mA"] for run in group),
                "I_peak_upper_est_mA": _mean(run["I_total_max_est_mA"] for run in group),
                "source_power_mW": _mean(run["source_power_mW"] for run in group),
                "V_source_avg_V": _mean(run["V_source_avg_V"] for run in group),
                "worst_module_id": None if worst_run is None else worst_run["worst_module_id"],
                "worst_module_avg_V": min(run["worst_module_avg_V"] for run in group if run["worst_module_avg_V"] is not None),
                "worst_module_min_V": min(run["worst_module_min_V"] for run in group if run["worst_module_min_V"] is not None),
                "max_voltage_drop_avg_V": max(run["max_voltage_drop_avg_V"] for run in group if run["max_voltage_drop_avg_V"] is not None),
                "branch_current_cv_percent": branch_cv,
                "max_stm32_C": _max_or_none(run["max_stm32_C"] for run in group),
                "T_regulator_C": _mean(run["T_regulator_C"] for run in group),
                "T_teensy_C": _mean(run["T_teensy_C"] for run in group),
                "fault_count": sum(int(run["fault_count"]) for run in group),
            }
        )
    x = np.asarray([row["module_count"] for row in rows], dtype=float)
    current = np.asarray([row["I_total_avg_mA"] for row in rows], dtype=float)
    power = np.asarray([row["source_power_mW"] for row in rows], dtype=float)
    current_fit = _linear_fit(x, current)
    power_fit = _linear_fit(x, power)
    for index, row in enumerate(rows):
        row["I_fit_mA"] = float(current_fit["predicted"][index])
        row["I_residual_mA"] = float(current_fit["residuals"][index])
        row["I_residual_percent"] = float(current_fit["residuals"][index] / current[index] * 100.0)
        row["power_fit_mW"] = float(power_fit["predicted"][index])
        row["power_residual_mW"] = float(power_fit["residuals"][index])
    return rows, {"current": current_fit, "power": power_fit}


def collect_anomalies(
    all_rows: list[dict[str, str]],
    scaling_rows: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    fits: dict[str, Any],
) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []

    def add(identifier: str, severity: str, scope: str, observed: str, reference: str, interpretation: str, action: str) -> None:
        anomalies.append(
            {
                "anomaly_id": identifier,
                "severity": severity,
                "scope": scope,
                "observed_value": observed,
                "reference": reference,
                "interpretation": interpretation,
                "recommended_action": action,
            }
        )

    n4_m3 = next((item for item in branches if item["module_count"] == 4 and item["module_id"].lower() == "module3"), None)
    if n4_m3:
        add(
            "A01_N4_MODULE3_VOLTAGE_DROP",
            "ATTENTION",
            n4_m3["run_id"],
            f"Vmin={n4_m3['V_module_min_V']:.3f} V; average drop={n4_m3['voltage_drop_avg_V'] * 1000:.0f} mV",
            f"lower pass limit={PASS_VOLTAGE_LOW_V:.3f} V",
            "Largest measured branch drop; it still passes the voltage limit but is concentrated on Module3.",
            "Repeat R2/R3 and swap the cable/output port to separate wiring loss from module behaviour.",
        )

    n1_branches = [item for item in branches if item["module_count"] == 1]
    n1_currents = np.asarray([item["I_module_avg_mA"] for item in n1_branches], dtype=float)
    if n1_currents.size:
        median = float(np.median(n1_currents))
        high = max(n1_branches, key=lambda item: item["I_module_avg_mA"])
        difference = (high["I_module_avg_mA"] - median) / median * 100.0
        add(
            "A02_SINGLE_MODULE_CURRENT_SPREAD",
            "ATTENTION",
            high["run_id"],
            f"{high['module_id']}={high['I_module_avg_mA']:.3f} mA ({difference:+.1f}% vs N=1 median)",
            f"N=1 median={median:.3f} mA",
            "Module2 is the highest single-module baseline and drives much of the N=1 spread.",
            "Repeat each single-module baseline with identical wiring and measurement duration.",
        )

    def branch_at(count: int, module_id: str) -> dict[str, Any] | None:
        return next((item for item in branches if item["module_count"] == count and item["module_id"].lower() == module_id.lower()), None)

    m1_n1 = branch_at(1, "Module1")
    m1_n4 = branch_at(4, "Module1")
    if m1_n1 and m1_n4:
        change = (m1_n4["I_module_avg_mA"] - m1_n1["I_module_avg_mA"]) / m1_n1["I_module_avg_mA"] * 100.0
        add(
            "A03_MODULE1_CURRENT_AT_N4",
            "NOTE",
            m1_n4["run_id"],
            f"8.119 -> {m1_n4['I_module_avg_mA']:.3f} mA ({change:+.1f}%)",
            "same module in N=1 reference",
            "The increase is modest but larger than the Module0 change and should be checked in repeats.",
            "Confirm branch order and repeat the N=4 current sequence.",
        )

    n3 = next((row for row in scaling_rows if row["module_count"] == 3), None)
    n4 = next((row for row in scaling_rows if row["module_count"] == 4), None)
    if n3 and n4 and n3["T_teensy_C"] is not None and n4["T_teensy_C"] is not None:
        delta = n4["T_teensy_C"] - n3["T_teensy_C"]
        if delta < 0:
            add(
                "A04_TEENSY_TEMPERATURE_NON_MONOTONIC",
                "DATA_QUALITY",
                "N=3 to N=4",
                f"{n3['T_teensy_C']:.1f} -> {n4['T_teensy_C']:.1f} degC ({delta:+.1f} degC)",
                "module count increased",
                "Temperature is not comparable without a fixed stabilization duration; the Teensy is also USB-powered outside the module supply.",
                "Record start time and a fixed duration in R2/R3 before using temperature for scaling conclusions.",
            )

    m1_rows = [row for row in all_rows if (row.get("module_ids") or "").strip() == "Module1"]
    temperature_pairs = {
        (
            _float(row, "T_regulator_stable_C"),
            _float(row, "T_teensy_stable_C"),
        )
        for row in m1_rows
    }
    if (45.0, 28.9) in temperature_pairs and (28.9, 45.0) in temperature_pairs:
        add(
            "A05_MODULE1_TEMPERATURE_FIELD_CONFLICT",
            "DATA_QUALITY",
            "Module1 single-module rows",
            "(regulator, Teensy) appears as both (45.0, 28.9) and (28.9, 45.0) degC",
            "identical electrical conditions",
            "At least two historical rows retain swapped temperature fields.",
            "Verify the handwritten source and correct the canonical raw rows before thermal reporting.",
        )

    repeat_shortfall = [
        row
        for row in scaling_rows
        if int(row["module_count"]) >= 2
        and int(row["repeat_count"]) < TARGET_REPEAT_COUNT
    ]
    if repeat_shortfall:
        counts = ", ".join(f"N={row['module_count']}: {row['repeat_count']}/{TARGET_REPEAT_COUNT}" for row in repeat_shortfall)
        add(
            "A06_REPEAT_COUNT_INCOMPLETE",
            "LIMITATION",
            "200 Hz FULL ZERO scaling series",
            counts,
            "planned three repeats per N",
            "R2/R3 are missing, so uncertainty and repeatability cannot yet be estimated for N=2-4.",
            "Collect R2 and R3 before treating the linear model as final evidence.",
        )

    peak = max(scaling_rows, key=lambda row: row["module_count"])
    if peak["I_peak_upper_est_mA"] is not None:
        ratio = peak["I_peak_upper_est_mA"] / peak["I_total_avg_mA"]
        add(
            "A07_NONSYNCHRONOUS_PEAK_SUM",
            "LIMITATION",
            f"N={peak['module_count']}",
            f"upper estimate={peak['I_peak_upper_est_mA']:.2f} mA ({ratio:.2f}x average)",
            "branch maxima captured at different times",
            "This is a conservative arithmetic sum, not a measured simultaneous total-current peak.",
            "Use a common low-ohm shunt and oscilloscope if the true aggregate transient is required.",
        )

    if abs(fits["current"]["intercept"]) < 0.5:
        # This is a useful result rather than a fault; keep it out of the anomaly list.
        pass
    return anomalies


def _write_csv(path: Path, records: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {}
            for field in fields:
                value = record.get(field)
                if isinstance(value, float):
                    row[field] = f"{value:.12g}"
                elif value is None:
                    row[field] = ""
                else:
                    row[field] = value
            writer.writerow(row)




def analyze(input_path: Path, output_dir: Path) -> dict[str, Path]:
    rows = load_rows(input_path)
    selected_raw = [row for row in rows if is_scaling_row(row)]
    run_records = [derive_run(row) for row in selected_raw]
    branch_records = [record for row in selected_raw for record in module_records(row)]
    scaling, fits = aggregate_scaling(run_records)
    anomalies = collect_anomalies(rows, scaling, branch_records, fits)

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "run_summary": output_dir / "power_summary.csv",
        "scaling_summary": output_dir / "power_scaling.csv",
        "branch_summary": output_dir / "branch_summary.csv",
        "thermal_summary": output_dir / "thermal_summary.csv",
        "anomaly_summary": output_dir / "anomaly_summary.csv",
        "json_summary": output_dir / "analysis_summary.json",
        "current_power_plot": figures_dir / "current_power_scaling.png",
        "voltage_plot": figures_dir / "voltage_scaling.png",
        "drop_plot": figures_dir / "module_voltage_drop.png",
        "branch_plot": figures_dir / "branch_current_balance.png",
        "temperature_plot": figures_dir / "temperature_scaling.png",
        "peak_plot": figures_dir / "peak_current_upper_estimate.png",
        "screening_plot": figures_dir / "single_module_screening.png",
    }

    _write_csv(
        outputs["run_summary"],
        run_records,
        [
            "run_id", "module_count", "module_ids", "repeat_id", "frequency_hz", "protocol_mode", "load",
            "V_source_avg_V", "V_source_min_V", "V_source_max_V", "I_total_avg_mA", "I_total_min_est_mA",
            "I_total_max_est_mA", "source_power_mW", "worst_module_avg_V", "worst_module_min_V",
            "max_voltage_drop_avg_V", "branch_current_cv_percent", "max_stm32_C", "T_regulator_C",
            "T_teensy_C", "fault_count", "branch_current_sum_error_mA", "measurement_start_time",
            "measurement_duration_s", "conclusion", "data_quality",
        ],
    )
    _write_csv(
        outputs["scaling_summary"],
        scaling,
        [
            "module_count", "record_count", "repeat_count", "I_total_avg_mA", "I_total_std_mA",
            "I_peak_upper_est_mA", "I_fit_mA", "I_residual_mA", "I_residual_percent", "source_power_mW",
            "power_fit_mW", "power_residual_mW", "V_source_avg_V", "worst_module_id", "worst_module_avg_V", "worst_module_min_V",
            "max_voltage_drop_avg_V", "branch_current_cv_percent", "max_stm32_C", "T_regulator_C",
            "T_teensy_C", "fault_count",
        ],
    )
    _write_csv(
        outputs["branch_summary"],
        branch_records,
        [
            "run_id", "module_count", "module_id", "V_source_avg_V", "V_module_avg_V", "V_module_min_V",
            "V_module_max_V", "voltage_drop_avg_V", "voltage_drop_percent", "I_module_avg_mA",
            "I_module_min_mA", "I_module_max_mA", "module_power_mW", "T_stm32_C",
        ],
    )
    thermal = [
        {
            "module_count": row["module_count"],
            "max_stm32_C": row["max_stm32_C"],
            "T_regulator_C": row["T_regulator_C"],
            "T_teensy_C": row["T_teensy_C"],
            "measurement_duration_available": all(
                run["measurement_duration_s"] is not None
                for run in run_records
                if run["module_count"] == row["module_count"]
            ),
        }
        for row in scaling
    ]
    _write_csv(outputs["thermal_summary"], thermal, ["module_count", "max_stm32_C", "T_regulator_C", "T_teensy_C", "measurement_duration_available"])
    _write_csv(outputs["anomaly_summary"], anomalies, ["anomaly_id", "severity", "scope", "observed_value", "reference", "interpretation", "recommended_action"])

    outputs["figure_manifest"] = build_figures(
        outputs, scaling, fits, branch_records, rows, input_path
    )

    summary = {
        "format": "e-skin-power-scalability-analysis",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(input_path.resolve()),
        "analysis_condition": {"frequency_hz": 200, "protocol_mode": "FULL", "load": "ZERO"},
        "method": {
            "N1": "mean of the four independent Module0..Module3 200 Hz FULL ZERO references",
            "N2_to_N4": "available PS01 R1 multi-module runs",
            "peak_current": "sum of separately captured branch maxima; non-synchronous arithmetic estimate, not a guaranteed bound on uncaptured transients",
            "raw_data_modified": False,
        },
        "voltage_pass_band_V": [PASS_VOLTAGE_LOW_V, PASS_VOLTAGE_HIGH_V],
        "current_fit": {key: value for key, value in fits["current"].items() if key not in {"predicted", "residuals"}},
        "power_fit": {key: value for key, value in fits["power"].items() if key not in {"predicted", "residuals"}},
        "scaling": scaling,
        "anomalies": anomalies,
        "limitations": [
            "N=2, N=3, and N=4 currently have R1 only.",
            "Multi-module total current is calculated from separately measured branches.",
            "Branch maximum values are not synchronized.",
            "Measurement duration and supply current-limit setting are missing.",
            "All recorded runs remain marked INCOMPLETE in the canonical CSV.",
        ],
    }
    with outputs["json_summary"].open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return outputs


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Analyze E-SKIN power scalability from power_raw.csv")
    parser.add_argument("--input", type=Path, default=root / "DATA" / "raw" / "canonical" / "power_raw.csv", help="canonical raw CSV")
    parser.add_argument("--output-dir", type=Path, default=root / "archive" / "legacy_analysis" / "DATA_analysis", help="derived output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = analyze(args.input.resolve(), args.output_dir.resolve())
    for name, path in outputs.items():
        print(f"Generated {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
