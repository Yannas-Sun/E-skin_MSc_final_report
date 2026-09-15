"""Synthetic-only checks of restored single-capture artwork in gram units."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import capture_distribution_style as artwork
import new_protocol_evaluation as evaluation


def synthetic_capture(root: Path) -> dict:
    row = np.arange(256, dtype=float).reshape(16, 16)
    calibration = {"protocol_id": evaluation.PROTOCOL_ID, "load_range_g": [0, 4000],
                   "source_path": str(root / "synthetic_endpoint.json"),
                   "interval_low_zero": np.full((16, 16), 10.).tolist(),
                   "interval_high_full": np.full((16, 16), 1010.).tolist(),
                   "problem_cells": [{"row": 1, "column": 3, "flags": ["FULL_UNSTABLE"]}]}
    record = {
        "format": "e-skin-fsr-view-distribution-capture", "version": 4,
        "protocol_id": evaluation.PROTOCOL_ID, "prediction_units": "g", "load_range_g": [0, 4000],
        "evaluation_policy": {"statistical_load_range_g": [0, 4000]},
        "module_id": 1, "fsr": "FSR1", "actual_load": {"value": 2000, "unit": "g"},
        "status": "COMPLETE", "source_frames": {"count": 200, "target_count": 200},
        "experiment_metadata": {"synthetic_test_only": True},
        "source_models": {"two_point": str(root / "synthetic_endpoint.json"),
                          "fitted_response": str(root / "synthetic_fit.json"), "gamma": 2},
        "calibration_snapshot": calibration,
        "views": {"RAW": {"unit": "ADC code", "values": (100 + row * 3).tolist()},
                  "LINEAR": {"unit": "g", "values": (1000 + row * 8).tolist()},
                  "GAMMA": {"unit": "g", "values": (400 + row * 6).tolist()},
                  "FIT_PRESS": {"unit": "g", "values": (1700 + row * 2).tolist()}},
    }
    record["views"]["GAMMA"]["values"][0][0] = None
    record["calibration_snapshot"]["interval_high_full"][0][1] = 10.
    record["views"]["FIT_PRESS"]["values"][0][2] = 4700.
    return record


class CaptureDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = synthetic_capture(self.root)
        self.path = self.root / evaluation.CAPTURE_NAME
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        self.record = evaluation.load_matched_batch([self.path])[0]

    def tearDown(self):
        artwork.plt.close("all")
        self.temp.cleanup()

    def test_views_keep_same_cells_grams_and_finite_poor_predictions(self):
        before = {name: value.copy() for name, value in self.record["estimates_g"].items()}
        views, edges, limits = artwork.prepare_plot_views(self.record)
        self.assertEqual(limits, (0., 4700.))
        self.assertEqual(len(edges), 51)
        for name, view in views.items():
            self.assertEqual(view["unit"], "g")
            self.assertEqual(view["count"], 254)
            np.testing.assert_array_equal(view["values"], before[name][self.record["mask"]])
            np.testing.assert_array_equal(self.record["estimates_g"][name], before[name])
        self.assertIn(4700., views["FIT_PRESS"]["values"])

    def test_density_included_and_excluded_mass_integrates_to_one(self):
        views, edges, limits = artwork.prepare_plot_views(self.record)
        for name in artwork.METHODS:
            fig, axis = artwork.plt.subplots()
            artwork.plot_distribution(axis, name, views[name], 2000., "A", edges, limits)
            self.assertAlmostEqual(sum(bar.get_height() * bar.get_width() for bar in axis.patches), 1.)
            self.assertIn("1/g", axis.get_ylabel())
            self.assertEqual(axis.get_xlim(), limits)
            mean_lines = [line for line in axis.lines if line.get_label().startswith("Included mean")]
            self.assertAlmostEqual(float(mean_lines[0].get_xdata()[0]), float(views[name]["values"].mean()))

    def test_boxplot_matches_old_marker_style_on_one_mass_axis(self):
        views, _, limits = artwork.prepare_plot_views(self.record)
        for name in artwork.METHODS:
            fig, axis = artwork.plt.subplots()
            artwork.plot_boxplot(axis, name, views[name], 2000., "A", limits)
            self.assertEqual(axis.get_ylim(), limits)
            self.assertTrue(any(line.get_marker() == "D" for line in axis.lines))
            self.assertTrue(any(line.get_linestyle() == ":" and line.get_ydata()[0] == 2000. for line in axis.lines))
            self.assertIn("(g)", axis.get_ylabel())

    def test_overlay_retains_distinct_nonzero_means(self):
        views, edges, limits = artwork.prepare_plot_views(self.record)
        fig, axis = artwork.plt.subplots()
        artwork.plot_distribution_overlay(axis, views, 2000., edges, limits)
        for name in artwork.METHODS:
            label = artwork.LABELS[name] + " mean"
            line = next(line for line in axis.lines if line.get_label().startswith(label))
            self.assertAlmostEqual(float(line.get_xdata()[0]), float(views[name]["values"].mean()))
            self.assertGreater(line.get_xdata()[0], 100.)
        self.assertEqual(axis.get_xlim(), limits)
        self.assertNotIn("normalised", axis.get_xlabel().lower())
        self.assertNotIn("centred", axis.get_xlabel().lower())

    def test_analyze_capture_outputs_restored_family_and_preserves_source(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        output = self.root / "analysis"
        results = evaluation.analyze_capture(self.path, output)
        expected = {"linear_distribution.png", "gamma_distribution.png", "fit_press_distribution.png",
                    "view_distributions.png", "boxplot_distributions.png", "distribution_comparison.png",
                    "view_distribution_cells.csv", "view_distribution_exclusions.csv", "view_distribution_summary.json"}
        self.assertEqual({path.name for path in results.values()}, expected)
        self.assertFalse((output / "normalized_distributions.png").exists())
        self.assertFalse((output / "norm_cal_distribution.png").exists())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        summary = json.loads(results["summary"].read_text())
        self.assertEqual(summary["distribution_plot_policy"]["prediction_units"], "g")
        self.assertEqual(summary["record"]["common_cell_count"], 254)
        self.assertEqual(summary["record"]["methods"]["FIT_PRESS"]["above_upper_range_count"], 1)
        with results["exclusions"].open(newline="", encoding="utf-8") as handle:
            excluded = list(csv.DictReader(handle))
        self.assertEqual(len(excluded), 6)
        self.assertEqual({row["view"] for row in excluded}, set(artwork.METHODS))
        self.assertEqual({row["unit"] for row in excluded}, {"g"})
        self.assertTrue(all(path.stat().st_size > 10000 for path in results.values() if path.suffix == ".png"))


if __name__ == "__main__":
    unittest.main()
