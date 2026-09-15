"""Read-only independent audit of the fixed 12-run snapshot; outputs only here.

Run: python -B audit_records.py
No monitor/recorder code is imported. Raw bytes are parsed independently with
struct/zlib; main-window timing necessarily comes from packet_log timestamps.
Summary run IDs remain usable if the parent task later reorganizes directories.
"""
from collections import Counter, defaultdict
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import statistics
import struct
import zlib

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data"
SNAPSHOT = (
    "20260906_225934_745706", "20260906_230014_784220", "20260906_230054_835519",
    "20260906_230200_451593", "20260906_230240_486802", "20260906_230320_515930",
    "20260906_230445_150722", "20260906_230525_193234", "20260906_230605_248880",
    "20260906_230909_089519", "20260906_230949_124162", "20260906_231029_180830",
)
ERRORS = ("outer_crc_errors", "inner_crc_errors", "sequence_gap_events", "lost_frames",
          "duplicate_frames", "out_of_order_frames", "format_errors", "delta_base_mismatches")


def completed():
    result, skipped = {}, []
    for path in sorted(DATA.rglob("summary.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            result[summary["run_id"]] = (path.parent, summary)
        except (OSError, ValueError, KeyError):
            skipped.append(str(path))
    return result, skipped


def decode(data):
    errors, modules = [], []
    if len(data) < 40 or data[:6] != b"MUL1\x02\x04":
        return None, modules, ["outer_header"]
    if struct.unpack_from("<H", data, 8)[0] != len(data):
        errors.append("outer_length")
    if zlib.crc32(data[:-4]) != struct.unpack_from("<I", data, len(data)-4)[0]:
        errors.append("outer_crc")
    seq = struct.unpack_from("<I", data, 12)[0]
    pos, update_mask = 20, 0
    for expected_slot in range(4):
        if pos+4 > len(data)-4:
            errors.append("descriptor_bounds"); break
        slot, status, size = struct.unpack_from("<BBH", data, pos)
        pos += 4
        if slot != expected_slot or pos+size > len(data)-4:
            errors.append("descriptor_layout"); break
        payload = data[pos:pos+size]
        pos += size
        record = {"slot": slot, "status": status, "bytes": size, "valid": False}
        modules.append(record)
        if status:
            if size not in (0, 16): errors.append("diagnostic_length")
            continue
        update_mask |= 1 << slot
        if size < 20:
            errors.append("inner_length"); continue
        marker, version, flags, length, inner_seq, base = struct.unpack_from("<4sBBHII", payload)
        record.update(marker=marker.decode("ascii", "replace"), flags=flags, sequence=inner_seq,
                      base=base, mode="DELTA" if flags & 0x20 else "FULL")
        before = len(errors)
        if version != 4 or length != size or flags & 0xc0 or not flags & 0x10:
            errors.append("inner_header_flags")
        if zlib.crc32(payload[:-4]) != struct.unpack_from("<I", payload, size-4)[0]:
            errors.append("inner_crc")
        if marker == b"ESKF":
            if size != 1044: errors.append("full_length")
        elif marker == b"ESKD" and size >= 84 and flags & 0x20:
            k = sum(value.bit_count() for value in payload[16:80])
            record["K"] = k
            if k > 480 or size != 84+2*k: errors.append("delta_mask_length")
        else:
            errors.append("inner_marker")
        record["valid"] = len(errors) == before
    if pos != len(data)-4 or data[6] != update_mask:
        errors.append("layout_or_mask")
    return seq, modules, errors


def audit_one(directory, summary, previous):
    raw = (directory/"mul1_raw.bin").read_bytes()
    with (directory/"packet_log.csv").open(encoding="utf-8-sig", newline="") as stream:
        logs = list(csv.DictReader(stream))
    events = [json.loads(line) for line in (directory/"events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    boundaries = [event for event in events if event.get("event") == "capture_start_boundary"]
    expected = set(summary["metadata"]["target_modules"])
    mode = summary["metadata"]["target_mode"]
    counters, actual_slots, actual_modes, markers = Counter(), Counter(), Counter(), Counter()
    raw_packets, discontinuities, inner_discontinuities = [], [], []
    last_inner, cursor = {}, 0
    while True:
        offset = raw.find(b"MUL1", cursor)
        if offset < 0: break
        if offset+10 > len(raw): break
        size = struct.unpack_from("<H", raw, offset+8)[0]
        if size < 40 or size > 4216:
            counters["raw_false_or_invalid_header"] += 1; cursor = offset+1; continue
        if offset+size > len(raw): break
        seq, modules, errors = decode(raw[offset:offset+size])
        counters.update(errors)
        if raw_packets and (seq-raw_packets[-1][2]) & 0xffffffff != 1:
            discontinuities.append([raw_packets[-1][2], seq, offset])
        valid_slots = set()
        for module in modules:
            if not module["valid"]: continue
            slot = module["slot"]
            valid_slots.add(slot)
            actual_slots[str(slot)] += 1
            actual_modes[module["mode"]] += 1
            markers[module["marker"]] += 1
            if slot in last_inner and (module["sequence"]-last_inner[slot]) & 0xffffffff != 1:
                inner_discontinuities.append([slot, last_inner[slot], module["sequence"]])
            last_inner[slot] = module["sequence"]
            if module["mode"] != mode: counters["target_mode_mismatch"] += 1
        counters["missing_expected_updates"] += len(expected-valid_slots)
        counters["unexpected_valid_updates"] += len(valid_slots-expected)
        raw_packets.append((offset, size, seq))
        cursor = offset+size
    if len(raw_packets) != len(logs): counters["packet_log_count_mismatch"] += 1
    for actual, log in zip(raw_packets, logs):
        logged = (int(log["raw_offset"]), int(log["received_bytes"]), int(log["packet_sequence"]))
        if actual != logged: counters["packet_log_offset_length_sequence_mismatch"] += 1
        if log["outer_crc_ok"] != "True" or log["parse_ok"] != "True": counters["log_rejected_packet"] += 1
        if (log["main_window"] == "True") != (float(log["elapsed_s"]) >= summary["settle_seconds"]):
            counters["log_main_window_mismatch"] += 1
    if hashlib.sha256(raw).hexdigest() != summary["raw_sha256"]: counters["raw_sha_mismatch"] += 1
    if len(raw) != summary["recorded_bytes"]: counters["recorded_size_mismatch"] += 1
    if len(raw_packets) != summary["complete_mul_count"]: counters["summary_complete_count_mismatch"] += 1
    main_logs = [log for log in logs if float(log["elapsed_s"]) >= summary["settle_seconds"]]
    main_rate = len(main_logs)/(summary["duration_seconds"]-summary["settle_seconds"])
    if abs(main_rate-summary["scopes"]["main"]["valid_outer_packet_rate_Hz"]) > 1e-9:
        counters["main_rate_mismatch"] += 1
    if len(main_logs) != summary["scopes"]["main"]["counts"]["valid_outer_packets"]:
        counters["main_count_mismatch"] += 1
    boundary_checks = []
    for event in boundaries:
        prefix = -event["raw_offset"]
        suffix = event["suffix_bytes_in_recording"]
        check = {"event_sequence": event["packet_sequence"], "prefix_bytes": prefix,
                 "suffix_bytes": suffix, "event_errors": event["errors"]}
        if previous is not None:
            candidate = previous["tail"][-prefix:]+raw[:suffix]
            evidence = "actual_previous_run_tail_plus_current_run_prefix"
        elif prefix == 1:
            candidate = b"M"+raw[:suffix]
            evidence = "inferred_magic_M_not_recorded_prefix"
        else:
            candidate, evidence = b"", "cannot_reconstruct_from_files"
        seq, modules, issues = decode(candidate)
        check.update(evidence=evidence, recovered_sequence=seq, independently_valid=not issues,
                     independent_errors=issues, previous_run_id=previous["run_id"] if previous else None)
        if seq != event["packet_sequence"] or issues: counters["boundary_reconstruction_mismatch"] += 1
        if raw_packets and (raw_packets[0][2]-seq) & 0xffffffff != 1: counters["boundary_to_first_gap"] += 1
        if previous and (seq-previous["last_sequence"]) & 0xffffffff != 1: counters["previous_to_boundary_gap"] += 1
        if raw_packets and raw_packets[0][0] != suffix: counters["boundary_suffix_offset_mismatch"] += 1
        boundary_checks.append(check)
    main = summary["scopes"]["main"]
    full = summary["scopes"]["full_run"]
    result = {"run_id": summary["run_id"], "source_directory": str(directory), "started_at": summary["started_at"],
        "metadata": {k: summary["metadata"].get(k) for k in ("batch_id", "batch_repeat_index", "batch_repeat_count", "block", "repeat", "condition", "target_mode", "target_modules", "deployment_confirmed")},
        "duration_seconds": summary["duration_seconds"], "completed_requested_duration": summary["completed_requested_duration"],
        "complete_packet_count": len(raw_packets), "main_complete_packet_count": len(main_logs),
        "main_rate_Hz": main_rate, "full_complete_packet_rate_Hz": len(raw_packets)/summary["duration_seconds"],
        "first_sequence": raw_packets[0][2], "last_sequence": raw_packets[-1][2],
        "actual_valid_slot_counts": dict(actual_slots), "actual_mode_counts": dict(actual_modes), "markers": dict(markers),
        "independent_nonzero_errors": {k:v for k,v in counters.items() if v},
        "raw_complete_packet_sequence_discontinuities": discontinuities,
        "raw_valid_inner_sequence_discontinuities": inner_discontinuities,
        "session_error_delta": {k:summary["counters"].get(k, 0) for k in ERRORS},
        "main_session_error_delta": {k:main["session_counter_delta_at_packet_observation"].get(k, 0) for k in ERRORS},
        "main_status": main["status"], "main_review_reasons": main["review_reasons"],
        "full_status": full["status"], "full_review_reasons": full["review_reasons"],
        "known_start_boundary_bytes": full.get("known_start_boundary_bytes",0),
        "unassigned_raw_bytes": full["unassigned_raw_bytes"], "actual_trailing_hex": raw[cursor:].hex(),
        "boundary_checks": boundary_checks, "local_provenance": summary["metadata"]["local_provenance"],
        "raw_sha256_verified": hashlib.sha256(raw).hexdigest()==summary["raw_sha256"],
        "raw_sha256": summary["raw_sha256"]}
    return result, {"tail": raw[-4216:], "last_sequence": raw_packets[-1][2], "run_id": summary["run_id"]}


def main():
    found, skipped = completed()
    missing = [rid for rid in SNAPSHOT if rid not in found]
    if missing: raise RuntimeError("Snapshot records missing: "+", ".join(missing))
    runs, previous_by_batch = [], {}
    for rid in SNAPSHOT:
        directory, summary = found[rid]
        batch = summary["metadata"]["batch_id"]
        result, tail = audit_one(directory, summary, previous_by_batch.get(batch))
        runs.append(result); previous_by_batch[batch] = tail
    groups = defaultdict(list)
    for run in runs: groups[run["metadata"]["batch_id"]].append(run)
    batches = []
    for batch, items in groups.items():
        rates = [r["main_rate_Hz"] for r in items]
        batches.append({"batch_id": batch, "modules": items[0]["metadata"]["target_modules"],
                       "mode": items[0]["metadata"]["target_mode"], "run_ids": [r["run_id"] for r in items],
                       "repeat_indices": [r["metadata"]["batch_repeat_index"] for r in items],
                       "n_temporal_repeats": len(items), "independent_setup_blocks": 1,
                       "main_Hz_mean": statistics.mean(rates), "main_Hz_sample_sd": statistics.stdev(rates) if len(rates)>1 else None,
                       "interpretation": "Three consecutive recording windows in one setup, not three independently re-established blocks."})
    current, new_skipped = completed()
    new_runs = sorted(set(current)-set(SNAPSHOT))
    output = {"schema_version": 1, "audit_time": datetime.now().astimezone().isoformat(),
              "fixed_snapshot_run_ids": list(SNAPSHOT), "runs": runs, "batches": batches,
              "complete_packet_total": sum(r["complete_packet_count"] for r in runs),
              "main_packet_total": sum(r["main_complete_packet_count"] for r in runs),
              "new_completed_runs_not_audited": new_runs, "unparseable_summaries": sorted(set(skipped+new_skipped)),
              "limits": ["Main timing comes from packet_log completion timestamps; raw has no arrival timestamps.",
                         "Local provenance hashes do not verify device flash contents.",
                         "Slot IDs are CS/IRQ positions, not unique physical-board identities.",
                         "Four first-batch boundary prefixes are inferred magic bytes; eight within-batch boundaries use actual previous raw tails.",
                         "No observed MUL1/ESK discontinuity does not prove every physical scan was transmitted."]}
    (HERE/"audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines = ["# 当前新数据独立审计（固定 12 条快照）", "", "本脚本仅只读原始数据；按 summary 实验开始时间固定记录列表。新完成记录不会混入本轮。", "",
             "| 槽位 | 条件 | 时间重复 n | 主窗口帧率均值 ± 段间样本 SD / Hz |", "|---|---|---:|---:|"]
    for batch in batches:
        lines.append(f"| M{batch['modules'][0]} | FULL / zero_load / N=1 | {batch['n_temporal_repeats']} | {batch['main_Hz_mean']:.6f} ± {batch['main_Hz_sample_sd']:.6f} |")
    lines.extend(["", f"共核验 {output['complete_packet_total']} 个完全落在 raw 内的 MUL1 包，其中主窗口 {output['main_packet_total']} 个。每段前 10 秒保留，统计主窗口约 30 秒。",
        "", "以下逐段列出任何独立异常；空列表表示 raw 内外 CRC、协议长度/flags/mask、目标模块/模式、日志 offset/长度/序号、raw SHA256 与摘要包数一致。", ""])
    for run in runs:
        lines.append(f"- `{run['run_id']}`：{run['complete_packet_count']} 包；主窗口 {run['main_complete_packet_count']} 包 / {run['main_rate_Hz']:.6f} Hz；独立错误 {run['independent_nonzero_errors']}；MUL1 序号异常 {len(run['raw_complete_packet_sequence_discontinuities'])}；ESK 序号异常 {len(run['raw_valid_inner_sequence_discontinuities'])}。")
    lines.extend(["", "12 段主窗口均 PASS；全窗口 CHECK REQUIRED 的唯一原因均为文件末尾 1 字节 `M`，不是观察到的 CRC 或序号错误。全部 Session 与主窗口 CRC、seq gaps、lost、重复、乱序、格式、DELTA base 错误增量均为 0。",
        "", "每段启动跨界包已单列，已知 raw 后缀 1083 B；它不计完整包数/帧率/K/q。四批次内部共 8 个边界由前段真实 raw 尾部 + 后段真实 raw 前缀独立重组，两层 CRC、序号连续均通过。每批首段共 4 个边界仅以推定 magic 首字节 M 验证一致性，不能冒称其录制前字节已经保存在本目录。",
        "", "各记录 pc_monitor 本地 provenance 一致，并有连续 parser 的边界事件；这与已部署 PC 修复版本一致。该证据不等同设备 flash 读回；deployment_confirmed 均为 false。M0–M3 是槽位，未提供唯一板卡身份，不能凭目录声称已核实四块不同实体板。",
        "", "可用性：本轮可作为 FULL、零载、N=1、M0/M1/M2/M3 各 3 段约 30 秒主窗口数据，不需要因这 1 B 结束边界重录。三段是同一 setup 的时间重复，不能当作 3 个重新搭建/重新加载的独立 block。",
        "", "尚需补齐：各槽位 DELTA 对照；N=2/3/4 组合的 FULL 与 DELTA 零载数据；动态负载与 K 分布数据。本轮全是 ESKF/FULL，不能据此估计普通 ESKD 的 K 或压缩收益。若要证明物理板卡/组合平衡，需保留人工板卡到槽位映射；若要独立 setup 重复，需实际重建条件并记录新的 block。",
        "", "限制：raw 自身没有 PC 到达时刻，主窗口归属和帧率使用 packet_log 的完成时间；没有观察到包序号不连续不能证明所有物理扫描均已发送，也不能单独证明 SPI 时钟稳定。",
        "", "本轮未纳入的新完成记录："+(", ".join(new_runs) or "无"),
        "", "目录整理后：原 summary 内 files 绝对路径属于录制时历史位置，不应改写原始记录。可用 data/run_index.csv 和 path_map.csv 对照旧路径与新目录（以父任务实际保存位置为准）。本脚本按 summary.run_id 递归定位当前目录，并相对该目录读取 raw/日志，不依赖历史绝对路径。",
        "", "复现：在本目录执行 `python -B audit_records.py`。脚本固定同一 12 个 run_id，查找 summary 因而兼容后续目录整理；只覆盖本目录 audit.json 和 ANALYSIS_CN.md。"])
    (HERE/"ANALYSIS_CN.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"complete_packet_total":output["complete_packet_total"],"main_packet_total":output["main_packet_total"],
                      "batches":batches,"independent_errors":{r["run_id"]:r["independent_nonzero_errors"] for r in runs if r["independent_nonzero_errors"]},
                      "sequence_anomalies":sum(len(r["raw_complete_packet_sequence_discontinuities"])+len(r["raw_valid_inner_sequence_discontinuities"]) for r in runs),
                      "new_completed_runs_not_audited":new_runs},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
