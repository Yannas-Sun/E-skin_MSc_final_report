"""Offline Agg GUI checks using synthetic frames; no serial or hardware writes."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MAIN = Path(__file__).resolve().parents[1] / "script" / "Main"
sys.path.insert(0, str(MAIN))
spec = importlib.util.spec_from_file_location("shared_gui_test_base", MAIN / "data_scalability_monitor.py")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)
import calibration_shared_endpoints as controller


def frame(sequence, *, value=10, module=1, family="FULL", flags=0, raw=None):
    array = np.full((16, 16), value, dtype=np.uint16) if raw is None else np.asarray(raw)
    return base.DecodedFrame(marker="ESKF" if family == "FULL" else "ESKD",
                             family=family, sequence=sequence, base_sequence=None,
                             fsr1=array, fsr2=array.copy(), acc=(),
                             module_id=module, flags=flags)


class SharedGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calibration_queue = queue.Queue()
        self.measurement_queue = queue.Queue()
        gui_type = controller.make_calibration_gui(base.SquareScalabilityGui)
        self.gui = gui_type(queue.Queue(), base.MonitorStats(), threading.Event(),
                            "OFFLINE", 2000000, "fsr1", 50, 1, "pyocd", None, None,
                            self.calibration_queue, self.measurement_queue)
        self.gui._calibration_directory = lambda: self.root
        self.gui.latest = frame(100)
        self.gui.latest_by_module[1] = self.gui.latest
        # Synthetic checks drive handlers explicitly, rather than a GUI timer.
        self.gui.animation.event_source.stop()
        self.gui.animation._draw_was_started = True
        self.gui.figure.canvas.draw_idle = lambda: None

    def tearDown(self):
        plt.close(self.gui.figure)
        self.temp.cleanup()

    def start(self):
        self.gui.calibration_button._observers.process("clicked", None)
        self.assertEqual(self.gui.calibration_phase, "pressure_capture")

    def record(self, load, value, start_sequence=200):
        self.gui._record_pressure_point(str(load))
        self.assertIsNotNone(self.gui.fit_pending)
        for sequence in range(start_sequence, start_sequence + 200):
            self.calibration_queue.put(frame(sequence, value=value))
        self.gui._consume_normalized_frames()
        self.assertIsNone(self.gui.fit_pending)
        self.gui.latest = frame(start_sequence + 199, value=value)
        self.gui.latest_by_module[1] = self.gui.latest

    def test_button_starts_sweep_and_first_load_must_be_zero(self):
        self.start()
        self.gui._record_pressure_point("75")
        self.assertIsNone(self.gui.fit_pending)
        self.assertIn("first", self.gui.calibration_status.get_text().lower())
        self.gui._record_pressure_point("0")
        self.assertEqual(self.gui.fit_pending["load"], 0)
        self.assertEqual(self.gui.calibration_pressure_points, [])

    def test_fresh_full_only_unique_selected_module_and_integer_adc(self):
        self.start()
        self.calibration_queue.put(frame(90))  # queued before Record: discarded
        self.gui._record_pressure_point("0")
        self.assertTrue(self.calibration_queue.empty())
        for item in (frame(100), frame(99), frame(101, family="DELTA"),
                     frame(102, module=3), frame(103), frame(103),
                     frame(104, flags=0x20), frame(105, raw=np.zeros((15, 16))),
                     frame(106, raw=np.full((16, 16), 10.25))):
            self.calibration_queue.put(item)
        self.gui._consume_normalized_frames()
        self.assertEqual(self.gui.fit_pending["sequences"], [103])
        self.assertEqual(len(self.gui.fit_pending["frames"]), 1)

    def test_sequence_wrap_is_forward_and_duplicate_rejected(self):
        self.gui.latest = frame(0xfffffffe)
        self.gui.latest_by_module[1] = self.gui.latest
        self.start()
        self.gui._record_pressure_point("0")
        for sequence in (0xffffffff, 0, 0, 1):
            self.calibration_queue.put(frame(sequence))
        self.gui._consume_normalized_frames()
        self.assertEqual(self.gui.fit_pending["sequences"], [0xffffffff, 0, 1])

    def test_dynamic_shared_endpoints_saved_from_same_sweep(self):
        self.start()
        for load, value, seq in ((0, 10, 200), (1600, 500, 400), (4000, 1010, 600)):
            self.record(load, value, seq)
        with patch.object(controller.threading, "Thread") as worker:
            self.gui.calibration_button._observers.process("clicked", None)
        self.assertEqual(self.gui.calibration_phase, "idle")
        worker.return_value.start.assert_called_once()
        sweep_path = next((self.root / "DATA/module_1/FSR1/fit/raw").glob("*.json"))
        sweep = json.loads(sweep_path.read_text())
        endpoint_path = next((self.root / "DATA/module_1/FSR1/two_point").glob("*.json"))
        endpoint = json.loads(endpoint_path.read_text())
        self.assertEqual(sweep["load_range_g"], [0, 4000])
        self.assertEqual(endpoint["load_range_g"], [0, 4000])
        self.assertEqual(endpoint["source_file"], str(sweep_path.resolve()))
        self.assertEqual(endpoint["zero_load"]["median"], sweep["points"][0]["raw_adc"])
        self.assertEqual(endpoint["full_load"]["median"], sweep["points"][-1]["raw_adc"])
        self.assertEqual(self.gui.calibration_data["FSR1"]["upper_load_g"], 4000)
        np.testing.assert_allclose(self.gui.calibration_data["FSR1"]["span"], 1000)

    def test_second_upper_4500_and_last_point_must_equal_max(self):
        self.start()
        for load, value, seq in ((0, 10, 200), (4500, 1010, 400), (1800, 500, 600)):
            self.record(load, value, seq)
        self.gui._finish_calibration()
        self.assertEqual(self.gui.calibration_phase, "pressure_capture")
        self.assertIn("last", self.gui.calibration_status.get_text().lower())
        self.assertFalse((self.root / "DATA/module_1/FSR1/fit/raw").exists())
        self.record(4500, 1010, 800)
        with patch.object(controller.threading, "Thread"):
            self.gui._finish_calibration()
        path = next((self.root / "DATA/module_1/FSR1/fit/raw").glob("*.json"))
        self.assertEqual(json.loads(path.read_text())["load_range_g"], [0, 4500])

    def test_previous_measurement_module_does_not_block_next_sweep(self):
        self.gui._measurement_module_id = 3  # a previously completed validation
        self.start()
        self.gui._record_pressure_point("0")
        self.calibration_queue.put(frame(101))
        self.gui._consume_normalized_frames()
        self.assertEqual(self.gui.fit_pending["sequences"], [101])

    def test_incomplete_point_not_saved_after_timeout(self):
        self.start()
        self.gui._record_pressure_point("0")
        self.calibration_queue.put(frame(101))
        self.gui.capture_deadline = 0
        self.gui._consume_normalized_frames()
        self.assertIsNone(self.gui.fit_pending)
        self.assertEqual(self.gui.calibration_pressure_points, [])
        self.assertIn("Timed out", self.gui.calibration_status.get_text())

    def test_display_snapshot_is_not_saved_as_training_raw(self):
        self.gui.display_mode = "LINEAR"
        self.gui.calibration_data["FSR1"] = {"low": np.zeros((16, 16)),
            "high": np.full((16, 16), 100), "span": np.full((16, 16), 100), "upper_load_g": 4200}
        self.gui._save_current_frame(None)
        snapshots = list((self.root / "DATA/module_1/snapshots").glob("*/snapshot.json"))
        self.assertEqual(len(snapshots), 1)
        data = json.loads(snapshots[0].read_text())
        self.assertEqual(data["display_unit"], "g")
        self.assertEqual(data["views"]["FSR1"]["raw_adc"][0][0], 10)
        self.assertEqual(data["views"]["FSR1"]["display_values"][0][0], 420)
        self.assertFalse((self.root / "DATA/module_1/FSR1/fit/raw").exists())

    def test_gamma_button_and_snapshot_use_grams(self):
        self.gui.calibration_data["FSR1"] = {"low": np.zeros((16, 16)),
            "high": np.full((16, 16), 100), "span": np.full((16, 16), 100), "upper_load_g": 4200}
        self.gui.calibration_gamma = 2
        with patch.object(self.gui, "_load_calibration"):
            self.gui.normalized_button._observers.process("clicked", None)
        self.assertEqual(self.gui.display_mode, "GAMMA")
        np.testing.assert_allclose(self.gui._display_fsr("FSR1", np.full((16, 16), 10)), 42)
        self.assertEqual(self.gui.fsr_artists["fsr1"].get_clim(), (0, 4200))
        self.gui._save_current_frame(None)
        data = json.loads(next((self.root / "DATA/module_1/snapshots").glob("*/snapshot.json")).read_text())
        self.assertEqual(data["display_mode"], "GAMMA")
        self.assertEqual(data["display_unit"], "g")
        self.assertAlmostEqual(data["views"]["FSR1"]["display_values"][0][0], 42)

    def test_gamma_button_and_snapshot_use_grams(self):
        self.gui.calibration_data["FSR1"] = {"low": np.zeros((16, 16)),
            "high": np.full((16, 16), 100), "span": np.full((16, 16), 100), "upper_load_g": 4200}
        self.gui.calibration_gamma = 2
        with patch.object(self.gui, "_load_calibration"):
            self.gui.normalized_button._observers.process("clicked", None)
        self.assertEqual(self.gui.display_mode, "GAMMA")
        np.testing.assert_allclose(self.gui._display_fsr("FSR1", np.full((16, 16), 10)), 42)
        self.assertEqual(self.gui.fsr_artists["fsr1"].get_clim(), (0, 4200))
        self.gui._save_current_frame(None)
        data = json.loads(next((self.root / "DATA/module_1/snapshots").glob("*/snapshot.json")).read_text())
        self.assertEqual(data["display_mode"], "GAMMA")
        self.assertEqual(data["display_unit"], "g")
        self.assertAlmostEqual(data["views"]["FSR1"]["display_values"][0][0], 42)

    def test_display_snapshot_is_not_saved_as_training_raw(self):
        self.gui.display_mode = "LINEAR"
        self.gui.calibration_data["FSR1"] = {"low": np.zeros((16, 16)),
            "high": np.full((16, 16), 100), "span": np.full((16, 16), 100), "upper_load_g": 4200}
        self.gui._save_current_frame(None)
        snapshots = list((self.root / "DATA/module_1/snapshots").glob("*/snapshot.json"))
        self.assertEqual(len(snapshots), 1)
        data = json.loads(snapshots[0].read_text())
        self.assertEqual(data["display_unit"], "g")
        self.assertEqual(data["views"]["FSR1"]["raw_adc"][0][0], 10)
        self.assertEqual(data["views"]["FSR1"]["display_values"][0][0], 420)
        self.assertFalse((self.root / "DATA/module_1/FSR1/fit/raw").exists())


class GuiAnalysisDispatchTests(unittest.TestCase):
    def setUp(self):
        gui_type = controller.make_calibration_gui(base.SquareScalabilityGui)
        self.gui = gui_type.__new__(gui_type)
        self.gui.view_distribution_results = queue.Queue()

    def test_validation_dispatches_only_single_capture_distributions(self):
        result = controller.subprocess.CompletedProcess([], 0, stdout="Generated combined: test/view_distributions.png", stderr="")
        path = Path("test/view_distribution/run/view_distribution_capture.json")
        with patch.object(controller.subprocess, "run", return_value=result) as worker:
            self.gui._run_view_distribution_analysis([(path, path.parent)], ("FSR1",), 1500)
        command = worker.call_args.args[0]
        worker.assert_called_once()
        self.assertEqual(Path(command[2]).name, "analyze_view_distributions.py")
        self.assertEqual(command[3:], ["--input", str(path), "--output-dir", str(path.parent)])
        message, color = self.gui.view_distribution_results.get_nowait()
        self.assertIn("Capture + distributions saved", message)
        self.assertIn("error/dispersion manual", message)
        self.assertEqual(color, "#86efac")

    def test_analysis_failure_does_not_report_success_or_remove_capture(self):
        result = controller.subprocess.CompletedProcess([], 2, stdout="", stderr="single-capture plot unavailable")
        path = Path("test/view_distribution/run/view_distribution_capture.json")
        with patch.object(controller.subprocess, "run", return_value=result):
            self.gui._run_view_distribution_analysis([(path, path.parent)], ("FSR1",), 1500)
        message, color = self.gui.view_distribution_results.get_nowait()
        self.assertIn("Capture saved; distribution plotting failed", message)
        self.assertNotIn("Capture + distributions saved", message)
        self.assertEqual(color, "#fca5a5")


def render(path):
    case = SharedGuiTests()
    case.setUp()
    try:
        case.gui.figure.canvas.draw()
        case.gui.figure.savefig(path, dpi=140)
    finally:
        case.tearDown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", type=Path)
    args, rest = parser.parse_known_args()
    if args.render:
        render(args.render)
    unittest.main(argv=[sys.argv[0], *rest])
