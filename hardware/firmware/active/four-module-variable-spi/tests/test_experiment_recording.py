"""Backend tests with real protocol bytes and a controlled monotonic clock."""
from collections import Counter
from datetime import datetime, timezone
import csv
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

MODULE = Path(__file__).resolve().parents[1]/"pc"/"experiment_recording.py"
spec = importlib.util.spec_from_file_location("experiment_recording_backend_test", MODULE)
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


def full(seq, delta=True):
    data = bytearray(1044)
    data[:4] = b"ESKF"
    struct.pack_into("<BBHII", data, 4, 4, 0x33 if delta else 0x13, 1044, seq, 0xffffffff)
    struct.pack_into("<I", data, 1040, zlib.crc32(data[:1040]))
    return bytes(data)


def delta(seq, base, indices=(0, 257)):
    data = bytearray(84+2*len(indices))
    data[:4] = b"ESKD"
    struct.pack_into("<BBHII", data, 4, 4, 0x33, len(data), seq, base)
    for index in indices:
        data[16+index//8] |= 1 << (index % 8)
    for i in range(len(indices)):
        struct.pack_into("<H", data, 80+i*2, 100+i)
    struct.pack_into("<I", data, len(data)-4, zlib.crc32(data[:-4]))
    return bytes(data)


def packet(sequence, modules):
    data = bytearray(20)
    data[:6] = b"MUL1\x02\x04"
    struct.pack_into("<II", data, 12, sequence, sequence*5)
    for mid in range(4):
        value = modules.get(mid, (0x83, b""))
        if isinstance(value, tuple):
            status, payload = value
        else:
            status, payload = 0, value
            data[6] |= 1 << mid
        data.extend(struct.pack("<BBH", mid, status, len(payload)))
        data.extend(payload)
    data.extend(b"\0"*4)
    struct.pack_into("<H", data, 8, len(data))
    struct.pack_into("<I", data, len(data)-4, zlib.crc32(data[:-4]))
    return bytes(data)


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = 100.0
        self.timer = patch.object(backend.time, "monotonic", side_effect=lambda: self.clock)
        self.timer.start()
        self.rec = None

    def tearDown(self):
        if self.rec and self.rec.active:
            self.rec.finish({}, "test cleanup")
        self.timer.stop()
        self.tmp.cleanup()

    def begin(self, modules=(0,), mode="DELTA", start_counters=None, settle=1, duration=4):
        config = backend.RecordingConfig(output_dir=Path(self.tmp.name), duration_seconds=duration,
            settle_seconds=settle, metadata={"target_modules": list(modules), "target_mode": mode,
            "target_hz": 200, "condition": "zero_load", "deployment_confirmed": False})
        self.rec = backend.ExperimentRecorder("FAKE", 2_000_000, config)
        self.rec.start(start_counters or {}, started_at=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
                       started_monotonic=100)
        return self.rec

    def add(self, data, elapsed, counters=None, error=None):
        offset = self.rec.total_bytes
        self.rec.record_raw(data, elapsed_s=elapsed)
        self.rec.record_packet(data, raw_offset=offset, elapsed_s=elapsed, counters=counters, error=error)

    def finish(self, elapsed=4, counters=None):
        self.clock = 100+elapsed
        self.rec.finish(counters or {}, "completed" if elapsed >= 4 else "stopped early")
        return json.loads((self.rec.run_dir/"summary.json").read_text(encoding="utf-8"))

    def test_full_and_delta_status_bits_q_and_cache_from_settle(self):
        self.begin(start_counters={"format_errors": 9})
        self.add(packet(1, {0: full(10)}), .2, counters={"format_errors": 9})
        self.add(packet(2, {0: delta(11, 10)}), 1.2, counters={"format_errors": 9})
        self.add(packet(3, {0: full(12)}), 2.0, counters={"format_errors": 9})
        summary = self.finish(counters={"format_errors": 9})
        main = summary["scopes"]["main"]
        self.assertEqual(main["status"], "PASS")
        self.assertEqual(main["q_ESKF"], .5)
        self.assertEqual(main["K_ESKD_pooled"]["mean"], 2)
        self.assertEqual(main["modules"]["M0"]["K1"]["mean"], 1)
        self.assertEqual(main["modules"]["M0"]["K2"]["mean"], 1)
        self.assertEqual(main["modules"]["M0"]["flags_counts"], {"0x33": 2})
        self.assertEqual(summary["counters"]["format_errors"], 0)
        self.assertEqual(main["actual_duration_seconds"], 3)
        self.assertEqual(summary["test_condition"]["algorithm"], "DELTA")
        self.assertEqual(summary["test_condition"]["load_label"], "zero_load")
        self.assertTrue(summary["metadata_warnings"])

    def test_full_flag_0x13_and_expected_mode(self):
        self.begin(mode="FULL")
        self.add(packet(1, {0: full(0, delta=False)}), 1.1)
        summary = self.finish()
        self.assertEqual(summary["scopes"]["main"]["status"], "PASS")
        self.assertIsNone(summary["scopes"]["main"]["K_ESKD_pooled"]["mean"])
        self.assertEqual(summary["scopes"]["main"]["q_ESKF"], 1)

    def test_all_raw_bytes_preserved_without_packet_double_write(self):
        self.begin(mode="FULL")
        data = packet(7, {0: full(1, delta=False)})
        self.rec.record_raw(b"boot", elapsed_s=.1)
        self.rec.record_raw(data[:90], elapsed_s=.9)
        self.rec.record_raw(data[90:], elapsed_s=1.1)
        self.rec.record_packet(data, raw_offset=4, elapsed_s=1.1)
        self.rec.record_raw(b"MUL1\x02", elapsed_s=3.99)
        summary = self.finish()
        self.assertEqual((self.rec.run_dir/"mul1_raw.bin").read_bytes(), b"boot"+data+b"MUL1\x02")
        self.assertEqual(summary["recorded_bytes"], 4+len(data)+5)
        whole, main = summary["scopes"]["full_run"], summary["scopes"]["main"]
        self.assertEqual(whole["unassigned_raw_bytes"], 9)
        self.assertEqual(whole["status"], "CHECK REQUIRED")
        self.assertEqual(main["counts"]["trailing_unassigned_raw_bytes"], 5)
        self.assertEqual(main["raw_arrival_bytes"], len(data)-90+5)
        self.assertEqual(main["valid_outer_packet_bytes"], len(data))
        self.assertEqual(main["status"], "PASS")
        with (self.rec.run_dir/"packet_log.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_offset"], "4")

    def test_interior_garbage_main_requires_review(self):
        self.begin(mode="FULL")
        self.add(packet(1, {0: full(1, delta=False)}), 1.1)
        self.rec.record_raw(b"junk", elapsed_s=2)
        self.add(packet(2, {0: full(2, delta=False)}), 2.1)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["counts"]["interior_unassigned_raw_bytes"], 4)
        self.assertIn("unassigned_interior_or_unframed_raw_bytes", main["review_reasons"])

    def test_partial_module_updates_diagnostic_bytes_and_no_false_crc(self):
        self.begin(modules=(0, 1, 2, 3))
        self.add(packet(1, {0: (0x80, b""), 1: full(1), 2: full(1),
                            3: (0x87, b"bad frame prefix")}), 1.2)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["valid_expected_module_frames"], 2)
        self.assertEqual(main["expected_module_update_opportunities"], 4)
        self.assertEqual(main["counts"]["missing_valid_expected_updates"], 2)
        self.assertEqual(main["counts"]["diagnostic_payload_bytes"], 16)
        self.assertEqual(main["counts"]["valid_outer_packets"], 1)
        self.assertEqual(main["counts"].get("inner_crc_error", 0), 0)
        self.assertEqual(main["status"], "CHECK REQUIRED")

    def test_unexpected_module_and_wrong_mode_are_reviewed(self):
        self.begin(mode="FULL")
        self.add(packet(1, {0: full(1), 1: full(1)}), 1.2)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["counts"]["unexpected_valid_module_frames"], 1)
        self.assertEqual(main["counts"]["target_mode_mismatches"], 2)
        self.assertEqual(main["status"], "CHECK REQUIRED")

    def test_inner_crc_error_does_not_discard_other_modules(self):
        self.begin(modules=(0, 1))
        broken = bytearray(full(1))
        broken[24] ^= 1
        self.add(packet(1, {0: bytes(broken), 1: full(1)}), 1.2)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["counts"]["inner_crc_error"], 1)
        self.assertEqual(main["valid_expected_module_frames"], 1)
        self.assertEqual(main["modules"]["M1"]["counts"]["applied_full_baseline"], 1)

    def test_prefix_break_episode_and_full_recovery_are_distinct(self):
        self.begin()
        self.add(packet(1, {0: delta(8, 7)}), .1)
        self.add(packet(2, {0: full(10)}), .2)
        self.add(packet(3, {0: delta(11, 999)}), 1.1)
        self.add(packet(4, {0: delta(12, 11)}), 1.2)
        self.add(packet(5, {0: full(13)}), 1.3)
        self.add(packet(6, {0: delta(14, 13)}), 1.4)
        summary = self.finish()
        whole, main = summary["scopes"]["full_run"], summary["scopes"]["main"]
        self.assertEqual(whole["counts"]["initial_unanchored_delta"], 1)
        self.assertEqual(main["counts"].get("initial_unanchored_delta", 0), 0)
        self.assertEqual(main["counts"]["base_break_events_after_anchor"], 1)
        self.assertEqual(main["counts"]["unapplied_after_anchor"], 2)
        self.assertEqual(main["counts"]["applied_delta"], 1)

    def test_settle_error_does_not_poison_main_counter_delta(self):
        self.begin(start_counters={"format_errors": 5})
        self.add(b"invalid bytes", .1, counters={"format_errors": 6}, error="invalid format")
        self.add(packet(1, {0: full(1)}), .5, counters={"format_errors": 6})
        self.add(packet(2, {0: delta(2, 1)}), 1.2, counters={"format_errors": 6})
        summary = self.finish(counters={"format_errors": 6})
        self.assertEqual(summary["counters"]["format_errors"], 1)
        self.assertEqual(summary["scopes"]["full_run"]["status"], "CHECK REQUIRED")
        self.assertEqual(summary["scopes"]["main"]["status"], "PASS")

    def test_empty_and_early_recording_cannot_pass(self):
        self.begin()
        summary = self.finish(elapsed=2)
        self.assertFalse(summary["completed_requested_duration"])
        self.assertEqual(summary["scopes"]["main"]["status"], "CHECK REQUIRED")
        self.assertIn("no_valid_packets_in_window", summary["scopes"]["main"]["review_reasons"])

    def test_directory_collision_cannot_overwrite(self):
        first = self.begin()
        first.record_raw(b"preserve", elapsed_s=.1)
        second = backend.ExperimentRecorder("FAKE", 1, first.config)
        with self.assertRaises(FileExistsError):
            second.start({}, started_at=first.started_at, started_monotonic=100)
        self.finish()
        self.assertEqual((first.run_dir/"mul1_raw.bin").read_bytes(), b"preserve")

    def test_status_defaults_and_histogram_reference(self):
        self.assertIsNone(backend.RecordingStatus("notice").elapsed_seconds)
        self.assertEqual(backend.RecordingStatus("notice").phase, "info")
        stats = backend._histogram(Counter([0, 0, 2, 4]))
        self.assertEqual(stats["mean"], 1.5)
        self.assertEqual(stats["median"], 1)
        self.assertAlmostEqual(stats["p95"], 3.7)
        self.assertIsNone(backend._histogram(Counter())["sd_population"])

    def test_small_durations_commands_and_actual_overrun(self):
        self.begin(duration=.75, settle=.05, mode="FULL")
        self.clock = 100.1
        self.rec.note_command("RESYNC DELTA", source="automatic_recovery")
        self.add(packet(1, {0: full(1, delta=False)}), .2)
        self.clock = 100.8
        self.assertTrue(self.rec.expired())
        self.rec.finish({}, "capture deadline")
        summary = json.loads((self.rec.run_dir/"summary.json").read_text())
        self.assertAlmostEqual(summary["capture_overrun_seconds"], .05)
        self.assertEqual(summary["commands"][0]["source"], "automatic_recovery")

    def test_known_start_boundary_preserves_raw_and_excludes_complete_statistics(self):
        self.begin(mode="FULL")
        crossing = packet(10, {0: full(1, delta=False)})
        following = packet(11, {0: full(2, delta=False)})
        self.rec.record_raw(crossing[11:], elapsed_s=.2)
        self.rec.record_start_boundary(crossing, raw_offset=-11, elapsed_s=.2)
        self.add(following, 1.2)
        summary = self.finish()
        whole = summary["scopes"]["full_run"]
        self.assertEqual((self.rec.run_dir/"mul1_raw.bin").read_bytes(), crossing[11:]+following)
        self.assertEqual(summary["capture_start_boundary_packets"], 1)
        self.assertEqual(summary["complete_mul_count"], 1)
        self.assertEqual(whole["known_start_boundary_bytes"], len(crossing)-11)
        self.assertEqual(whole["unassigned_raw_bytes"], 0)
        self.assertEqual(whole["valid_outer_packet_bytes"], len(following))
        self.assertEqual(whole["counts"]["valid_module_frames"], 1)
        self.assertEqual(whole["q_ESKF"], 1)
        self.assertEqual(whole["status"], "PASS")
        with (self.rec.run_dir/"packet_log.csv").open(newline="", encoding="utf-8") as stream:
            logged = list(csv.DictReader(stream))
        self.assertEqual(len(logged), 1)
        self.assertEqual(int(logged[0]["raw_offset"]), len(crossing)-11)
        events = [json.loads(line) for line in (self.rec.run_dir/"events.jsonl").read_text().splitlines()]
        boundary = next(event for event in events if event["event"] == "capture_start_boundary")
        self.assertEqual(boundary["packet_sequence"], 10)
        self.assertTrue(boundary["known_suffix_accounted"])
        self.assertEqual(boundary["errors"], [])

    def test_boundary_does_not_supply_an_unrecorded_delta_baseline(self):
        self.begin()
        crossing = packet(10, {0: full(1)})
        self.rec.record_raw(crossing[11:], elapsed_s=.2)
        self.rec.record_start_boundary(crossing, raw_offset=-11, elapsed_s=.2)
        self.add(packet(11, {0: delta(2, 1)}), 1.2)
        whole = self.finish()["scopes"]["full_run"]
        self.assertEqual(whole["counts"]["initial_unanchored_delta"], 1)
        self.assertEqual(whole["counts"].get("ESKF", 0), 0)
        self.assertEqual(whole["K_ESKD_pooled"]["n"], 1)
        self.assertEqual(whole["K_ESKD_pooled"]["mean"], 2)

    def test_boundary_module_and_parser_errors_remain_explicit(self):
        self.begin(modules=(0, 1), mode="FULL")
        broken = bytearray(full(1, delta=False))
        broken[30] ^= 1
        crossing = packet(10, {0: bytes(broken), 2: full(1)})
        self.rec.record_raw(crossing[11:], elapsed_s=1.1)
        self.rec.record_start_boundary(crossing, -11, elapsed_s=1.1, error="live parse rejected")
        self.add(packet(11, {0: full(2, delta=False), 1: full(2, delta=False)}), 1.2)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["known_start_boundary_bytes"], len(crossing)-11)
        self.assertEqual(main["unassigned_raw_bytes"], 0)
        self.assertEqual(main["status"], "CHECK REQUIRED")
        self.assertIn("capture_start_boundary_errors", main["review_reasons"])
        for key, value in {"inner_crc_error": 1, "missing_valid_expected_updates": 2,
                           "unexpected_valid_module_frames": 1, "target_mode_mismatches": 1,
                           "pc_parser_errors": 1}.items():
            self.assertEqual(main["counts"]["start_boundary_"+key], value)
        self.assertEqual(main["expected_module_update_opportunities"], 2)
        self.assertEqual(main["valid_expected_module_frames"], 2)

    def test_boundary_bad_outer_crc_cannot_hide_raw_bytes(self):
        self.begin(mode="FULL")
        crossing = bytearray(packet(10, {0: full(1, delta=False)}))
        crossing[-1] ^= 1
        self.rec.record_raw(crossing[11:], elapsed_s=1.1)
        self.rec.record_start_boundary(crossing, -11, elapsed_s=1.1)
        self.add(packet(11, {0: full(2, delta=False)}), 1.2)
        main = self.finish()["scopes"]["main"]
        self.assertEqual(main["known_start_boundary_bytes"], 0)
        self.assertEqual(main["unassigned_raw_bytes"], len(crossing)-11)
        self.assertEqual(main["counts"]["start_boundary_outer_crc_error"], 1)
        self.assertEqual(main["status"], "CHECK REQUIRED")

    def test_boundary_claim_must_match_actual_raw_suffix(self):
        self.begin(mode="FULL")
        crossing = packet(10, {0: full(1, delta=False)})
        self.rec.record_raw(b"X"+crossing[12:], elapsed_s=.2)
        self.rec.record_start_boundary(crossing, -11, elapsed_s=.2)
        self.add(packet(11, {0: full(2, delta=False)}), 1.2)
        whole = self.finish()["scopes"]["full_run"]
        self.assertEqual(whole["known_start_boundary_bytes"], 0)
        self.assertEqual(whole["unassigned_raw_bytes"], len(crossing)-11)
        self.assertEqual(whole["counts"]["start_boundary_boundary_suffix_does_not_match_recorded_raw"], 1)
        self.assertEqual(whole["status"], "CHECK REQUIRED")

    def test_boundary_updates_counter_checkpoint_before_main(self):
        self.begin(mode="FULL", start_counters={"format_errors": 5, "valid_packets": 10})
        crossing = packet(10, {0: full(1, delta=False)})
        self.rec.record_raw(crossing[11:], elapsed_s=.2)
        self.rec.record_start_boundary(crossing, -11, elapsed_s=.2, error="live parser error",
                                       counters={"format_errors": 6, "valid_packets": 11})
        self.add(packet(11, {0: full(2, delta=False)}), 1.2,
                 counters={"format_errors": 6, "valid_packets": 12})
        summary = self.finish(counters={"format_errors": 6, "valid_packets": 12})
        self.assertEqual(summary["scopes"]["full_run"]["status"], "CHECK REQUIRED")
        self.assertEqual(summary["scopes"]["main"]["status"], "PASS")
        changes = summary["scopes"]["main"]["session_counter_delta_at_packet_observation"]
        self.assertEqual(changes["format_errors"], 0)
        self.assertEqual(changes["valid_packets"], 1)

    def test_known_boundary_bytes_follow_raw_arrival_windows(self):
        self.begin(mode="FULL")
        crossing = packet(10, {0: full(1, delta=False)})
        self.rec.record_raw(crossing[11:30], elapsed_s=.5)
        self.rec.record_raw(crossing[30:], elapsed_s=1.1)
        self.rec.record_start_boundary(crossing, -11, elapsed_s=1.1)
        self.add(packet(11, {0: full(2, delta=False)}), 1.2)
        summary = self.finish()
        self.assertEqual(summary["scopes"]["full_run"]["known_start_boundary_bytes"], len(crossing)-11)
        self.assertEqual(summary["scopes"]["main"]["known_start_boundary_bytes"], len(crossing)-30)
        self.assertEqual(summary["scopes"]["main"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
