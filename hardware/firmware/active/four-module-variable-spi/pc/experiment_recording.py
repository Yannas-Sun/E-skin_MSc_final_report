"""Standard-library recording/audit backend for MUL1 v2 / ESK v4.

Raw chunks are attributed by arrival time; decoded packets by completion time.
These are deliberately separate byte ledgers at analysis-window boundaries.
This module does not open serial ports or infer firmware deployment from files.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path
import struct
import time
from typing import Any
import zlib


@dataclass(kw_only=True)
class RecordingConfig:
    output_dir: Path
    duration_seconds: float = 40.0
    settle_seconds: float = 10.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)
        self.duration_seconds = float(self.duration_seconds)
        self.settle_seconds = float(self.settle_seconds)
        if not (math.isfinite(self.duration_seconds) and math.isfinite(self.settle_seconds)
                and 0 <= self.settle_seconds < self.duration_seconds):
            raise ValueError("Require 0 <= settle_seconds < duration_seconds, both finite")
        self.metadata = dict(self.metadata)


@dataclass
class RecordingStatus:
    message: str
    phase: str = "info"
    elapsed_seconds: float | None = None
    remaining_seconds: float | None = None


def _json_default(value):
    if isinstance(value, (Path, datetime)):
        return str(value) if isinstance(value, Path) else value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _snapshot(counters):
    if counters is None:
        return {}
    if isinstance(counters, dict):
        return dict(counters)
    if is_dataclass(counters):
        return asdict(counters)
    return dict(vars(counters))


def _counter_delta(before, after):
    delta, resets = {}, []
    for key, value in after.items():
        if key.startswith("last_") or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        old = before.get(key, 0)
        if not isinstance(old, (int, float)):
            continue
        if value < old:
            resets.append(key)
        else:
            delta[key] = value - old
    return delta, resets


def _histogram(hist):
    n = sum(hist.values())
    empty = {"n": 0, "mean": None, "sd_population": None, "min": None, "max": None,
             "p05": None, "p25": None, "median": None, "p75": None, "p95": None,
             "zero_fraction": None}
    if not n:
        return empty
    mu = sum(k*c for k, c in hist.items())/n
    ordered = sorted(hist.items())
    def at(index):
        seen = 0
        for value, count in ordered:
            seen += count
            if index < seen:
                return value
        raise AssertionError("histogram index")
    def quantile(p):
        index = (n-1)*p
        lo, hi = math.floor(index), math.ceil(index)
        return at(lo)+(at(hi)-at(lo))*(index-lo)
    return {"n": n, "mean": mu,
            "sd_population": math.sqrt(sum(c*(k-mu)**2 for k, c in hist.items())/n),
            "min": ordered[0][0], "max": ordered[-1][0], "p05": quantile(.05),
            "p25": quantile(.25), "median": quantile(.5), "p75": quantile(.75),
            "p95": quantile(.95), "zero_fraction": hist.get(0, 0)/n}


def _module_stats():
    return {"counts": Counter(), "K": Counter(), "K1": Counter(), "K2": Counter(),
            "statuses": Counter(), "flags": Counter(), "full_times": []}


class _Scope:
    def __init__(self, name, start):
        self.name, self.start = name, start
        self.counts = Counter()
        self.modules = [_module_stats() for _ in range(4)]
        self.session_observed_deltas = Counter()


STATUS_NAMES = {0: "NOT_UPDATED", 1: "BAD_FRAME", 2: "BAD_CRC", 3: "NO_IRQ",
                4: "TIMEOUT", 5: "MODE_TRANSITION", 6: "RESYNC_NEEDED", 7: "BAD_VERSION"}


def _status_name(status):
    if status == 0:
        return "OK"
    return STATUS_NAMES.get(status & 15, f"NOT_UPDATED_{status & 15}") if status & 128 else f"ERROR_{status}"


def _decode(data):
    """Return a structural audit, without modifying cache state."""
    out = {"outer_valid": False, "layout_valid": False, "errors": [], "modules": [],
           "sequence": None, "host_ms": None, "declared_length": None, "updated_mask": None}
    if len(data) >= 10:
        out["declared_length"] = struct.unpack_from("<H", data, 8)[0]
    if len(data) < 40 or data[:4] != b"MUL1" or data[4:6] != bytes((2, 4)):
        out["errors"].append("outer_format_error")
        return out
    out.update(sequence=struct.unpack_from("<I", data, 12)[0],
               host_ms=struct.unpack_from("<I", data, 16)[0], updated_mask=data[6])
    if out["declared_length"] != len(data):
        out["errors"].append("outer_length_error")
        return out
    if zlib.crc32(data[:-4]) != struct.unpack_from("<I", data, len(data)-4)[0]:
        out["errors"].append("outer_crc_error")
        return out
    out["outer_valid"] = True
    pos = 20
    for expected_id in range(4):
        if pos+4 > len(data)-4:
            out["errors"].append("module_layout_error")
            return out
        mid, status, length = struct.unpack_from("<BBH", data, pos)
        pos += 4
        if mid != expected_id or pos+length > len(data)-4:
            out["errors"].append("module_layout_error")
            return out
        payload = data[pos:pos+length]
        pos += length
        m = {"module_id": mid, "status": status, "status_name": _status_name(status),
             "payload_bytes": length, "valid": False, "marker": "", "mode": "",
             "flags": None, "sequence": None, "base_sequence": None, "K": None,
             "K1": None, "K2": None, "error": "", "diagnostic_prefix_hex": ""}
        out["modules"].append(m)
        if status != 0:
            m["diagnostic_prefix_hex"] = payload.hex()
            if length not in (0, 16):
                m["error"] = "diagnostic_length_error"
            continue
        if length < 20:
            m["error"] = "inner_format_error"
            continue
        m.update(marker=payload[:4].decode("ascii", errors="replace"), flags=payload[5],
                 sequence=struct.unpack_from("<I", payload, 8)[0],
                 base_sequence=struct.unpack_from("<I", payload, 12)[0])
        if payload[4] != 4 or struct.unpack_from("<H", payload, 6)[0] != length:
            m["error"] = "inner_header_error"
        elif zlib.crc32(payload[:-4]) != struct.unpack_from("<I", payload, length-4)[0]:
            m["error"] = "inner_crc_error"
        elif payload[5] & 0xC0 or not payload[5] & 0x10:
            m["error"] = "inner_flags_error"
        elif payload[:4] == b"ESKF" and length == 1044:
            m["mode"] = "DELTA" if payload[5] & 0x20 else "FULL"
            m["valid"] = True
        elif payload[:4] == b"ESKD" and length >= 84 and payload[5] & 0x20:
            k1 = sum(b.bit_count() for b in payload[16:48])
            k2 = sum(b.bit_count() for b in payload[48:80])
            if k1+k2 > 480 or length != 84+2*(k1+k2):
                m["error"] = "delta_mask_length_error"
            else:
                m.update(valid=True, mode="DELTA", K=k1+k2, K1=k1, K2=k2)
        else:
            m["error"] = "inner_format_error"
    if pos != len(data)-4:
        out["errors"].append("module_layout_error")
        return out
    out["layout_valid"] = True
    descriptor_mask = sum(1 << m["module_id"] for m in out["modules"] if m["status"] == 0)
    if out["updated_mask"] != descriptor_mask:
        out["errors"].append("updated_mask_error")
    return out


class ExperimentRecorder:
    def __init__(self, port_name, baud, config: RecordingConfig):
        self.port_name, self.baud, self.config = port_name, baud, config
        self.metadata = json.loads(json.dumps(config.metadata, default=_json_default))
        modules = self.metadata.get("target_modules", self.metadata.get("active_module_ids"))
        self.expected_modules = []
        if modules is not None:
            if not isinstance(modules, (list, tuple)):
                raise ValueError("target_modules must be a list of 0..3 or M0..M3")
            self.expected_modules = sorted(int(str(m).upper().removeprefix("M")) for m in modules)
            if not self.expected_modules or len(set(self.expected_modules)) != len(self.expected_modules) or not all(0 <= m < 4 for m in self.expected_modules):
                raise ValueError("target_modules must contain distinct module IDs 0..3")
        self.expected_mask = sum(1 << m for m in self.expected_modules)
        self.target_mode = str(self.metadata.get("target_mode", self.metadata.get("mode", self.metadata.get("algorithm", "")))).upper()
        if self.target_mode and self.target_mode not in ("FULL", "DELTA"):
            raise ValueError("target_mode must be FULL or DELTA")
        self.active = False
        self.total_bytes = 0
        self.started_monotonic = None
        self.started_at = None
        self.run_id = ""
        self.run_dir = config.output_dir
        self.scopes = {"full_run": _Scope("full_run", 0.0),
                       "main": _Scope("main", config.settle_seconds)}
        self._chains = [dict(anchored=False, valid=False, previous=None, applied=None,
                             prefix_reported=False) for _ in range(4)]
        self._outer_previous = None
        self._last_elapsed = 0.0
        self._raw_sha = hashlib.sha256()
        self._files = []
        self._packet_intervals = []
        self._start_boundary_intervals = []
        self._capture_start_boundary_packets = 0
        self._raw_chunks = []
        self._commands = []
        self._finished_status = None
        self._counter_resets = []

    def _elapsed(self, supplied=None):
        value = float(supplied) if supplied is not None else time.monotonic()-self.started_monotonic
        if not math.isfinite(value) or value < 0:
            raise ValueError("elapsed_s must be finite and nonnegative")
        self._last_elapsed = max(self._last_elapsed, value)
        return value

    def _windows(self, elapsed):
        return [scope for scope in self.scopes.values() if elapsed >= scope.start]

    def _event(self, kind, elapsed, **detail):
        self._events.write(json.dumps({"event": kind, "elapsed_s": elapsed,
                                      "time": (self.started_at+timedelta(seconds=elapsed)).isoformat(),
                                      **detail}, ensure_ascii=False, default=_json_default)+"\n")

    def start(self, counters, started_at=None, started_monotonic=None):
        if self.started_monotonic is not None:
            raise RuntimeError("Recorder instances can only start once")
        self.started_at = started_at or datetime.now().astimezone()
        if self.started_at.tzinfo is None:
            self.started_at = self.started_at.astimezone()
        self.started_monotonic = time.monotonic() if started_monotonic is None else started_monotonic
        self.run_id = self.started_at.strftime("%Y%m%d_%H%M%S_%f")
        self.run_dir = self.config.output_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._raw = (self.run_dir/"mul1_raw.bin").open("xb")
            self._files.append(self._raw)
            self._events = (self.run_dir/"events.jsonl").open("x", encoding="utf-8")
            self._files.append(self._events)
            packet_file = (self.run_dir/"packet_log.csv").open("x", encoding="utf-8", newline="")
            self._files.append(packet_file)
            module_file = (self.run_dir/"module_log.csv").open("x", encoding="utf-8", newline="")
            self._files.append(module_file)
            self._packet_writer = csv.DictWriter(packet_file, fieldnames=["elapsed_s", "mul_start_time",
                "packet_completed_time", "raw_offset", "received_bytes", "declared_length",
                "packet_sequence", "host_ms", "outer_crc_ok", "parse_ok", "updated_mask",
                "module_statuses", "algorithms", "main_window", "error"])
            self._packet_writer.writeheader()
            self._module_writer = csv.DictWriter(module_file, fieldnames=["elapsed_s", "packet_sequence",
                "module_id", "expected", "status", "status_name", "payload_bytes", "valid",
                "marker", "mode", "flags", "sequence", "base_sequence", "K", "K1", "K2",
                "cache_outcome", "main_window", "error", "diagnostic_prefix_hex"])
            self._module_writer.writeheader()
        except Exception:
            for handle in self._files:
                handle.close()
            raise
        self._counter_start = _snapshot(counters)
        self._counter_last = dict(self._counter_start)
        self.active = True
        self._event("recording_started", 0.0, metadata=self.metadata,
                    duration_seconds=self.config.duration_seconds, settle_seconds=self.config.settle_seconds,
                    session_counters_start=self._counter_start)
        return self.progress_status()

    def record_raw(self, chunk, elapsed_s=None):
        if not self.active:
            return
        elapsed = self._elapsed(elapsed_s)
        self._raw_chunks.append((self.total_bytes, self.total_bytes+len(chunk), elapsed))
        self._raw.write(chunk)
        self._raw_sha.update(chunk)
        self.total_bytes += len(chunk)
        for scope in self._windows(elapsed):
            scope.counts["raw_arrival_bytes"] += len(chunk)
            scope.counts["raw_chunks"] += 1

    def note_command(self, command, source="user"):
        if not self.active:
            return
        elapsed = self._elapsed()
        entry = {"command": str(command), "source": source, "elapsed_s": elapsed}
        self._commands.append(entry)
        self._event("command_sent", elapsed, **{k: v for k, v in entry.items() if k != "elapsed_s"})

    def record_start_boundary(self, data, raw_offset, elapsed_s=None, error=None, counters=None):
        """Audit a live-parser packet whose prefix arrived before this recording.

        Only its already-recorded suffix belongs to this raw file. Neither the
        prefix nor a reconstructed packet is written, counted, or used to seed
        the file's DELTA cache. Independent checks still expose real errors.
        """
        if not self.active:
            return
        elapsed = self._elapsed(elapsed_s)
        scopes = self._windows(elapsed)
        decoded = _decode(data)
        errors = list(decoded["errors"])
        if error:
            errors.append("pc_parser_errors")
        suffix_end = raw_offset+len(data)
        valid_range = isinstance(raw_offset, int) and raw_offset < 0 < suffix_end <= self.total_bytes
        if not valid_range:
            errors.append("raw_offset_out_of_recorded_range")
        elif self._start_boundary_intervals or any(begin < suffix_end and end > 0
                                                   for begin, end in self._packet_intervals):
            errors.append("overlapping_boundary_raw_offsets")
            valid_range = False
        if valid_range:
            self._raw.flush()
            with (self.run_dir/"mul1_raw.bin").open("rb") as stream:
                suffix_matches = stream.read(suffix_end) == data[-raw_offset:]
            if not suffix_matches:
                errors.append("boundary_suffix_does_not_match_recorded_raw")
                valid_range = False
        if decoded["layout_valid"]:
            valid_expected = set()
            for module in decoded["modules"]:
                mid = module["module_id"]
                if module["error"]:
                    errors.append(module["error"])
                if module["valid"]:
                    if mid in self.expected_modules:
                        valid_expected.add(mid)
                    else:
                        errors.append("unexpected_valid_module_frames")
                    if self.target_mode and module["mode"] != self.target_mode:
                        errors.append("target_mode_mismatches")
            errors.extend("missing_valid_expected_updates"
                          for _ in set(self.expected_modules)-valid_expected)
        accounted = valid_range and decoded["outer_valid"] and decoded["layout_valid"] and not decoded["errors"]
        if accounted:
            self._start_boundary_intervals.append((0, suffix_end))
            self._outer_previous = decoded["sequence"]
        self._capture_start_boundary_packets += 1
        if counters is not None:
            current = _snapshot(counters)
            changes, resets = _counter_delta(self._counter_last, current)
            self._counter_resets.extend(resets)
            self._counter_last = current
            for scope in scopes:
                scope.session_observed_deltas.update(changes)
        for scope in scopes:
            scope.counts["capture_start_boundary_packets"] += 1
            scope.counts["capture_start_boundary_errors"] += len(errors)
            for code in errors:
                scope.counts["start_boundary_"+code] += 1
        self._event("capture_start_boundary", elapsed, raw_offset=raw_offset,
                    packet_sequence=decoded["sequence"], packet_bytes=len(data),
                    prefix_bytes_before_recording=max(0, -raw_offset),
                    suffix_bytes_in_recording=suffix_end if valid_range else None,
                    known_suffix_accounted=bool(accounted), outer_crc_ok=decoded["outer_valid"],
                    layout_valid=decoded["layout_valid"], errors=errors,
                    pc_parser_error=str(error) if error else None, modules=decoded["modules"],
                    statistical_scope="excluded_from_complete_packet_counts_rates_K_q_and_file_cache")

    def record_packet(self, data, packet=None, error=None, raw_offset=0, elapsed_s=None,
                      packet_started_at=None, counters=None):
        if not self.active:
            return
        elapsed = self._elapsed(elapsed_s)
        scopes = self._windows(elapsed)
        decoded = _decode(data)
        errors = list(decoded["errors"])
        if error:
            errors.append("pc_parser_error: "+str(error))
        if raw_offset < 0 or raw_offset+len(data) > self.total_bytes:
            errors.append("raw_offset_out_of_recorded_range")
        if self._packet_intervals and raw_offset < self._packet_intervals[-1][1]:
            errors.append("overlapping_packet_raw_offsets")
        if any(raw_offset < end and raw_offset+len(data) > begin
               for begin, end in self._start_boundary_intervals):
            errors.append("overlapping_packet_raw_offsets")
        self._packet_intervals.append((raw_offset, raw_offset+len(data)))
        if counters is not None:
            current = _snapshot(counters)
            changes, resets = _counter_delta(self._counter_last, current)
            self._counter_resets.extend(resets)
            self._counter_last = current
            for scope in scopes:
                scope.session_observed_deltas.update(changes)
        for scope in scopes:
            c = scope.counts
            c["packet_candidates"] += 1
            c["candidate_packet_bytes"] += len(data)
            if error:
                c["pc_parser_errors"] += 1
            for code in decoded["errors"]:
                c[code] += 1
            if decoded["outer_valid"]:
                c["valid_outer_packets"] += 1
                c["valid_outer_packet_bytes"] += len(data)
                c["expected_module_update_opportunities"] += len(self.expected_modules)
        if decoded["outer_valid"]:
            seq = decoded["sequence"]
            if self._outer_previous is not None:
                difference = (seq-self._outer_previous) & 0xffffffff
                code = None
                if difference == 0:
                    code = "outer_duplicate_packets"
                elif difference >= 0x80000000:
                    code = "outer_out_of_order_packets"
                elif difference > 1:
                    code = "outer_sequence_gap_events"
                if code:
                    for scope in scopes:
                        scope.counts[code] += 1
                        if code == "outer_sequence_gap_events":
                            scope.counts["outer_missing_sequence_numbers"] += difference-1
                    self._event(code, elapsed, previous=self._outer_previous, current=seq)
            self._outer_previous = seq
        valid_expected = set()
        module_errors = []
        if decoded["layout_valid"]:
            for module in decoded["modules"]:
                mid = module["module_id"]
                expected = mid in self.expected_modules
                chain = self._chains[mid]
                outcome = "not_updated" if module["status"] else "invalid"
                if module["valid"]:
                    if expected:
                        valid_expected.add(mid)
                    if module["marker"] == "ESKF":
                        if not chain["anchored"] or not chain["valid"]:
                            self._event("baseline_established", elapsed, module_id=mid,
                                        sequence=module["sequence"], trigger_reason="unknown")
                        chain.update(anchored=True, valid=True, applied=module["sequence"])
                        outcome = "applied_full_baseline"
                    elif not chain["anchored"]:
                        outcome = "initial_unanchored_delta"
                        if not chain["prefix_reported"]:
                            self._event("initial_unanchored_delta", elapsed, module_id=mid)
                            chain["prefix_reported"] = True
                    elif chain["valid"] and module["base_sequence"] == chain["applied"]:
                        chain["applied"] = module["sequence"]
                        outcome = "applied_delta"
                    else:
                        outcome = "unapplied_after_anchor"
                        if chain["valid"]:
                            for scope in scopes:
                                scope.modules[mid]["counts"]["base_break_events_after_anchor"] += 1
                                scope.counts["base_break_events_after_anchor"] += 1
                            self._event("base_chain_break", elapsed, module_id=mid,
                                        expected_base=chain["applied"], received_base=module["base_sequence"])
                        chain["valid"] = False
                    if module["marker"] == "ESKD" and chain["previous"] is not None and module["base_sequence"] != chain["previous"]:
                        for scope in scopes:
                            scope.modules[mid]["counts"]["observed_base_discontinuities"] += 1
                    chain["previous"] = module["sequence"]
                if module["error"]:
                    module_errors.append(module["error"])
                for scope in scopes:
                    stats, c = scope.modules[mid], scope.counts
                    stats["statuses"][f"0x{module['status']:02x}"] += 1
                    stats["counts"]["slot_observations"] += 1
                    if module["status"]:
                        c["diagnostic_payload_bytes"] += module["payload_bytes"]
                        if expected:
                            c["expected_not_updated_status_entries"] += 1
                            stats["counts"]["not_updated_status_entries"] += 1
                    if module["error"]:
                        c[module["error"]] += 1
                        stats["counts"][module["error"]] += 1
                    if not module["valid"]:
                        continue
                    c["valid_module_frames"] += 1
                    c["valid_module_payload_bytes"] += module["payload_bytes"]
                    c["valid_expected_module_frames" if expected else "unexpected_valid_module_frames"] += 1
                    stats["counts"]["valid_frames"] += 1
                    stats["counts"]["payload_bytes"] += module["payload_bytes"]
                    stats["counts"][module["marker"]] += 1
                    stats["counts"][outcome] += 1
                    stats["flags"][f"0x{module['flags']:02x}"] += 1
                    c[module["marker"]] += 1
                    c[outcome] += 1
                    if self.target_mode and module["mode"] != self.target_mode:
                        c["target_mode_mismatches"] += 1
                        stats["counts"]["target_mode_mismatches"] += 1
                    if module["marker"] == "ESKD":
                        for key in ("K", "K1", "K2"):
                            stats[key][module[key]] += 1
                    else:
                        stats["full_times"].append(elapsed)
                if module["error"] or (expected and module["status"]) or (module["valid"] and not expected):
                    self._event("module_observation_requires_review", elapsed,
                                packet_sequence=decoded["sequence"], **module)
                row = {key: module[key] for key in ("module_id", "status_name", "payload_bytes", "valid",
                    "marker", "mode", "sequence", "base_sequence", "K", "K1", "K2", "error", "diagnostic_prefix_hex")}
                row.update(elapsed_s=elapsed, packet_sequence=decoded["sequence"], expected=expected,
                           status=f"0x{module['status']:02x}", flags=None if module["flags"] is None else f"0x{module['flags']:02x}",
                           cache_outcome=outcome, main_window=elapsed >= self.config.settle_seconds)
                self._module_writer.writerow(row)
        if decoded["outer_valid"]:
            for scope in scopes:
                missing = set(self.expected_modules)-valid_expected
                scope.counts["missing_valid_expected_updates"] += len(missing)
                for mid in missing:
                    scope.modules[mid]["counts"]["missing_valid_updates"] += 1
                if not missing and self.expected_modules:
                    scope.counts["all_expected_modules_updated_packets"] += 1
                else:
                    scope.counts["partial_expected_update_packets"] += 1
                if decoded["layout_valid"] and not module_errors and not decoded["errors"]:
                    scope.counts["valid_inner_packets"] += 1
        errors.extend(module_errors)
        if errors:
            self._event("packet_review", elapsed, raw_offset=raw_offset, errors=errors)
        offset_errors = [e for e in errors if e in ("raw_offset_out_of_recorded_range", "overlapping_packet_raw_offsets")]
        for scope in scopes:
            scope.counts["raw_offset_errors"] += len(offset_errors)
        began = packet_started_at or self.started_at+timedelta(seconds=elapsed)
        if isinstance(began, datetime):
            began = began.isoformat(timespec="milliseconds")
        self._packet_writer.writerow({"elapsed_s": elapsed, "mul_start_time": began,
            "packet_completed_time": (self.started_at+timedelta(seconds=elapsed)).isoformat(),
            "raw_offset": raw_offset, "received_bytes": len(data), "declared_length": decoded["declared_length"],
            "packet_sequence": decoded["sequence"], "host_ms": decoded["host_ms"],
            "outer_crc_ok": decoded["outer_valid"], "parse_ok": not errors,
            "updated_mask": "" if decoded["updated_mask"] is None else f"0x{decoded['updated_mask']:02x}",
            "module_statuses": ",".join(m["status_name"] for m in decoded["modules"]),
            "algorithms": ",".join(("DELTA_SYNC" if m["marker"] == "ESKF" and m["mode"] == "DELTA" else m["mode"]) if m["valid"] else "NONE" for m in decoded["modules"]),
            "main_window": elapsed >= self.config.settle_seconds, "error": " | ".join(errors)})

    def expired(self):
        return self.active and time.monotonic()-self.started_monotonic >= self.config.duration_seconds

    def progress_status(self):
        elapsed = max(0.0, time.monotonic()-self.started_monotonic) if self.started_monotonic is not None else 0.0
        remaining = max(0.0, self.config.duration_seconds-elapsed)
        return RecordingStatus(f"Recording {elapsed:.1f}/{self.config.duration_seconds:g} s | {self.total_bytes:,} raw bytes",
                               "recording" if self.active else "idle", elapsed, remaining)

    def _scope_summary(self, scope, elapsed, complete):
        duration = max(0.0, elapsed-scope.start)
        c = scope.counts
        rate = lambda value: value/duration if duration else None
        modules = {}
        pooled = Counter()
        for mid, stats in enumerate(scope.modules):
            mc = stats["counts"]
            frames = mc["valid_frames"]
            gaps = [b-a for a, b in zip(stats["full_times"], stats["full_times"][1:])]
            modules[f"M{mid}"] = {"expected": mid in self.expected_modules,
                "counts": dict(mc), "status_counts": dict(stats["statuses"]), "flags_counts": dict(stats["flags"]),
                "q_ESKF": mc["ESKF"]/frames if frames else None,
                "K": _histogram(stats["K"]), "K1": _histogram(stats["K1"]), "K2": _histogram(stats["K2"]),
                "K_histogram": dict(sorted(stats["K"].items())), "valid_update_rate_Hz": rate(frames),
                "ESKF_interval_count": len(gaps), "ESKF_interval_mean_s": sum(gaps)/len(gaps) if gaps else None,
                "ESKF_interval_min_s": min(gaps) if gaps else None,
                "ESKF_interval_max_s": max(gaps) if gaps else None,
                "ESKF_trigger_reason": "unknown_without_correlated_firmware_events"}
            pooled.update(stats["K"])
        reasons = []
        if not complete:
            reasons.append("recording_ended_before_requested_duration")
        if duration <= 0 or c["valid_outer_packets"] == 0:
            reasons.append("no_valid_packets_in_window")
        if not self.expected_modules:
            reasons.append("target_modules_not_configured")
        if not self.target_mode:
            reasons.append("target_mode_not_configured")
        fail_counts = ("outer_format_error", "outer_length_error", "outer_crc_error", "module_layout_error",
            "updated_mask_error", "inner_format_error", "inner_header_error", "inner_crc_error", "inner_flags_error",
            "delta_mask_length_error", "diagnostic_length_error", "pc_parser_errors", "raw_offset_errors",
            "outer_duplicate_packets", "outer_out_of_order_packets", "outer_sequence_gap_events",
            "missing_valid_expected_updates", "unexpected_valid_module_frames", "target_mode_mismatches",
            "base_break_events_after_anchor", "unapplied_after_anchor", "capture_start_boundary_errors")
        reasons.extend(key for key in fail_counts if c[key])
        if c["initial_unanchored_delta"]:
            reasons.append("initial_delta_prefix_cache_not_verifiable_from_file")
        frames, packets = c["valid_module_frames"], c["valid_outer_packets"]
        return {"start_elapsed_s": scope.start, "end_elapsed_s": elapsed if duration else scope.start,
            "actual_duration_seconds": duration, "requested_duration_seconds": self.config.duration_seconds-scope.start,
            "counts": dict(c), "status": "CHECK REQUIRED" if reasons else "PASS", "review_reasons": reasons,
            "raw_arrival_bytes": c["raw_arrival_bytes"], "raw_arrival_bytes_per_s": rate(c["raw_arrival_bytes"]),
            "raw_arrival_Mbit_per_s": rate(c["raw_arrival_bytes"]*8/1e6),
            "valid_outer_packet_bytes": c["valid_outer_packet_bytes"],
            "Lmean_valid_packet_B": c["valid_outer_packet_bytes"]/packets if packets else None,
            "packet_completion_Mbit_per_s": rate(c["valid_outer_packet_bytes"]*8/1e6),
            "valid_outer_packet_rate_Hz": rate(packets),
            "all_expected_modules_updated_rate_Hz": rate(c["all_expected_modules_updated_packets"]),
            "valid_expected_module_frames": c["valid_expected_module_frames"],
            "expected_module_update_opportunities": c["expected_module_update_opportunities"],
            "q_ESKF": c["ESKF"]/frames if frames else None,
            "K_ESKD_pooled": _histogram(pooled), "modules": modules,
            "session_counter_delta_at_packet_observation": dict(scope.session_observed_deltas),
            "byte_window_note": "raw by chunk arrival; complete packet bytes by completion and only for packets fully contained in raw; start-boundary packets are excluded"}

    def _audit_unassigned_raw(self):
        """Intersect unframed raw ranges with timestamped arrival chunks."""
        merged = []
        for begin, end in sorted(self._packet_intervals+self._start_boundary_intervals):
            begin, end = max(0, begin), min(self.total_bytes, end)
            if end <= begin:
                continue
            if merged and begin <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((begin, end))
        gaps, cursor = [], 0
        for begin, end in merged:
            if cursor < begin:
                gaps.append((cursor, begin, "leading" if cursor == 0 else "interior"))
            cursor = end
        if cursor < self.total_bytes:
            gaps.append((cursor, self.total_bytes, "trailing" if merged else "unframed"))
        index = 0
        for begin, end, elapsed in self._raw_chunks:
            for lo, hi in self._start_boundary_intervals:
                overlap = max(0, min(hi, end)-max(lo, begin))
                for scope in self._windows(elapsed):
                    scope.counts["known_start_boundary_bytes"] += overlap
            while index < len(gaps) and gaps[index][1] <= begin:
                index += 1
            scan = index
            while scan < len(gaps) and gaps[scan][0] < end:
                lo, hi, kind = gaps[scan]
                overlap = max(0, min(hi, end)-max(lo, begin))
                for scope in self._windows(elapsed):
                    scope.counts["unassigned_raw_bytes"] += overlap
                    scope.counts[kind+"_unassigned_raw_bytes"] += overlap
                scan += 1

    def finish(self, counters, reason):
        if not self.active:
            return self._finished_status
        elapsed = max(self._elapsed(), self._last_elapsed)
        complete = elapsed+1e-6 >= self.config.duration_seconds
        end = _snapshot(counters)
        delta, resets = _counter_delta(self._counter_start, end)
        self._counter_resets.extend(resets)
        self._audit_unassigned_raw()
        scopes = {name: self._scope_summary(scope, elapsed, complete) for name, scope in self.scopes.items()}
        full = scopes["full_run"]
        full["session_counter_delta"] = delta
        session_error_names = {"outer_crc_errors", "inner_crc_errors", "sequence_gap_events", "lost_frames",
                               "duplicate_frames", "out_of_order_frames", "format_errors", "delta_base_mismatches"}
        for name, scope in scopes.items():
            local = delta if name == "full_run" else scope["session_counter_delta_at_packet_observation"]
            scope["review_reasons"].extend("session_"+k for k in sorted(session_error_names) if local.get(k, 0))
            if self._counter_resets:
                scope["review_reasons"].append("session_counter_reset_during_recording")
            raw_counts = self.scopes[name].counts
            scope["unassigned_raw_bytes"] = raw_counts["unassigned_raw_bytes"]
            scope["known_start_boundary_bytes"] = raw_counts["known_start_boundary_bytes"]
            scope["raw_boundary_warnings"] = [key for key in
                ("leading_unassigned_raw_bytes", "trailing_unassigned_raw_bytes") if raw_counts[key]]
            if name == "full_run" and raw_counts["unassigned_raw_bytes"]:
                scope["review_reasons"].append("unassigned_raw_bytes_in_full_capture")
            elif raw_counts["interior_unassigned_raw_bytes"] or raw_counts["unframed_unassigned_raw_bytes"]:
                scope["review_reasons"].append("unassigned_interior_or_unframed_raw_bytes")
            if scope["review_reasons"]:
                scope["status"] = "CHECK REQUIRED"
        warnings = []
        if not self.metadata.get("deployment_confirmed", False):
            warnings.append("deployment_not_confirmed_by_operator; local hashes do not verify device flash")
        self._event("recording_finished", elapsed, reason=reason, main_status=scopes["main"]["status"])
        for handle in self._files:
            handle.close()
        self.active = False
        condition = dict(self.metadata)
        condition.update(N=len(self.expected_modules), module_count=len(self.expected_modules),
            algorithm=self.target_mode, target_mode=self.target_mode, modules=[f"M{m}" for m in self.expected_modules],
            active_module_ids=[f"M{m}" for m in self.expected_modules],
            target_modules=self.expected_modules, scan_hz=self.metadata.get("target_hz"),
            target_scan_rate_hz=self.metadata.get("target_hz"),
            load_label=self.metadata.get("load_label", self.metadata.get("condition", self.metadata.get("load_condition", ""))))
        result = scopes["main"]["status"]+": "+("main window checks passed" if scopes["main"]["status"] == "PASS" else "; ".join(scopes["main"]["review_reasons"]))
        summary = {"schema_version": 2, "run_id": self.run_id, "started_at": self.started_at.isoformat(),
            "duration_seconds": elapsed, "requested_duration_seconds": self.config.duration_seconds,
            "settle_seconds": self.config.settle_seconds, "capture_overrun_seconds": max(0, elapsed-self.config.duration_seconds),
            "reason": str(reason), "completed_requested_duration": complete, "port": self.port_name, "baud": self.baud,
            "metadata": self.metadata, "metadata_warnings": warnings, "test_condition": condition,
            "provenance_note": "Local artifact hashes identify source/build files; no device flash readback was performed by this recorder.",
            "expected_module_mask": f"0x{self.expected_mask:02x}", "commands": self._commands,
            "recorded_bytes": self.total_bytes, "raw_sha256": self._raw_sha.hexdigest(),
            "recorded_candidate_rows": self.scopes["full_run"].counts["packet_candidates"],
            "complete_mul_count": self.scopes["full_run"].counts["valid_outer_packets"],
            "capture_start_boundary_packets": self._capture_start_boundary_packets,
            "result": result, "result_scope": "main", "scopes": scopes,
            "counters": delta, "session_counters": {"start": self._counter_start, "end": end, "delta": delta,
                                                         "reset_keys": sorted(set(self._counter_resets))},
            "definitions": {"initial_unanchored_delta": "valid ESKD before first recorded baseline, not proven loss",
                "main_cache": "cache is built from complete packets in recorded settle prefix and carried into main; start-boundary packets do not seed the file cache",
                "module_missing": "target slot has no valid update; not a count of lost physical scans",
                "q": "ESKF/(ESKF+ESKD) over valid module frames; no trigger-cause attribution",
                "K": "ordinary ESKD mask popcount only; histogram SD is within-run population SD",
                "session_main": "counter increments attributed at next complete or known start-boundary packet observation; independent backend window audits remain separate",
                "complete_packet_bytes": "only complete packet candidates fully contained in this raw file; known start-boundary packets do not contribute complete counts, rates, K or q",
                "known_start_boundary_bytes": "actual raw suffix bytes of independently validated outer/layout packets whose prefix arrived before recording; counted by chunk arrival, without writing pre-record bytes; module/parser errors remain explicit",
                "unassigned_raw": "bytes outside logged candidate and validated start-boundary suffix ranges, attributed by chunk arrival; interior gaps require review; other leading/trailing fragments retain boundary warnings in main and require review in full capture",
                "outer_sequence": "Teensy enqueue sequence, not STM32 physical scan count"},
            "files": {key: str(self.run_dir/name) for key, name in
                      (("raw_usb", "mul1_raw.bin"), ("packet_log", "packet_log.csv"),
                       ("module_log", "module_log.csv"), ("events", "events.jsonl"),
                       ("summary", "summary.json"), ("experiment_log", "experiment_log.md"))}}
        (self.run_dir/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2,
            allow_nan=False, default=_json_default)+"\n", encoding="utf-8")
        lines = [f"# Experiment {self.run_id}", "", f"Started: {self.started_at.isoformat()}",
            f"Actual duration: {elapsed:.6f} s; requested: {self.config.duration_seconds:g} s; settle: {self.config.settle_seconds:g} s.",
            f"Result (main window): {result}", "", "## Conditions", "", "```json",
            json.dumps(condition, ensure_ascii=False, indent=2), "```", "", "## Scope checks", ""]
        for name, scope in scopes.items():
            lines.extend([f"- {name}: {scope['status']}; {scope['actual_duration_seconds']:.6f} s; "
                          f"{scope['counts'].get('valid_outer_packets', 0)} valid MUL1; "
                          f"{scope['valid_expected_module_frames']}/{scope['expected_module_update_opportunities']} target updates.",
                          f"  Review reasons: {', '.join(scope['review_reasons']) or 'none'}."])
        lines.extend(["", "Raw bytes are assigned by chunk arrival; complete packet bytes by completion time.",
                      f"Start-boundary packets: {self._capture_start_boundary_packets}; suffixes are audited separately and excluded from complete packet rates, K and q.",
                      "Missing updates and unknown initial cache prefixes are not proven physical-scan losses.",
                      summary["provenance_note"]])
        (self.run_dir/"experiment_log.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        self._finished_status = RecordingStatus(f"Recording complete: {result} | {self.run_dir}", "complete", elapsed, 0.0)
        return self._finished_status
