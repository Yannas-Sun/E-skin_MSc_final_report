"""Headless GUI/serial integration checks; never opens a real serial device.

Run with the project Python environment. The optional --render path saves an
Agg screenshot after all assertions pass. All recording output uses temporary
directories, never the experiment data directory.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

os.environ["MPLBACKEND"] = "Agg"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
GUI_PATH = ROOT / "pc/four-module-fsr-monitor.py"


def load_gui():
    name = "recording_integration_gui"
    spec = importlib.util.spec_from_file_location(name, GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def corrupt_inner(frame):
    damaged = bytearray(frame)
    damaged[100] ^= 1
    return bytes(damaged)


class FakeSerialException(Exception):
    pass


class FakeClock:
    def __init__(self, step_seconds=0.025):
        self.value = 1000.0
        self.step_seconds = step_seconds

    def monotonic(self):
        return self.value


class FakePort:
    """Deliver real packet bytes in awkward chunks and then serial timeouts."""

    def __init__(self, chunks, stop, clock, on_read=None):
        self.chunks = list(chunks)
        self.stop = stop
        self.clock = clock
        self.timeout = 0.25
        self.received = bytearray()
        self.written = []
        self.empty_reads = 0
        self.read_count = 0
        self.on_read = on_read

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, length=1):
        self.clock.value += self.clock.step_seconds
        self.read_count += 1
        if not self.chunks:
            self.empty_reads += 1
            if self.empty_reads >= 80:
                self.stop.set()
            if self.on_read:
                self.on_read(self)
            return b""
        chunk = self.chunks[0][:length]
        self.chunks[0] = self.chunks[0][length:]
        if not self.chunks[0]:
            self.chunks.pop(0)
        self.received.extend(chunk)
        if self.on_read:
            self.on_read(self)
        return chunk

    def write(self, data):
        self.written.append(data)
        return len(data)

    def flush(self):
        pass


class GuiRecordingIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui()

    def setUp(self):
        self.m = self.gui
        self.plot_launcher = mock.patch.object(self.m, "launch_recording_plots").start()
        self.addCleanup(mock.patch.stopall)

    def full_packet(self, sequence=10):
        return self.m.make_packet([
            self.m.make_full_frame(sequence, 100 * module)
            for module in range(4)
        ], sequence)

    def selected_packet(self, modules=(0, 3), mode="FULL", sequence=10):
        data = bytearray(20)
        data[:7] = b"MUL1\x02\x04" + bytes([sum(1 << i for i in modules)])
        struct.pack_into("<II", data, 12, sequence, 99)
        for module in range(4):
            frame = (self.m.make_full_frame(sequence, 100 * module,
                                            flags=0x33 if mode == "DELTA" else 0x13)
                     if module in modules else b"")
            data.extend(bytes([module, 0 if frame else 0x83]))
            data.extend(struct.pack("<H", len(frame)))
            data.extend(frame)
        data.extend(bytes(4))
        struct.pack_into("<H", data, 8, len(data))
        struct.pack_into("<I", data, len(data) - 4,
                         self.m.zlib.crc32(data[:-4]) & 0xFFFFFFFF)
        return bytes(data)

    def observed_packet(self, modules=(0, 3), mode="FULL", now=1.0):
        detector = self.m.ModuleDetector()
        for sequence, timestamp in enumerate((now - 1.0, now - 0.5, now), 10):
            packet = self.m.parse_multi_packet(self.selected_packet(modules, mode, sequence))
            packet.received_monotonic = timestamp
            packet.detection = detector.observe(packet, timestamp)
        return packet

    def test_import_by_filename_without_pc_on_sys_path(self):
        # Mirrors run_protocol_regression.py; -I also excludes cwd/PYTHONPATH.
        source = (
            "import importlib.util,sys; "
            f"p={str(GUI_PATH)!r}; "
            "s=importlib.util.spec_from_file_location('isolated_gui',p); "
            "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
            "s.loader.exec_module(m); m.self_test()"
        )
        result = subprocess.run([sys.executable, "-I", "-c", source],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_outer_crc_failure_cannot_mutate_any_module(self):
        states = [self.m.ProtocolState() for _ in range(4)]
        self.m.parse_multi_packet(self.full_packet(10), states)
        bad = bytearray(self.full_packet(11))
        bad[150] ^= 1
        with self.assertRaises(ValueError):
            self.m.parse_multi_packet(bytes(bad), states, allow_partial=True)
        self.assertEqual([s.last_sequence for s in states], [10] * 4)

    def test_partial_packet_preserves_healthy_modules_and_all_errors(self):
        states = [self.m.ProtocolState() for _ in range(4)]
        self.m.parse_multi_packet(self.full_packet(10), states)
        frames = [self.m.make_full_frame(11, 1000 + i) for i in range(4)]
        frames[1] = corrupt_inner(frames[1])
        frames[3] = corrupt_inner(frames[3])
        parsed = self.m.parse_multi_packet(self.m.make_packet(frames, 11),
                                          states, allow_partial=True)
        self.assertEqual([s.last_sequence for s in states], [11, 10, 11, 10])
        self.assertEqual(parsed.algorithms, ("FULL", None, "FULL", None))
        self.assertEqual(sum(bool(error) for error in parsed.errors), 2)
        self.assertEqual(int(parsed.states[0].fsr1[0, 0]), 1000)
        # Default exception behavior remains compatible with old callers.
        with self.assertRaises(ValueError):
            self.m.parse_multi_packet(self.m.make_packet(frames, 11), states)

    def test_queued_packet_is_a_snapshot_and_zero_delta_keeps_values(self):
        states = [self.m.ProtocolState() for _ in range(4)]
        first = self.m.parse_multi_packet(self.full_packet(10), states)
        deltas = [self.m.make_esk_delta(11, 10, [(0, 0, 0, 3000 + i)])
                  for i in range(4)]
        self.m.parse_multi_packet(self.m.make_packet(deltas, 11), states)
        self.assertEqual(int(first.states[0].fsr1[0, 0]), 0)
        self.assertEqual(first.states[0].last_sequence, 10)
        zeros = [self.m.make_esk_delta(12, 11, []) for _ in range(4)]
        last = self.m.parse_multi_packet(self.m.make_packet(zeros, 12), states)
        self.assertEqual(int(last.states[0].fsr1[0, 0]), 3000)
        self.assertEqual(last.algorithms, ("DELTA",) * 4)

    def test_initial_delta_needs_its_own_module_base_then_resync_recovers(self):
        states = [self.m.ProtocolState() for _ in range(4)]
        missing_base = self.m.make_esk_delta(11, 10, [(0, 0, 0, 3000)])
        full = self.m.make_full_frame(11, 100)
        packet = self.m.parse_multi_packet(
            self.m.make_packet([missing_base, full, full, full], 11),
            states, allow_partial=True)
        self.assertEqual(packet.algorithms, (None, "FULL", "FULL", "FULL"))
        self.assertEqual(sum(bool(error) for error in packet.errors), 1)
        self.assertFalse(states[0].delta_valid)
        self.assertEqual([s.last_sequence for s in states], [None, 11, 11, 11])
        sync = self.m.make_full_frame(12, 200, flags=0x33)
        zero = self.m.make_esk_delta(12, 11, [])
        recovered = self.m.parse_multi_packet(
            self.m.make_packet([sync, zero, zero, zero], 12),
            states, allow_partial=True)
        self.assertFalse(any(recovered.errors))
        self.assertEqual(recovered.algorithms,
                         ("DELTA_SYNC", "DELTA", "DELTA", "DELTA"))
        self.assertTrue(states[0].delta_valid)

    def test_framer_chunk_boundaries_offsets_and_reset(self):
        packet = self.full_packet()
        invalid = bytearray(20)
        invalid[:6] = b"MUL1\x02\x04"
        struct.pack_into("<H", invalid, 8, 9)
        prefix = b"boot\r\n" + bytes(invalid)
        stream = prefix + packet + b"MUL1\x02"
        framer = self.m.PacketFramer()
        result = []
        # Marker, length field and body are repeatedly split across reads.
        for cursor in range(0, len(stream), 7):
            result.extend(framer.feed(stream[cursor:cursor + 7]))
        self.assertEqual(result, [(len(prefix), packet)])
        framer.reset()
        self.assertEqual(framer.feed(packet), [(0, packet)])

    def test_worker_records_every_received_byte_and_finishes_real_window(self):
        stop = threading.Event()
        commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
        first = self.full_packet(10)
        frames = [self.m.make_full_frame(11, 200 + i) for i in range(4)]
        frames[1] = corrupt_inner(frames[1])
        second = self.m.make_packet(frames, 11)
        tail = b"MUL1\x02\x04\x0f"
        raw = b"boot noise\r\n" + first + second + tail
        chunks = [raw[:2], raw[2:19], raw[19:83], raw[83:4000], raw[4000:]]
        clock = FakeClock()
        port = FakePort(chunks, stop, clock)
        serial_module = types.SimpleNamespace(
            Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
        with tempfile.TemporaryDirectory(prefix="eskin-gui-integration-") as folder:
            config = self.m.RecordingConfig(output_dir=Path(folder),
                                           duration_seconds=0.75,
                                           settle_seconds=0.05,
                                           metadata={"test": "synthetic serial",
                                                     "target_modules": [0, 1, 2, 3],
                                                     "target_mode": "FULL"})
            commands.put({"action": "START_RECORDING", "config": config})
            gui = self.m.FsrGui(packets, commands, events, stop, "FAKE")
            recorded_events = []
            try:
                gui._open_settings()
                self.assertTrue(gui.display_paused)
                with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                        mock.patch.object(self.m.time, "monotonic", clock.monotonic):
                    self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                         commands, events, stop)
                self.assertTrue(gui.display_paused)
                while not events.empty():
                    recorded_events.append(events.get_nowait())
            finally:
                if gui.experiment.is_open:
                    gui.experiment.close_settings()
                self.m.plt.close(gui.fig)
            serial_module.Serial.assert_called_once()
            self.assertEqual(bytes(port.received), raw)
            runs = list(Path(folder).glob("*/summary.json"))
            self.assertEqual(len(runs), 1)
            run_dir = runs[0].parent
            self.assertEqual((run_dir / "mul1_raw.bin").read_bytes(), raw)
            with (run_dir / "packet_log.csv").open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual([int(row["raw_offset"]) for row in rows],
                             [len(b"boot noise\r\n"), len(b"boot noise\r\n") + len(first)])
            summary = json.loads(runs[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["schema_version"], 2)
            self.assertIn("full_run", summary["scopes"])
            self.assertIn("main", summary["scopes"])
            self.assertGreaterEqual(summary["duration_seconds"], 0.75)
            self.assertLess(summary["duration_seconds"], 0.80)
            self.assertAlmostEqual(summary["scopes"]["main"]["actual_duration_seconds"],
                                   summary["duration_seconds"] - 0.05)
            self.assertEqual(summary["scopes"]["main"]["counts"]["inner_crc_error"], 1)
            while not events.empty():
                recorded_events.append(events.get_nowait())
            self.assertTrue(any(e.phase == "complete" for e in recorded_events))

    def test_worker_rejects_stale_or_changed_automatic_snapshot_before_opening_run(self):
        for modules, mode, delayed_reads in (([0], "FULL", 0),
                                             ([0, 1, 2, 3], "DELTA", 0),
                                             ([0, 1, 2, 3], "FULL", 21)):
            with self.subTest(modules=modules, mode=mode, delay=delayed_reads):
                stop, clock = threading.Event(), FakeClock()
                commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
                warmup = ([self.full_packet(1)] + [b""] * 20 + [self.full_packet(2)]
                          + [b""] * 20 + [self.full_packet(3)])
                with tempfile.TemporaryDirectory(prefix="eskin-detection-reject-") as folder:
                    config = self.m.RecordingConfig(output_dir=Path(folder), duration_seconds=.5,
                        settle_seconds=0, metadata={"module_selection_source": "automatic",
                            "target_modules": modules, "target_mode": mode})
                    def arm(port):
                        if port.read_count == len(warmup) + delayed_reads:
                            commands.put({"action": "START_RECORDING", "config": config})
                    port = FakePort(warmup, stop, clock, arm)
                    serial_module = types.SimpleNamespace(
                        Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
                    with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                            mock.patch.object(self.m.time, "monotonic", clock.monotonic):
                        self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                             commands, events, stop)
                    self.assertEqual(list(Path(folder).iterdir()), [])
                    self.assertEqual(port.written, [])
                    statuses = []
                    while not events.empty():
                        statuses.append(events.get_nowait())
                    self.assertTrue(any(event.phase == "unavailable" for event in statuses))

    def test_worker_freezes_automatic_module_set_despite_later_dropout(self):
        stop, clock = threading.Event(), FakeClock()
        commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
        warmup = ([self.full_packet(1)] + [b""] * 20 + [self.full_packet(2)]
                  + [b""] * 20 + [self.full_packet(3)])
        dropout = self.selected_packet((0, 3), sequence=4)
        with tempfile.TemporaryDirectory(prefix="eskin-detection-freeze-") as folder:
            config = self.m.RecordingConfig(output_dir=Path(folder), duration_seconds=.5,
                settle_seconds=0, metadata={"module_selection_source": "automatic",
                    "target_modules": [0, 1, 2, 3], "target_mode": "FULL", "N": 4, "M": 4})
            def arm(port):
                if port.read_count == len(warmup):
                    commands.put({"action": "START_RECORDING", "config": config})
            port = FakePort(warmup + [dropout], stop, clock, arm)
            serial_module = types.SimpleNamespace(
                Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
            with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                    mock.patch.object(self.m.time, "monotonic", clock.monotonic):
                self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                     commands, events, stop)
            paths = list(Path(folder).glob("*/summary.json"))
            self.assertEqual(len(paths), 1)
            summary = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["metadata"]["target_modules"], [0, 1, 2, 3])
            self.assertEqual(summary["metadata"]["N"], 4)
            self.assertEqual((paths[0].parent / "mul1_raw.bin").read_bytes(), dropout)
            self.assertEqual(port.written, [])

    def run_start_boundary_scenario(self, delta=False, genuine_gap=False):
        stop, clock = threading.Event(), FakeClock()
        commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
        warmup = ([self.full_packet(1)] + [b""] * 20 + [self.full_packet(2)]
                  + [b""] * 20 + [self.full_packet(3)])
        next_sequence = 6 if genuine_gap else 5
        if delta:
            crossing = self.m.make_packet([
                self.m.make_esk_delta(4, 3, [(0, 0, 0, 1000 + module)])
                for module in range(4)], 4)
            following = self.m.make_packet([
                self.m.make_esk_delta(next_sequence, 4, [(0, 0, 0, 2000 + module)])
                for module in range(4)], next_sequence)
        else:
            crossing, following = self.full_packet(4), self.full_packet(next_sequence)
        prefix_size = 11  # An incomplete MUL1 header already consumed before Record.
        new_raw = crossing[prefix_size:] + following
        with tempfile.TemporaryDirectory(prefix="eskin-start-boundary-") as folder:
            config = self.m.RecordingConfig(output_dir=Path(folder), duration_seconds=.2,
                settle_seconds=.05, metadata={"module_selection_source": "automatic",
                    "target_modules": [0, 1, 2, 3], "target_mode": "FULL", "N": 4, "M": 4})
            def arm(port):
                if port.read_count == len(warmup) + 1:
                    commands.put({"action": "START_RECORDING", "config": config})
            port = FakePort(warmup + [crossing[:prefix_size], new_raw], stop, clock, arm)
            serial_module = types.SimpleNamespace(
                Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
            with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                    mock.patch.object(self.m.time, "monotonic", clock.monotonic):
                self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                     commands, events, stop)
            paths = list(Path(folder).glob("*/summary.json"))
            self.assertEqual(len(paths), 1)
            summary = json.loads(paths[0].read_text(encoding="utf-8"))
            raw = (paths[0].parent / "mul1_raw.bin").read_bytes()
            with (paths[0].parent / "packet_log.csv").open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            live = []
            while not packets.empty():
                item = packets.get_nowait()
                if isinstance(item, self.m.MultiModulePacket):
                    live.append(item)
            self.assertEqual(raw, new_raw, "Never copy the pre-Record prefix into this run")
            self.assertEqual(len(rows), 1, "Cross-start packet is not a complete packet in this file")
            self.assertEqual(int(rows[0]["packet_sequence"]), next_sequence)
            offset, size = int(rows[0]["raw_offset"]), int(rows[0]["received_bytes"])
            self.assertEqual(offset, len(crossing) - prefix_size)
            self.assertEqual(raw[offset:offset + size], following,
                             "CSV offset must address the actual recorded byte stream")
            self.assertEqual(summary["capture_start_boundary_packets"], 1)
            self.assertEqual(summary["scopes"]["full_run"]["known_start_boundary_bytes"],
                             len(crossing) - prefix_size)
            event_rows = [json.loads(line) for line in
                          (paths[0].parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            boundary_events = [event for event in event_rows if event["event"] == "capture_start_boundary"]
            self.assertEqual(len(boundary_events), 1)
            self.assertEqual(boundary_events[0]["raw_offset"], -prefix_size)
            self.assertEqual(boundary_events[0]["packet_sequence"], 4)
            self.assertEqual(boundary_events[0]["suffix_bytes_in_recording"], len(crossing) - prefix_size)
            return summary, live

    def test_start_preserves_previously_received_partial_header_without_false_gap(self):
        summary, live = self.run_start_boundary_scenario()
        self.assertEqual(summary["session_counters"]["delta"]["sequence_gap_events"], 0)
        self.assertEqual(summary["session_counters"]["delta"]["lost_frames"], 0)
        self.assertEqual([packet.sequence for packet in live], [1, 2, 3, 4, 5])

    def test_start_preserves_delta_cache_across_split_packet(self):
        summary, live = self.run_start_boundary_scenario(delta=True)
        self.assertEqual(summary["session_counters"]["delta"]["delta_base_mismatches"], 0)
        self.assertEqual(summary["session_counters"]["delta"]["sequence_gap_events"], 0)
        self.assertEqual([state.last_sequence for state in live[-1].states], [5] * 4)
        self.assertEqual([int(state.fsr1[0, 0]) for state in live[-1].states],
                         [2000, 2001, 2002, 2003])

    def test_start_boundary_does_not_hide_a_real_following_sequence_gap(self):
        summary, _ = self.run_start_boundary_scenario(genuine_gap=True)
        self.assertEqual(summary["session_counters"]["delta"]["sequence_gap_events"], 1)
        self.assertEqual(summary["session_counters"]["delta"]["lost_frames"], 1)

    def test_three_repeats_preserve_split_headers_and_delta_cache_at_every_boundary(self):
        for mode in ("FULL", "DELTA"):
            with self.subTest(mode=mode):
                stop, clock = threading.Event(), FakeClock(step_seconds=.125)
                commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
                def packet(sequence):
                    frames = []
                    for module in range(4):
                        if mode == "DELTA" and sequence > 3:
                            frame = self.m.make_esk_delta(sequence, sequence - 1,
                                                        [(0, 0, 0, 2000 + sequence + module)])
                        else:
                            frame = self.m.make_full_frame(sequence, 100 * module,
                                                          flags=0x33 if mode == "DELTA" else 0x13)
                        frames.append(frame)
                    return self.m.make_packet(frames, sequence)
                data = {sequence: packet(sequence) for sequence in range(1, 17)}
                warmup = [data[1], b"", b"", b"", data[2], b"", b"", b"", data[3]]
                split = 11
                repeat_chunks = [
                    [data[4][split:] + data[5], data[6], data[7], data[8][:split]],
                    [data[8][split:] + data[9], data[10], data[11], data[12][:split]],
                    [data[12][split:] + data[13], data[14], data[15], data[16]],
                ]
                with tempfile.TemporaryDirectory(prefix="eskin-repeat-boundaries-") as folder:
                    config = self.m.RecordingConfig(output_dir=Path(folder), duration_seconds=.5,
                        settle_seconds=.125, metadata={"module_selection_source": "automatic",
                            "target_modules": [0, 1, 2, 3], "target_mode": mode, "N": 4, "M": 4})
                    def arm(port):
                        if port.read_count == len(warmup) + 1:
                            commands.put({"action": "START_RECORDING", "config": config, "repeats": 3})
                    chunks = warmup + [data[4][:split]] + [chunk for group in repeat_chunks for chunk in group]
                    port = FakePort(chunks, stop, clock, arm)
                    serial_module = types.SimpleNamespace(
                        Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
                    with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                            mock.patch.object(self.m.time, "monotonic", clock.monotonic):
                        self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                             commands, events, stop)
                    paths = sorted(Path(folder).glob("*/summary.json"))
                    self.assertEqual(len(paths), 3)
                    for index, path in enumerate(paths):
                        summary = json.loads(path.read_text(encoding="utf-8"))
                        counts = summary["session_counters"]["delta"]
                        self.assertEqual(counts["sequence_gap_events"], 0, f"{mode} repeat {index + 1}")
                        self.assertEqual(counts["lost_frames"], 0, f"{mode} repeat {index + 1}")
                        self.assertEqual(counts["delta_base_mismatches"], 0, f"{mode} repeat {index + 1}")
                        self.assertEqual(summary["capture_start_boundary_packets"], 1)
                        crossing_sequence = (4, 8, 12)[index]
                        self.assertEqual(summary["scopes"]["full_run"]["known_start_boundary_bytes"],
                                         len(data[crossing_sequence]) - split)
                        raw = (path.parent / "mul1_raw.bin").read_bytes()
                        self.assertEqual(raw, b"".join(repeat_chunks[index]))
                        with (path.parent / "packet_log.csv").open(encoding="utf-8", newline="") as f:
                            rows = list(csv.DictReader(f))
                        expected_sequences = ([5, 6, 7], [9, 10, 11], [13, 14, 15, 16])[index]
                        self.assertEqual([int(row["packet_sequence"]) for row in rows], expected_sequences)
                        for row in rows:
                            offset, size = int(row["raw_offset"]), int(row["received_bytes"])
                            self.assertGreaterEqual(offset, 0)
                            self.assertEqual(raw[offset:offset + size], data[int(row["packet_sequence"])])
                    live = []
                    while not packets.empty():
                        item = packets.get_nowait()
                        if isinstance(item, self.m.MultiModulePacket):
                            live.append(item)
                    self.assertEqual([item.sequence for item in live], list(range(1, 17)))
                    self.assertEqual([state.last_sequence for state in live[-1].states], [16] * 4)
                    if mode == "DELTA":
                        self.assertEqual([int(state.fsr1[0, 0]) for state in live[-1].states],
                                         [2016, 2017, 2018, 2019])

    def run_batch_scenario(self, scenario="normal", settings_open=False, mode="FULL"):
        """Exercise the real worker/recorder with deterministic, advancing time."""
        stop, clock = threading.Event(), FakeClock()
        commands, packets, events = queue.Queue(), queue.Queue(), queue.Queue()
        def batch_packet(sequence):
            return self.selected_packet((0, 1, 2, 3), mode, sequence)
        warmup = ([batch_packet(1)] + [b""] * 20 + [batch_packet(2)]
                  + [b""] * 20 + [batch_packet(3)])
        if scenario == "check_then_no_response":
            frames = [self.m.make_full_frame(4, i * 100) for i in range(4)]
            frames[0] = corrupt_inner(frames[0])
            capture = [self.m.make_packet(frames, 4)]
        else:
            capture = [batch_packet(sequence) for sequence in range(4, 84)]
        with tempfile.TemporaryDirectory(prefix="eskin-three-repeat-") as folder:
            config = self.m.RecordingConfig(output_dir=Path(folder), duration_seconds=.3,
                settle_seconds=.05, metadata={"module_selection_source": "automatic",
                    "target_modules": [0, 1, 2, 3], "target_mode": mode, "N": 4, "M": 4,
                    "condition": "zero_load", "block": "B7", "repeat": "99",
                    "notes": "same untouched physical setup", "deployment_confirmed": True})
            start_command = {"action": "START_RECORDING", "config": config, "repeats": 3}
            def on_read(port):
                if port.read_count == len(warmup):
                    commands.put(start_command)
                if scenario == "normal" and port.read_count == len(warmup) + 1:
                    # A second queued click must not create another three runs.
                    commands.put(start_command)
                if scenario == "disconnect_second" and port.read_count == len(warmup) + 17:
                    raise FakeSerialException("synthetic disconnect during repeat two")
            port = FakePort(warmup + capture, stop, clock, on_read)
            serial_module = types.SimpleNamespace(
                Serial=mock.Mock(return_value=port), SerialException=FakeSerialException)
            original_finish = self.m.ExperimentRecorder.finish
            original_raw = self.m.ExperimentRecorder.record_raw
            original_start = self.m.ExperimentRecorder.start
            finish_calls = []
            def finish_recording(recorder, counters, reason):
                result = original_finish(recorder, counters, reason)
                finish_calls.append(str(reason))
                if scenario == "stop_between" and len(finish_calls) == 1:
                    # Queue at the exact completion boundary, before the worker
                    # decides whether to start the next capture.
                    commands.put("STOP_RECORDING")
                if scenario == "finish_failure_first" and len(finish_calls) == 1:
                    raise OSError("synthetic final summary close failure")
                return result
            def start_recording(recorder, counters, *args, **kwargs):
                if scenario == "start_failure_second" and str(recorder.metadata.get("repeat")) == "2":
                    raise OSError("synthetic new run creation failure")
                return original_start(recorder, counters, *args, **kwargs)
            def record_raw(recorder, chunk, elapsed_s=None):
                if scenario == "write_failure_second" and str(recorder.metadata.get("repeat")) == "2":
                    raise OSError("synthetic write failure during repeat two")
                return original_raw(recorder, chunk, elapsed_s=elapsed_s)
            gui = None
            if settings_open:
                gui = self.m.FsrGui(packets, commands, events, stop, "FAKE")
                gui._open_settings()
                self.assertTrue(gui.display_paused)
            try:
                with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                        mock.patch.object(self.m.time, "monotonic", clock.monotonic), \
                        mock.patch.object(self.m.ExperimentRecorder, "start", start_recording), \
                        mock.patch.object(self.m.ExperimentRecorder, "finish", finish_recording), \
                        mock.patch.object(self.m.ExperimentRecorder, "record_raw", record_raw):
                    self.m.serial_worker("FAKE_SERIAL_ONLY", 115200, packets,
                                         commands, events, stop)
                if gui:
                    self.assertTrue(gui.display_paused, "A batch must not resume Settings drawing")
                statuses = []
                while not events.empty():
                    statuses.append(events.get_nowait())
                summaries = []
                for path in sorted(Path(folder).glob("*/summary.json")):
                    summary = json.loads(path.read_text(encoding="utf-8"))
                    summary["_test_raw"] = (path.parent / "mul1_raw.bin").read_bytes()
                    summary["_test_folder"] = path.parent.name
                    summaries.append(summary)
                self.assertEqual(port.written, [], "Record must not modify the live mode or rate")
                return summaries, statuses
            finally:
                if gui:
                    if gui.experiment.is_open:
                        gui.experiment.close_settings()
                    self.m.plt.close(gui.fig)

    def test_delta_plots_launch_once_only_after_three_closed_recordings(self):
        observed = []
        def launch(paths):
            closed = list(paths[0].parent.glob("*/summary.json"))
            self.assertEqual(len(closed), 3, "No plotting between repeats")
            for path in paths:
                for name in ("mul1_raw.bin", "packet_log.csv", "module_log.csv", "events.jsonl", "summary.json", "experiment_log.md"):
                    self.assertTrue((path / name).is_file(), name)
                observed.append(json.loads((path / "summary.json").read_text(encoding="utf-8"))["metadata"]["repeat"])
        self.plot_launcher.side_effect = launch
        summaries, statuses = self.run_batch_scenario(mode="DELTA", settings_open=True)
        self.assertEqual(len(summaries), 3)
        self.plot_launcher.assert_called_once()
        self.assertEqual(observed, ["1", "2", "3"])
        self.assertIn("Plots queued", [s for s in statuses if s.phase == "complete"][-1].message)

    def test_delta_stop_or_failure_still_plots_previously_saved_repeats(self):
        for scenario, count in (("stop_between", 1), ("disconnect_second", 2), ("start_failure_second", 1)):
            with self.subTest(scenario=scenario):
                self.plot_launcher.reset_mock()
                summaries, _ = self.run_batch_scenario(scenario, mode="DELTA")
                self.assertEqual(len(summaries), count)
                self.plot_launcher.assert_called_once()
                self.assertEqual(len(self.plot_launcher.call_args.args[0]), count)

    def test_plot_launch_failure_preserves_saved_batch_and_completion(self):
        self.plot_launcher.side_effect = OSError("synthetic plot spawn failure")
        summaries, statuses = self.run_batch_scenario(mode="DELTA")
        self.assertEqual(len(summaries), 3)
        self.assertTrue(all(row["completed_requested_duration"] for row in summaries))
        self.assertEqual(sum(s.phase == "complete" for s in statuses), 1)
        self.assertIn("automatic plots could not start", [s for s in statuses if s.phase == "complete"][-1].message)

    def test_full_batch_does_not_launch_delta_auto_plots(self):
        self.run_batch_scenario()
        self.plot_launcher.assert_not_called()

    def test_three_repeat_batch_saves_separate_windows_while_settings_remains_open(self):
        summaries, statuses = self.run_batch_scenario(settings_open=True)
        self.assertEqual(len(summaries), 3, "A queued double-click must still produce only three runs")
        self.assertEqual(len({row["_test_folder"] for row in summaries}), 3)
        self.assertEqual(len({row["metadata"]["batch_id"] for row in summaries}), 1)
        self.assertTrue(summaries[0]["metadata"]["batch_id"])
        for index, summary in enumerate(summaries, 1):
            metadata = summary["metadata"]
            self.assertEqual(metadata["repeat"], str(index))
            self.assertEqual(metadata["batch_repeat_index"], index)
            self.assertEqual(metadata["batch_repeat_count"], 3)
            self.assertEqual(metadata["batch_recording_method"],
                             "consecutive_capture_windows_same_setup")
            self.assertEqual(metadata["target_modules"], [0, 1, 2, 3])
            self.assertEqual(metadata["target_mode"], "FULL")
            self.assertEqual(metadata["condition"], "zero_load")
            self.assertEqual(metadata["block"], "B7")
            self.assertEqual(metadata["notes"], "same untouched physical setup")
            self.assertEqual(summary["requested_duration_seconds"], .3)
            self.assertEqual(summary["settle_seconds"], .05)
            self.assertAlmostEqual(summary["scopes"]["main"]["actual_duration_seconds"],
                                   summary["duration_seconds"] - .05)
            self.assertTrue(summary["_test_raw"])
        self.assertEqual(sum(status.phase == "between" for status in statuses), 2)
        self.assertEqual(sum(status.phase == "complete" for status in statuses), 1)

    def test_three_repeat_batch_keeps_check_results_and_later_no_response_runs(self):
        summaries, _ = self.run_batch_scenario("check_then_no_response")
        self.assertEqual(len(summaries), 3)
        self.assertEqual(summaries[0]["scopes"]["full_run"]["counts"]["inner_crc_error"], 1)
        for index, summary in enumerate(summaries, 1):
            self.assertEqual(summary["metadata"]["repeat"], str(index))
            self.assertEqual(summary["metadata"]["target_modules"], [0, 1, 2, 3])
            self.assertEqual(summary["scopes"]["main"]["status"], "CHECK REQUIRED")
        self.assertEqual(summaries[1]["_test_raw"], b"")
        self.assertEqual(summaries[2]["_test_raw"], b"")

    def test_stop_queued_at_repeat_boundary_cancels_remaining_runs(self):
        summaries, _ = self.run_batch_scenario("stop_between")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["metadata"]["repeat"], "1")
        self.assertTrue(summaries[0]["completed_requested_duration"])

    def test_disconnect_saves_current_repeat_and_cancels_remaining_runs(self):
        summaries, _ = self.run_batch_scenario("disconnect_second")
        self.assertEqual(len(summaries), 2)
        self.assertEqual([row["metadata"]["repeat"] for row in summaries], ["1", "2"])
        self.assertFalse(summaries[1]["completed_requested_duration"])
        self.assertIn("disconnect", summaries[1]["reason"].lower())

    def test_write_failure_saves_current_repeat_and_cancels_remaining_runs(self):
        summaries, _ = self.run_batch_scenario("write_failure_second")
        self.assertEqual(len(summaries), 2)
        self.assertEqual([row["metadata"]["repeat"] for row in summaries], ["1", "2"])
        self.assertFalse(summaries[1]["completed_requested_duration"])
        self.assertTrue("error" in summaries[1]["reason"].lower())

    def test_start_failure_cancels_remaining_repeats(self):
        summaries, statuses = self.run_batch_scenario("start_failure_second")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["metadata"]["repeat"], "1")
        self.assertTrue(any(status.phase == "unavailable" for status in statuses))

    def test_finish_failure_does_not_schedule_another_repeat(self):
        summaries, statuses = self.run_batch_scenario("finish_failure_first")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["metadata"]["repeat"], "1")
        self.assertTrue(any(status.phase == "unavailable" for status in statuses))

    def test_agg_gui_constructs_updates_and_can_start_recording(self):
        packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
        gui = self.m.FsrGui(packets, commands, events, threading.Event(), "FAKE")
        try:
            self.assertEqual(len(gui.collections), 8)
            packets.put(self.observed_packet(mode="DELTA"))
            with mock.patch.object(self.m.time, "monotonic", return_value=1.0):
                gui.update(0)
                gui.fig.canvas.draw()
                gui._start_recording(None)
                gui._start_recording(None)
            queued = []
            while not commands.empty():
                queued.append(commands.get_nowait())
            self.assertEqual(len(queued), 1, "Record must not resend mode or rate")
            command = queued[-1]
            self.assertEqual(command["action"], "START_RECORDING")
            self.assertEqual(command["repeats"], 3)
            self.assertIsInstance(command["config"], self.m.RecordingConfig)
            metadata = command["config"].metadata
            self.assertEqual(metadata["target_modules"], [0, 3])
            self.assertEqual(metadata["target_mode"], "DELTA")
            self.assertEqual(metadata["N"], 2)
            gui.experiment.metadata["target_modules"] = [1]
            self.assertEqual(metadata["target_modules"], [0, 3], "Run config must be frozen")
        finally:
            self.m.plt.close(gui.fig)

    def test_record_rejects_missing_stale_or_disconnected_detection(self):
        packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
        gui = self.m.FsrGui(packets, commands, events, threading.Event(), "FAKE")
        try:
            with mock.patch.object(self.m.time, "monotonic", return_value=1.0):
                gui._start_recording()
            self.assertTrue(commands.empty())
            self.assertFalse(gui.recording_active)
            packets.put(self.observed_packet())
            with mock.patch.object(self.m.time, "monotonic", return_value=2.0):
                gui._start_recording()
            self.assertTrue(commands.empty())
            self.assertFalse(gui.recording_active)
            packets.put(self.observed_packet())
            packets.put(self.m.SerialError("synthetic disconnected serial port"))
            with mock.patch.object(self.m.time, "monotonic", return_value=1.0):
                gui._start_recording()
            self.assertTrue(commands.empty())
            self.assertFalse(gui.recording_active)
        finally:
            self.m.plt.close(gui.fig)

    def test_between_repeat_gui_remains_active_and_blocks_mode_rate_changes(self):
        packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
        gui = self.m.FsrGui(packets, commands, events, threading.Event(), "FAKE")
        try:
            gui.fig.canvas.draw()
            gui._handle_recording_status(self.m.RecordingStatus(
                "Repeat 1/3 | Recording", phase="recording", elapsed_seconds=.1,
                remaining_seconds=.2))
            self.assertTrue(gui.recording_active)
            self.assertIn("1/3", gui.record_button.label.get_text())
            gui._handle_recording_status(self.m.RecordingStatus(
                "Repeat 1/3 | Saved; next repeat", phase="between", elapsed_seconds=.3,
                remaining_seconds=0))
            self.assertTrue(gui.recording_active)
            gui._start_recording()
            gui._send_command("MODE DELTA")
            gui._send_command("SCAN_HZ 500")
            gui.rate_box.set_val("500")
            gui._apply_scan_rate()
            self.assertEqual(gui.target_scan_hz, 200)
            self.assertTrue(commands.empty())
            gui._send_command("RESYNC DELTA")
            self.assertEqual(commands.get_nowait(), "RESYNC DELTA")
            gui._handle_recording_status(self.m.RecordingStatus(
                "Repeat 2/3 | Recording", phase="recording", elapsed_seconds=.1))
            self.assertTrue(gui.recording_active)
            self.assertIn("2/3", gui.record_button.label.get_text())
            gui._handle_recording_status(self.m.RecordingStatus(
                "Repeat 3/3 | Saved", phase="complete", elapsed_seconds=.3))
            self.assertFalse(gui.recording_active)
            self.assertEqual(gui.record_button.label.get_text(), "Record x3")
        finally:
            self.m.plt.close(gui.fig)

    def test_schedule_preserves_expected_modules_when_detection_is_partial(self):
        packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
        gui = self.m.FsrGui(packets, commands, events, threading.Event(), "FAKE")
        try:
            gui.experiment.metadata.update(module_selection_source="schedule",
                                           target_modules=[0, 1, 2, 3],
                                           target_mode="FULL", planned_id="plan-four-modules")
            packets.put(self.observed_packet(modules=(0, 3)))
            with mock.patch.object(self.m.time, "monotonic", return_value=1.0):
                gui._start_recording()
            command = commands.get_nowait()
            self.assertEqual(command["action"], "START_RECORDING")
            self.assertTrue(commands.empty())
            self.assertEqual(command["config"].metadata["target_modules"], [0, 1, 2, 3])
            self.assertEqual(command["config"].metadata["N"], 4)
        finally:
            self.m.plt.close(gui.fig)

    def test_settings_pauses_only_drawing_and_close_displays_latest_packet(self):
        packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
        stop = threading.Event()
        gui = self.m.FsrGui(packets, commands, events, stop, "FAKE")
        try:
            packets.put(self.observed_packet())
            gui.update(0)
            gui.fig.canvas.draw()
            timer = mock.Mock()
            gui.animation.event_source = timer
            with mock.patch.object(gui.collections[0], "set_array",
                                   wraps=gui.collections[0].set_array) as draw:
                gui._open_settings()
                self.assertTrue(gui.display_paused)
                timer.stop.assert_called()
                packets.put(self.m.parse_multi_packet(self.full_packet(13)))
                packets.put(self.m.parse_multi_packet(self.full_packet(14)))
                gui.update(1)
                draw.assert_not_called()
                self.assertFalse(stop.is_set(), "Settings must not stop the serial worker")
                self.assertTrue(commands.empty(), "Settings must not send serial commands")
                gui.experiment.close_settings()
                self.assertFalse(gui.display_paused)
                timer.start.assert_called()
                draw.assert_called()
                self.assertEqual(gui.last_packet.sequence, 14)
        finally:
            if gui.experiment.is_open:
                gui.experiment.close_settings()
            self.m.plt.close(gui.fig)

    def test_settings_save_updates_human_conditions_and_detaches_old_plan(self):
        for source in ("automatic", "schedule"):
            with self.subTest(source=source):
                packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
                gui = self.m.FsrGui(packets, commands, events, threading.Event(), "FAKE")
                try:
                    if source == "schedule":
                        gui.experiment.metadata.update(module_selection_source="schedule",
                            target_modules=[0, 1, 2, 3], planned_id="old-plan", pair_id="old-pair",
                            group="old-group", schedule_row=9, schedule_path="old-plan.csv")
                    gui.fig.canvas.draw()
                    timer = mock.Mock()
                    gui.animation.event_source = timer
                    gui._open_settings()
                    controls = gui.experiment
                    self.assertTrue(gui.display_paused)
                    self.assertEqual(set(controls.boxes), {"notes"})
                    self.assertFalse({"modules", "mode", "rate", "repeat"}.intersection(controls.radios))
                    for key, value in (("condition", "rolling"),
                                       ("block", "2"), ("duration", "310")):
                        index = next(i for i, item in enumerate(controls._radio_values[key].values())
                                     if str(item) == value)
                        controls.radios[key].set_active(index)
                    controls._save()
                    self.assertFalse(controls.is_open)
                    self.assertFalse(gui.display_paused)
                    timer.start.assert_called()
                    self.assertEqual(controls.metadata["condition"], "rolling")
                    self.assertEqual(controls.metadata["block"], "2")
                    self.assertEqual(controls.duration_seconds, 310.0)
                    self.assertEqual(controls.metadata["module_selection_source"], "automatic")
                    self.assertFalse(any(controls.metadata.get(key) for key in
                                         ("planned_id", "pair_id", "group", "schedule_path", "schedule_row")))
                    self.assertTrue(commands.empty(), "Settings Save must not send device commands")
                finally:
                    if gui.experiment.is_open:
                        gui.experiment.close_settings()
                    self.m.plt.close(gui.fig)


def render_gui(path):
    m = load_gui()
    packets, commands, events = queue.Queue(), queue.Queue(), queue.Queue()
    gui = m.FsrGui(packets, commands, events, threading.Event(), "HEADLESS QA")
    try:
        frames = [m.make_full_frame(10, 700 * module) for module in range(4)]
        packet = m.parse_multi_packet(m.make_packet(frames, 10))
        packet.usb_rate, packet.round_rate = 850_000, 200.0
        detector = m.ModuleDetector()
        now = m.time.monotonic()
        for timestamp in (now - 1, now - .5, now):
            packet.detection = detector.observe(packet, timestamp)
        packet.received_monotonic = now
        packets.put(packet)
        gui.update(0)
        path.parent.mkdir(parents=True, exist_ok=True)
        gui.fig.savefig(path, dpi=140)
        gui._open_settings()
        settings_path = path.with_name(path.stem + "-settings" + path.suffix)
        gui.experiment.figure.savefig(settings_path, dpi=140)
        print(f"Agg settings render: {settings_path}")
    finally:
        if gui.experiment.is_open:
            gui.experiment.close_settings()
        m.plt.close(gui.fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path)
    args, remaining = parser.parse_known_args()
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2)
    if program.result.wasSuccessful() and args.render:
        render_gui(args.render)
        print(f"Agg GUI render: {args.render}")
    raise SystemExit(0 if program.result.wasSuccessful() else 1)
