"""Endpoint and wire-parser checks; synthetic data only, never opens hardware."""
from __future__ import annotations

import importlib.util
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import queue
import types
import unittest
from unittest.mock import patch
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "endpoint_calibration", ROOT / "script/Main/Calibration/calibrate_fsr.py"
)
cal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cal)


def frames(value: int, count: int = 200) -> list[np.ndarray]:
    return [np.full((16, 16), value, dtype=np.uint16) for _ in range(count)]


class SharedEndpointTests(unittest.TestCase):
    def write_sweep(self, folder, loads=(0, 0, 1600, 3200, 3200)):
        points = []
        for i, load in enumerate(loads):
            value = (100, 120, 600, 1100, 1300)[i]
            raw = frames(value)
            points.append({"pressure": load, "raw_frames": [f.tolist() for f in raw],
                           "raw_adc": np.median(np.stack(raw), axis=0).tolist()})
        data = {"format": "e-skin-fsr-pressure-response-sweep", "version": 3,
                "protocol_id": cal.SHARED_PROTOCOL_ID, "module_id": 3, "fsr": "FSR2",
                "load_range_g": [0, max(loads)], "pressure": {"unit": "g"}, "points": points}
        path = Path(folder) / "sweep.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_shared_sweep_aggregates_same_endpoints_and_dynamic_upper(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_sweep(folder)
            result = cal.build_from_sweep(path, 2)
        self.assertEqual(result["load_range_g"], [0, 3200])
        self.assertEqual(result["version"], 3)
        self.assertEqual(result["zero_load"]["median"][0][0], 110)
        self.assertEqual(result["full_load"]["median"][0][0], 1200)
        self.assertEqual(result["full_load"]["frame_count"], 400)
        self.assertEqual(len(result["full_load"]["source_captures"]), 2)
        self.assertEqual(result["calibration"]["interval_low_zero"], result["zero_load"]["median"])
        self.assertTrue(result["source"]["shared_with_fit"])

    def test_refuses_missing_raw_mismatched_aggregate_and_nonmaximum_final(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_sweep(folder)
            original = json.loads(path.read_text())
            for kind in ("missing_raw", "bad_median", "last_not_max", "legacy"):
                data = json.loads(json.dumps(original))
                if kind == "missing_raw":
                    del data["points"][0]["raw_frames"]
                elif kind == "bad_median":
                    data["points"][0]["raw_adc"][0][0] += 1
                elif kind == "last_not_max":
                    data["points"][-1]["pressure"] = 2000
                else:
                    data["protocol_id"] = "whole_layer_0_5000_v2"
                path.write_text(json.dumps(data))
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    cal.build_from_sweep(path)

    def test_gamma_and_adc_validation_use_the_active_sweep_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_sweep(folder)
            for gamma in (0, -1, np.inf, np.nan):
                with self.subTest(gamma=gamma), self.assertRaises(ValueError):
                    cal.build_from_sweep(path, gamma)
            data = json.loads(path.read_text())
            data["points"][1]["raw_frames"][0][0][0] = 4096
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                cal.build_from_sweep(path)

    def test_active_cli_and_nonoverwriting_save(self):
        with patch.object(sys, "argv", ["calibrate_fsr.py", "--sweep", "source.json"]):
            args = cal.parse_args()
        self.assertEqual(args.output_root, ROOT)
        self.assertEqual(args.gamma, 4)
        self.assertEqual(args.sweep, Path("source.json"))
        with tempfile.TemporaryDirectory() as folder:
            source = self.write_sweep(folder)
            result = cal.build_from_sweep(source)
            first = cal.save_calibration(result, Path(folder))
            original = first.read_bytes()
            second = cal.save_calibration(result, Path(folder))
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)
            saved = json.loads(original)
            self.assertEqual(saved["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(len(saved["zero_load"]["raw_frames"]), 400)

    def test_qc_reports_noise_saturation_and_invalid_response(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.write_sweep(folder)
            data = json.loads(source.read_text())
            # Apply the same altered cell patterns to both repeated upper captures.
            for point in data["points"][-2:]:
                raw = np.asarray(point["raw_frames"])
                raw[:, 0, 0] = 110  # equals the shared zero endpoint
                raw[:100, 0, 1], raw[100:, 0, 1] = 1000, 1050  # threshold inclusive
                raw[:100, 0, 2], raw[100:, 0, 2] = 1000, 1052
                raw[-1, 0, 3] = 4095  # isolated saturation is retained
                point["raw_frames"] = raw.tolist()
                point["raw_adc"] = np.median(raw, axis=0).tolist()
            source.write_text(json.dumps(data))
            result = cal.build_from_sweep(source)
        flags = {(p["row"], p["column"]): p["flags"] for p in result["problem_cells"]}
        self.assertIn("NO_RESPONSE_OR_REVERSED", flags[(1, 1)])
        self.assertNotIn((1, 2), flags)
        self.assertIn("FULL_UNSTABLE", flags[(1, 3)])
        self.assertIn("SATURATED", flags[(1, 4)])
        self.assertFalse(result["calibration"]["valid_response_mask"][0][0])


MEASUREMENT_SPEC = importlib.util.spec_from_file_location(
    "calibration_measurement", ROOT / "script/Main/calibration_measurement.py")
measurement = importlib.util.module_from_spec(MEASUREMENT_SPEC)
MEASUREMENT_SPEC.loader.exec_module(measurement)


class DummyText:
    def __init__(self, text=""):
        self.text = text
    def set_text(self, value):
        self.text = value
    def set_color(self, value):
        pass


class MeasurementHarness(measurement.CalibrationMeasurementMixin):
    def __init__(self, folder, endpoint, fit):
        self.folder, self.endpoint, self.fit = Path(folder), endpoint, fit
        self.module_id, self.mode, self.calibration_gamma = 3, "FSR2", 2
        self.measurement_frames = queue.Queue()
        self.load_capture_busy = self.view_distribution_busy = self.view_distribution_collecting = False
        self.latest = None
        self.stats = types.SimpleNamespace(parse_errors=0)
        self.figure = types.SimpleNamespace(canvas=types.SimpleNamespace(draw_idle=lambda: None))
        self.view_distribution_load_box = DummyText("1600")
        self.view_distribution_status = DummyText()
        self.view_distribution_button = types.SimpleNamespace(label=DummyText())
        self.load_value_text, self.load_status = DummyText(), DummyText()
        self.jobs = []
    def _load_calibration(self, layer):
        return self.endpoint
    def _load_pressure_model(self, layer):
        return self.fit
    def _calibration_directory(self):
        return self.folder
    def _clear_measurement_frames(self):
        while not self.measurement_frames.empty():
            self.measurement_frames.get_nowait()
    def _clear_view_distribution_input(self):
        pass
    def _run_view_distribution_analysis(self, jobs, layers, actual):
        self.jobs = jobs


class MeasurementTests(unittest.TestCase):
    def model_files(self, folder):
        path = SharedEndpointTests().write_sweep(folder)
        endpoint = cal.build_from_sweep(path, 2)
        ep_path = Path(folder) / "endpoints.json"
        ep_path.write_text(json.dumps(endpoint), encoding="utf-8")
        fit = {"version": 3, "protocol_id": cal.SHARED_PROTOCOL_ID,
               "source_module_id": 3, "source_fsr": "FSR2", "load_range_g": [0, 3200],
               "source_sha256": endpoint["source_sha256"], "fit": {"cells": []}}
        for r in range(16):
            for c in range(16):
                fit["fit"]["cells"].append({"row": r+1, "column": c+1,
                    "pressure_from_adc": {"x": [110, 1200], "y": [0, 3200]}})
        fit_path = Path(folder) / "fit.json"
        fit_path.write_text(json.dumps(fit), encoding="utf-8")
        return ep_path, fit_path

    def frame(self, sequence, value=655, module_id=3, family="FULL"):
        return types.SimpleNamespace(module_id=module_id, module_status=0, cache_valid=True,
                                     marker="ESKF", family=family, flags=0,
                                     sequence=sequence, fsr1=np.full((16,16), value),
                                     fsr2=np.full((16,16), value))

    def test_frozen_models_full_capture_and_median_not_mean(self):
        with tempfile.TemporaryDirectory() as folder:
            endpoint, fit = self.model_files(folder)
            original = fit.read_bytes()
            gui = MeasurementHarness(folder, endpoint, fit)
            gui._capture_view_distributions(None)
            self.assertTrue(gui.view_distribution_collecting)
            fit.write_text("changed after capture began")
            gui.measurement_frames.put(self.frame(1, module_id=1))
            gui.measurement_frames.put(self.frame(1, family="DELTA"))
            for i in range(200):
                gui.measurement_frames.put(self.frame(i+1, value=2000 if i==199 else 655))
            gui.measurement_frames.put(self.frame(200))
            gui._consume_measurement_frames()
            capture = json.loads(gui.last_validation_capture_path.read_text())
            frozen = Path(capture["source_models"]["fitted_response"])
            self.assertEqual(frozen.read_bytes(), original)
            self.assertEqual(capture["load_range_g"], [0, 3200])
            self.assertEqual(capture["source_frames"]["count"], 200)
            self.assertEqual(len(capture["raw_frames"]), 200)
            self.assertEqual(capture["views"]["RAW"]["values"][0][0], 655)
            self.assertEqual(capture["version"], 4)
            self.assertEqual(capture["prediction_units"], "g")
            self.assertEqual(set(capture["views"]), {"RAW", "LINEAR", "GAMMA", "FIT_PRESS"})
            self.assertEqual(capture["views"]["LINEAR"]["values"][0][0], 1600)
            self.assertEqual(capture["views"]["GAMMA"]["values"][0][0], 800)
            self.assertTrue(all(capture["views"][name]["unit"] == "g" for name in ("LINEAR", "GAMMA", "FIT_PRESS")))
            self.assertNotIn("linear_unclipped_ratio", capture["clipping"])
            self.assertEqual(capture["views"]["FIT_PRESS"]["values"][0][0], 1600)
            self.assertEqual(capture["source_models"]["fitted_response_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(capture["calibration_snapshot"]["source_path"],
                             capture["source_models"]["two_point"])

    def test_upper_range_and_timeout_partial_are_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            endpoint, fit = self.model_files(folder)
            gui = MeasurementHarness(folder, endpoint, fit)
            gui.view_distribution_load_box.text = "3201"
            gui._capture_view_distributions(None)
            self.assertFalse(gui.view_distribution_collecting)
            gui.view_distribution_load_box.text = "100"
            gui._capture_view_distributions(None)
            gui.measurement_frames.put(self.frame(1))
            gui.view_distribution_started_at = time.monotonic() - 21
            gui._consume_measurement_frames()
            capture = json.loads(gui.last_validation_capture_path.read_text())
            self.assertEqual(capture["status"], "INCOMPLETE")
            self.assertEqual(capture["source_frames"]["count"], 1)
            self.assertEqual(gui.jobs, [])
            self.assertFalse(gui.view_distribution_busy)

    def test_model_shared_source_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            endpoint, fit = self.model_files(folder)
            model = json.loads(fit.read_text())
            model["source_sha256"] = "wrong"
            fit.write_text(json.dumps(model))
            gui = MeasurementHarness(folder, endpoint, fit)
            gui._capture_view_distributions(None)
            self.assertFalse(gui.view_distribution_collecting)
            self.assertIn("same sweep SHA", gui.view_distribution_status.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
