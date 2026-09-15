"""Add reproducibility metadata to existing data-scalability runs.

This migration is intentionally kept in the project so archived runs can be
rechecked after a folder reorganisation.  It infers active modules from the
per-MUL ``updated_mask``/``algorithms`` fields and uses the folder naming rule
as a fallback.  Existing Delta runs are manually labelled as zero-load, as
requested for the current archive.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_ROOT = SCRIPT_DIR.parent / "data"
MODULE_RE = re.compile(r"M\d+")
RATE_RE = re.compile(r"^(\d+)Hz$")
N_RE = re.compile(r"^N=(\d+)$")


def module_ids_from_packet_log(path: Path) -> set[str]:
    module_ids: set[str] = set()
    if not path.is_file():
        return module_ids

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            mask_text = (row.get("updated_mask") or "").strip()
            try:
                mask = int(mask_text, 0) if mask_text else 0
            except ValueError:
                mask = 0
            for module_id in range(8):
                if mask & (1 << module_id):
                    module_ids.add(f"M{module_id}")

            for module_id, algorithm in enumerate(
                (row.get("algorithms") or "").split(",")
            ):
                if algorithm.strip().startswith("DELTA"):
                    module_ids.add(f"M{module_id}")
    return module_ids


def infer_condition(summary: dict, run_dir: Path) -> tuple[dict, list[str]]:
    relative_parts = run_dir.relative_to(DATA_ROOT).parts
    observed = [str(value) for value in summary.get("observed_algorithms", [])]
    is_delta = relative_parts[:1] == ("DELTA",) or any(
        value.startswith("DELTA") for value in observed
    )
    algorithm = "DELTA" if is_delta else "FULL"

    module_ids = {
        match.group(0)
        for part in relative_parts
        for match in MODULE_RE.finditer(part)
    }
    module_ids.update(module_ids_from_packet_log(run_dir / "packet_log.csv"))
    if not module_ids:
        for part in relative_parts:
            match = N_RE.match(part)
            if match:
                module_ids.update(f"M{index}" for index in range(int(match.group(1))))
                break
    active_modules = sorted(module_ids, key=lambda value: int(value[1:]))

    old_condition = summary.get("test_condition") or {}
    scan_rate = old_condition.get("target_scan_rate_hz")
    if scan_rate is None:
        scan_rate = old_condition.get("scan_rate_hz")
    if scan_rate is None:
        for part in relative_parts:
            match = RATE_RE.match(part)
            if match:
                scan_rate = int(match.group(1))
                break
    if scan_rate is None:
        scan_rate = 200 if is_delta else round(
            float(summary.get("average_packet_rate_Hz", 200))
        )
    scan_rate = int(scan_rate)

    module_count = len(active_modules)
    if module_count == 0:
        module_scope = "no active modules"
    elif module_count == 1:
        module_scope = "single module"
    else:
        module_scope = f"{module_count} modules"

    condition = dict(old_condition)
    condition.update(
        {
            "algorithm": algorithm,
            "target_scan_rate_hz": scan_rate,
            "scan_rate_hz": scan_rate,
            "active_module_ids": active_modules,
            "module_count": module_count,
            "module_scope": module_scope,
        }
    )
    if module_count == 1:
        condition["module_id"] = active_modules[0]
    else:
        condition["module_ids"] = active_modules
    if is_delta:
        condition["load_condition"] = "Zero load"
        condition["load_condition_source"] = "manual"

    frequency_text = "不限速" if scan_rate == 0 else f"{scan_rate} Hz"
    log_lines = [
        f"- 活动模块：{', '.join(active_modules) or '无'}。",
        f"- 模块数量 N：{module_count}。",
        f"- 目标扫描频率：{frequency_text}。",
        f"- 算法：{algorithm}。",
    ]
    if is_delta:
        log_lines.append("- 负载情况：无负载（手动添加；当前记录未采集力值）。")
    return condition, log_lines


def update_log(log_path: Path, condition_lines: list[str], files: dict[str, str]) -> None:
    if not log_path.is_file():
        return

    removable = re.compile(
        r"^- (测试条件|活动模块|模块数量 N|目标扫描频率|算法|负载情况)："
    )
    output_line = re.compile(r"^- (原始数据|逐包记录|机器可读总结)：")
    new_lines: list[str] = []
    inserted_conditions = False
    inserted_outputs = False
    lines = log_path.read_text(encoding="utf-8-sig").splitlines()
    for line in lines:
        if removable.match(line) or output_line.match(line):
            continue
        new_lines.append(line)
        if line.startswith("- 端口：") and not inserted_conditions:
            new_lines.extend(condition_lines)
            inserted_conditions = True
        if line == "## 输出文件" and not inserted_outputs:
            new_lines.extend(
                [
                    "",
                    f"- 原始数据：`{files['raw_usb']}`",
                    f"- 逐包记录：`{files['packet_log']}`",
                    f"- 机器可读总结：`{files['summary']}`",
                ]
            )
            inserted_outputs = True

    if not inserted_conditions:
        new_lines.extend(["", "## 实验条件", "", *condition_lines])
    if not inserted_outputs:
        new_lines.extend(
            [
                "",
                "## 输出文件",
                "",
                f"- 原始数据：`{files['raw_usb']}`",
                f"- 逐包记录：`{files['packet_log']}`",
                f"- 机器可读总结：`{files['summary']}`",
            ]
        )
    log_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def migrate() -> int:
    summary_files = sorted(DATA_ROOT.rglob("summary.json"))
    for summary_path in summary_files:
        run_dir = summary_path.parent
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        condition, condition_lines = infer_condition(summary, run_dir)
        summary["test_condition"] = condition

        files = dict(summary.get("files") or {})
        files.update(
            {
                "raw_usb": str(run_dir / "mul1_raw.bin"),
                "packet_log": str(run_dir / "packet_log.csv"),
                "summary": str(summary_path),
                "experiment_log": str(run_dir / "experiment_log.md"),
            }
        )
        summary["files"] = files
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        update_log(run_dir / "experiment_log.md", condition_lines, files)

    print(f"Updated metadata for {len(summary_files)} existing experiment(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(migrate())
