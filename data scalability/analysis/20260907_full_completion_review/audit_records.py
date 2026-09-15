"""Fixed six-run FULL completion audit, supporting mixed N=3 / N=4.

This contains the N=3 auditor's independent raw/module-log checking function,
with expected packet size 40+1044*N and conditional module counts based on N.
No production GUI/recorder code is imported. Overlapping and bad candidates
remain visible. Only this directory's JSON/Markdown outputs are written.
"""
from collections import Counter,defaultdict
from datetime import datetime
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import zlib

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("independent_n3_audit",HERE.parent/"20260907_n3_full_review"/"audit_records.py")
prior=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(prior)
base=prior.base
gaps=prior.gaps
compact=prior.compact
discontinuities=prior.discontinuities
SNAPSHOT=("20260907_004948_668301","20260907_005028_724004","20260907_005108_797842",
          "20260907_005250_875035","20260907_005330_930696","20260907_005410_996854")
KNOWN_PRIOR=set(prior.KNOWN_PRIOR)|set(prior.SNAPSHOT)
assert len(KNOWN_PRIOR)==42


def stats(values):
 return {"n":len(values),"mean":statistics.mean(values) if values else None,
         "sample_sd":statistics.stdev(values) if len(values)>1 else None}


def audit_one(directory,s,previous):
 raw=(directory/"mul1_raw.bin").read_bytes()
 with (directory/"packet_log.csv").open(encoding="utf-8-sig",newline="") as f:logs=list(csv.DictReader(f))
 events=[json.loads(line) for line in (directory/"events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
 boundary_events=[e for e in events if e["event"]=="capture_start_boundary"]
 candidates=[];cursor=0;partials=[]
 while True:
  offset=raw.find(b"MUL1",cursor)
  if offset<0:break
  cursor=offset+1
  if offset+20>len(raw):partials.append({"offset":offset,"available_bytes":len(raw)-offset});continue
  size=struct.unpack_from("<H",raw,offset+8)[0]
  if raw[offset+4:offset+6]!=b"\x02\x04" or not 40<=size<=4216:continue
  if offset+size>len(raw):partials.append({"offset":offset,"declared_bytes":size,"available_bytes":len(raw)-offset});continue
  data=raw[offset:offset+size]
  seq,modules,errors=base.decode(data)
  calculated=zlib.crc32(data[:-4]);stored=struct.unpack_from("<I",data,len(data)-4)[0]
  candidates.append({"offset":offset,"length":size,"sequence":seq,"host_ms":struct.unpack_from("<I",data,16)[0],
                     "outer_crc_valid":calculated==stored,"crc_calculated":f"0x{calculated:08x}","crc_stored":f"0x{stored:08x}",
                     "independent_decode_errors":errors,"modules":modules})
 by_offset={c["offset"]:c for c in candidates};logged_offsets={int(r["raw_offset"]) for r in logs}
 raw_valid=[c for c in candidates if c["outer_crc_valid"]]
 rejected=[c for c in candidates if not c["outer_crc_valid"]]
 unlogged=[c for c in raw_valid if c["offset"] not in logged_offsets]
 checks=Counter();accepted=[];main_accepted=[];module_counts=Counter();module_modes=Counter();inner_chains=defaultdict(list)
 log_errors=[];module_row_count=0;logged_bad=[]
 expected=set(s["metadata"]["target_modules"])
 module_count=len(expected)
 expected_packet_bytes=40+1044*module_count
 with (directory/"module_log.csv").open(encoding="utf-8-sig",newline="") as f:
  module_rows=csv.DictReader(f)
  for r in logs:
   offset=int(r["raw_offset"]);c=by_offset.get(offset)
   if c is None:checks["logged_candidate_not_found_in_raw"]+=1;continue
   is_main=float(r["elapsed_s"])>=s["settle_seconds"]
   if c["length"]!=int(r["received_bytes"]) or c["sequence"]!=int(r["packet_sequence"]) or c["host_ms"]!=int(r["host_ms"]):checks["packet_log_offset_header_mismatch"]+=1
   if (r["outer_crc_ok"]=="True")!=c["outer_crc_valid"]:checks["packet_log_crc_verdict_mismatch"]+=1
   if (r["main_window"]=="True")!=is_main:checks["packet_log_main_window_mismatch"]+=1
   if c["length"]!=expected_packet_bytes:checks["candidate_length_not_expected"]+=1
   if not c["outer_crc_valid"]:
    logged_bad.append(compact(c)|{"elapsed_s":float(r["elapsed_s"]),"main_window":is_main,"packet_completed_time":r["packet_completed_time"],"logged_error":r["error"]})
    continue
   accepted.append(c)
   if is_main:main_accepted.append(c)
   if c["independent_decode_errors"]:log_errors.append({"offset":offset,"errors":c["independent_decode_errors"]})
   if r["parse_ok"]!="True":checks["valid_outer_packet_rejected_by_pc"]+=1
   valid_slots={m["slot"] for m in c["modules"] if m["valid"]}
   checks["missing_expected_updates_in_valid_envelopes"]+=len(expected-valid_slots)
   checks["unexpected_valid_updates"]+=len(valid_slots-expected)
   for m in c["modules"]:
    row=next(module_rows,None)
    if row is None:checks["module_log_missing_row"]+=1;continue
    module_row_count+=1
    values={"packet_sequence":str(c["sequence"]),"module_id":str(m["slot"]),"status":f"0x{m['status']:02x}",
            "expected":str(m["slot"] in expected),"valid":str(m["valid"]),"payload_bytes":str(m["bytes"]),
            "marker":m.get("marker",""),"mode":m.get("mode",""),"main_window":str(is_main),
            "flags":f"0x{m['flags']:02x}" if "flags" in m else "", "sequence":str(m["sequence"]) if "sequence" in m else "",
            "base_sequence":str(m["base"]) if "base" in m else "", "K":str(m["K"]) if "K" in m else ""}
    if any(row.get(k)!=v for k,v in values.items()) or float(row["elapsed_s"])!=float(r["elapsed_s"]) or row["error"]:checks["module_log_row_mismatch"]+=1
    if m["valid"]:
     module_counts[str(m["slot"])]+=1;module_modes[m["mode"]]+=1
     if m["mode"]!="FULL" or m["flags"]!=0x13:checks["active_module_not_full_0x13"]+=1
  extra=sum(1 for _ in module_rows)
  if extra:checks["module_log_extra_rows"]+=extra
 for c in raw_valid:
  for m in c["modules"]:
   if m["valid"]:inner_chains[m["slot"]].append({"sequence":m["sequence"],"offset":c["offset"]})
 if hashlib.sha256(raw).hexdigest()!=s["raw_sha256"]:checks["raw_sha_mismatch"]+=1
 if len(raw)!=s["recorded_bytes"]:checks["raw_size_mismatch"]+=1
 if len(logs)!=s["recorded_candidate_rows"]:checks["summary_logged_candidate_count_mismatch"]+=1
 if len(accepted)!=s["complete_mul_count"]:checks["summary_logged_valid_count_mismatch"]+=1
 main=s["scopes"]["main"];full=s["scopes"]["full_run"]
 if len(main_accepted)!=main["counts"]["valid_outer_packets"]:checks["summary_main_valid_count_mismatch"]+=1
 rate=len(main_accepted)/(s["duration_seconds"]-s["settle_seconds"])
 if abs(rate-main["valid_outer_packet_rate_Hz"])>1e-9:checks["summary_main_rate_mismatch"]+=1
 for scope_name,valid_count in (("full_run",len(accepted)),("main",len(main_accepted))):
  scope=s["scopes"][scope_name]
  if scope["valid_expected_module_frames"]!=valid_count*module_count or scope["expected_module_update_opportunities"]!=valid_count*module_count:checks[scope_name+"_conditional_module_denominator_mismatch"]+=1
 boundary_checks=[];boundary_intervals=[]
 for e in boundary_events:
  prefix=-e["raw_offset"];suffix=e["suffix_bytes_in_recording"]
  if previous:
   prefix_data=previous["tail"][-prefix:];evidence="actual_previous_raw_tail"
  elif prefix==1:prefix_data=b"M";evidence="inferred_magic_M_not_recorded"
  else:prefix_data=b"";evidence="cannot_reconstruct"
  seq,mods,err=base.decode(prefix_data+raw[:suffix])
  boundary_checks.append({"sequence":e["packet_sequence"],"prefix_bytes":prefix,"suffix_bytes":suffix,"evidence":evidence,
                          "independent_errors":err,"decoded_sequence":seq,"event_errors":e["errors"]})
  if seq!=e["packet_sequence"] or err:checks["boundary_validation_mismatch"]+=1
  boundary_intervals.append((0,suffix))
 logged_gaps=gaps([(int(r["raw_offset"]),int(r["raw_offset"])+int(r["received_bytes"])) for r in logs]+boundary_intervals,len(raw))
 if sum(g["bytes"] for g in logged_gaps)!=full["unassigned_raw_bytes"]:checks["summary_unassigned_byte_mismatch"]+=1
 valid_gaps=gaps([(c["offset"],c["offset"]+c["length"]) for c in raw_valid]+boundary_intervals,len(raw))
 anomaly_context=[]
 for bad in logged_bad:
  i=next(i for i,c in enumerate(candidates) if c["offset"]==bad["offset"])
  neighbours=candidates[max(0,i-1):i+3]
  following=candidates[i+1] if i+1<len(candidates) else None
  anomaly_context.append({"rejected_logged_candidate":bad,"neighbour_candidates":[compact(c) for c in neighbours],
                          "distance_to_next_magic_bytes":following["offset"]-bad["offset"] if following else None,
                          "shortfall_vs_declared_length_bytes":bad["length"]-(following["offset"]-bad["offset"]) if following else None,
                          "overlapping_raw_valid_unlogged":[compact(c) for c in unlogged if bad["offset"]<c["offset"]<bad["offset"]+bad["length"]]})
 main_logs=[r for r in logs if r["outer_crc_ok"]=="True" and float(r["elapsed_s"])>=s["settle_seconds"]]
 timing=[]
 for a,b in zip(main_logs,main_logs[1:]):
  timing.append({"previous_sequence":int(a["packet_sequence"]),"sequence":int(b["packet_sequence"]),"elapsed_s":float(b["elapsed_s"]),
                 "pc_completion_gap_ms":1000*(float(b["elapsed_s"])-float(a["elapsed_s"])),
                 "bridge_host_gap_ms":(int(b["host_ms"])-int(a["host_ms"]))&0xffffffff})
 result={"run_id":s["run_id"],"directory":str(directory),"started_at":s["started_at"],"duration_seconds":s["duration_seconds"],
         "metadata":{k:s["metadata"].get(k) for k in ("target_modules","target_mode","condition","batch_id","batch_repeat_index","block","repeat")},
         "logged_candidate_count":len(logs),"logged_valid_outer_count":len(accepted),"logged_rejected_count":len(logged_bad),
         "main_logged_candidate_count":sum(float(r["elapsed_s"])>=s["settle_seconds"] for r in logs),"main_logged_valid_count":len(main_accepted),
         "raw_all_magic_candidate_count":len(candidates),"raw_independent_valid_outer_count":len(raw_valid),"raw_crc_bad_candidate_count":len(rejected),
         "raw_valid_unlogged_packets":[compact(c) for c in unlogged],"module_log_rows_checked":module_row_count,
         "logged_valid_module_counts":dict(module_counts),"actual_modes":dict(module_modes),"cross_check_errors":{k:v for k,v in checks.items() if v},
         "valid_envelope_decode_errors":log_errors,"logged_valid_sequence_discontinuities":discontinuities(accepted),
         "raw_valid_sequence_discontinuities":discontinuities(raw_valid),"raw_valid_inner_sequence_discontinuities":{str(k):discontinuities(v) for k,v in inner_chains.items() if discontinuities(v)},
         "main_status":main["status"],"full_status":full["status"],"main_review_reasons":main["review_reasons"],"full_review_reasons":full["review_reasons"],
         "main_Hz":rate,"main_Lmean_B":main["Lmean_valid_packet_B"],"main_packet_Mbit_per_s":main["packet_completion_Mbit_per_s"],
         "session_error_delta":{k:s["counters"].get(k,0) for k in base.ERRORS},"main_session_error_delta":{k:main["session_counter_delta_at_packet_observation"].get(k,0) for k in base.ERRORS},
         "logged_unassigned_ranges":logged_gaps,"forensic_valid_packet_uncovered_ranges":valid_gaps,"boundary_checks":boundary_checks,
         "trailing_partial_candidates":partials,"anomaly_context":anomaly_context,"raw_sha256":s["raw_sha256"],
         "main_timing_largest_pc_gaps":sorted(timing,key=lambda p:p["pc_completion_gap_ms"],reverse=True)[:5],
         "main_timing_largest_bridge_gaps":sorted(timing,key=lambda p:p["bridge_host_gap_ms"],reverse=True)[:5]}
 return result,{"tail":raw[-4216:],"run_id":s["run_id"]}


def main():
 found,skipped=base.completed()
 missing=set(SNAPSHOT)-set(found)
 if missing:raise RuntimeError("Fixed snapshot missing: "+", ".join(sorted(missing)))
 previous={};runs=[]
 for rid in SNAPSHOT:
  directory,s=found[rid];batch=s["metadata"]["batch_id"]
  result,tail=audit_one(directory,s,previous.get(batch));previous[batch]=tail
  result["configured_module_count"]=len(s["metadata"]["target_modules"])
  result["expected_full_packet_B"]=40+1044*result["configured_module_count"]
  result["recorded_pc_monitor_sha256"]=s["metadata"]["local_provenance"]["files"]["pc_monitor"]["sha256"]
  result["main_raw_arrival_Mbit_per_s"]=s["scopes"]["main"]["raw_arrival_Mbit_per_s"]
  result["completed_requested_duration"]=s["completed_requested_duration"]
  runs.append(result)
 grouped=defaultdict(list)
 for r in runs:grouped[r["metadata"]["batch_id"]].append(r)
 groups=[]
 for batch,items in grouped.items():
  groups.append({"batch_id":batch,"slots":items[0]["metadata"]["target_modules"],"N":items[0]["configured_module_count"],
                 "run_ids":[r["run_id"] for r in items],"repeat_indices":[r["metadata"]["batch_repeat_index"] for r in items],
                 "main_PASS":sum(r["main_status"]=="PASS" for r in items),"full_PASS":sum(r["full_status"]=="PASS" for r in items),
                 "main_Hz":stats([r["main_Hz"] for r in items]),"main_Lmean_B":stats([r["main_Lmean_B"] for r in items]),
                 "main_packet_Mbit_per_s":stats([r["main_packet_Mbit_per_s"] for r in items]),
                 "main_raw_arrival_Mbit_per_s":stats([r["main_raw_arrival_Mbit_per_s"] for r in items])})
 totals={k:sum(r[k] for r in runs) for k in ("logged_candidate_count","logged_valid_outer_count","logged_rejected_count","main_logged_candidate_count","main_logged_valid_count","raw_all_magic_candidate_count","raw_independent_valid_outer_count","module_log_rows_checked")}
 totals.update(logged_valid_ESKF=sum(sum(r["logged_valid_module_counts"].values()) for r in runs),
               main_logged_valid_ESKF=sum(r["main_logged_valid_count"]*r["configured_module_count"] for r in runs),
               main_PASS=sum(r["main_status"]=="PASS" for r in runs),full_PASS=sum(r["full_status"]=="PASS" for r in runs))
 current,_=base.completed();new=sorted(set(current)-KNOWN_PRIOR-set(SNAPSHOT))
 boundaries=[b for r in runs for b in r["boundary_checks"]]
 totals.update(actual_cross_file_boundaries=sum(b["evidence"]=="actual_previous_raw_tail" for b in boundaries),
               inferred_magic_boundaries=sum(b["evidence"]=="inferred_magic_M_not_recorded" for b in boundaries))
 nonzero={r["run_id"]:{"cross_check_errors":r["cross_check_errors"],"CRC_bad":r["raw_crc_bad_candidate_count"],
                       "unlogged_valid":len(r["raw_valid_unlogged_packets"]),"raw_sequence_gaps":r["raw_valid_sequence_discontinuities"],
                       "inner_sequence_gaps":r["raw_valid_inner_sequence_discontinuities"],"decode_errors":r["valid_envelope_decode_errors"]}
          for r in runs if r["cross_check_errors"] or r["raw_crc_bad_candidate_count"] or r["raw_valid_unlogged_packets"] or r["raw_valid_sequence_discontinuities"] or r["raw_valid_inner_sequence_discontinuities"] or r["valid_envelope_decode_errors"]}
 output={"schema_version":1,"audit_time":datetime.now().astimezone().isoformat(),"fixed_snapshot_run_ids":list(SNAPSHOT),
         "known_prior_42_run_ids_excluded":sorted(KNOWN_PRIOR),"totals":totals,"groups":groups,"runs":runs,
         "independent_nonzero_issues":nonzero,"new_completed_runs_not_audited":new,
         "history_note":"The prior M012 run 20260907_000133_670681 remains CHECK; these six successful new windows do not make all 48 historical runs error-free.",
         "timing_definition":"PC completion gaps and bridge host_ms gaps are separate observations, not equivalent clocks or proof of root cause."}
 (HERE/"audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 lines=["# FULL 补测完成审计：新 M012 批次与 N=4", "", "固定六条新完成记录，只读 raw/packet_log/module_log/events/summary，不改原文件。旧 42 条不算新增未审计。M012 新批次独立存放，原 Repeat 1–3 与原失败证据不覆盖。", "",
        "| 新批次 | n | 主窗 Hz 均值 ± 样本 SD | 完整包长度 B | 完整包吞吐 Mbit/s 均值 ± SD | main/full PASS |",
        "|---|---:|---:|---:|---:|---:|"]
 for group in groups:
  h=group["main_Hz"];b=group["main_packet_Mbit_per_s"]
  lines.append(f"| {'+'.join('M'+str(x) for x in group['slots'])} / N={group['N']} | {h['n']} | {h['mean']:.6f} ± {h['sample_sd']:.6f} | {group['main_Lmean_B']['mean']:.0f} | {b['mean']:.6f} ± {b['sample_sd']:.6f} | {group['main_PASS']}/{group['full_PASS']} |")
 lines.extend(["", f"逐包核验候选 {totals['logged_candidate_count']:,} / 有效 MUL1 {totals['logged_valid_outer_count']:,}，有效 ESKF {totals['logged_valid_ESKF']:,}；主窗口候选 {totals['main_logged_candidate_count']:,} / 有效 MUL1 {totals['main_logged_valid_count']:,} / ESKF {totals['main_logged_valid_ESKF']:,}。核对 {totals['module_log_rows_checked']:,} 行 module_log。",
        "", "长度按 N 动态验证：40+1044N，因此 N=3 为 3172 B、N=4 为 4216 B。扫描每个 MAGIC，包括可能被坏候选覆盖的内部 MAGIC；候选与有效包分别统计。独立核对外 CRC、内 CRC、版本/flags/mask、MUL1 和模块序号、实际有效槽位、日志 offset/长度/序号/时间/字段、raw SHA256 及原 summary 同口径计数。",
        "", "独立非零问题：`"+json.dumps(nonzero,ensure_ascii=False)+"`。", "",
        "全部六条主窗口 PASS，可用于各自条件的性能分析。全窗口三条 PASS，另三条仅因结束时保留 1 B M 片段而 CHECK；没有内部 unassigned、CRC、序号、漏更新或原日志未解析的有效重叠包。原状态不改。",
        "", f"启动边界共 {len(boundaries)} 个：{totals['actual_cross_file_boundaries']} 个用前段真实尾字节+后段真实前缀双层 CRC 验证；{totals['inferred_magic_boundaries']} 个每批首段仅补推定 M 验证一致性。边界后缀单列，不回填前缀，不混入完整包率/K/q。", "",
        "## 每段状态及时间停顿线索", ""])
 for r in runs:
  pc=r["main_timing_largest_pc_gaps"][0];host=r["main_timing_largest_bridge_gaps"][0]
  lines.append(f"- `{r['run_id']}`：N={r['configured_module_count']}；候选/有效 {r['logged_candidate_count']}/{r['logged_valid_outer_count']}；main={r['main_status']} / full={r['full_status']}；主窗 {r['main_Hz']:.6f} Hz。最大 PC 包完成间隔 {pc['pc_completion_gap_ms']:.6f} ms（桥端相邻间隔 {pc['bridge_host_gap_ms']} ms）；最大桥端 host_ms 间隔 {host['bridge_host_gap_ms']} ms（{host['previous_sequence']}→{host['sequence']}）。")
 lines.extend(["", "PC 完成间隔受读取、缓冲与调度影响，不等同 SPI 时钟周期；桥端 host_ms 也是协议时间字段。这些停顿线索与序号/CRC审计分开保留，不能只凭一次时间间隔定位硬件、USB或PC根因。",
        "", "历史必须保留：原 M012 `20260907_000133_670681` 的主窗口仍为 CHECK，包含短缺/损坏候选及一个 raw 可恢复、PC漏解析的包。本轮新批次通过，不能改写为之前全部 48 条均无错误。新三条 M012 是补测批次；此前两条 PASS 可由父任务在明确批次来源后另行汇总，原失败条不覆写。",
        "", "三段是同一 setup 的连续时间重复，不等于独立重新搭建 block；物理板身份不能从槽位ID唯一确定；记录内本地源文件hash不等于设备flash读回。本轮完成的是FULL零载条件，DELTA及动态/K实验仍需独立数据。",
        "", "迁移后脚本按 summary.run_id 递归定位当前目录，可查父任务 run_index/path_map；原summary历史files路径不改。复现：`python -B audit_records.py`。新完成未纳入记录："+(", ".join(new) or "无")])
 (HERE/"ANALYSIS_CN.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
 print(json.dumps({"totals":totals,"groups":groups,"independent_nonzero_issues":nonzero,
                   "max_timing_by_run":{r["run_id"]:{"pc_ms":r["main_timing_largest_pc_gaps"][0]["pc_completion_gap_ms"],"bridge_ms":r["main_timing_largest_bridge_gaps"][0]["bridge_host_gap_ms"]} for r in runs},
                   "session_nonzero_errors":{r["run_id"]:{k:v for k,v in r["session_error_delta"].items() if v} for r in runs if any(r["session_error_delta"].values())},
                   "new_completed_runs_not_audited":new},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
