"""Synthetic regression checks; these are not sensor experiments."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from new_protocol_evaluation import (
    PROTOCOL_ID, LEGACY_ID, protocol_key, batch_protocol, prepare_matched,
    load_matched_batch, compact_record, recorded_two_point, analyze_capture,
)


def matrix(value):
    return np.full((16, 16), value, dtype=float).tolist()


def capture(root, upper=4000):
    return {
        "format": "e-skin-fsr-view-distribution-capture", "version": 3,
        "protocol_id": PROTOCOL_ID, "load_range_g": [0, upper],
        "evaluation_policy": {"statistical_load_range_g": [0, upper]},
        "module_id": 1, "fsr": "FSR1", "actual_load": {"value": .8*upper, "unit": "g"},
        "source_models": {"normalized_calibration": str(root / "recorded.json"),
                          "fitted_response": str(root / "fit.json"), "normalized_gamma": 2},
        "calibration_snapshot": {"protocol_id": PROTOCOL_ID, "load_range_g": [0, upper],
                                 "source_path": str(root / "recorded.json"),
                                 "interval_low_zero": matrix(10), "interval_high_full": matrix(1010),
                                 "problem_cells": [{"row": 1, "column": 1, "flags": ["FULL_UNSTABLE"]}]},
        "views": {"RAW": {"values": matrix(810), "unit": "ADC code"},
                  "LINEAR": {"values": matrix(.8), "unit": "ratio"},
                  "NORM_CAL": {"values": matrix(.64), "unit": "ratio"},
                  "FIT_PRESS": {"values": matrix(.8*upper+100), "unit": "g"}},
    }


def grams_capture(old):
    result = copy.deepcopy(old)
    upper = result["load_range_g"][1]
    result.update(version=4, prediction_units="g")
    result["views"] = {
        "RAW": copy.deepcopy(old["views"]["RAW"]),
        "LINEAR": {"unit": "g", "values": (np.asarray(old["views"]["LINEAR"]["values"]) * upper).tolist()},
        "GAMMA": {"unit": "g", "values": (np.asarray(old["views"]["NORM_CAL"]["values"]) * upper).tolist()},
        "FIT_PRESS": copy.deepcopy(old["views"]["FIT_PRESS"]),
    }
    sources = result["source_models"]
    sources["two_point"] = sources.pop("normalized_calibration")
    sources["gamma"] = sources.pop("normalized_gamma")
    if "normalized_calibration_sha256" in sources:
        sources["two_point_sha256"] = sources.pop("normalized_calibration_sha256")
    return result


class NewProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = capture(self.root)
        self.path = self.root / "view_distribution_capture.json"

    def tearDown(self):
        self.temp.cleanup()

    def save(self, data, directory="run1"):
        path = self.root / directory / "view_distribution_capture.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_dynamic_range_and_old_3000_policy(self):
        self.assertEqual(protocol_key(self.data), (PROTOCOL_ID, 0, 4000))
        self.assertEqual(protocol_key({}), (LEGACY_ID, 0, 3000))
        self.data["evaluation_policy"]["statistical_load_range_g"] = [0, 3000]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            protocol_key(self.data)

    def test_mixed_batch_refused_before_outputs(self):
        new_path = self.save(self.data)
        old = copy.deepcopy(self.data)
        for key in ("protocol_id", "load_range_g", "evaluation_policy"):
            old.pop(key)
        old["version"] = 2
        old_path = self.save(old, "old")
        with self.assertRaisesRegex(ValueError, "Mixed"):
            batch_protocol([new_path, old_path])
        import analyze_load_accuracy
        output = self.root / "output"
        with self.assertRaisesRegex(ValueError, "Mixed"):
            analyze_load_accuracy.analyze(self.root, output)
        self.assertFalse(output.exists())

    def test_matched_set_retains_finite_bad_predictions_and_qc_flags(self):
        self.data["views"]["FIT_PRESS"]["values"][0][0] = 7000
        self.data["views"]["NORM_CAL"]["values"][0][1] = None
        self.data["calibration_snapshot"]["interval_high_full"][0][2] = 10
        record = prepare_matched(self.data, self.path)
        self.assertEqual(int(record["mask"].sum()), 254)
        self.assertTrue(record["mask"][0, 0])
        result = compact_record(record)
        for method in ("LINEAR", "GAMMA", "FIT_PRESS"):
            self.assertEqual(result["methods"][method]["matched_statistics"]["count"], 254)
        self.assertEqual(result["methods"]["FIT_PRESS"]["above_upper_range_count"], 1)
        self.assertEqual(result["methods"]["FIT_PRESS"]["all_finite_source_statistics"]["count"], 256)
        self.assertEqual(result["model_quality_flags"][0]["flags"], ["FULL_UNSTABLE"])

    def test_fixed_set_across_in_range_captures(self):
        path1 = self.save(self.data)
        second = copy.deepcopy(self.data)
        second["views"]["FIT_PRESS"]["values"][1][1] = None
        second["actual_load"]["value"] = 4000
        path2 = self.save(second, "run2")
        records = load_matched_batch([path1, path2])
        self.assertEqual([int(r["mask"].sum()) for r in records], [255, 255])
        np.testing.assert_array_equal(records[0]["mask"], records[1]["mask"])

    def test_snapshot_is_frozen_and_never_uses_latest_file(self):
        (self.root / "newest.json").write_text("{}")
        model, provenance = recorded_two_point(self.data, self.path)
        self.assertEqual(model["interval_high_full"][0][0], 1010)
        self.assertEqual(provenance["two_point_source"], "embedded_snapshot")
        self.assertTrue(provenance["two_point"].endswith("recorded.json"))
        self.data["calibration_snapshot"]["source_path"] = str(self.root / "wrong.json")
        with self.assertRaisesRegex(ValueError, "source path"):
            recorded_two_point(self.data, self.path)

    def test_recorded_file_hash_is_enforced(self):
        model = self.data.pop("calibration_snapshot")
        raw = json.dumps(model).encode()
        (self.root / "recorded.json").write_bytes(raw)
        self.data["source_models"]["normalized_calibration_sha256"] = hashlib.sha256(raw).hexdigest()
        _, provenance = recorded_two_point(self.data, self.path)
        self.assertEqual(provenance["two_point_source"], "recorded_path_sha256_verified")
        (self.root / "recorded.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            recorded_two_point(self.data, self.path)

    def test_zero_load_percentage_errors_null(self):
        self.data["actual_load"]["value"] = 0
        summary = compact_record(prepare_matched(self.data, self.path))
        for method in summary["methods"].values():
            self.assertIsNone(method["matched_statistics"]["mean_estimate_absolute_percentage_error"])
            self.assertIsNone(method["matched_statistics"]["cell_mean_absolute_percentage_error"])

    def test_new_capture_routes_and_generates_fair_artifacts(self):
        path = self.save(self.data)
        import analyze_view_distributions
        outputs = analyze_view_distributions.analyze(path, self.root / "plots")
        summary = json.loads(outputs["summary"].read_text())
        self.assertEqual(summary["quality_policy"]["range_g"], [0, 4000])
        self.assertEqual(summary["record"]["methods"]["LINEAR"]["matched_statistics"]["mean"], 3200)
        self.assertTrue(outputs["combined"].is_file())
        self.assertIn("quality_flags", outputs["cells"].read_text().splitlines()[0])

    def test_upper_4500_scaling_and_mixed_ranges_rejected(self):
        other = capture(self.root, upper=4500)
        record = prepare_matched(other, self.path)
        self.assertEqual(record["load_range_g"], [0, 4500])
        self.assertEqual(float(record["estimates_g"]["LINEAR"][0, 0]), 3600)
        self.assertEqual(float(record["estimates_g"]["GAMMA"][0, 0]), 2880)
        paths = [self.save(self.data), self.save(other, "different_range")]
        with self.assertRaisesRegex(ValueError, "Mixed"):
            batch_protocol(paths)

    def test_dynamic_bounds_must_be_valid_and_match_endpoint_model(self):
        for upper in (0, -1, float("nan"), float("inf")):
            data = capture(self.root, upper=upper)
            with self.assertRaises(ValueError):
                protocol_key(data)
        self.data["calibration_snapshot"]["load_range_g"] = [0, 4500]
        with self.assertRaisesRegex(ValueError, "range differs"):
            prepare_matched(self.data, self.path)

    def test_dynamic_batch_plot_uses_recorded_upper_range(self):
        data = capture(self.root, upper=4500)
        self.save(data)
        data["views"]["FIT_PRESS"]["values"] = matrix(3800)
        self.save(data, "repeat2")
        import analyze_load_accuracy
        axes = []
        def inspect_figure(figure, *args, **kwargs):
            if Path(args[0]).suffix == ".png":
                axes.append((figure.axes[0].get_xlim(), len(figure.axes[0].patches)))
        with patch("matplotlib.figure.Figure.savefig", new=inspect_figure):
            outputs = analyze_load_accuracy.analyze(self.root, self.root / "analysis", include_shared_lut=False)
        self.assertEqual(len(axes), 3)
        for (lower, upper), patch_count in axes:
            self.assertLessEqual(lower, 3600)
            self.assertGreaterEqual(upper, 3600)
            self.assertLess(upper, 4500)
            self.assertEqual(patch_count, 0)
        summary = json.loads(outputs["summary"].read_text())
        self.assertEqual(summary["quality_policy"]["range_g"], [0, 4500])
        metrics = summary["groups"][0]["methods"]["FIT_PRESS"]["mean"]
        self.assertEqual(metrics["n"], 2)
        self.assertEqual(metrics["mean"], 3750)
        self.assertAlmostEqual(metrics["sd"], np.sqrt(5000))

    def test_incomplete_capture_excluded_and_reported_not_counted_as_repeat(self):
        self.save(self.data)
        partial = copy.deepcopy(self.data)
        partial["status"] = "INCOMPLETE"
        partial["source_frames"] = {"count": 37, "target_count": 200}
        path = self.save(partial, "partial")
        import analyze_load_accuracy, analyze_view_distributions
        with patch("matplotlib.figure.Figure.savefig"):
            outputs = analyze_load_accuracy.analyze(self.root, self.root / "analysis", include_shared_lut=False)
        summary = json.loads(outputs["summary"].read_text())
        self.assertEqual(summary["groups"][0]["methods"]["FIT_PRESS"]["mean"]["n"], 1)
        self.assertEqual(summary["excluded_incomplete_capture_count"], 1)
        self.assertEqual(summary["excluded_incomplete_captures"][0]["frame_count"], 37)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            analyze_view_distributions.analyze(path, self.root / "single_partial")
        self.assertFalse((self.root / "single_partial").exists())

    def test_false_complete_with_partial_frames_rejected(self):
        self.data["status"] = "COMPLETE"
        self.data["source_frames"] = {"count": 199, "target_count": 200}
        with self.assertRaisesRegex(ValueError, "incomplete_frame_count"):
            prepare_matched(self.data, self.path)

    def test_changed_gamma_is_not_aggregated_as_a_repeat(self):
        first = self.save(self.data)
        changed = copy.deepcopy(self.data)
        changed["source_models"]["normalized_gamma"] = 3
        second = self.save(changed, "changed_gamma")
        with self.assertRaisesRegex(ValueError, "Mixed calibration models or gamma"):
            load_matched_batch([first, second])

    def test_changed_model_hash_rejected_but_same_hash_copy_paths_match(self):
        self.data["source_models"].update(normalized_calibration_sha256="a" * 64,
                                          fitted_response_sha256="b" * 64)
        first = self.save(self.data)
        for field in ("normalized_calibration_sha256", "fitted_response_sha256"):
            changed = copy.deepcopy(self.data)
            changed["source_models"][field] = "c" * 64
            second = self.save(changed, field)
            with self.assertRaisesRegex(ValueError, "Mixed calibration models or gamma"):
                load_matched_batch([first, second])
        copied = copy.deepcopy(self.data)
        copied["source_models"]["normalized_calibration"] = str(self.root / "copy" / "endpoints.json")
        copied["source_models"]["fitted_response"] = str(self.root / "copy" / "fit.json")
        copied["calibration_snapshot"]["source_path"] = copied["source_models"]["normalized_calibration"]
        copied_path = self.save(copied, "identical_model_copies")
        records = load_matched_batch([first, copied_path])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["provenance"]["comparison_condition"],
                         records[1]["provenance"]["comparison_condition"])

    def test_version4_g_and_version3_ratios_have_identical_estimates_and_batch(self):
        self.data["source_models"].update(normalized_calibration_sha256="a" * 64,
                                          fitted_response_sha256="b" * 64)
        new = grams_capture(self.data)
        old_record = prepare_matched(self.data, self.path)
        new_record = prepare_matched(new, self.path)
        self.assertEqual(set(new_record["estimates_g"]), {"LINEAR", "GAMMA", "FIT_PRESS"})
        for method in new_record["estimates_g"]:
            np.testing.assert_array_equal(new_record["estimates_g"][method], old_record["estimates_g"][method])
        records = load_matched_batch([self.save(self.data), self.save(new, "version4")])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["provenance"]["comparison_condition"], records[1]["provenance"]["comparison_condition"])

    def test_version4_4000_g_is_not_multiplied_again(self):
        new = grams_capture(self.data)
        new["views"]["LINEAR"]["values"] = matrix(4000)
        new["views"]["GAMMA"]["values"] = matrix(4000)
        record = prepare_matched(new, self.path)
        self.assertEqual(float(record["estimates_g"]["LINEAR"][0, 0]), 4000)
        self.assertEqual(float(record["estimates_g"]["GAMMA"][0, 0]), 4000)
        from evaluation_plotting import load_capture
        self.assertEqual(load_capture(self.save(new))["version"], 4)

    def test_wrong_units_and_missing_version4_prediction_units_rejected(self):
        cases = []
        old = copy.deepcopy(self.data)
        old["views"]["LINEAR"]["unit"] = "g"
        cases.append(old)
        for method in ("LINEAR", "GAMMA", "FIT_PRESS"):
            new = grams_capture(self.data)
            new["views"][method]["unit"] = "ratio"
            cases.append(new)
        new = grams_capture(self.data)
        new.pop("prediction_units")
        cases.append(new)
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValueError, "units"):
                    prepare_matched(data, self.path)

    def test_explicit_capture_selection_ignores_other_conditions_and_refuses_duplicates(self):
        first = self.save(self.data)
        other = copy.deepcopy(self.data)
        other["source_models"]["normalized_gamma"] = 3
        self.save(other, "other_gamma")
        from new_protocol_evaluation import analyze_batch
        with patch("matplotlib.figure.Figure.savefig"):
            outputs = analyze_batch(self.root, self.root / "selected", capture_paths=[first])
        summary = json.loads(outputs["summary"].read_text())
        self.assertEqual(summary["selected_source_captures"], [str(first.resolve())])
        self.assertEqual(len(summary["records"]), 1)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            analyze_batch(self.root, self.root / "duplicate", capture_paths=[first, first])
        self.assertFalse((self.root / "duplicate").exists())

    def test_error_overlay_has_three_signed_curves_zero_reference_and_no_n1_errorbars(self):
        data = grams_capture(self.data)
        data["actual_load"]["value"] = 100
        for name, value in (("LINEAR", 110), ("GAMMA", 90), ("FIT_PRESS", 100)):
            data["views"][name]["values"] = matrix(value)
        path = self.save(data)
        seen = []
        def inspect(figure, destination, **_kwargs):
            if Path(destination).name == "load_error_vs_load.png":
                self.assertEqual(len(figure.axes), 1)
                axis = figure.axes[0]
                by_label = {line.get_label(): line for line in axis.lines}
                self.assertEqual(set(by_label), {"LINEAR", "GAMMA", "FIT_PRESS", "Zero error"})
                for name, value in (("LINEAR", 10), ("GAMMA", -10), ("FIT_PRESS", 0)):
                    np.testing.assert_allclose(by_label[name].get_ydata(), [value])
                self.assertEqual(len(axis.containers), 0)  # n=1 has no invented zero-length error bar
                self.assertEqual(axis.get_ylabel(), "Signed mean error (g)")
                seen.append(True)
        from new_protocol_evaluation import analyze_batch
        with patch("matplotlib.figure.Figure.savefig", new=inspect):
            outputs = analyze_batch(self.root, self.root / "error", capture_paths=[path])
        self.assertEqual(seen, [True])
        self.assertEqual(outputs["plot"], outputs["mean"])
        self.assertEqual(outputs["error_plot"], outputs["bias_g"])
        self.assertEqual(outputs["pdf"].suffix, ".pdf")
        summary = json.loads(outputs["summary"].read_text())
        for method in summary["groups"][0]["methods"].values():
            self.assertIsNone(method["bias_g"]["sd"])
            self.assertEqual(method["bias_g"]["n"], 1)
            self.assertIn("mae_g", method)
            self.assertIn("rmse_g", method)

    def test_dispersion_panel_uses_g_units_and_repeated_metric_sd(self):
        paths = []
        for repeat, values in enumerate(((90, 110), (90, 130))):
            data = grams_capture(self.data)
            data["actual_load"]["value"] = 100
            cells = np.tile([values[0]] * 8 + [values[1]] * 8, (16, 1)).tolist()
            for name in ("LINEAR", "GAMMA", "FIT_PRESS"):
                data["views"][name]["values"] = cells
            paths.append(self.save(data, f"dispersion_{repeat}"))
        seen = []
        def inspect(figure, destination, **_kwargs):
            if Path(destination).name == "dispersion_comparison.png":
                self.assertEqual(len(figure.axes), 4)
                self.assertEqual([axis.get_ylabel() for axis in figure.axes],
                                 ["Spatial SD (g)", "Spatial variance (g²)", "Spatial IQR (g)", "Spatial MAD (g)"])
                for axis in figure.axes:
                    self.assertTrue({"LINEAR", "GAMMA", "FIT_PRESS"}.issubset({line.get_label() for line in axis.lines}))
                    self.assertEqual(len(axis.containers), 3)
                seen.append(True)
        from new_protocol_evaluation import analyze_batch
        with patch("matplotlib.figure.Figure.savefig", new=inspect):
            outputs = analyze_batch(self.root, self.root / "dispersion", kind="dispersion", capture_paths=paths)
        self.assertEqual(seen, [True])
        self.assertEqual(outputs["plot"], outputs["cv_percent"])
        summary = json.loads(outputs["summary"].read_text())
        self.assertEqual(summary["plot_metrics"], ["cv_percent", "variance", "iqr", "mad"])
        self.assertIn("cv_percent", summary["groups"][0]["methods"]["LINEAR"])
        expected = {"std": (15, np.sqrt(50)), "variance": (250, np.sqrt(45000)),
                    "iqr": (30, np.sqrt(200)), "mad": (15, np.sqrt(50))}
        for method in summary["groups"][0]["methods"].values():
            for name, (mean, sd) in expected.items():
                self.assertAlmostEqual(method[name]["mean"], mean)
                self.assertAlmostEqual(method[name]["sd"], sd)
                self.assertEqual(method[name]["n"], 2)


if __name__ == "__main__":
    unittest.main()
