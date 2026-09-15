"""Read-only N=3 audit retaining bad, overlapping and unlogged candidates.

The independent stdlib decoder comes from the earlier audit, not production
code. Raw scans advance past each MAGIC by one byte, so a CRC-bad candidate
cannot hide a valid overlapping successor. No recovered packet is written back.
"""
from collections import Counter, defaultdict
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
SPEC=importlib.util.spec_from_file_location("independent_decoder",HERE.parent/"20260906_current_data_review"/"audit_records.py")
base=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(base)
SNAPSHOT=(
 "20260907_000133_670681","20260907_000213_737553","20260907_000253_764287",
 "20260907_001345_234235","20260907_001425_309099","20260907_001505_375008",
 "20260907_001710_986331","20260907_001751_034069","20260907_001831_069491",
 "20260907_003258_918645","20260907_003339_025463","20260907_003419_073823")
KNOWN_PRIOR=set(base.SNAPSHOT)
KNOWN_PRIOR.update(json.loads((HERE.parent/"20260906_n2_full_review"/"audit.json").read_text(encoding="utf-8"))["fixed_snapshot_run_ids"])


def stats(values):
 return {"n":len(values),"mean":statistics.mean(values) if values else None,
         "sample_sd":statistics.stdev(values) if len(values)>1 else None}


def discontinuities(items):
 out=[]
 for a,b in zip(items,items[1:]):
  difference=(b["sequence"]-a["sequence"])&0xffffffff
  if difference!=1:
   out.append({"previous":a["sequence"],"current":b["sequence"],"current_offset":b["offset"],
               "step":difference,"missing_sequence_numbers":difference-1 if 1<difference<0x80000000 else 0})
 return out


def gaps(intervals,total):
 merged=[]
 for begin,end in sorted(intervals):
  if merged and begin<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
  else: merged.append((begin,end))
 out=[];cursor=0
 for begin,end in merged:
  if begin>cursor:out.append({"start":cursor,"end":begin,"bytes":begin-cursor,"kind":"leading" if cursor==0 else "interior"})
  cursor=max(cursor,end)
 if cursor<total:out.append({"start":cursor,"end":total,"bytes":total-cursor,"kind":"trailing"})
 return out


def compact(candidate):
 return {key:value for key,value in candidate.items() if key not in ("modules",)} | {
  "module_sequences":{str(m["slot"]):m["sequence"] for m in candidate["modules"] if m.get("valid")}}


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
 with (directory/"module_log.csv").open(encoding="utf-8-sig",newline="") as f:
  module_rows=csv.DictReader(f)
  for r in logs:
   offset=int(r["raw_offset"]);c=by_offset.get(offset)
   if c is None:checks["logged_candidate_not_found_in_raw"]+=1;continue
   is_main=float(r["elapsed_s"])>=s["settle_seconds"]
   if c["length"]!=int(r["received_bytes"]) or c["sequence"]!=int(r["packet_sequence"]) or c["host_ms"]!=int(r["host_ms"]):checks["packet_log_offset_header_mismatch"]+=1
   if (r["outer_crc_ok"]=="True")!=c["outer_crc_valid"]:checks["packet_log_crc_verdict_mismatch"]+=1
   if (r["main_window"]=="True")!=is_main:checks["packet_log_main_window_mismatch"]+=1
   if c["length"]!=3172:checks["candidate_length_not_3172"]+=1
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
  if scope["valid_expected_module_frames"]!=valid_count*3 or scope["expected_module_update_opportunities"]!=valid_count*3:checks[scope_name+"_conditional_module_denominator_mismatch"]+=1
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
 if set(SNAPSHOT)-set(found):raise RuntimeError("Fixed snapshot contains missing records")
 runs=[];previous={}
 for rid in SNAPSHOT:
  directory,s=found[rid];batch=s["metadata"]["batch_id"]
  result,tail=audit_one(directory,s,previous.get(batch));previous[batch]=tail;runs.append(result)
 grouped=defaultdict(list)
 for run in runs:grouped[tuple(run["metadata"]["target_modules"])].append(run)
 groups=[]
 for slots,items in sorted(grouped.items()):
  passed=[r for r in items if r["main_status"]=="PASS"]
  groups.append({"slots":list(slots),"all_run_ids":[r["run_id"] for r in items],"PASS_run_ids":[r["run_id"] for r in passed],
                 "PASS_window_statistics":{"main_Hz":stats([r["main_Hz"] for r in passed]),"main_packet_Mbit_per_s":stats([r["main_packet_Mbit_per_s"] for r in passed])},
                 "all_runs_diagnostic_statistics":{"main_Hz":stats([r["main_Hz"] for r in items]),"main_packet_Mbit_per_s":stats([r["main_packet_Mbit_per_s"] for r in items])}})
 current,_=base.completed();new=sorted(set(current)-set(SNAPSHOT)-KNOWN_PRIOR)
 totals={k:sum(r[k] for r in runs) for k in ("logged_candidate_count","logged_valid_outer_count","logged_rejected_count","main_logged_candidate_count","main_logged_valid_count","raw_all_magic_candidate_count","raw_independent_valid_outer_count","module_log_rows_checked")}
 totals.update(main_PASS=sum(r["main_status"]=="PASS" for r in runs),full_PASS=sum(r["full_status"]=="PASS" for r in runs),
               logged_valid_ESKF=sum(sum(r["logged_valid_module_counts"].values()) for r in runs),
               main_logged_valid_ESKF=3*sum(r["main_logged_valid_count"] for r in runs),
               PASS_subset_main_logged_valid_MUL1=sum(r["main_logged_valid_count"] for r in runs if r["main_status"]=="PASS"),
               PASS_subset_main_logged_valid_ESKF=3*sum(r["main_logged_valid_count"] for r in runs if r["main_status"]=="PASS"))
 output={"schema_version":1,"audit_time":datetime.now().astimezone().isoformat(),"fixed_snapshot_run_ids":list(SNAPSHOT),
         "known_prior_excluded":sorted(KNOWN_PRIOR),"totals":totals,"groups":groups,"runs":runs,"new_completed_runs_not_audited":new,
         "definitions":{"logged_valid":"CRC-valid envelopes present in packet_log; comparable to original summary.",
                        "forensic_raw_valid":"All independently CRC-valid raw candidates, including overlaps missed by original live framer; never substituted into original statistics.",
                        "missing_updates":"Conditional on accepted valid outer envelopes; excludes wholesale rejected candidates.",
                        "main_time":"Original PC packet-completion timestamp, not raw byte arrival or device physical scan time."}}
 (HERE/"audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 lines=["# N=3 FULL 独立审计：保留异常与原统计口径", "", "固定 12 条已完成记录，M012/M013/M023/M123 各 3 条；不改原始 raw、packet_log、module_log 或 summary。旧 N=1/N=2 不计作新增未审计。", "",
        "| 组合 | PASS 性能 n | PASS 主窗 Hz 均值 ± 样本 SD | 全3条诊断 Hz 均值 ± SD |",
        "|---|---:|---:|---:|"]
 for group in groups:
  p=group["PASS_window_statistics"]["main_Hz"];a=group["all_runs_diagnostic_statistics"]["main_Hz"]
  lines.append(f"| {'+'.join('M'+str(x) for x in group['slots'])} | {p['n']} | {p['mean']:.6f} ± {p['sample_sd']:.6f} | {a['mean']:.6f} ± {a['sample_sd']:.6f} |")
 lines.extend(["", f"原日志共 {totals['logged_candidate_count']:,} 个候选，其中 {totals['logged_valid_outer_count']:,} 个外 CRC 有效，拒绝 {totals['logged_rejected_count']} 个；主窗口候选 {totals['main_logged_candidate_count']:,}、有效 {totals['main_logged_valid_count']:,}。核对 module_log {totals['module_log_rows_checked']:,} 行，有效 ESKF {totals['logged_valid_ESKF']:,} 个。独立全 MAGIC 扫描另找到一个 CRC 有效但原日志漏解析的重叠包，故 forensic 数量与原日志口径分开。",
 "", f"主窗口有效 ESKF {totals['main_logged_valid_ESKF']:,} 个；11 条 PASS 性能子集仅包含 {totals['PASS_subset_main_logged_valid_MUL1']:,} 个主窗口 MUL1 / {totals['PASS_subset_main_logged_valid_ESKF']:,} 个 ESKF。异常记录仍保留在全部 12 条诊断统计中。",
 "", "## 首段异常：20260907_000133_670681（M0+M1+M2 Repeat 1）", "",
 "异常发生在 elapsed **19.4723392 s**（主窗口开始后 9.4723392 s），PC 记录完成时间 **00:01:53.143020 +01:00**。原统计完整候选 8003 / CRC 有效 8002；主窗口候选 6002 / 有效 6001。该段 main/full CHECK 原样保留，性能汇总的 M012 仅使用另外两条 PASS，n=2；全三条另列诊断统计，不静默删除异常。", "",
 "| 观察 | 序号 | raw 字节 offset | 长度/状态 |",
 "|---|---:|---:|---|",
 "| 前有效包 | 1675976 | 12326391 | 3172 B；双层 CRC 有效 |",
 "| 被拒候选 | 1675977 | 12329563 | 声明 3172 B；外 CRC 错 |",
 "| raw 中有效、原日志未解析包 | 1675978 | 12331711 | 3172 B；外 CRC 与三个 ESKF 内 CRC 全有效 |",
 "| 原日志恢复有效解析 | 1675979 | 12334883 | 3172 B；双层 CRC 有效 |", "",
 "5977 头到 5978 头实际相隔 **2148 B**，比头中声明 3172 B 少 **1024 B**。这直接支持字节流存在短缺/畸形片段，不能仅凭 raw 判定发生在 Teensy 构包、USB/驱动、串口缓冲或 PC 读取的哪一层。不能声称已证明 USB 物理丢了两个包。", "",
 "当时 framer 从 5977 头取满声明的 3172 B，包含下一个有效 5978 的前 1024 B。CRC 被拒后，后续重同步跳过 5978 余下的 2148 B，直到 5979。因而原 Session **lost=2** 包含 **1 个短缺/损坏候选 5977，加 1 个 raw 中仍完整有效但被 PC 解析跳过的 5978**。独立所有 MAGIC 扫描恢复的是证据，未回填原日志或修改原计数。", "",
 "原日志将区间 **[12332735,12334883)** 的 2148 B 标为 interior unassigned；这些字节实际是有效包 5978 的后缀，不是随机垃圾。若按独立有效包范围看，无法由有效包覆盖的是较早的 **[12329563,12331711)** 2148 B 短缺候选片段。两种范围碰巧同为 2148 B，但位置与含义不同，不能混淆。另有 1 B 结束边界。", "",
 "有效包对应三个模块内序号为：5976 的 M0/M1/M2 = 8040/8041/8040；raw 恢复 5978 为 8042/8043/8042；5979 为 8043/8044/8043。原日志成功包跨过两次序号；计入 raw 可恢复包后只剩一次缺口。原 summary 的模块更新 18003/18003 是**以已接受外 CRC 有效包为条件**，不包含整个被拒包，不能据此声称主窗口完全没有传输异常。", "",
 "## M013 Repeat 3：199.123828 Hz", "",
 "20260907_001505_375008 的主窗口为 5974 个有效包 / 30.001432 s = **199.123828 Hz**；CRC、MUL1/模块序号和日志一致性没有异常，保留为 PASS，n=3 性能统计不得为提高均值而剔除。", "",
 "桥端 host_ms 在连续序号 **1836089→1836090** 之间相隔 **123 ms**，三个模块内序号各增加 1。PC 完成时间最大间隔 **301.3735 ms**（1836053→1836054），对应桥端 host_ms 仅隔 5 ms，说明 PC 接收/调度时间和桥端时间不能混为一个时钟。数据支持这一段存在输出/观测节奏停顿，不能用低帧率直接断言包序号丢失，也不能仅凭记录定位停顿根因。末尾保留 **1020 B** 未完成包片段，是结束边界，不是首段的 interior 故障。", "",
 "## 逐段原始状态", ""])
 for r in runs:
  lines.append(f"- `{r['run_id']}`：main={r['main_status']} / full={r['full_status']}；候选/有效={r['logged_candidate_count']}/{r['logged_valid_outer_count']}；主窗={r['main_Hz']:.6f} Hz；cross-check={r['cross_check_errors']}；full理由={r['full_review_reasons']}。")
 lines.extend(["", "建议：首条 M012 Repeat 1 保留为完整性失败证据，并补一条同条件重复用于达到 3 条 PASS 性能数据；明确后补的时间与新 run_id，不覆写原 Repeat 1。其余 11 条主窗口可用；低率 PASS 记录保留。若研究目标包括恢复能力，可将此次坏包后的漏解析作为已发现的 PC 恢复行为局限，不能宣称协议已无损恢复。", "",
 "三次是同一 setup 的时间重复，不是三个独立 block。所有有效完整包应为 3172 B（20+16+3×1044+4）。槽位不是唯一板卡身份；本地代码哈希不是设备 flash 读回。raw 本身无 PC 到达时间，主窗口依赖日志完成时间。", "",
 "脚本按 summary.run_id 递归定位，因此搬迁后可复跑；原 summary 的历史 files 路径不改，可查父任务 run_index/path_map。复现：`python -B audit_records.py`。新完成未纳入记录："+(", ".join(new) or "无")])
 (HERE/"ANALYSIS_CN.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
 print(json.dumps({"totals":totals,"groups":groups,"cross_check_errors":{r["run_id"]:r["cross_check_errors"] for r in runs if r["cross_check_errors"]},
                   "raw_unlogged_valid":{r["run_id"]:[c["sequence"] for c in r["raw_valid_unlogged_packets"]] for r in runs if r["raw_valid_unlogged_packets"]},
                   "new_completed_runs_not_audited":new},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
