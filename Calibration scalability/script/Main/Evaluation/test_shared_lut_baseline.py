"""Independent frozen-model and per-cell prediction tests for Shared LUT."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from shared_lut_baseline import PROTOCOL_ID, build_shared_lut, predict_shared_lut


class SharedLutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "frozen_fit.json"
        self.model = {
            "format": "e-skin-fsr-pressure-response-monotonic-model", "version": 3,
            "protocol_id": PROTOCOL_ID, "load_range_g": [0, 4000],
            "source_module_id": 1, "source_fsr": "FSR1",
            "source_file": str(self.root / "absent_training_sweep.json"),
            "source_sha256": "f" * 64,
            "fit": {"mean_cell": {"pressure_from_adc": {
                "type": "linear_lut", "x": [0, 1000, 2000], "y": [0, 1000, 4000]}}},
        }
        self.record = {"module_id": 1, "fsr": "FSR1", "load_range_g": [0, 4000],
                       "provenance": {"fit": str(self.path)}}
        self.write_model()

    def write_model(self):
        content = json.dumps(self.model).encode("utf-8")
        self.path.write_bytes(content)
        self.record["provenance"]["fit_sha256"] = hashlib.sha256(content).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_frozen_model_metadata_and_sources_are_preserved(self):
        before = self.path.read_bytes()
        baseline = build_shared_lut(self.record)
        self.assertEqual(baseline["method"], "GLOBAL_LUT")
        self.assertEqual(baseline["label"], "Shared LUT")
        self.assertEqual(baseline["lut"], {"x": [0., 1000., 2000.], "y": [0., 1000., 4000.]})
        self.assertEqual(baseline["source_model"]["sha256"], self.record["provenance"]["fit_sha256"])
        self.assertEqual(baseline["training_sweep"]["sha256"], "f" * 64)
        self.assertFalse(baseline["validation_used_for_construction"])
        self.assertFalse(baseline["model_rebuilt"])
        self.assertFalse(Path(self.model["source_file"]).exists())
        self.assertEqual(self.path.read_bytes(), before)
        json.dumps(baseline, allow_nan=False)

    def test_actual_validation_load_and_predictions_do_not_construct_baseline(self):
        baseline = build_shared_lut(self.record)
        changed = copy.deepcopy(self.record)
        changed.update(actual_load_g=1e9, raw="never inspect this", estimates_g="never inspect this")
        self.assertEqual(build_shared_lut(changed), baseline)

    def test_model_sha_is_required_and_checked(self):
        for bad in (None, "", "a" * 63, "q" * 64, "0" * 64):
            with self.subTest(bad=bad):
                record = copy.deepcopy(self.record)
                record["provenance"]["fit_sha256"] = bad
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    build_shared_lut(record)
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            build_shared_lut(self.record)

    def test_protocol_identity_range_and_version_must_match(self):
        original = copy.deepcopy(self.model)
        for changes in ({"version": 2}, {"protocol_id": "legacy"}, {"load_range_g": [0, 4500]},
                        {"source_module_id": 3}, {"source_fsr": "FSR2"}, {"format": "other"}):
            with self.subTest(changes=changes):
                self.model = {**copy.deepcopy(original), **changes}
                self.write_model()
                with self.assertRaises(ValueError):
                    build_shared_lut(self.record)

    def test_lut_finiteness_size_monotonicity_and_output_range(self):
        for x, y in (([0], [0]), ([0, 1], [0]), ([0, 0], [0, 1]),
                     ([1, 0], [0, 1]), ([0, 1], [2, 1]), ([0, np.nan], [0, 1]),
                     ([0, 1], [0, np.inf]), ([0, 1], [-1, 1]), ([0, 1], [0, 4001])):
            with self.subTest(x=x, y=y):
                self.model["fit"]["mean_cell"]["pressure_from_adc"] = {"type": "linear_lut", "x": x, "y": y}
                self.write_model()
                with self.assertRaises(ValueError):
                    build_shared_lut(self.record)

    def test_mean_training_lut_is_used_instead_of_cell_models(self):
        self.model["fit"]["cells"] = [{"pressure_from_adc": {"x": [0, 2000], "y": [0, 2000]}}] * 256
        self.write_model()
        baseline = build_shared_lut(self.record)
        predicted = predict_shared_lut(np.full((16, 16), 1000.), baseline)
        np.testing.assert_array_equal(predicted, np.full((16, 16), 1000.))
        predicted = predict_shared_lut(np.full((16, 16), 1500.), baseline)
        np.testing.assert_array_equal(predicted, np.full((16, 16), 2500.))

    def test_prediction_precedes_spatial_averaging_for_nonlinear_lut(self):
        baseline = build_shared_lut(self.record)
        raw = np.zeros((16, 16))
        raw[8:] = 2000.
        predicted = predict_shared_lut(raw, baseline)
        self.assertEqual(predicted.mean(), 2000.)
        prediction_of_raw_mean = predict_shared_lut(np.full((16, 16), raw.mean()), baseline)[0, 0]
        self.assertEqual(prediction_of_raw_mean, 1000.)
        self.assertNotEqual(predicted.mean(), prediction_of_raw_mean)
        np.testing.assert_array_equal(raw[:8], np.zeros((8, 16)))

    def test_nan_and_endpoint_clamping_keep_plateau_offsets(self):
        self.model["fit"]["mean_cell"]["pressure_from_adc"] = {
            "type": "linear_lut", "x": [100, 1000, 2000], "y": [50, 1000, 3900]}
        self.write_model()
        baseline = build_shared_lut(self.record)
        raw = np.full((16, 16), 1000.)
        raw[0, :5] = [np.nan, np.inf, -np.inf, -5, 4095]
        predicted = predict_shared_lut(raw, baseline)
        self.assertTrue(np.all(np.isnan(predicted[0, :3])))
        self.assertEqual(predicted[0, 3], 50.)
        self.assertEqual(predicted[0, 4], 3900.)
        self.assertEqual(predicted[1, 1], 1000.)

    def test_raw_must_have_one_layer_matrix_shape(self):
        baseline = build_shared_lut(self.record)
        for raw in (np.zeros(256), np.zeros((2, 16, 16)), np.zeros((15, 16))):
            with self.assertRaisesRegex(ValueError, "16x16"):
                predict_shared_lut(raw, baseline)


if __name__ == "__main__":
    unittest.main()
