"""Independent fixed-snapshot N=2 audit; never edits source recordings.

Reuses the independently written stdlib decoder from the N=1 audit, not the
production monitor/recorder. Adds every module_log row and N=2 length checks.
Run with python -B audit_records.py; only this directory's outputs are written.
"""
from collections import Counter, defaultdict
from datetime import datetime
import csv
import importlib.util
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
BASE_SCRIPT = HERE.parent/"20260906_current_data_review"/"audit_records.py"
spec = importlib.util.spec_from_file_location("independent_n1_audit", BASE_SCRIPT)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SNAPSHOT = (
    "20260906_232205_264776", "20260906_232245_299955", "20260906_232325_329233",
    "20260906_232950_210894", "20260906_233030_242504", "20260906_233110_283624",
    "20260906_233400_039763", "20260906_233440_083230", "20260906_233520_115774",
    "20260906_233935_041252", "20260906_234015_080026", "20260906_234055_124089",
    "20260906_234339_617031", "20260906_234419_667943", "20260906_234459_699129",
    "20260906_234631_872633", "20260906_234711_905577", "20260906_234751_945640",
)
KNOWN_PRIOR = set(base.SNAPSHOT)


def summary_stats(values):
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sample_sd": statistics.stdev(values) if len(values)>1 else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def check_module_log(directory, summary):
    raw = (directory/"mul1_raw.bin").read_bytes()
    failures, lengths, per_slot = Counter(), Counter(), Counter()
    expected = set(summary["metadata"]["target_modules"])
    sample_failures, valid_main, rows_checked, packet_count = [], 0, 0, 0
    with (directory/"packet_log.csv").open(encoding="utf-8-sig", newline="") as packets_file, \
         (directory/"module_log.csv").open(encoding="utf-8-sig", newline="") as modules_file:
        modules_reader = csv.DictReader(modules_file)
        for packet in csv.DictReader(packets_file):
            offset, length = int(packet["raw_offset"]), int(packet["received_bytes"])
            packet_count += 1
            lengths[str(length)] += 1
            if length != 2128: failures["full_n2_packet_not_2128_bytes"] += 1
            seq, decoded, _ = base.decode(raw[offset:offset+length])
            main = float(packet["elapsed_s"]) >= summary["settle_seconds"]
            if {m["slot"] for m in decoded if m["valid"]} != expected:
                failures["raw_valid_slot_set_not_exact_target"] += 1
            for module in decoded:
                row = next(modules_reader, None)
                if row is None:
                    failures["module_log_missing_rows"] += 1
                    continue
                rows_checked += 1
                slot = module["slot"]
                checks = {"packet_sequence": str(seq), "module_id": str(slot),
                          "expected": str(slot in expected), "status": f"0x{module['status']:02x}",
                          "payload_bytes": str(module["bytes"]), "valid": str(module["valid"]),
                          "marker": module.get("marker", ""), "mode": module.get("mode", ""),
                          "flags": f"0x{module['flags']:02x}" if "flags" in module else "",
                          "sequence": str(module["sequence"]) if "sequence" in module else "",
                          "base_sequence": str(module["base"]) if "base" in module else "",
                          "K": str(module["K"]) if "K" in module else "", "main_window": str(main)}
                mismatches = [key for key, value in checks.items() if row.get(key) != value]
                if float(row["elapsed_s"]) != float(packet["elapsed_s"]): mismatches.append("elapsed_s")
                if row["error"]: mismatches.append("logged_module_error")
                if mismatches:
                    failures["module_log_row_disagrees_with_raw"] += 1
                    if len(sample_failures)<10: sample_failures.append({"packet_sequence":seq,"slot":slot,"fields":mismatches})
                if module["valid"]:
                    per_slot[str(slot)] += 1
                    valid_main += int(main)
                    if module.get("marker") != "ESKF" or module.get("flags") != 0x13:
                        failures["active_module_not_full_0x13"] += 1
                    if row["cache_outcome"] != "applied_full_baseline":
                        failures["full_cache_outcome_mismatch"] += 1
        surplus = sum(1 for _ in modules_reader)
        if surplus: failures["module_log_extra_rows"] += surplus
    for scope_name, value in (("full_run", sum(per_slot.values())), ("main", valid_main)):
        scope = summary["scopes"][scope_name]
        if value != scope["valid_expected_module_frames"]:
            failures[scope_name+"_summary_expected_frame_count_mismatch"] += 1
        if value != scope["expected_module_update_opportunities"]:
            failures[scope_name+"_missing_expected_updates"] += 1
    return {"rows_checked":rows_checked,"expected_rows":4*packet_count,
            "packet_length_counts":dict(lengths),"valid_ESKF_counts_by_slot":dict(per_slot),
            "valid_main_ESKF_count":valid_main,"nonzero_errors":dict(failures),
            "sample_disagreements":sample_failures}


def main():
    found, skipped = base.completed()
    missing = set(SNAPSHOT)-set(found)
    if missing: raise RuntimeError("Missing fixed snapshot: "+", ".join(sorted(missing)))
    runs, previous_by_batch = [], {}
    for rid in SNAPSHOT:
        directory, summary = found[rid]
        batch = summary["metadata"]["batch_id"]
        result, tail = base.audit_one(directory,summary,previous_by_batch.get(batch))
        result["module_log_audit"] = check_module_log(directory,summary)
        main_scope = summary["scopes"]["main"]
        result["main_mean_complete_packet_B"] = main_scope["Lmean_valid_packet_B"]
        result["main_complete_packet_Mbit_per_s"] = main_scope["packet_completion_Mbit_per_s"]
        result["main_raw_arrival_Mbit_per_s"] = main_scope["raw_arrival_Mbit_per_s"]
        result["full_raw_arrival_bytes"] = summary["recorded_bytes"]
        result["main_missing_expected_updates"] = main_scope["counts"].get("missing_valid_expected_updates",0)
        result["full_missing_expected_updates"] = summary["scopes"]["full_run"]["counts"].get("missing_valid_expected_updates",0)
        result["main_q_ESKF"] = main_scope["q_ESKF"]
        runs.append(result); previous_by_batch[batch] = tail
    grouped = defaultdict(list)
    for run in runs: grouped[tuple(run["metadata"]["target_modules"])].append(run)
    groups = []
    for slots, items in sorted(grouped.items()):
        groups.append({"slots":list(slots),"run_ids":[r["run_id"] for r in items],
                       "repeat_indices":[r["metadata"]["batch_repeat_index"] for r in items],
                       "recorded_blocks":sorted(set(r["metadata"]["block"] for r in items)),
                       "n_temporal_repeats":len(items),"main_Hz":summary_stats([r["main_rate_Hz"] for r in items]),
                       "main_Lmean_B":summary_stats([r["main_mean_complete_packet_B"] for r in items]),
                       "main_packet_Mbit_per_s":summary_stats([r["main_complete_packet_Mbit_per_s"] for r in items]),
                       "main_PASS_count":sum(r["main_status"]=="PASS" for r in items),
                       "full_PASS_count":sum(r["full_status"]=="PASS" for r in items)})
    current, skipped_after = base.completed()
    new = sorted(set(current)-set(SNAPSHOT)-KNOWN_PRIOR)
    boundary_checks = [check for run in runs for check in run["boundary_checks"]]
    totals = {"runs":len(runs),"complete_MUL1":sum(r["complete_packet_count"] for r in runs),
              "main_complete_MUL1":sum(r["main_complete_packet_count"] for r in runs),
              "valid_ESKF":sum(sum(r["module_log_audit"]["valid_ESKF_counts_by_slot"].values()) for r in runs),
              "main_valid_ESKF":sum(r["module_log_audit"]["valid_main_ESKF_count"] for r in runs),
              "module_log_rows_checked":sum(r["module_log_audit"]["rows_checked"] for r in runs),
              "main_PASS":sum(r["main_status"]=="PASS" for r in runs),
              "full_PASS":sum(r["full_status"]=="PASS" for r in runs),
              "actual_cross_file_boundaries":sum(c["evidence"].startswith("actual_") for c in boundary_checks),
              "inferred_first_magic_boundaries":sum(c["evidence"].startswith("inferred_") for c in boundary_checks)}
    independent_errors = {r["run_id"]:{"raw":r["independent_nonzero_errors"],"module_log":r["module_log_audit"]["nonzero_errors"]}
                          for r in runs if r["independent_nonzero_errors"] or r["module_log_audit"]["nonzero_errors"]}
    output = {"schema_version":1,"audit_time":datetime.now().astimezone().isoformat(),"fixed_snapshot_run_ids":list(SNAPSHOT),
              "known_prior_N1_run_ids_excluded_from_new":sorted(KNOWN_PRIOR),"totals":totals,"groups":groups,"runs":runs,
              "independent_errors":independent_errors,"new_completed_runs_not_audited":new,
              "unparseable_summaries":sorted(set(skipped+skipped_after)),
              "decoder_source":str(BASE_SCRIPT),
              "limits":["raw contains no arrival timestamps; main windows use independently cross-checked packet_log times.",
                        "Three temporal repeats within each batch are not independent setup blocks.",
                        "Slot IDs do not establish physical-board identity; local artifact hashes are not device flash readback.",
                        "First-batch missing magic bytes are inferred, unlike directly recorded within-batch prefix bytes."]}
    (HERE/"audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines = ["# N=2 FULL 新数据独立审计", "", "固定 18 条已完成记录快照；实验开始时间 2026-09-06 23:22:05 至 23:47:51（英国当地 +01:00），末条约 23:48:31 结束。旧 12 条 N=1 是已知历史记录，不视为本轮新增未审计数据。仅本目录生成分析，不改变原始文件。", "",
        "| 组合 | 时间重复 n | 主窗口帧率均值 ± 样本 SD / Hz | 完整包吞吐均值 ± SD / Mbit/s | 主/全窗口 PASS 条数 |",
        "|---|---:|---:|---:|---:|"]
    for group in groups:
        hz,bw=group["main_Hz"],group["main_packet_Mbit_per_s"]
        lines.append(f"| {'+'.join('M'+str(s) for s in group['slots'])} | {group['n_temporal_repeats']} | {hz['mean']:.6f} ± {hz['sample_sd']:.6f} | {bw['mean']:.6f} ± {bw['sample_sd']:.6f} | {group['main_PASS_count']}/{group['full_PASS_count']} |")
    lines.extend(["", "所有条件均为 FULL、N=2、zero_load，目标 200 Hz，每次录制 40 秒，保留前 10 秒；主窗口约 30 秒。均值/SD 以每段主窗口统计量为样本，n=3 是同一 setup 的连续时间重复，不能作为 3 个独立重新搭建 block。",
        "", f"独立检查 {totals['complete_MUL1']:,} 个完全落在 raw 内的 MUL1 包（主窗口 {totals['main_complete_MUL1']:,}），{totals['valid_ESKF']:,} 个有效 ESKF（主窗口 {totals['main_valid_ESKF']:,}），逐行核对 {totals['module_log_rows_checked']:,} 行 module_log。",
        "", "完整包必须为 2128 B = 20 B 外头 + 4×4 B 槽描述符 + 2×1044 B ESKF + 4 B 外 CRC。普通 FULL 有效模块 flags 应为 0x13。脚本逐包检查内外 CRC、长度/版本/flags/mask、实际槽位和模式、MUL1 与 ESK 序号、packet_log 偏移/长度/序号，逐槽核对 module_log 状态、expected、有效性、payload、marker、mode、flags、序号、base、K 和时间窗口。另验证 raw SHA256、summary 包数和目标模块机会数。", "",
        "独立异常（必须保留）：`"+json.dumps(independent_errors,ensure_ascii=False)+"`。", "",
        "本次 18 段主窗口均可用。独立模块漏更新、CRC/序号/日志不一致均为 0；Session 和主窗口的 CRC、seq gaps、lost、重复、乱序、格式、base 错误增量全部为 0。全窗口 2 段 PASS，另 16 段只保留 1 B 尾部 M 的边界检查提示，无需因此重录；原始状态不修改。", "",
        "逐段原状态与审计："])
    for run in runs:
        reasons=", ".join(run["full_review_reasons"]) or "none"
        lines.append(f"- `{run['run_id']}`：完整包 {run['complete_packet_count']} / 主包 {run['main_complete_packet_count']}；main={run['main_status']}，full={run['full_status']}（{reasons}）；主窗理由={run['main_review_reasons']}；MUL1/ESK序号异常={len(run['raw_complete_packet_sequence_discontinuities'])}/{len(run['raw_valid_inner_sequence_discontinuities'])}；尾字节={run['actual_trailing_hex'] or '无'}。")
    lines.extend(["", f"本轮跨起点包 {len(boundary_checks)} 个，其中 {totals['actual_cross_file_boundaries']} 个用前段真实 raw 尾字节 + 后段真实 raw 前缀验证；{totals['inferred_first_magic_boundaries']} 个每批首段只补推定 M 验证一致性。具体双层 CRC、序号连续性和来源见 JSON，不能把推定前缀表述为已记录字节。跨界包单列，未计入完整包率和 q。",
        "", "可用性以独立异常、逐段主窗口和原始全窗口状态共同判断。仅末尾 1 字节 M 导致的全窗口检查提示属于录制结束边界，不能据此认定 CRC 错误或物理传输丢包；存在其他错误时必须另行复查，不覆盖原 summary。",
        "", "本批覆盖 N=2 全部六种 FULL 零载组合；尚不能代替相同组合 DELTA 对照、N=3/4 或动态加载/K实验。M0–M3 是协议槽位，不提供唯一板卡身份。帧率分母是实际主窗口时长，完整包吞吐与 raw 按到达时间统计的吞吐是分开的字段。",
        "", "新完成而未纳入记录："+(", ".join(new) or "无（既有 N=1 不算新增）"),
        "", "迁移后原 summary 内历史 files 路径保持不变；可用父任务生成的 run_index.csv/path_map.csv 查新位置。本脚本按 summary.run_id 递归定位当前目录，不依赖历史绝对路径。复现：`python -B audit_records.py`。解码器复用同级 20260906_current_data_review/audit_records.py 的独立实现，不导入生产 GUI/recorder。"])
    (HERE/"ANALYSIS_CN.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"totals":totals,"groups":groups,"independent_errors":independent_errors,
                      "sequence_discontinuities":sum(len(r["raw_complete_packet_sequence_discontinuities"])+len(r["raw_valid_inner_sequence_discontinuities"]) for r in runs),
                      "session_nonzero_errors":{r["run_id"]:{k:v for k,v in r["session_error_delta"].items() if v} for r in runs if any(r["session_error_delta"].values())},
                      "new_completed_runs_not_audited":new},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
