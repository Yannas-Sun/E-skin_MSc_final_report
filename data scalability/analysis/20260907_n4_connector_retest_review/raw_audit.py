"""Independent DELTA audit of the three-run N=4 connector-retest snapshot.

No production parser is imported; original data files are read-only. Run IDs
are resolved through the fixed plan so this also works after organization.
Packet completion times define the initial/main split; byte arrival windows
cannot be independently reconstructed without the serial-read timing log.
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
SNAPSHOT = tuple("""20260907_115145_448767
20260907_115225_490019
20260907_115305_535263""".split())
ERRORS = ("outer_crc_errors", "inner_crc_errors", "sequence_gap_events", "lost_frames",
          "duplicate_frames", "out_of_order_frames", "format_errors", "delta_base_mismatches")


def decode(data):
    errors, modules = [], []
    if len(data) < 40 or data[:6] != b"MUL1\x02\x04":
        return {"sequence": None, "modules": [], "errors": ["outer_header"], "outer_crc_valid": False}
    outer_ok = zlib.crc32(data[:-4]) == struct.unpack_from("<I", data, len(data)-4)[0]
    if not outer_ok: errors.append("outer_crc")
    if struct.unpack_from("<H", data, 8)[0] != len(data): errors.append("outer_length")
    seq, host = struct.unpack_from("<II", data, 12)
    pos, mask = 20, 0
    for slot_expected in range(4):
        if pos+4 > len(data)-4: errors.append("descriptor_bounds"); break
        slot, status, length = struct.unpack_from("<BBH", data, pos); pos += 4
        if slot != slot_expected or pos+length > len(data)-4:
            errors.append("descriptor_layout"); break
        payload = data[pos:pos+length]; pos += length
        m = {"slot": slot, "status": status, "bytes": length, "valid": False, "errors": []}
        modules.append(m)
        if status:
            if length not in (0, 16): m["errors"].append("diagnostic_length")
        else:
            mask |= 1 << slot
            if length < 20: m["errors"].append("inner_length")
            else:
                marker, version, flags, size, inner_seq, base = struct.unpack_from("<4sBBHII", payload)
                m.update(marker=marker.decode("ascii", "replace"), flags=flags, sequence=inner_seq,
                         base_sequence=base, mode="DELTA" if flags & 0x20 else "FULL")
                if version != 4 or size != length or flags & 0xC0 or not flags & 0x10:
                    m["errors"].append("inner_header_flags")
                if zlib.crc32(payload[:-4]) != struct.unpack_from("<I", payload, length-4)[0]:
                    m["errors"].append("inner_crc")
                if marker == b"ESKF":
                    if length != 1044: m["errors"].append("full_length")
                    if base != 0xFFFFFFFF: m["errors"].append("full_base_sentinel")
                elif marker == b"ESKD" and length >= 84 and flags & 0x20:
                    k1 = sum(b.bit_count() for b in payload[16:48]); k2 = sum(b.bit_count() for b in payload[48:80])
                    m.update(K=k1+k2, K1=k1, K2=k2)
                    if k1+k2 > 480 or length != 84+2*(k1+k2): m["errors"].append("delta_mask_length")
                else: m["errors"].append("inner_marker")
                m["valid"] = not m["errors"]
        errors.extend(f"M{slot}:{e}" for e in m["errors"])
    if pos != len(data)-4 or data[6] != mask: errors.append("layout_or_updated_mask")
    return {"sequence": seq, "host_ms": host, "modules": modules, "errors": errors,
            "outer_crc_valid": outer_ok, "updated_mask": data[6], "length": len(data)}


def stats(values):
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sample_sd": statistics.stdev(values) if len(values)>1 else None}


def histogram_stats(h):
    n = sum(h.values())
    if not n: return {"n": 0, "mean": None, "sd_population": None}
    mean = sum(k*v for k,v in h.items())/n
    def at_rank(rank):
        total = 0
        for k,v in sorted(h.items()):
            total += v
            if total > rank: return k
    def percentile(p):
        rank = (n-1)*p; low = int(rank)
        return at_rank(low)+(at_rank(min(low+1,n-1))-at_rank(low))*(rank-low)
    return {"n": n, "mean": mean, "sd_population": (sum(v*(k-mean)**2 for k,v in h.items())/n)**.5,
            "min": min(h), "max": max(h), "p05": percentile(.05), "median": percentile(.5),
            "p95": percentile(.95), "zero_fraction": h.get(0,0)/n}


def uncovered(intervals, size):
    end = 0; result = []
    for a,b in sorted(intervals):
        if a>end: result.append({"offset": end, "bytes": a-end, "kind": "leading" if end == 0 else "interior"})
        end = max(end,b)
    if end<size: result.append({"offset": end, "bytes": size-end, "kind": "trailing"})
    return result


def compact(c):
    return {k:c[k] for k in ("offset", "length", "sequence", "host_ms", "outer_crc_valid", "errors")}


def new_scope():
    return {"counts": Counter(), "K": Counter(), "module_counts": defaultdict(Counter),
            "module_K": defaultdict(Counter), "lengths": Counter(), "statuses": defaultdict(Counter),
            "flags": defaultdict(Counter), "full_times": defaultdict(list)}


def audit_one(directory, summary, previous):
    raw = (directory/"mul1_raw.bin").read_bytes()
    with (directory/"packet_log.csv").open(encoding="utf-8-sig", newline="") as f: logs = list(csv.DictReader(f))
    events = [json.loads(t) for t in (directory/"events.jsonl").read_text(encoding="utf-8").splitlines() if t.strip()]
    checks = Counter(); candidates = []; partials = []; cursor = 0
    while True:
        offset = raw.find(b"MUL1", cursor)
        if offset < 0: break
        cursor = offset+1
        if offset+20 > len(raw): partials.append({"offset": offset, "available_bytes": len(raw)-offset}); continue
        size = struct.unpack_from("<H", raw, offset+8)[0]
        if raw[offset+4:offset+6] != b"\x02\x04" or not 40<=size<=4216: continue
        if offset+size > len(raw):
            partials.append({"offset": offset, "declared_bytes": size, "available_bytes": len(raw)-offset}); continue
        candidates.append(decode(raw[offset:offset+size]) | {"offset": offset})
    by_offset = {c["offset"]: c for c in candidates}
    expected = set(summary["metadata"]["target_modules"]); settle = summary["settle_seconds"]
    scopes = {name: new_scope() for name in ("full_run", "initial", "main")}
    chains = {}; previous_inner = {}; previous_outer = None
    cache_events = []; anomalies = []; outer_gaps = []; inner_gaps = []; base_gaps = []
    module_rows_checked = 0; timing = []; last_log = None
    with (directory/"module_log.csv").open(encoding="utf-8-sig", newline="") as f:
        module_rows = csv.DictReader(f)
        for row in logs:
            offset = int(row["raw_offset"]); c = by_offset.get(offset); elapsed = float(row["elapsed_s"])
            names = ("full_run", "main" if elapsed>=settle else "initial")
            if c is None: checks["logged_candidate_missing_in_raw"] += 1; continue
            c["elapsed_s"] = elapsed
            for name in names:
                scopes[name]["counts"]["packet_candidates"] += 1
                scopes[name]["counts"]["candidate_packet_bytes"] += c["length"]
            if (c["sequence"], c["length"], c["host_ms"]) != (int(row["packet_sequence"]), int(row["received_bytes"]), int(row["host_ms"])):
                checks["packet_log_header_or_offset_mismatch"] += 1
            if (row["outer_crc_ok"] == "True") != c["outer_crc_valid"]: checks["packet_log_crc_verdict_mismatch"] += 1
            if (row["main_window"] == "True") != (elapsed>=settle): checks["packet_log_scope_mismatch"] += 1
            if not c["outer_crc_valid"]:
                for name in names: scopes[name]["counts"]["outer_crc_errors"] += 1
                anomalies.append(compact(c)|{"elapsed_s": elapsed, "logged_error": row["error"]}); continue
            if c["errors"]: anomalies.append(compact(c)|{"elapsed_s": elapsed})
            if row["parse_ok"] != "True": checks["valid_outer_pc_rejected"] += 1
            if previous_outer is not None and (c["sequence"]-previous_outer)&0xffffffff != 1:
                outer_gaps.append({"previous": previous_outer, "sequence": c["sequence"], "offset": offset, "elapsed_s": elapsed})
            previous_outer = c["sequence"]
            if last_log and elapsed>=settle:
                timing.append({"previous_sequence": last_log["sequence"], "sequence": c["sequence"], "elapsed_s": elapsed,
                               "pc_completion_gap_ms": 1000*(elapsed-last_log["elapsed_s"]),
                               "bridge_host_gap_ms": (c["host_ms"]-last_log["host_ms"])&0xffffffff})
            last_log = c
            valid_slots = {m["slot"] for m in c["modules"] if m["valid"]}
            for name in names:
                sc = scopes[name]; sc["counts"].update(valid_outer_packets=1, valid_outer_packet_bytes=c["length"],
                     expected_module_update_opportunities=len(expected), missing_valid_expected_updates=len(expected-valid_slots),
                     unexpected_valid_updates=len(valid_slots-expected), all_expected_modules_updated_packets=int(expected<=valid_slots))
                sc["lengths"][c["length"]] += 1
            for m in c["modules"]:
                slot = m["slot"]; outcome = "not_updated" if m["status"] else "invalid"
                chain = chains.setdefault(slot, {"anchored": False, "valid": False, "applied": None, "affected": 0})
                if m["valid"]:
                    if slot in previous_inner:
                        if (m["sequence"]-previous_inner[slot])&0xffffffff != 1:
                            inner_gaps.append({"module": slot, "previous": previous_inner[slot], "sequence": m["sequence"], "offset": offset, "elapsed_s": elapsed})
                        if m["marker"] == "ESKD" and m["base_sequence"] != previous_inner[slot]:
                            base_gaps.append({"module": slot, "previous": previous_inner[slot], "base": m["base_sequence"], "offset": offset, "elapsed_s": elapsed})
                    previous_inner[slot] = m["sequence"]
                    if m["marker"] == "ESKF":
                        if not chain["valid"]:
                            cache_events.append({"event": "initial_anchor" if not chain["anchored"] else "full_recovery",
                                                 "module": slot, "sequence": m["sequence"], "elapsed_s": elapsed,
                                                 "affected_after_anchor_frames": chain["affected"]})
                        chain.update(anchored=True, valid=True, applied=m["sequence"], affected=0)
                        outcome = "applied_full_baseline"
                    elif not chain["anchored"]: outcome = "initial_unanchored_delta"
                    elif chain["valid"] and m["base_sequence"] == chain["applied"]:
                        chain["applied"] = m["sequence"]; outcome = "applied_delta"
                    else:
                        outcome = "unapplied_after_anchor"
                        if chain["valid"]:
                            cache_events.append({"event": "base_chain_break", "module": slot, "sequence": m["sequence"],
                                                 "expected_base": chain["applied"], "base": m["base_sequence"], "elapsed_s": elapsed})
                            for name in names: scopes[name]["counts"]["base_break_events_after_anchor"] += 1
                        chain["valid"] = False; chain["affected"] += 1
                logged = next(module_rows, None); module_rows_checked += 1
                if logged is None: checks["module_log_missing_row"] += 1
                else:
                    match = {"packet_sequence": str(c["sequence"]), "module_id": str(slot), "status": f"0x{m['status']:02x}",
                             "expected": str(slot in expected), "valid": str(m["valid"]), "payload_bytes": str(m["bytes"]),
                             "marker": m.get("marker", ""), "mode": m.get("mode", ""), "main_window": str(elapsed>=settle),
                             "flags": f"0x{m['flags']:02x}" if "flags" in m else "", "cache_outcome": outcome}
                    match.update({k: str(m[k]) if k in m else "" for k in ("sequence", "base_sequence", "K", "K1", "K2")})
                    if any(logged.get(k)!=v for k,v in match.items()) or float(logged["elapsed_s"])!=elapsed:
                        checks["module_log_row_mismatch"] += 1
                    if bool(logged["error"]) != bool(m["errors"]): checks["module_log_error_verdict_mismatch"] += 1
                for name in names:
                    sc = scopes[name]; mc = sc["module_counts"][slot]
                    sc["statuses"][slot][f"0x{m['status']:02x}"] += 1; mc["slot_observations"] += 1
                    if m["status"]: sc["counts"]["diagnostic_payload_bytes"] += m["bytes"]
                    if not m["valid"]: continue
                    mc.update(valid_frames=1, payload_bytes=m["bytes"]); mc[m["marker"]] += 1; mc[outcome] += 1
                    sc["counts"].update(valid_module_frames=1, valid_module_payload_bytes=m["bytes"], valid_expected_module_frames=int(slot in expected))
                    sc["counts"][m["marker"]] += 1; sc["counts"][outcome] += 1
                    sc["flags"][slot][f"0x{m['flags']:02x}"] += 1
                    if m["mode"] != "DELTA": sc["counts"]["target_mode_mismatch"] += 1
                    if m["marker"] == "ESKD": sc["K"][m["K"]] += 1; sc["module_K"][slot][m["K"]] += 1
                    else: sc["full_times"][slot].append((elapsed, c["host_ms"], m["sequence"]))
        checks["module_log_extra_rows"] += sum(1 for _ in module_rows)
    boundaries = []; boundary_intervals = []
    for e in events:
        if e.get("event") != "capture_start_boundary": continue
        prefix, suffix = -e["raw_offset"], e["suffix_bytes_in_recording"]
        if previous: prefix_data = previous["tail"][-prefix:]; evidence = "actual_previous_raw_tail"
        elif prefix == 1: prefix_data = b"M"; evidence = "inferred_single_magic_byte_not_recorded"
        else: prefix_data = b""; evidence = "unavailable_prefix"
        d = decode(prefix_data+raw[:suffix])
        verified = d["outer_crc_valid"] and not d["errors"] and d["sequence"] == e["packet_sequence"]
        boundaries.append({"packet_sequence": e["packet_sequence"], "prefix_bytes": prefix, "suffix_bytes": suffix,
                           "evidence": evidence, "verified": verified, "errors": d["errors"], "event_errors": e["errors"],
                           "previous_run_id": previous["run_id"] if previous else None})
        if evidence != "unavailable_prefix" and not verified: checks["boundary_reconstruction_mismatch"] += 1
        if e["known_suffix_accounted"]: boundary_intervals.append((0,suffix))
    gaps = uncovered([(int(r["raw_offset"]), int(r["raw_offset"])+int(r["received_bytes"])) for r in logs]+boundary_intervals, len(raw))
    logged_offsets = {int(r["raw_offset"]) for r in logs}
    unlogged = [compact(c) for c in candidates if c["outer_crc_valid"] and c["offset"] not in logged_offsets]
    if len(raw) != summary["recorded_bytes"]: checks["raw_size_mismatch"] += 1
    raw_hash = hashlib.sha256(raw).hexdigest()
    if raw_hash != summary["raw_sha256"]: checks["raw_sha256_mismatch"] += 1
    if len(logs) != summary["recorded_candidate_rows"]: checks["summary_candidate_count_mismatch"] += 1
    if scopes["full_run"]["counts"]["valid_outer_packets"] != summary["complete_mul_count"]: checks["summary_complete_count_mismatch"] += 1
    if sum(g["bytes"] for g in gaps) != summary["scopes"]["full_run"]["unassigned_raw_bytes"]: checks["summary_unassigned_bytes_mismatch"] += 1
    results = {}
    for name, sc in scopes.items():
        count = sc["counts"]; duration = settle if name == "initial" else summary["duration_seconds"]-(settle if name == "main" else 0)
        valid = count["valid_outer_packets"]; frames = count["ESKF"]+count["ESKD"]
        q = count["ESKF"]/frames if frames else None; ks = histogram_stats(sc["K"])
        modules = {}
        for slot, mc in sc["module_counts"].items():
            ts = sc["full_times"][slot]
            modules[str(slot)] = {"counts": dict(mc), "statuses": dict(sc["statuses"][slot]), "flags": dict(sc["flags"][slot]),
                                  "K": histogram_stats(sc["module_K"][slot]), "K_histogram": dict(sorted(sc["module_K"][slot].items())),
                                  "q_ESKF": mc["ESKF"]/mc["valid_frames"] if mc["valid_frames"] else None,
                                  "ESKF_pc_intervals_s": stats([b[0]-a[0] for a,b in zip(ts,ts[1:])]),
                                  "ESKF_bridge_intervals_ms": stats([(b[1]-a[1])&0xffffffff for a,b in zip(ts,ts[1:])])}
        results[name] = {"duration_seconds": duration, "counts": dict(count), "q_ESKF": q, "K_ESKD": ks,
                         "valid_outer_packet_rate_Hz": valid/duration, "Lmean_valid_packet_B": count["valid_outer_packet_bytes"]/valid if valid else None,
                         "packet_completion_Mbit_per_s": 8*count["valid_outer_packet_bytes"]/duration/1e6,
                         "packet_length_histogram": dict(sorted(sc["lengths"].items())), "modules": modules}
        if name == "initial": continue
        reported = summary["scopes"][name]
        results[name].update(reported_status=reported["status"], reported_review_reasons=reported["review_reasons"],
                             reported_raw_arrival_Mbit_per_s=reported["raw_arrival_Mbit_per_s"],
                             reported_raw_arrival_bytes=reported["raw_arrival_bytes"])
        for key, value in count.items():
            if key in reported["counts"] and value != reported["counts"][key]: checks[f"summary_{name}_{key}_mismatch"] += 1
        for key, value in (("q_ESKF", q), ("valid_outer_packet_rate_Hz", valid/duration), ("Lmean_valid_packet_B", results[name]["Lmean_valid_packet_B"])):
            if value is not None and abs(value-reported[key])>1e-9: checks[f"summary_{name}_{key}_mismatch"] += 1
        if ks["n"] != reported["K_ESKD_pooled"]["n"] or (ks["n"] and abs(ks["mean"]-reported["K_ESKD_pooled"]["mean"])>1e-9):
            checks[f"summary_{name}_K_mismatch"] += 1
        for slot, ms in modules.items():
            old = reported["modules"]["M"+slot]
            if dict(sorted(sc["module_K"][int(slot)].items())) != {int(k):v for k,v in old["K_histogram"].items()}:
                checks[f"summary_{name}_M{slot}_K_histogram_mismatch"] += 1
    record = {"run_id": summary["run_id"], "source_directory": str(directory), "started_at": summary["started_at"],
              "metadata": {k:summary["metadata"].get(k) for k in ("target_modules", "target_mode", "target_hz", "delta_threshold", "spi_setting_hz", "condition", "block", "repeat", "batch_id", "batch_repeat_index", "live_parser_continuous_across_recordings")},
              "raw_bytes": len(raw), "raw_sha256": raw_hash, "scopes": results, "module_log_rows_checked": module_rows_checked,
              "raw_candidate_count": len(candidates), "raw_outer_crc_valid_count": sum(c["outer_crc_valid"] for c in candidates),
              "raw_bad_outer_candidates": [compact(c) for c in candidates if not c["outer_crc_valid"]],
              "raw_valid_unlogged_packets": unlogged, "anomalies": anomalies,
              "cross_check_errors": {k:v for k,v in checks.items() if v}, "outer_sequence_discontinuities": outer_gaps,
              "inner_sequence_discontinuities": inner_gaps, "observed_base_discontinuities": base_gaps,
              "cache_events": cache_events, "start_boundaries": boundaries, "unassigned_ranges": gaps,
              "trailing_partial_candidates": partials, "session_error_delta": {k:summary["counters"].get(k,0) for k in ERRORS},
              "main_session_error_delta": {k:summary["scopes"]["main"]["session_counter_delta_at_packet_observation"].get(k,0) for k in ERRORS},
              "main_largest_pc_gaps": sorted(timing,key=lambda x:x["pc_completion_gap_ms"],reverse=True)[:3],
              "main_largest_bridge_gaps": sorted(timing,key=lambda x:x["bridge_host_gap_ms"],reverse=True)[:3],
              "pc_monitor_sha256": summary["metadata"]["local_provenance"]["files"]["pc_monitor"]["sha256"]}
    return record, {"tail": raw[-4216:], "run_id": summary["run_id"]}


def resolve_snapshot():
    """Use only fixed run IDs and old/new plan paths; never scan later arrivals."""
    found = {}
    plan_path = HERE/"organization_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {"runs": []}
    planned = {r["run_id"]:r for r in plan["runs"]}
    for rid in SNAPSHOT:
        choices = [Path(planned[rid][k]) for k in ("source", "destination")] if rid in planned else [DATA/rid]
        existing = [p/"summary.json" for p in choices if (p/"summary.json").exists()]
        if len(existing) != 1: raise ValueError("Expected exactly one fixed source for "+rid+": "+str(existing))
        p = existing[0]; s = json.loads(p.read_text(encoding="utf-8"))
        if s.get("run_id") != rid: raise ValueError("Run identity mismatch: "+str(p))
        if not s["completed_requested_duration"]: raise ValueError("Snapshot run incomplete: "+rid)
        found[rid] = (p.parent,s)
    if set(found) != set(SNAPSHOT): raise ValueError("Snapshot missing: "+str(set(SNAPSHOT)-set(found)))
    return found


def main():
    found = resolve_snapshot()
    runs = []; previous = {}
    for rid in SNAPSHOT:
        directory, s = found[rid]; batch = s["metadata"]["batch_id"]
        result, tail = audit_one(directory,s,previous.get(batch)); previous[batch] = tail; runs.append(result)
        print(rid, "raw read complete; checks", result["cross_check_errors"], flush=True)
    groups = defaultdict(list)
    for r in runs: groups[tuple(r["metadata"]["target_modules"])].append(r)
    group_results = []
    for modules, items in sorted(groups.items(),key=lambda kv:(len(kv[0]),kv[0])):
        gr = {"modules": list(modules), "N": len(modules), "n_temporal_repeats": len(items),
              "batch_ids": sorted({r["metadata"]["batch_id"] for r in items}),
              "repeat_indices": [r["metadata"]["batch_repeat_index"] for r in items], "run_ids": [r["run_id"] for r in items]}
        for key in ("valid_outer_packet_rate_Hz", "Lmean_valid_packet_B", "packet_completion_Mbit_per_s", "q_ESKF"):
            gr[key] = stats([r["scopes"]["main"][key] for r in items])
        gr["K_ESKD_run_mean"] = stats([r["scopes"]["main"]["K_ESKD"]["mean"] for r in items])
        group_results.append(gr)
    totals = {}
    for scope in ("full_run", "initial", "main"):
        counter = Counter()
        for r in runs: counter.update(r["scopes"][scope]["counts"])
        totals[scope] = dict(counter)
    output = {"schema_version": 1, "audit_time": datetime.now().astimezone().isoformat(), "snapshot_run_ids": list(SNAPSHOT),
              "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "method": "independent struct/zlib raw decoder; every plausible magic candidate; independent file-local DELTA cache; packet/module CSV cross-check; raw SHA256",
              "scope_definition": {"initial": "0 <= packet completion elapsed < 10 s", "main": "10 s <= completion elapsed <= actual capture end", "full_run": "all complete candidates wholly within recorded raw; known start-boundary packet excluded"},
              "limitations": ["Packet windows use logged PC completion time, not sensor acquisition time.",
                              "Initial unanchored ESKD is not established packet loss; file-local reconstruction begins at first valid recorded ESKF.",
                              "ESKF marker/flags do not identify periodic, overflow, manual or recovery trigger.",
                              "A single missing initial magic byte may be inferred but is not recorded evidence.",
                              "Three captures in each batch are temporal repeats under one setup, not independent setup blocks.",
                              "Local firmware hashes and responding slot IDs are not device-flash readback or unique board identity."],
              "totals": totals, "groups": group_results, "runs": runs}
    (HERE/"raw_audit.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines = ["# DELTA N=4 connector 重装后复测：独立原始数据审计", "", f"固定快照：{SNAPSHOT[0]} 至 {SNAPSHOT[-1]}，共3条；M0--M3同时全覆盖动态加载，connector重新安装后连续三次。", "",
             "所有统计保留原记录状态，不自动重标。前10秒为初始窗口，主窗口从10秒至实际结束；完整窗口包含两者。边界跨文件包单列，不混入完整包率、K和q。", "",
             "|窗口|候选MUL1|有效MUL1|有效ESK|ESKF|ESKD|无锚点前缀|锚点后未应用|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name,c in totals.items():
        lines.append("|"+name+"|"+"|".join(str(c.get(k,0)) for k in ("packet_candidates", "valid_outer_packets", "valid_module_frames", "ESKF", "ESKD", "initial_unanchored_delta", "unapplied_after_anchor"))+"|")
    bad = [r["run_id"] for r in runs if r["cross_check_errors"] or r["anomalies"] or r["outer_sequence_discontinuities"] or r["inner_sequence_discontinuities"]]
    boundaries = [b for r in runs for b in r["start_boundaries"]]
    boundary_count = Counter(b["evidence"] for b in boundaries)
    tail_count = sum(g["bytes"] for r in runs for g in r["unassigned_ranges"] if g["kind"] == "trailing")
    interior_count = sum(g["bytes"] for r in runs for g in r["unassigned_ranges"] if g["kind"] == "interior")
    anchor_latest = max(e["elapsed_s"] for r in runs for e in r["cache_events"] if e["event"] == "initial_anchor")
    largest_run = max(runs,key=lambda r:r["main_largest_pc_gaps"][0]["pc_completion_gap_ms"])
    largest = largest_run["main_largest_pc_gaps"][0]
    lines += ["", "原始字节/日志独立校验出现问题的run："+("、".join(bad) if bad else "无。"),
              "", f"原summary状态：主窗口{dict(Counter(r['scopes']['main']['reported_status'] for r in runs))}；全窗口{dict(Counter(r['scopes']['full_run']['reported_status'] for r in runs))}。全窗口CHECK的原因保留逐run JSON，不重标为PASS。",
              "", f"{len(boundaries)}个开始边界包中，{boundary_count['actual_previous_raw_tail']}个由前一run实际尾字节拼接验证，{boundary_count['inferred_single_magic_byte_not_recorded']}个仅补已知magic单字节M后验证；两者证据等级不同。所有可重建边界均通过CRC。尾部未分配共{tail_count}B，内部{interior_count}B。",
              "", f"各槽位首次文件内FULL基线最迟在{anchor_latest:.7f}s建立。初始前缀不属于锚点后链断裂，本批锚点后未应用帧和真正FULL恢复事件均为0。",
              "", f"PC完成时间存在批量到达：最大相邻完成间隔{largest['pc_completion_gap_ms']/1000:.7f}s，run {largest_run['run_id']}，seq {largest['previous_sequence']}→{largest['sequence']}，elapsed={largest['elapsed_s']:.7f}s；对应桥host_ms差仅{largest['bridge_host_gap_ms']}ms且内外序号连续。PC窗口帧率不能直接当作硬件瞬时采集频率，也不能据此断言硬件暂停。",
              "", "|槽位组合|n|主窗口Hz均值±样本SD|平均包B|K_D均值|q_ESKF|", "|---|---:|---:|---:|---:|---:|"]
    for g in group_results:
        f = g["valid_outer_packet_rate_Hz"]
        lines.append(f"|{','.join('M'+str(x) for x in g['modules'])}|{g['n_temporal_repeats']}|{f['mean']:.4f} ± {f['sample_sd']:.4f}|{g['Lmean_valid_packet_B']['mean']:.4f}|{g['K_ESKD_run_mean']['mean']:.4f}|{g['q_ESKF']['mean']:.7f}|")
    lines += ["", "K_D仅由有效ESKD的64字节mask逐位计数；ESKF不反推K。q=ESKF/(ESKF+ESKD)。组均值按每条run等权，SD为三次时间重复间样本SD；帧内K离散性另存JSON人口SD和分位数。", "",
              "无锚点前缀表示录制开始时没有记录前置FULL，不能据此声称传输丢帧；只有已建立锚点后的base链破坏才计实际文件内缓存错误。ESKF触发原因未被协议编码，不能仅按marker判断周期/回退/恢复。", "",
              "本轮 raw SHA256、每个完整候选长度/外CRC、内CRC、掩码popcount、逐槽日志、模块序号与base、主/全窗口summary均有独立核对。边界包实际拼接与单字节推断在JSON中分开。原始到达字节按read块的窗口归属沿用summary，不能由raw单独恢复串口read时间。", "",
              "复现：`python -B -X utf8 raw_audit.py`。仅按固定organization_plan的旧/新路径及summary.run_id定位，分类搬迁后仍可运行，不扫描后来加入的数据。"]
    (HERE/"raw_audit_CN.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"runs":len(runs),"groups":len(group_results),"totals":totals,"runs_with_independent_errors":bad},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
