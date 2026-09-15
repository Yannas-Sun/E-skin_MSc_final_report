"""Shared-LUT accuracy integration using a real, frozen model JSON fixture."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from new_protocol_evaluation import METHODS, PROTOCOL_ID, analyze_batch
from shared_lut_baseline import build_shared_lut
from test_new_protocol_evaluation import capture, grams_capture, matrix


class SharedLutAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fit = self.root / "fit.json"
        self.fit.write_text(json.dumps({
            "format": "e-skin-fsr-pressure-response-monotonic-model",
            "version": 3, "protocol_id": PROTOCOL_ID, "load_range_g": [0, 4000],
            "source_module_id": 1, "source_fsr": "FSR1",
            "source_file": "frozen_training_sweep.json", "source_sha256": "a" * 64,
            "fit": {"mean_cell": {"pressure_from_adc": {
                "type": "linear_lut", "x": [10, 110, 310], "y": [0, 1000, 4000]}}},
        }), encoding="utf-8")
        self.data = grams_capture(capture(self.root))
        self.data["source_models"]["fitted_response_sha256"] = hashlib.sha256(self.fit.read_bytes()).hexdigest()
        self.data["actual_load"]["value"] = 2000
        self.data["views"]["RAW"]["values"] = np.tile([10, 310] * 8, (16, 1)).tolist()
        # Nonfinite RAW already excluded by the original three-method mask;
        # its Shared LUT NaN must not exclude any additional finite cell.
        self.data["views"]["RAW"]["values"][0][0] = None
        self.paths = [self.save(self.data, "load2000")]
        zero = copy.deepcopy(self.data)
        zero["actual_load"]["value"] = 0
        zero["views"]["RAW"]["values"] = matrix(10)
        self.paths.append(self.save(zero, "load0"))

    def tearDown(self):
        self.temp.cleanup()

    def save(self, data, name):
        path = self.root / name / "view_distribution_capture.json"
        path.parent.mkdir()
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_four_curves_from_frozen_lut_preserve_original_three_and_cell_mask(self):
        original_bytes = {path: path.read_bytes() for path in [*self.paths, self.fit]}
        with patch("matplotlib.figure.Figure.savefig"):
            old = analyze_batch(self.root, self.root / "old", capture_paths=self.paths)
        seen = {}
        def inspect(figure, path, **_kwargs):
            if Path(path).suffix == ".png":
                seen[Path(path).name] = {line.get_label(): line.get_marker() for line in figure.axes[0].lines}
        with patch("shared_lut_baseline.build_shared_lut", wraps=build_shared_lut) as build, \
             patch("matplotlib.figure.Figure.savefig", new=inspect):
            new = analyze_batch(self.root, self.root / "new", capture_paths=self.paths, include_shared_lut=True)
        build.assert_called_once()
        self.assertEqual(len(seen), 3)
        for plotted in seen.values():
            self.assertTrue(set(METHODS).issubset(plotted))
            self.assertEqual(plotted["Shared LUT"], "D")
        before = json.loads(old["summary"].read_text())
        after = json.loads(new["summary"].read_text())
        self.assertEqual(after["methods"], [*METHODS, "GLOBAL_LUT"])
        for left, right in zip(before["groups"], after["groups"]):
            for method in METHODS:
                self.assertEqual(left["methods"][method], right["methods"][method])
        for left, right in zip(before["records"], after["records"]):
            self.assertEqual(left["common_cell_mask"], right["common_cell_mask"])
            self.assertEqual(left["common_cell_count"], 255)
            for method in METHODS:
                self.assertEqual(left["methods"][method], right["methods"][method])
        for method in METHODS:
            self.assertEqual(before["metrics_by_method"][method], after["metrics_by_method"][method])
        lut_model = json.loads(new["shared_lut_model"].read_text())
        self.assertEqual(lut_model["lut"], {"x": [10, 110, 310], "y": [0, 1000, 4000]})
        self.assertFalse(lut_model["validation_used_for_construction"])
        self.assertFalse(after["shared_lut_baseline"]["validation_refit"])
        self.assertEqual(lut_model["source_model"]["sha256"], self.data["source_models"]["fitted_response_sha256"])
        with new["cells"].open(newline="", encoding="utf-8") as handle:
            cells = list(csv.DictReader(handle))
        current = [row for row in cells if row["actual_load_g"] == "2000.0"]
        self.assertEqual(current[0]["global_lut_g"], "")
        self.assertEqual(current[1]["global_lut_g"], "4000.0")
        self.assertEqual(current[2]["global_lut_g"], "0.0")
        actual_mean = after["groups"][1]["methods"]["GLOBAL_LUT"]["mean"]["mean"]
        self.assertAlmostEqual(actual_mean, 128 * 4000 / 255)
        inverted_mean_raw = np.interp((127 * 10 + 128 * 310) / 255, [10, 110, 310], [0, 1000, 4000])
        self.assertNotAlmostEqual(actual_mean, inverted_mean_raw)
        with new["csv"].open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["error_rate_percent"] == "" for row in rows if row["actual_load_g"] == "0.0"))
        self.assertEqual(original_bytes, {path: path.read_bytes() for path in original_bytes})

    def test_nonfinite_shared_prediction_on_original_mask_aborts_before_outputs(self):
        invalid = np.zeros((16, 16))
        invalid[0, 1] = np.nan
        output = self.root / "rejected"
        with patch("shared_lut_baseline.predict_shared_lut", return_value=invalid), \
             self.assertRaisesRegex(ValueError, "original fixed common mask"):
            analyze_batch(self.root, output, capture_paths=self.paths, include_shared_lut=True)
        self.assertFalse(output.exists())

    def test_dispersion_ignores_accuracy_baseline_flag_and_remains_three_methods(self):
        with patch("shared_lut_baseline.build_shared_lut") as build, patch("matplotlib.figure.Figure.savefig"):
            outputs = analyze_batch(self.root, self.root / "dispersion", kind="dispersion",
                                    capture_paths=self.paths, include_shared_lut=True)
        build.assert_not_called()
        result = json.loads(outputs["summary"].read_text())
        self.assertEqual(result["methods"], list(METHODS))
        self.assertIsNone(result["shared_lut_baseline"])
        self.assertNotIn("shared_lut_model", outputs)
        self.assertNotIn("global_lut_g", outputs["cells"].read_text().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
