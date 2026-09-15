"""Offline tests of protocol boundaries and the plotted estimation functions."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[1] / "script" / "Main" / "Model"
sys.path.insert(0, str(MODEL_DIR))
import plot_pressure_calibration_monotonic as fitting
import plot_calibration_comparison as comparison


def synthetic_inputs(directory: Path, *, upper_plateau: bool = False) -> tuple[Path, Path]:
    """Clearly synthetic values exercise a low-load plateau and cell variation."""
    loads = np.asarray([0., 100., 500., 1500., 3000., 4500.])
    zero = 100 + np.arange(256).reshape(16, 16) / 10
    span = 2400 + np.arange(256).reshape(16, 16)
    raw = zero[None, :, :] + span[None, :, :] * np.sqrt(loads[:, None, None] / 4500)
    raw[1] = raw[0]  # The PAVA plateau must not be erased by plotting.
    if upper_plateau:
        raw[-2] = raw[-1] + 100  # PAVA upper knot differs from the measured U endpoint.
    source = {"format": "e-skin-fsr-pressure-response-sweep", "version": 3,
              "protocol_id": fitting.NEW_PROTOCOL, "load_range_g": [0, 4500],
              "pressure": {"unit": "g"}, "module_id": 1, "fsr": "FSR1"}
    source["points"] = ([{"pressure": 0., "raw_adc": (raw[0] + shift).tolist()} for shift in (-2, 2)] +
                        [{"pressure": float(load), "raw_adc": values.tolist()} for load, values in zip(loads[1:-1], raw[1:-1])] +
                        [{"pressure": 4500., "raw_adc": (raw[-1] + shift).tolist()} for shift in (-4, 4)])
    source_path = directory / "synthetic_sweep.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    cells, mean = fitting.build_models(loads, raw, load_range_g=(0, 4500))
    fitting.save_model(directory, source, loads, raw, cells, mean, protocol=fitting.NEW_PROTOCOL, input_path=source_path)
    model_path = directory / "pressure_response_model.json"
    model = json.loads(model_path.read_text())
    model["synthetic_test_only"] = True
    model_path.write_text(json.dumps(model), encoding="utf-8")
    endpoint = {"format": "e-skin-fsr-two-point-calibration", "version": 3,
                "protocol_id": fitting.NEW_PROTOCOL, "load_range_g": [0, 4500],
                "module_id": 1, "fsr": "FSR1", "synthetic_test_only": True,
                "source_file": str(source_path.resolve()), "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "zero_load": {"median": zero.tolist()}, "full_load": {"median": (zero + span).tolist()},
                "calibration": {"interval_low_zero": zero.tolist(), "interval_high_full": (zero + span).tolist()}}
    endpoint_path = directory / "synthetic_two_point.json"
    endpoint_path.write_text(json.dumps(endpoint), encoding="utf-8")
    return endpoint_path, model_path


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.source = {"protocol_id": fitting.NEW_PROTOCOL, "version": 3, "load_range_g": [0, 4500],
                       "pressure": {"unit": "g"}, "module_id": 1, "fsr": "FSR1"}
        self.loads = np.asarray([0., 500., 4500.])
        self.raw = np.asarray([np.full((16, 16), v) for v in (100., 500., 3000.)])

    def test_new_protocol_requires_real_tag_and_both_endpoints(self):
        fitting.validate_protocol(self.source, self.loads, self.raw, fitting.NEW_PROTOCOL)
        for changes, loads in (({"protocol_id": None}, self.loads), ({}, np.asarray([0, 500, 4499])),
                               ({}, np.asarray([0, 4500, 500])), ({"version": 2}, self.loads),
                               ({"pressure": {"unit": "Pa"}}, self.loads)):
            with self.subTest(changes=changes, loads=loads), self.assertRaises(ValueError):
                fitting.validate_protocol({**self.source, **changes}, loads, self.raw, fitting.NEW_PROTOCOL)

    def test_no_silent_legacy_analysis_of_new_sweep(self):
        with self.assertRaises(ValueError):
            fitting.validate_protocol(self.source, self.loads, self.raw, "legacy")
        fitting.validate_protocol({}, self.loads, self.raw, "legacy")

    def test_upper_load_is_dynamic_and_last_capture_is_maximum(self):
        for upper in (4000., 1750., 650.5):
            fitting.validate_protocol({**self.source, "load_range_g": [0, upper]},
                                      np.array([0., upper / 3, upper]), self.raw, fitting.NEW_PROTOCOL)
        for loads in (np.array([0., 4500., 500.]), np.array([0., 0., 0.]), np.array([100., 500., 4500.])):
            with self.assertRaises(ValueError):
                fitting.validate_protocol(self.source, loads, self.raw, fitting.NEW_PROTOCOL)

    def test_new_metrics_include_upper_range_legacy_is_retained(self):
        loads = np.asarray([0., 500., 3000., 4500.])
        raw = np.asarray([10., 300., 2800., 2500.])
        old = fitting.fit_monotonic_response(loads, raw)
        new = fitting.fit_monotonic_response(loads, raw, load_range_g=(0, 4500))
        self.assertEqual(old["metrics"]["included_points"], 3)
        self.assertEqual(new["metrics"]["included_points"], 4)
        self.assertEqual(new["metrics"]["statistical_load_range_g"], [0, 4500])
        self.assertEqual(old["pressure_from_adc"], new["pressure_from_adc"])

    def test_plateau_midpoint_is_retained(self):
        result = fitting.fit_monotonic_response(np.array([0., 100., 4500.]), np.array([10., 10., 3000.]), load_range_g=(0, 4500))
        self.assertEqual(result["pressure_from_adc"]["y"][0], 50.)

    def test_new_fit_main_preserves_sources_and_previous_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = {**self.source, "format": "e-skin-fsr-pressure-response-sweep",
                      "points": [{"pressure": float(load), "raw_adc": raw.tolist()}
                                 for load, raw in zip(self.loads, self.raw)]}
            source_path = directory / "sweep.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            previous = directory / "previous_model.json"
            previous.write_text("preserve me", encoding="utf-8")
            args = SimpleNamespace(input=source_path, output_dir=directory / "new_run",
                                   protocol=fitting.NEW_PROTOCOL, per_cell_grid=False)
            with patch.object(fitting, "parse_args", return_value=args), \
                 patch.object(fitting, "archive_previous_calibration", side_effect=AssertionError("must not archive")), \
                 patch.object(fitting, "plot_all_cells_raw"), patch.object(fitting, "plot_all_cells_fits"), \
                 patch.object(fitting, "plot_mean_response"):
                self.assertEqual(fitting.main(), 0)
                model = json.loads((args.output_dir / "pressure_response_model.json").read_text())
                self.assertEqual(model["protocol_id"], fitting.NEW_PROTOCOL)
                self.assertEqual(model["source_file"], str(source_path.resolve()))
                self.assertEqual(len(model["source_sha256"]), 64)
                self.assertTrue(source_path.is_file())
                self.assertEqual(previous.read_text(), "preserve me")
                with self.assertRaises(ValueError):
                    fitting.main()


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.two_path, self.model_path = synthetic_inputs(self.directory)
        self.two = json.loads(self.two_path.read_text())
        self.model = json.loads(self.model_path.read_text())

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_and_legacy_rejection(self):
        comparison.validate_inputs(self.two, self.model)
        for changed in ({"version": 1}, {"protocol_id": None}, {"module_id": 3}, {"fsr": "FSR2"}, {"load_range_g": [0, 3000]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                comparison.validate_inputs({**self.two, **changed}, self.model)

    def test_corner_max_rejected_even_with_new_label(self):
        self.two["full_load"]["maximum_over_all_corners"] = self.two["full_load"]["median"]
        with self.assertRaises(ValueError):
            comparison.validate_inputs(self.two, self.model)

    def test_shared_sweep_hash_and_path_are_required(self):
        other = copy.deepcopy(self.two)
        other["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            comparison.validate_inputs(other, self.model)
        copied_sweep = self.directory / "other_sweep.json"
        copied_sweep.write_bytes(Path(self.two["source_file"]).read_bytes())
        other = {**self.two, "source_file": str(copied_sweep)}
        with self.assertRaisesRegex(ValueError, "same sweep path"):
            comparison.validate_inputs(other, self.model)

    def test_endpoints_must_be_median_of_same_sweep_captures(self):
        changed = copy.deepcopy(self.two)
        changed["calibration"]["interval_high_full"][0][0] += 4
        changed["full_load"]["median"][0][0] += 4
        with self.assertRaisesRegex(ValueError, "median-aggregated"):
            comparison.validate_inputs(changed, self.model)

    def test_model_knots_cannot_be_changed_under_original_source_hash(self):
        changed = copy.deepcopy(self.model)
        changed["fit"]["cells"][0]["adc_from_pressure"]["y"][3] += 1
        with self.assertRaisesRegex(ValueError, "knots differ"):
            comparison.validate_inputs(self.two, changed)

    def test_gamma_is_prescribed_and_linear_at_one(self):
        zero, full, cells = comparison.validate_inputs(self.two, self.model)
        adc = np.array([0., 1300., 4095.])
        output, valid = comparison.estimate_curves(zero, full, cells, 1., adc)
        np.testing.assert_array_equal(output["LINEAR"], output["GAMMA"])
        self.assertTrue(np.all(valid))
        output, _ = comparison.estimate_curves(zero, full, cells, 4., adc)
        self.assertEqual(output["GAMMA"][0, 1], 281.25)
        for invalid in [0, -1, float("inf"), float("nan")]:
            with self.assertRaises(ValueError):
                comparison.positive_gamma(invalid)

    def test_same_adc_does_not_reanchor_multi_point(self):
        zero, full, cells = comparison.validate_inputs(self.two, self.model)
        output, _ = comparison.estimate_curves(zero, full, cells, 4., np.array([0., 4095.]))
        self.assertEqual(output["LINEAR"][0, 0], 0.)
        self.assertEqual(output["MULTI-POINT"][0, 0], 50.)

    def test_common_actual_adc_uses_each_cells_own_endpoints(self):
        zero, full, cells = comparison.validate_inputs(self.two, self.model)
        adc = np.array([0., 1300., 4095.])
        output, valid = comparison.estimate_curves(zero, full, cells, 4., adc)
        expected_linear = 4500 * np.clip((1300. - zero.ravel()) / (full - zero).ravel(), 0, 1)
        np.testing.assert_allclose(output["LINEAR"][:, 1], expected_linear)
        self.assertNotEqual(output["LINEAR"][0, 1], output["LINEAR"][-1, 1])
        function_mean = output["LINEAR"][valid, 1].mean()
        self.assertAlmostEqual(function_mean, expected_linear.mean())
        representative_index = 7 * 16 + 7
        self.assertNotAlmostEqual(function_mean, output["LINEAR"][representative_index, 1])
        for name in ("LINEAR", "GAMMA"):
            np.testing.assert_array_equal(output[name][:, 0], np.zeros(256))
            np.testing.assert_array_equal(output[name][:, -1], np.full(256, 4500.))

    def test_adc_axis_rejects_invalid_or_transposed_coordinates(self):
        zero, full, cells = comparison.validate_inputs(self.two, self.model)
        for invalid in (np.array([]), np.array([-1., 1.]), np.array([0., 4096.]),
                        np.array([np.nan]), np.array([[0., 1.]])):
            with self.assertRaisesRegex(ValueError, "ADC axis"):
                comparison.estimate_curves(zero, full, cells, 4., invalid)

    def test_nonpositive_span_uses_same_mask_for_all_methods(self):
        zero, full, cells = comparison.validate_inputs(self.two, self.model)
        full[0, 0] = zero[0, 0]
        output, valid = comparison.estimate_curves(zero, full, cells, 4., np.array([0., 1300., 4095.]))
        self.assertEqual(valid.sum(), 255)
        for values in output.values():
            self.assertTrue(np.all(np.isnan(values[0])))

    def test_generate_declares_synthetic_and_hashes_sources(self):
        destination = self.directory / "figures"
        result = comparison.generate_comparison(self.two_path, self.model_path, destination)
        self.assertTrue(result["synthetic_test_only"])
        self.assertEqual(result["available_positive_span_cells"], 256)
        self.assertEqual(result["plotted_cells"], 1)
        self.assertEqual(result["load_range_g"], [0, 4500])
        self.assertEqual(result["panels"], ["representative_cell_load_to_adc", "representative_cell_adc_to_load"])
        self.assertEqual(result["inverse_input_axis"]["quantity"], "raw_adc_code")
        self.assertEqual(result["inverse_input_axis"]["range"], [0, self.two["full_load"]["median"][7][7]])
        self.assertEqual(result["inverse_input_axis"]["upper_bound_load_g"], 4500.)
        self.assertNotIn("mean_curve_policy", result)
        self.assertEqual(len(result["sources"][0]["sha256"]), 64)
        self.assertGreater((destination / "calibration_comparison.png").stat().st_size, 10000)
        self.assertTrue((destination / "calibration_comparison.pdf").read_bytes().startswith(b"%PDF"))

    def test_two_panels_axis_ends_at_selected_measured_adc_not_pava_knot(self):
        directory = self.directory / "upper_plateau"
        directory.mkdir()
        endpoint_path, model_path = synthetic_inputs(directory, upper_plateau=True)
        endpoint = json.loads(endpoint_path.read_text())
        model = json.loads(model_path.read_text())
        full_adc = endpoint["full_load"]["median"][15][15]
        self.assertNotEqual(full_adc, model["fit"]["cells"][-1]["adc_from_pressure"]["y"][-1])
        with patch.object(comparison.plt, "close"):
            result = comparison.generate_comparison(endpoint_path, model_path, directory / "figures", cell=(16, 16))
            figure = comparison.plt.gcf()
            self.assertEqual(len(figure.axes), 2)
            self.assertEqual(figure.axes[1].get_xlim(), (0, full_adc))
            for line in figure.axes[1].lines:
                self.assertEqual(line.get_xdata()[-1], full_adc)
            self.assertEqual(result["inverse_input_axis"]["range"], [0, full_adc])
            self.assertEqual(result["representative_cell"], {"row": 16, "column": 16})
        comparison.plt.close(figure)


if __name__ == "__main__":
    unittest.main()
