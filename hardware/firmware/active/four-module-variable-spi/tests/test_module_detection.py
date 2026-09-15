"""Independent rolling module detection checks; no serial or GUI required."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_detector():
    spec = importlib.util.spec_from_file_location(
        "module_detection_test_target", ROOT / "pc/module_detection.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ModuleDetector


def packet(modules=(0, 3), modes=None, statuses=None, errors=None, mask=None):
    modes = modes or {module: "FULL" for module in modules}
    return types.SimpleNamespace(
        updated_mask=sum(1 << module for module in modules) if mask is None else mask,
        statuses=tuple(statuses if statuses is not None else
                       [0 if module in modules else 0x83 for module in range(4)]),
        algorithms=tuple(modes.get(module) for module in range(4)),
        errors=tuple(errors if errors is not None else [None] * 4),
    )


class ModuleDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector_type = load_detector()

    def setUp(self):
        self.detector = self.detector_type()

    def observe_ready(self, modules=(0, 3)):
        for now in (0.0, 0.5, 1.0):
            snapshot = self.detector.observe(packet(modules), now)
        return snapshot

    def test_requires_three_packets_and_one_second_span(self):
        self.assertFalse(self.detector.snapshot(0.0)["ready"])
        self.assertFalse(self.detector.observe(packet(), 0.0)["ready"])
        self.assertFalse(self.detector.observe(packet(), 1.0)["ready"])
        snapshot = self.detector.observe(packet(), 1.1)
        self.assertTrue(snapshot["ready"])
        self.assertEqual(snapshot["packet_count"], 3)
        self.assertGreaterEqual(snapshot["window_span_seconds"], 1.0)
        short = self.detector_type()
        for now in (0.0, 0.1, 0.2):
            snapshot = short.observe(packet(), now)
        self.assertFalse(snapshot["ready"])

    def test_freshness_expires_after_half_second(self):
        self.assertTrue(self.observe_ready()["ready"])
        self.assertTrue(self.detector.snapshot(1.5)["ready"])
        stale = self.detector.snapshot(1.5001)
        self.assertFalse(stale["ready"])
        self.assertEqual(stale["last_packet_monotonic"], 1.0)
        self.assertEqual(stale["observed_at_monotonic"], 1.5001)

    def test_one_partial_packet_does_not_shrink_recent_success_union(self):
        self.detector.observe(packet((0, 3)), 0.0)
        self.detector.observe(packet((0, 3)), 0.5)
        snapshot = self.detector.observe(packet((0,)), 1.0)
        self.assertTrue(snapshot["ready"])
        self.assertEqual(snapshot["modules"], [0, 3])
        self.assertEqual(snapshot["mode"], "FULL")

    def test_success_requires_status_mask_algorithm_and_no_inner_error(self):
        observation = packet(
            (0, 1, 2, 3),
            statuses=[0, 0, 0, 0x87],
            errors=[None, "inner CRC failure", None, None],
            mask=0b1011,
        )
        for now in (0.0, 0.5, 1.0):
            snapshot = self.detector.observe(observation, now)
        self.assertEqual(snapshot["modules"], [0])
        empty_algorithm = packet((0,), modes={0: None})
        for now in (2.0, 2.5, 3.0):
            snapshot = self.detector.observe(empty_algorithm, now)
        self.assertEqual(snapshot["modules"], [])
        self.assertFalse(snapshot["ready"])

    def test_old_success_leaves_union_after_rolling_window(self):
        self.detector.observe(packet((0, 3)), 0.0)
        self.detector.observe(packet((3,)), 0.5)
        before = self.detector.observe(packet((3,)), 1.0)
        self.assertEqual(before["modules"], [0, 3])
        after = self.detector.observe(packet((3,)), 1.6)
        self.assertTrue(after["ready"])
        self.assertEqual(after["modules"], [3])

    def test_delta_sync_normalizes_and_latest_mode_is_per_slot(self):
        self.detector.observe(packet(), 0.0)
        modes = {0: "DELTA_SYNC", 3: "DELTA"}
        self.detector.observe(packet(modes=modes), 0.5)
        delta = self.detector.observe(packet(modes=modes), 1.0)
        self.assertEqual(delta["mode"], "DELTA")
        mixed = self.detector.observe(packet((0,), modes={0: "FULL"}), 1.1)
        self.assertEqual(mixed["modules"], [0, 3])
        self.assertIsNone(mixed["mode"])
        full = self.detector.observe(packet((3,), modes={3: "FULL"}), 1.2)
        self.assertEqual(full["mode"], "FULL")

    def test_snapshot_metadata_cannot_mutate_detector_state(self):
        snapshot = self.observe_ready()
        snapshot["modules"].append(2)
        self.assertEqual(self.detector.snapshot(1.0)["modules"], [0, 3])
        self.assertTrue(snapshot["source"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
