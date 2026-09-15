"""Fixed three-run follow-up audit. Only raw_audit.* derived files are written.

Reuses the same independent decoder used by the large-area audit, never the
production GUI parser. Original files remain in their timestamp directories.
"""
from collections import Counter
from datetime import datetime
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1]/"data"
PARSER = HERE.parent/"20260907_delta_zero_review"/"raw_audit.py"
spec = importlib.util.spec_from_file_location("fixed_independent_delta_auditor",PARSER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SNAPSHOT = ("20260907_053858_001637","20260907_053938_027960","20260907_054018_056649")


def file_hashes():
    result = {}
    for rid in SNAPSHOT:
        directory = DATA/rid
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(DATA))] = {"bytes":path.stat().st_size,
                                                      "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def packet_context(raw,row,slot):
    offset,length = int(row["raw_offset"]),int(row["received_bytes"])
    decoded = base.decode(raw[offset:offset+length])
    module = next((m for m in decoded["modules"] if m["slot"] == slot),None)
    return {"raw_offset":offset,"packet_bytes":length,"packet_sequence":decoded["sequence"],
            "host_ms":decoded.get("host_ms"),"elapsed_s":float(row["elapsed_s"]),
            "packet_completed_time":row["packet_completed_time"],"outer_crc_valid":decoded["outer_crc_valid"],
            "main_window":row["main_window"]=="True","module":module}


def add_context(directory,run,previous_run):
    raw = (directory/"mul1_raw.bin").read_bytes()
    with (directory/"packet_log.csv").open(encoding="utf-8-sig",newline="") as f: rows = list(csv.DictReader(f))
    index = {int(r["raw_offset"]):i for i,r in enumerate(rows)}
    for event in run["inner_sequence_discontinuities"]:
        i = index[event["offset"]]; slot = event["module"]
        points = {name:packet_context(raw,rows[j],slot) for name,j in (("before",i-1),("at",i),("after",i+1)) if 0<=j<len(rows)}
        event["context"] = points
        change = (event["sequence"]-event["previous"])&0xffffffff
        event["classification"] = "duplicate" if change == 0 else "forward_gap" if change<0x80000000 else "backward_or_reinitialization_pattern"
        event["unobserved_sequence_values"] = change-1 if 1<change<0x80000000 else None
        if "before" in points:
            event["bridge_host_gap_ms"] = (points["at"]["host_ms"]-points["before"]["host_ms"])&0xffffffff
            event["pc_completion_gap_ms"] = 1000*(points["at"]["elapsed_s"]-points["before"]["elapsed_s"])
        event["main_window"] = event["elapsed_s"]>=10
    actual = {}
    for slot in run["metadata"]["target_modules"]:
        actual[str(slot)] = {"first":packet_context(raw,rows[0],slot),"last":packet_context(raw,rows[-1],slot)}
    run["first_last_complete_packet"] = actual
    run["cross_run_sequence_checks"] = []
    if previous_run:
        for slot in run["metadata"]["target_modules"]:
            previous = previous_run["first_last_complete_packet"][str(slot)]["last"]
            current = actual[str(slot)]["first"]
            # One wholly excluded boundary packet bridges these two complete packets.
            boundary_packets = len(run["start_boundaries"])
            outer_difference = (current["packet_sequence"]-previous["packet_sequence"])&0xffffffff
            inner_difference = (current["module"]["sequence"]-previous["module"]["sequence"])&0xffffffff
            run["cross_run_sequence_checks"].append({"module":slot,"previous_run_id":previous_run["run_id"],
                "previous_packet_sequence":previous["packet_sequence"],"first_packet_sequence":current["packet_sequence"],
                "previous_inner_sequence":previous["module"]["sequence"],"first_inner_sequence":current["module"]["sequence"],
                "excluded_start_boundary_packets":boundary_packets,"outer_difference":outer_difference,"inner_difference":inner_difference,
                "matches_one_plus_excluded_boundary":outer_difference == inner_difference == 1+boundary_packets})


def main():
    before = file_hashes()
    runs = []; tails = {}; previous_by_batch = {}
    for rid in SNAPSHOT:
        directory = DATA/rid
        summary = json.loads((directory/"summary.json").read_text(encoding="utf-8"))
        if summary["run_id"] != rid or not summary["completed_requested_duration"]:
            raise ValueError("Fixed record incomplete or mismatched: "+rid)
        batch = summary["metadata"]["batch_id"]
        run,tail = base.audit_one(directory,summary,tails.get(batch)); tails[batch] = tail
        run["recorded_condition"] = summary["metadata"].get("condition")
        run["actual_condition"] = "rolling"
        run["actual_description"] = "rolling"
        run["actual_condition_source"] = "user_confirmed_rolling; original metadata preserved"
        run["requested_duration_seconds"] = summary["requested_duration_seconds"]
        run["duration_seconds"] = summary["duration_seconds"]
        add_context(directory,run,previous_by_batch.get(batch)); previous_by_batch[batch] = run
        independent_problems = bool(run["cross_check_errors"] or run["anomalies"] or run["raw_bad_outer_candidates"] or
                                    run["raw_valid_unlogged_packets"] or run["outer_sequence_discontinuities"] or
                                    run["inner_sequence_discontinuities"] or run["observed_base_discontinuities"] or
                                    any(g["kind"] == "interior" for g in run["unassigned_ranges"]) or
                                    any(run["scopes"]["full_run"]["counts"].get(k,0) for k in
                                        ("missing_valid_expected_updates","unexpected_valid_updates","target_mode_mismatch",
                                         "base_break_events_after_anchor","unapplied_after_anchor")) or
                                    any(not c["matches_one_plus_excluded_boundary"] for c in run["cross_run_sequence_checks"]))
        for scope in ("full_run","initial","main"):
            run["scopes"][scope]["inner_sequence_discontinuity_count"] = sum(
                scope == "full_run" or (scope == "main") == e["main_window"] for e in run["inner_sequence_discontinuities"])
        run["independent_protocol_findings"] = "CHECK REQUIRED" if independent_problems else "NO DETECTED PROTOCOL ANOMALY"
        runs.append(run)
        print(rid,"raw/log mismatches",run["cross_check_errors"],"inner gaps",len(run["inner_sequence_discontinuities"]),flush=True)
    after = file_hashes()
    changed = [name for name in sorted(set(before)|set(after)) if before.get(name)!=after.get(name)]
    totals = {}
    for scope in ("full_run","initial","main"):
        total = Counter()
        for r in runs: total.update(r["scopes"][scope]["counts"])
        total["inner_sequence_discontinuities"] = sum(r["scopes"][scope]["inner_sequence_discontinuity_count"] for r in runs)
        totals[scope] = dict(total)
    output = {"schema_version":1,"audit_at":datetime.now().astimezone().isoformat(),"snapshot_run_ids":list(SNAPSHOT),
              "audit_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "independent_parser":{"path":str(PARSER),"sha256":hashlib.sha256(PARSER.read_bytes()).hexdigest()},
              "original_files_before":before,"original_files_after":after,"changed_original_files":changed,
              "original_file_count":len(before),"original_bytes":sum(v["bytes"] for v in before.values()),
              "scope_note":"full_run counts complete packets within each file; initial is elapsed < 10 s; main is elapsed >= 10 s; excluded boundary packets remain separately audited",
              "condition_note":"metadata records zero_load; user explicitly confirmed rolling; original metadata preserved",
              "totals":totals,"runs":runs}
    (HERE/"raw_audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    issues = sum(len(r["inner_sequence_discontinuities"]) for r in runs)
    lines = ["# Rolling 三条 DELTA 记录：独立原始协议审计", "",
             "固定记录："+"、".join(SNAPSHOT)+"。原始目录未移动或分类，GUI与原始summary未修改。",
             "", "记录元数据均为zero_load；用户明确说明实际为rolling。派生分析保留recorded_condition=zero_load，并记录actual_condition=rolling与用户说明，不改写原始summary，也不补写未记录的力值、滚动物尺寸、路线或速度。",
             "", f"完整扫描{totals['full_run']['packet_candidates']:,}个MUL1候选、{totals['full_run']['valid_module_frames']:,}个有效模块内帧，并逐项核对{sum(r['module_log_rows_checked'] for r in runs):,}条模块CSV。共{len(before)}个原始/记录生成文件前后SHA-256一致：{not changed}。",
             "", "|窗口|候选MUL1|有效MUL1|ESKD|ESKF|初始无锚点ESKD|模块序号不连续|",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name,c in totals.items():
        lines.append("|"+name+"|"+"|".join(str(c.get(k,0)) for k in ("packet_candidates","valid_outer_packets","ESKD","ESKF","initial_unanchored_delta","inner_sequence_discontinuities"))+"|")
    lines += ["", "|Repeat|原主窗口状态|独立协议结论|主窗K_D|主窗q_ESKF|主窗平均包B|主窗PC包率Hz|",
              "|---|---|---|---:|---:|---:|---:|"]
    for r in runs:
        m = r["scopes"]["main"]
        lines.append(f"|{r['metadata']['repeat']}|{m['reported_status']}|{r['independent_protocol_findings']}|{m['K_ESKD']['mean']:.6f}|{m['q_ESKF']:.8f}|{m['Lmean_valid_packet_B']:.6f}|{m['valid_outer_packet_rate_Hz']:.6f}|")
    lines += ["", f"跨ESKD与ESKF统一检查模块sequence，共发现{issues}次不连续。有效ESKF建立新基线不会使本审计跳过sequence检查；此项独立检查覆盖原GUI的检查盲点，原GUI状态保持不变。"]
    for r in runs:
        if not r["inner_sequence_discontinuities"]: continue
        lines += ["", "## "+r["run_id"]+" 的模块序号事件", "",
                  "|elapsed s|前帧→当前帧|后帧|桥host_ms差/ms|PC间隔/ms|窗口|",
                  "|---:|---|---|---:|---:|---|"]
        for e in r["inner_sequence_discontinuities"]:
            points = e["context"]; a = points["before"]["module"]; b = points["at"]["module"]; c = points.get("after",{}).get("module",{})
            lines.append(f"|{e['elapsed_s']:.7f}|{a['marker']} {a['sequence']} → {b['marker']} {b['sequence']}|{c.get('marker','')} {c.get('sequence','')}|{e['bridge_host_gap_ms']}|{e['pc_completion_gap_ms']:.6f}|{'main' if e['main_window'] else 'initial'}|")
    lines += ["", "## CRC、缓存和文件边界", ""]
    for r in runs:
        c = r["scopes"]["full_run"]["counts"]
        lines.append(f"- {r['run_id']}：raw/log/summary差异={r['cross_check_errors']}；外CRC坏候选={len(r['raw_bad_outer_candidates'])}；外层序号事件={len(r['outer_sequence_discontinuities'])}；base不连续={len(r['observed_base_discontinuities'])}；目标缺更新={c.get('missing_valid_expected_updates',0)}；锚点后未应用={c.get('unapplied_after_anchor',0)}。")
        lines.append("  开始边界="+json.dumps(r["start_boundaries"],ensure_ascii=False)+"；未分配区="+json.dumps(r["unassigned_ranges"],ensure_ascii=False)+"。")
    lines += ["", "初始未锚定ESKD表示文件尚未包含基线，不证明传输丢帧；开始边界包不混入完整包数、K或q。实际前一文件尾部拼接与仅补magic单字节的推断在JSON中分别标注。",
              "", "q=全部有效ESKF/(ESKF+ESKD)，K_D仅由普通ESKD两层mask计数。ESKF触发原因没有独立事件字段，不能由ESKF或其出现时刻确诊硬件重启、供电原因或丢失物理扫描。序号跳变仅表明记录中的编号不连续。",
              "", "PC包完成时间决定初始/主窗口，桥host_ms是桥端时间字段；两者都不是直接SCK波形测量。三次连续录制是同一setup的时间重复。复现：`python -B -X utf8 raw_audit.py`。"]
    (HERE/"raw_audit.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"totals":totals,"changed_original_files":changed,"runs":[{"run_id":r['run_id'],"inner_sequence_events":len(r['inner_sequence_discontinuities'])} for r in runs]},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
