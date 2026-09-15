"""Read-only, whole-stream review of recorded MUL1 v2 / ESK v4 experiments.

Only files below this script's directory are written. Acquisition dates come
from summary.started_at, never filesystem timestamps. Python standard library.
The default input is the pre-variable-SPI history; --data-root overrides it.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import statistics
import struct
import sys
import zlib

OUTPUT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = OUTPUT.parents[1] / "history" / "pre_variable_spi_20260906" / "data"
DATA = DEFAULT_DATA_ROOT
REFERENCE_DATE = "2026-09-05"
MAX_RAW_BYTES = 64 * 1024 * 1024


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def csv_write(path, records):
    if not records:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(dict.fromkeys(key for row in records for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False)
                             if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def repeat_sd(values):
    values = [v for v in values if v is not None]
    return statistics.stdev(values) if len(values) > 1 else None


def histogram_stats(hist):
    n = sum(hist.values())
    if not n:
        return {"n": 0, "mean": None, "sd_population": None,
                "p05": None, "p25": None, "median": None,
                "p75": None, "p95": None, "min": None, "max": None,
                "zero_fraction": None}
    total = sum(k * count for k, count in hist.items())
    mu = total / n
    def order(index):
        cumulative = 0
        for value, count in sorted(hist.items()):
            cumulative += count
            if index < cumulative:
                return value
        raise AssertionError("histogram order out of range")
    def quantile(p):
        x = (n - 1) * p
        lo, hi = math.floor(x), math.ceil(x)
        return order(lo) + (order(hi) - order(lo)) * (x - lo)
    return {"n": n, "mean": mu,
            "sd_population": math.sqrt(sum(c * (k - mu) ** 2
                                             for k, c in hist.items()) / n),
            "p05": quantile(.05), "p25": quantile(.25),
            "median": quantile(.5), "p75": quantile(.75),
            "p95": quantile(.95), "min": min(hist), "max": max(hist),
            "zero_fraction": hist.get(0, 0) / n}


def module_state():
    return {"counts": Counter(), "k": Counter(), "k1": Counter(),
            "k2": Counter(), "flags": Counter(), "full_times": [],
            "last_wire_seq": None, "last_applied_seq": None,
            "anchored": False, "chain_valid": False, "chain": Counter(),
            "payload_bytes": 0}


def load_category(path, condition):
    parts = set(path.parts)
    if "Zero_load" in parts:
        return "zero_load", "directory_and_metadata"
    for part, label in (("Small_area_3x1.6cm", "small_area_3x1.6cm"),
                        ("Large_area", "large_area"),
                        ("High_frequency_rolling", "rolling"),
                        ("Full_coverage_all_FSR", "full_area_simultaneous")):
        if part in parts:
            return label, "directory_and_metadata"
    return condition.get("load_condition", "load_not_recorded"), "metadata_or_missing"


def require_legacy_summary(summary, path):
    if int(summary.get("schema_version", 1)) >= 2:
        raise ValueError(
            f"Unsupported summary schema_version >= 2: {path}. "
            "New recordings require scopes.main statistics and explicit run selection; "
            "this historical review cannot analyse them using the old summary fields."
        )


def inspect_run(summary_path):
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    require_legacy_summary(summary, summary_path)
    folder = summary_path.parent
    started = datetime.fromisoformat(summary["started_at"])
    date = started.date().isoformat()  # preserve acquisition's recorded offset
    bucket = "yesterday_2026-09-05" if date == REFERENCE_DATE else (
        "before_2026-09-05" if date < REFERENCE_DATE else "other_date")
    condition = summary.get("test_condition", {})
    load, load_source = load_category(folder, condition)
    issues = Counter()
    examples = []
    def issue(code, detail=""):
        issues[code] += 1
        if len(examples) < 12:
            examples.append({"code": code, "detail": str(detail)[:160]})
    run_id = str(summary["run_id"])
    if not re.fullmatch(r"\d{8}_\d{6}", run_id):
        raise ValueError("Unsafe or unsupported run_id format")
    if run_id[:8] != started.strftime("%Y%m%d"):
        issue("run_id_date_mismatch")
    raw_path, log_path = folder / "mul1_raw.bin", folder / "packet_log.csv"
    for file in (summary_path, raw_path, log_path, folder / "experiment_log.md"):
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(DATA):
            raise ValueError(f"Not a regular in-root experiment file: {file}")
    if raw_path.stat().st_size > MAX_RAW_BYTES:
        raise ValueError("Run exceeds the reviewed 64 MiB input cap")
    if run_id not in (folder / "experiment_log.md").read_text(encoding="utf-8-sig"):
        issue("experiment_log_run_id_missing")
    for key, name in (("raw_usb", "mul1_raw.bin"), ("packet_log", "packet_log.csv"),
                      ("summary", "summary.json"), ("experiment_log", "experiment_log.md")):
        recorded = summary.get("files", {}).get(key)
        if recorded and Path(recorded).resolve() != (folder / name).resolve():
            issue("stale_metadata_file_path", key)
    modules = [module_state() for _ in range(4)]
    counts, statuses, modes, mask_counts = Counter(), Counter(), Counter(), Counter()
    lengths = Counter()
    observed_ids = set()
    sha = hashlib.sha256()
    wire_seq = None
    offset = 0
    model_bytes = 0
    first_log_time = last_log_time = None
    with raw_path.open("rb") as raw, log_path.open(newline="", encoding="utf-8-sig") as logfile:
        rows = csv.DictReader(logfile)
        required = {"raw_offset", "received_bytes", "declared_length", "packet_sequence",
                    "elapsed_s", "mul_start_time", "parse_ok", "outer_crc_ok",
                    "algorithms", "updated_mask", "error"}
        if not required <= set(rows.fieldnames or []):
            raise ValueError("packet_log missing required fields")
        for row in rows:
            counts["log_rows"] += 1
            if row["parse_ok"].lower() != "true":
                counts["log_parse_errors"] += 1
            if row["error"]:
                counts["log_error_rows"] += 1
            if row["outer_crc_ok"].lower() != "true":
                counts["log_outer_crc_errors"] += 1
            first_log_time = first_log_time or row["mul_start_time"]
            last_log_time = row["mul_start_time"]
            declared_log, received = int(row["declared_length"]), int(row["received_bytes"])
            if int(row["raw_offset"]) != offset:
                issue("log_raw_offset_mismatch", counts["log_rows"])
            packet = raw.read(received)
            sha.update(packet)
            offset += len(packet)
            if len(packet) != received or len(packet) < 24:
                issue("truncated_raw_packet", counts["log_rows"])
                continue
            counts["raw_packets"] += 1
            lengths[len(packet)] += 1
            if packet[:4] != b"MUL1" or packet[4] != 2 or packet[5] != 4:
                issue("invalid_mul_header", counts["log_rows"])
                continue
            declared = struct.unpack_from("<H", packet, 8)[0]
            if declared != len(packet) or declared != declared_log:
                issue("outer_length_mismatch", counts["log_rows"])
                continue
            if zlib.crc32(packet[:-4]) != struct.unpack_from("<I", packet, len(packet)-4)[0]:
                issue("outer_crc_error", counts["log_rows"])
                continue
            counts["raw_complete_outer_packets"] += 1
            seq = struct.unpack_from("<I", packet, 12)[0]
            if seq != int(row["packet_sequence"]):
                issue("log_packet_sequence_mismatch")
            if wire_seq is not None and seq != (wire_seq + 1) & 0xFFFFFFFF:
                counts["outer_sequence_discontinuities"] += 1
            wire_seq = seq
            pos, packet_model = 20, 40
            packet_ok = True
            frame_labels = []
            active_mask = 0
            full_in_packet = 0
            for expected_id in range(4):
                if pos + 4 > len(packet)-4:
                    issue("truncated_module_header")
                    packet_ok = False
                    break
                mid, status, size = struct.unpack_from("<BBH", packet, pos)
                pos += 4
                payload = packet[pos:pos+size]
                pos += size
                statuses[f"M{mid}:0x{status:02x}"] += 1
                if mid != expected_id or pos > len(packet)-4:
                    issue("invalid_module_layout")
                    packet_ok = False
                    break
                if status != 0:
                    frame_labels.append("NONE")
                    packet_model += size  # actual diagnostic prefix, when present
                    counts["diagnostic_payload_bytes"] += size
                    if size not in (0, 16):
                        issue("unexpected_diagnostic_length", size)
                    continue
                active_mask |= 1 << mid
                observed_ids.add(f"M{mid}")
                state = modules[mid]
                if size < 20 or payload[4] != 4 or struct.unpack_from("<H", payload, 6)[0] != size:
                    issue("invalid_inner_header", mid)
                    packet_ok = False
                    frame_labels.append("INVALID")
                    continue
                if zlib.crc32(payload[:-4]) != struct.unpack_from("<I", payload, size-4)[0]:
                    issue("inner_crc_error", mid)
                    packet_ok = False
                    frame_labels.append("INVALID")
                    continue
                flags = payload[5]
                state["flags"][f"0x{flags:02x}"] += 1
                if flags & 0xC0 or not flags & 0x10:
                    issue("unexpected_inner_flags", flags)
                inner_seq, base_seq = struct.unpack_from("<II", payload, 8)
                marker = payload[:4]
                if marker == b"ESKF" and size == 1044:
                    state["counts"]["ESKF"] += 1
                    state["full_times"].append(float(row["elapsed_s"]))
                    full_in_packet += 1
                    packet_model += 1044
                    label = "DELTA_SYNC" if flags & 0x20 else "FULL"
                    state["anchored"] = state["chain_valid"] = True
                    state["last_applied_seq"] = inner_seq
                elif marker == b"ESKD" and size >= 84 and flags & 0x20:
                    k1 = sum(b.bit_count() for b in payload[16:48])
                    k2 = sum(b.bit_count() for b in payload[48:80])
                    k = k1 + k2
                    if size != 84 + 2*k or k > 480:
                        issue("delta_mask_length_error", mid)
                        packet_ok = False
                    state["counts"]["ESKD"] += 1
                    state["k"][k] += 1
                    state["k1"][k1] += 1
                    state["k2"][k2] += 1
                    packet_model += 84 + 2*k
                    label = "DELTA"
                    if state["last_wire_seq"] is not None and base_seq != state["last_wire_seq"]:
                        state["chain"]["base_link_discontinuities"] += 1
                    if not state["anchored"]:
                        state["chain"]["initial_unanchored_delta_frames"] += 1
                    elif state["chain_valid"] and base_seq == state["last_applied_seq"]:
                        state["last_applied_seq"] = inner_seq
                    else:
                        if state["chain_valid"]:
                            state["chain"]["break_events_after_anchor"] += 1
                        state["chain_valid"] = False
                        state["chain"]["unapplied_frames_after_anchor"] += 1
                else:
                    issue("unsupported_inner_frame", marker.decode("ascii", errors="replace"))
                    packet_ok = False
                    label = "INVALID"
                state["last_wire_seq"] = inner_seq
                state["payload_bytes"] += size
                frame_labels.append(label)
                modes["DELTA" if label.startswith("DELTA") else label] += 1
            if pos != len(packet)-4:
                issue("trailing_packet_bytes")
                packet_ok = False
            if packet_model != len(packet):
                issue("packet_byte_model_mismatch")
            model_bytes += packet_model
            if packet_ok:
                counts["raw_valid_inner_packets"] += 1
            mask_counts[active_mask] += 1
            if full_in_packet:
                counts["packets_containing_eskf"] += 1
            if row["parse_ok"].lower() == "true":
                if frame_labels != row["algorithms"].split(","):
                    issue("log_algorithm_mismatch")
                if int(row["updated_mask"], 0) != active_mask or packet[6] != active_mask:
                    issue("log_updated_mask_mismatch")
        trailing = raw.read()
        sha.update(trailing)
        if trailing:
            issue("unlogged_raw_bytes", len(trailing))
            offset += len(trailing)
    for field, observed in (("recorded_bytes", offset),
                            ("recorded_candidate_rows", counts["log_rows"]),
                            ("complete_mul_count", counts["raw_complete_outer_packets"])):
        if summary.get(field) != observed:
            issue("summary_" + field + "_mismatch")
    if first_log_time and datetime.fromisoformat(first_log_time).date().isoformat() != date:
        issue("record_start_date_mismatch")
    for field, observed in (("first_mul_start_time", first_log_time),
                            ("last_mul_start_time", last_log_time)):
        if summary.get(field) != observed:
            issue("summary_" + field + "_mismatch")
    ids = sorted(observed_ids)
    expected_ids = sorted(condition.get("active_module_ids", condition.get("module_ids", [])))
    if ids != expected_ids or len(ids) != condition.get("module_count"):
        issue("module_metadata_mismatch")
    observed_mode = next(iter(modes)) if len(modes) == 1 else "/".join(sorted(modes))
    if observed_mode != condition.get("algorithm"):
        issue("algorithm_metadata_mismatch")
    requested_mode = condition.get("requested_algorithm")
    if requested_mode and requested_mode != observed_mode:
        issue("requested_vs_observed_algorithm")
    duration = float(summary["duration_seconds"])
    if duration <= 0:
        raise ValueError("Non-positive recorded duration")
    n = counts["raw_packets"]
    pooled_k = sum((m["k"] for m in modules), Counter())
    pooled_counts = sum((m["counts"] for m in modules), Counter())
    present_module_frames = sum(pooled_counts.values())
    expected_module_frames = len(ids) * n
    expected_mask = sum(1 << int(module[1:]) for module in ids)
    all_updated_packets = mask_counts[expected_mask]
    valid_payload_bytes = sum(m["payload_bytes"] for m in modules)
    kstats = histogram_stats(pooled_k)
    q = pooled_counts["ESKF"] / sum(pooled_counts.values())
    repeat_parts = [p for p in folder.parts if re.fullmatch(r"(?:Repeat_|R)\d+", p)]
    run = {"run_id": run_id, "started_at": summary["started_at"], "date": date,
           "date_bucket": bucket, "mode": observed_mode,
           "target_Hz": condition.get("target_scan_rate_hz", condition.get("scan_rate_hz")),
           "N": len(ids), "modules": "+".join(ids), "load": load,
           "load_source": load_source, "load_metadata": condition.get("load_condition"),
           "repeat_label": repeat_parts[-1] if repeat_parts else "single_run_no_repeat_label",
           "duration_s": duration, "raw_bytes": offset, "raw_packets": n,
           "complete_outer_packets": counts["raw_complete_outer_packets"],
           "valid_inner_packets": counts["raw_valid_inner_packets"],
           "valid_module_frames": present_module_frames,
           "expected_module_frames": expected_module_frames,
           "unupdated_expected_module_frames": expected_module_frames-present_module_frames,
           "all_expected_modules_updated_packets": all_updated_packets,
           "partial_update_packets": n-all_updated_packets,
           "f_all_expected_modules_Hz": all_updated_packets/duration,
           "diagnostic_payload_bytes": counts["diagnostic_payload_bytes"],
           "unupdated_module_status_counts": {key: value for key, value in statuses.items()
                                               if key.split(":")[0] in ids and not key.endswith(":0x00")},
           "fixed_N_mixture_applicable": present_module_frames == expected_module_frames and counts["diagnostic_payload_bytes"] == 0,
           "K_effective_present_module_frames": (valid_payload_bytes/present_module_frames-84)/2 if observed_mode == "DELTA" else None,
           "Lmean_B": offset/n, "Lmodel_mean_B": model_bytes/n,
           "f_packet_Hz": n/duration,
           "f_complete_Hz": counts["raw_complete_outer_packets"]/duration,
           "f_valid_inner_Hz": counts["raw_valid_inner_packets"]/duration,
           "bytes_per_s": offset/duration, "Mbit_per_s": offset/duration*8/1e6,
           "ESKF_count": pooled_counts["ESKF"], "ESKD_count": pooled_counts["ESKD"],
           "q_ESKF_module_frames": q, "K_ESKD_mean": kstats["mean"],
           "K_ESKD_sd_population": kstats["sd_population"],
           "K_ESKD_median": kstats["median"], "K_ESKD_p05": kstats["p05"],
           "K_ESKD_p95": kstats["p95"], "K_zero_fraction": kstats["zero_fraction"],
           "K_effective_all_frames": ((offset/n-40)/len(ids)-84)/2 if observed_mode == "DELTA" else None,
           "summary_result": summary.get("result"),
           "summary_session_base_mismatches": summary.get("counters", {}).get("delta_base_mismatches"),
           "log_parse_errors": counts["log_parse_errors"],
           "raw_base_break_events_after_anchor": sum(m["chain"]["break_events_after_anchor"] for m in modules),
           "raw_unapplied_after_anchor": sum(m["chain"]["unapplied_frames_after_anchor"] for m in modules),
           "raw_initial_unanchored_delta_frames": sum(m["chain"]["initial_unanchored_delta_frames"] for m in modules),
           "raw_sha256": sha.hexdigest(), "source_dir": str(folder.relative_to(DATA)),
           "audit_issue_counts": dict(issues)}
    details = []
    for mid, state in enumerate(modules):
        if not state["counts"]:
            continue
        stats = histogram_stats(state["k"])
        gaps = [b-a for a, b in zip(state["full_times"], state["full_times"][1:])]
        detail = {k: run[k] for k in ("run_id", "date", "date_bucket", "mode", "target_Hz", "N", "modules", "load", "repeat_label")}
        detail.update({"module_id": f"M{mid}", "ESKF_count": state["counts"]["ESKF"],
                       "ESKD_count": state["counts"]["ESKD"],
                       "q_ESKF": state["counts"]["ESKF"]/sum(state["counts"].values()),
                       "module_update_rate_Hz": sum(state["counts"].values())/duration,
                       "unupdated_packets_for_this_module": n-sum(state["counts"].values()),
                       **{"K_"+k: v for k, v in stats.items()},
                       "K_FSR1_mean": histogram_stats(state["k1"])["mean"],
                       "K_FSR2_mean": histogram_stats(state["k2"])["mean"],
                       "ESKF_interval_count": len(gaps),
                       "ESKF_interval_mean_s": mean(gaps),
                       "ESKF_interval_min_s": min(gaps) if gaps else None,
                       "ESKF_interval_max_s": max(gaps) if gaps else None,
                       "flags_counts": dict(state["flags"]),
                       "base_link_discontinuities": state["chain"]["base_link_discontinuities"],
                       "break_events_after_anchor": state["chain"]["break_events_after_anchor"],
                       "unapplied_after_anchor": state["chain"]["unapplied_frames_after_anchor"],
                       "initial_unanchored_delta_frames": state["chain"]["initial_unanchored_delta_frames"],
                       "full_trigger_reason": "not_identifiable_from_recorded_frame_type"})
        details.append(detail)
    payload = {"run": run, "modules": details, "raw_counts": dict(counts),
               "module_status_counts": dict(statuses), "audit_examples": examples,
               "updated_mask_counts": {f"0x{k:02x}": v for k, v in mask_counts.items()},
               "K_histograms_by_module": {f"M{i}": dict(m["k"]) for i, m in enumerate(modules) if m["counts"]},
               "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
               "packet_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()}
    return run, details, payload


METRICS = ("K_ESKD_mean", "q_ESKF_module_frames", "Lmean_B", "f_packet_Hz", "Mbit_per_s")
CONDITION_KEYS = ("mode", "target_Hz", "N", "modules", "load")


def group_runs(runs, keys):
    groups = defaultdict(list)
    for run in runs:
        groups[tuple(run[k] for k in keys)].append(run)
    output = []
    for key, members in sorted(groups.items(), key=lambda pair: str(pair[0])):
        row = dict(zip(keys, key))
        row.update({"n_runs": len(members), "run_ids": [m["run_id"] for m in members],
                    "module_combinations": sorted(set(m["modules"] for m in members))})
        for metric in METRICS:
            values = [m[metric] for m in members]
            row[metric+"_mean_over_runs"] = mean(values)
            row[metric+"_sd_between_runs"] = repeat_sd(values)
        nd = sum(m["ESKD_count"] for m in members)
        nf = sum(m["ESKF_count"] for m in members)
        row["K_ESKD_pooled_mean"] = sum(m["ESKD_count"]*(m["K_ESKD_mean"] or 0) for m in members)/nd if nd else None
        row["q_ESKF_pooled"] = nf/(nd+nf)
        output.append(row)
    return output


def fmt(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def build_report(runs, groups, zero_groups, comparisons, inventory):
    lines = ["# 2026-09-06 数据记录独立复核", "",
             "本分析仅新建派生文件；未修改原始记录、报告 ESKF/K 文字或现有实测图。",
             "实验日期取 summary.json 的 started_at（保留其时区偏移），并与 run_id、录制首包日期交叉核验；不使用文件修改时间。昨天固定定义为 2026-09-05；之前为更早日期；其他日期单列。", "",
             "## 范围和统计单位", "",
             f"全量读取 {len(runs)} 条记录、{sum(r['raw_bytes'] for r in runs):,} B 原始流、{sum(r['raw_packets'] for r in runs):,} 个 MUL1；每次仅处理一个 run，未抽样、未删除异常记录。",
             "日期 → 模式 → 目标频率 → N → 物理模块组合 → 负载条件 → 单次约30秒录制为统计层级。n表示录制次数，不自动等于独立重新加载或重新装配次数；单帧和同一run中的模块不是独立实验重复。组内SD仅对run汇总量计算，n=1留空；逐模块的K帧内SD使用总体SD，描述时间变化；逐run pooled SD还包含模块之间的差异。",
             "50/100 Hz FULL保留为补充记录，不混入200 Hz主比较。FULL未记录负载状态时标记load_not_recorded，不假定为空载。", "",
             "| 日期 | 条数 | FULL | DELTA | 目标频率分布 |",
             "|---|---:|---:|---:|---|" ]
    for date in sorted(set(r["date"] for r in runs)):
        members = [r for r in runs if r["date"] == date]
        lines.append(f"| {date} | {len(members)} | {sum(r['mode']=='FULL' for r in members)} | {sum(r['mode']=='DELTA' for r in members)} | {dict(Counter(r['target_Hz'] for r in members))} |")
    lines += ["", "## 定义和边界", "",
              "- 普通ESKD真实K：分别对两个32 B掩码计数，K=K_FSR1+K_FSR2；仅ESKD进入K分布。四个模块分别统计后再给pooled值。",
              "- q=ESKF数/(ESKF数+ESKD数)，以模块内帧为分母。ESKF只统计总比例；其marker/DELTA_SYNC标签不能证明周期同步、高K回退或失配恢复的具体触发原因。",
              "- Lmean=原始流字节数/原始包数；f=包数/summary.duration_seconds；R=字节数/T。另保留外层完整包数、内帧结构/CRC有效包数、所有目标模块均更新包数及各模块更新频率，避免将字节、包频率、模块更新频率及流量混为一项。",
              "- 当前四槽模型 L=40+Σ(ESKF:1044；ESKD:84+2K)；诊断前缀另计。按真实帧类型与K逐包核验，完整帧成本自然包含。",
              "- 仅当每包N个目标模块全部更新且没有诊断前缀时，平均模型 Lbar=40+Σ_m[q_m1044+(1-q_m)(84+2Kbar_D,m)]。此时由平均包长反推的Keff=((Lbar−40)/N−84)/2=(1−q)Kbar_D+480q；ESKF不等于实际有480个单元变化。",
              "- 通用口径：令J为有效模块内帧总数、P为USB包数、D为诊断payload字节数，则 K_eff,present=(1−q)Kbar_D+480q；Lbar=40+(J/P)(84+2K_eff,present)+D/P。这可处理某些目标模块在个别USB包中未更新的情况。",
              "- 保留0x13/0x33等正常flags：低位为采集状态，0x10为CRC、0x20为DELTA。",
              "- 分位数采用有序样本位置(n−1)p的线性插值。帧内SD与组间重复SD分别命名。", "",
              "## 零载K随N：按日期分开", "",
              "下表的SD是每个run普通ESKD平均K之间的样本SD；pooled K按ESKD内帧数加权。不同N可能包含不同模块组合，不能据此建立N导致噪声变化的因果结论。", "",
              "| 日期 | N | n runs | 普通K/run均值 ± SD | 普通K pooled | q pooled (%) | 模块组合数 |",
              "|---|---:|---:|---|---:|---:|---:|"]
    for group in zero_groups:
        lines.append(f"| {group['date']} | {group['N']} | {group['n_runs']} | {fmt(group['K_ESKD_mean_mean_over_runs'])} ± {fmt(group['K_ESKD_mean_sd_between_runs'])} | {fmt(group['K_ESKD_pooled_mean'])} | {fmt(100*group['q_ESKF_pooled'])} | {len(group['module_combinations'])} |")
    reference = next(r for r in runs if r["run_id"] == "20260901_205141")
    lines += ["", "剔除ESKF后，旧日期的普通ESKD均值仍随N增大；完整帧混入并不能解释整个跨N差异。但这仍是条件未完全控制的描述性趋势。",
              f"例如旧N4零载run {reference['run_id']}：ESKF={reference['ESKF_count']}、ESKD={reference['ESKD_count']}、q={fmt(100*reference['q_ESKF_module_frames'], 4)}%；普通K={fmt(reference['K_ESKD_mean'], 4)}，包长反推Keff={fmt(reference['K_effective_all_frames'], 4)}，差值仅{fmt(reference['K_effective_all_frames']-reference['K_ESKD_mean'], 4)}。该差值是完整帧混入造成的字节等效增量，不能当作额外真实变化单元。",
              "", "## 跨日期同条件对照", "",
              "仅匹配模式、频率、N、模块组合和负载。下表按run等权；不是同一场景同步配对测试。n=1处不提供SD。", "",
              "| N/模块/负载 | 之前n → 昨天n | 普通K均值 之前 → 昨天 | q (%) 之前 → 昨天 | Mbit/s 之前 → 昨天 |",
              "|---|---|---|---|---|"]
    for row in comparisons:
        lines.append(f"| {row['N']}/{row['modules']}/{row['load']} | {row['n_before']} → {row['n_yesterday']} | {fmt(row['K_before'])} → {fmt(row['K_yesterday'])} | {fmt(100*row['q_before'])} → {fmt(100*row['q_yesterday'])} | {fmt(row['Mbit_before'])} → {fmt(row['Mbit_yesterday'])} |")
    lines += ["", "新增日期没有FULL记录，也没有N2/N4全区域动态或rolling新重复；因此不能把这些旧动态结果当成昨天的验证。单模块与多模块、空载与动态加载分开保留。",
              "各物理模块在N1下的重复数并不完全平衡；跨N组平均还受组合构成、日期、装配/阈值状态与加载可比性影响。现有记录没有逐run固件hash、完整阈值/环境/重新装配记录，不能证明跨日期除日期以外完全相同。",
              "固定K的N>4外推只能作为保持相同每模块活动量和同步占比的条件预测；本分析不修改现有外推图，也不将USB记录当作变长SPI已部署的证据。", "",
              "## 完整性与元数据核验", ""]
    all_issues = Counter()
    for run in runs:
        all_issues.update(run["audit_issue_counts"])
    lines.append("核验问题计数：`" + json.dumps(dict(all_issues), ensure_ascii=False) + "`。这些是核验项次数，不能不加区分地称为传输错误。")
    hard_issues = {k: v for k, v in all_issues.items() if k not in
                   ("requested_vs_observed_algorithm", "experiment_log_run_id_missing", "stale_metadata_file_path")}
    lines.append("协议/流日志硬核验问题：" + (json.dumps(hard_issues, ensure_ascii=False)
                 if hard_issues else "MUL1外层和其status=0的有效ESK payload未发现CRC错误；未发现逐包长度/字节模型差异、CSV与raw偏移/序号/算法/活动模块差异，或summary字节/包数差异。status非0的诊断块不作为有效ESK帧检查或计入K/q；其实际字节仍计入流量。"))
    coverage_runs = [r for r in runs if r["unupdated_expected_module_frames"]]
    lines += ["", "### USB包有效性与模块更新覆盖率", "",
              f"共{len(coverage_runs)}条记录存在目标模块未更新：这类USB包本身仍可有效，不能用summary PASS或USB包频率替代逐模块更新核验。", "",
              "| run | 目标模块帧数/已更新 | 未更新模块帧数 | 部分更新USB包数 | 非零目标模块status | 诊断payload B |",
              "|---|---|---:|---:|---|---:|"]
    for run in coverage_runs:
        lines.append(f"| {run['run_id']} | {run['expected_module_frames']}/{run['valid_module_frames']} | {run['unupdated_expected_module_frames']} | {run['partial_update_packets']} | {json.dumps(run['unupdated_module_status_counts'], ensure_ascii=False)} | {run['diagnostic_payload_bytes']} |")
    lines += ["", "未更新计数表示录制USB包中目标模块没有有效payload，不能进一步推定丢失了多少独立物理扫描。该记录使用通用字节模型；其固定N反推Keff不能直接套用完整更新假设。其他记录也保留逐模块覆盖率供检查。", ""]
    missing_ids = [r for r in runs if r["audit_issue_counts"].get("experiment_log_run_id_missing")]
    lines.append(f"{len(missing_ids)}条人工experiment_log没有精确run_id字符串，模式分布为{dict(Counter(r['mode'] for r in missing_ids))}；这些记录保留，日期仍以summary.started_at及录制首包核验为准。")
    marked = [r for r in runs if r["summary_session_base_mismatches"]]
    lines += [f"保存summary会话计数带base mismatch的run共{len(marked)}条；这些run在自己的packet_log中共{sum(r['log_parse_errors'] for r in marked)}条parse错误。",
              f"全量录制文件在各模块第一次ESKF之后，离线base链断裂事件共{sum(r['raw_base_break_events_after_anchor'] for r in runs)}次，之后不可应用ESKD共{sum(r['raw_unapplied_after_anchor'] for r in runs)}个模块帧。",
              f"开始录制时尚未包含完整基线的前缀ESKD共有{sum(r['raw_initial_unanchored_delta_frames'] for r in runs)}个模块帧，单列为initial_unanchored；现场PC可能在按下录制前已有缓存，不能算作现场丢帧或失配。",
              "summary的counters是保存GUI版本的会话累计快照；不直接解释为每30秒窗口内新增事件。本脚本的链检查也不是对现场PC状态的完整重放。",
              "requested_algorithm与实际观察模式不符时保留标记并以原始帧类型确认模式，不静默改原元数据。raw字节hash用于检测直接副本，不能证明实验条件独立或随机化。", "",
              "## 输出与复现", "",
              "- inventory.json：日期分组、全部run来源、输入体量和hash/重复核验。",
              "- data_dictionary.json：统计单位、变量含义、单位、缺失值与派生公式。",
              "- runs.csv / runs.json：每run字节、包数、频率、真实K、q、有效性和元数据核验。",
              "- modules.csv：每run每模块的帧类型计数、K分布、层间K、完整帧间隔、离线链检查。",
              "- per_run/*.json：每run详细统计、K直方图和有限核验示例。",
              "- groups.csv：日期×完整实验条件的run均值与重复SD。",
              "- zero_load_by_date_N.csv：仅零载200 Hz的日期/N探索汇总；模块组合构成同时保留。",
              "- same_condition_date_comparison.csv：完整条件匹配的跨日期对照。",
              "- validate_outputs.py / validation.json：统计单位、计数闭合、字节和频率恒等式、混合模型及已知样本的可复现校验。", "",
              "复现：在本目录依次执行 `python -B analyze_records.py` 和 `python -B validate_outputs.py`。脚本只读取邻近data根目录，只在本目录写派生输出；未使用网络、未改原数据。",
              f"运行环境：Python {platform.python_version()}；平台 {platform.platform()}；统计与解析仅用标准库。"]
    return "\n".join(lines) + "\n"


def main():
    global DATA
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT,
                        help=f"Historical dataset root; no automatic fallback (default: {DEFAULT_DATA_ROOT})")
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    DATA = args.data_root.resolve()
    paths = sorted(DATA.rglob("summary.json"))
    if not paths:
        raise SystemExit(f"No experiment summaries under {DATA}. "
                         "Use --data-root to select an existing dataset explicitly.")
    inventory_rows = []
    for path in paths:
        summary = json.loads(path.read_text(encoding="utf-8-sig"))
        require_legacy_summary(summary, path)
        date = datetime.fromisoformat(summary["started_at"]).date().isoformat()
        inventory_rows.append({"run_id": summary["run_id"], "started_at": summary["started_at"],
                               "date": date, "relative_dir": str(path.parent.relative_to(DATA)),
                               "raw_bytes": (path.parent/"mul1_raw.bin").stat().st_size})
    inventory = {"analysis_date": "2026-09-06", "reference_date_yesterday": REFERENCE_DATE,
                 "data_root": str(DATA),
                 "date_source": "summary.started_at; preserved acquisition timezone offset; no mtime",
                 "runs": inventory_rows, "run_count": len(paths),
                 "total_raw_bytes": sum(r["raw_bytes"] for r in inventory_rows),
                 "runs_by_date": dict(Counter(r["date"] for r in inventory_rows)),
                 "max_run_bytes": max(r["raw_bytes"] for r in inventory_rows),
                 "strategy": "complete per-run reads; CSV-indexed packet boundaries; no sampling"}
    if len(set(row["run_id"] for row in inventory_rows)) != len(paths):
        raise ValueError("Duplicate run_id would make per-run output ambiguous")
    json_write(OUTPUT/"inventory.json", inventory)
    if args.inventory_only:
        print(json.dumps({k:v for k,v in inventory.items() if k != "runs"}, ensure_ascii=False))
        return
    (OUTPUT/"per_run").mkdir(exist_ok=True)
    runs, module_rows = [], []
    for index, path in enumerate(paths, 1):
        run, details, payload = inspect_run(path)
        runs.append(run)
        module_rows.extend(details)
        json_write(OUTPUT/"per_run"/(run["run_id"]+".json"), payload)
        if index % 10 == 0 or index == len(paths):
            print(f"Parsed {index}/{len(paths)} runs", flush=True)
    inventory["unique_run_ids"] = len(set(r["run_id"] for r in runs))
    inventory["unique_raw_hashes"] = len(set(r["raw_sha256"] for r in runs))
    inventory["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    json_write(OUTPUT/"inventory.json", inventory)
    groups = group_runs(runs, ("date", "date_bucket") + CONDITION_KEYS)
    zero_groups = group_runs([r for r in runs if r["load"] == "zero_load" and r["target_Hz"] == 200], ("date", "N"))
    match_groups = group_runs(runs, ("date_bucket",) + CONDITION_KEYS)
    match = defaultdict(dict)
    for group in match_groups:
        match[tuple(group[k] for k in CONDITION_KEYS)][group["date_bucket"]] = group
    comparisons = []
    for key, values in sorted(match.items(), key=lambda x: str(x[0])):
        if not {"before_2026-09-05", "yesterday_2026-09-05"} <= values.keys():
            continue
        before, yesterday = values["before_2026-09-05"], values["yesterday_2026-09-05"]
        row = dict(zip(CONDITION_KEYS, key))
        for suffix, group in (("before", before), ("yesterday", yesterday)):
            row["n_"+suffix] = group["n_runs"]
            for short, metric in (("K", "K_ESKD_mean"), ("q", "q_ESKF_module_frames"),
                                  ("Mbit", "Mbit_per_s"), ("Lmean", "Lmean_B"), ("f", "f_packet_Hz")):
                row[short+"_"+suffix] = group[metric+"_mean_over_runs"]
                row[short+"_SD_"+suffix] = group[metric+"_sd_between_runs"]
        comparisons.append(row)
    json_write(OUTPUT/"runs.json", runs)
    json_write(OUTPUT/"data_dictionary.json", {
        "observational_unit": "one recorded run; per-module frames are nested within a run",
        "missing": "JSON null / empty CSV cell; n=1 between-run SD is unavailable; FULL K is not applicable, not zero",
        "date": "calendar date of summary.started_at preserving its timezone offset; never file mtime",
        "date_bucket": "2026-09-05 is yesterday, smaller date is before, larger date is other_date",
        "run_id": "record identifier YYYYMMDD_HHMMSS, checked against recorded start date",
        "target_Hz": "recorded target packet/scan frequency; condition not inferred from file path",
        "N/modules/load": "active module count and physical IDs verified from raw packets; load category from archived condition path, original metadata retained",
        "repeat_label": "archive label, not proof of independent reassembly or loading",
        "raw_bytes": "bytes read from mul1_raw.bin, checked against CSV and summary",
        "raw_packets": "all CSV-indexed raw packet candidates; packet sizes and complete file coverage checked",
        "complete_outer_packets": "correct MUL1 header, declared length and outer CRC",
        "valid_inner_packets": "outer-valid packets whose module layouts and ESK headers/inner CRCs are valid; distinct from online cache reconstruction",
        "Lmean_B": "raw_bytes/raw_packets; B per packet, all recorded traffic",
        "Lmodel_mean_B": "mean of per-packet 40 B + 1044 B per ESKF + (84+2K) B per ESKD + actual diagnostic prefix sizes",
        "duration_s": "summary monotonic capture duration, seconds",
        "f_packet_Hz": "raw_packets/duration_s; packet/s",
        "f_complete_Hz": "complete_outer_packets/duration_s",
        "f_valid_inner_Hz": "valid_inner_packets/duration_s",
        "valid_module_frames": "count of valid ESKF+ESKD payloads across all target modules",
        "unupdated_expected_module_frames": "N*raw_packets-valid_module_frames; absent update count, not proven physical-scan loss",
        "partial_update_packets": "raw_packets-all_expected_modules_updated_packets",
        "f_all_expected_modules_Hz": "all_expected_modules_updated_packets/duration_s",
        "module_update_rate_Hz": "per-module (ESKF_count+ESKD_count)/duration_s",
        "diagnostic_payload_bytes": "payload byte count of nonzero-status module blocks; zero or 16 B per such block",
        "bytes_per_s/Mbit_per_s": "raw_bytes/duration_s; then multiply by 8/1e6",
        "K": "ordinary ESKD mask popcount over two 256-bit matrices; 0..480 under recorded protocol",
        "K_ESKD_sd_population": "population SD across all ESKD module frames within one run; combines temporal and between-module variability, not independent-repeat uncertainty",
        "K_quantiles": "linear interpolation at ordered position (n-1)*p",
        "q_ESKF_module_frames": "ESKF_count/(ESKF_count+ESKD_count), fraction 0..1, not packet fraction",
        "K_effective_all_frames": "((Lmean_B-40)/N-84)/2; nominal fixed-N byte equivalent, not observed changed count; mixture identity needs complete target-module updates and no diagnostics",
        "fixed_N_mixture_applicable": "all N target modules updated every recorded USB packet and zero diagnostic bytes",
        "K_effective_present_module_frames": "(valid_ESK_payload_bytes/valid_module_frames-84)/2 = (1-q)*K_ESKD_mean+480*q for DELTA runs",
        "general_packet_model": "Lmean=40+(J/P)*(84+2*K_effective_present_module_frames)+D/P for DELTA runs; J=valid_module_frames, P=raw_packets, D=diagnostic_payload_bytes",
        "group_mean_over_runs": "arithmetic mean of run summaries within specified date and conditions",
        "group_sd_between_runs": "sample SD (ddof=1) of run summaries; null if n<2; descriptive capture repeatability",
        "group_K_pooled": "weighted by number of ordinary ESKD module frames; distinguish from run-weighted mean",
        "ESKF_interval": "differences between successive recorded host elapsed_s of ESKF for one physical module; no trigger attribution",
        "base_link_discontinuities": "ESKD base_seq differs from previous valid observed module seq, when one exists",
        "break_events_after_anchor": "first base mismatch after an in-file ESKF anchor; repeated rejected frames in same episode counted separately",
        "initial_unanchored_delta_frames": "prefix before first in-file ESKF; unknown online PC cache, not a confirmed loss",
        "threshold/firmware/environment": "not consistently recorded per run; not imputed; limits cross-date comparability",
        "inference_scope": "exploratory descriptive review; no causal, inferential-significance, or achieved SPI capacity claims"
    })
    for name, rows in (("runs.csv", runs), ("modules.csv", module_rows), ("groups.csv", groups),
                       ("zero_load_by_date_N.csv", zero_groups),
                       ("same_condition_date_comparison.csv", comparisons)):
        csv_write(OUTPUT/name, rows)
    (OUTPUT/"ANALYSIS_CN.md").write_text(build_report(runs, groups, zero_groups, comparisons, inventory), encoding="utf-8")
    print(json.dumps({"runs": len(runs), "module_run_rows": len(module_rows),
                      "raw_bytes": inventory["total_raw_bytes"],
                      "unique_raw_hashes": inventory["unique_raw_hashes"],
                      "audit_issue_counts": dict(sum((Counter(r["audit_issue_counts"]) for r in runs), Counter()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
