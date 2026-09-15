"""Independent source-to-output checks for the Power 2.1 report data."""
from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "legacy"))
import analyze_power_revision as analysis


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RevisionValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = analysis.ROOT
        cls.source_files = [cls.root / "DATA/raw/canonical/power_raw.csv", *sorted((cls.root / "DATA/raw/canonical/power_experiment_records").rglob("*.yaml"))]
        cls.hashes_before = {str(p): sha(p) for p in cls.source_files}
        cls.temp = tempfile.TemporaryDirectory(prefix="power_revision_validation_")
        cls.summary = analysis.analyze(cls.root, Path(cls.temp.name) / "derived")
        cls.runs = {r["run_id"]: r for r in cls.summary["runs"]}
        cls.branches = {(b["run_id"], b["module_id"]): b for b in cls.summary["branches"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_canonical_records_no_duplicate_standby_yaml(self):
        self.assertEqual(self.summary["counts"], {"total_runs": 31, "continuous_runs": 18, "blocked_runs": 13, "branches": 58})
        self.assertEqual(len(self.runs), 31)
        self.assertEqual(self.summary["provenance"]["excluded_standby_yaml_count"], 11)
        self.assertEqual(len(self.summary["provenance"]["sources"]), 19)
        self.assertTrue(all("no_transmission" not in r["source_path"] for r in self.runs.values()))

    def test_every_original_and_excluded_yaml_is_byte_unchanged(self):
        self.assertEqual(self.hashes_before, {str(p): sha(p) for p in self.source_files})
        self.assertTrue(self.summary["provenance"]["source_files_verified_unchanged"])

    def test_source_decimal_totals_and_power_match_every_exported_run(self):
        # Independent import and Decimal arithmetic, without derive/load_sources helpers.
        with (self.root / "DATA/raw/canonical/power_raw.csv").open(encoding="utf-8-sig", newline="") as handle:
            raw_records = list(csv.DictReader(handle))
        raw_records += [yaml.safe_load(p.read_text(encoding="utf-8-sig")) for p in (self.root / "DATA/raw/canonical/power_experiment_records/transmission").rglob("*.yaml")]
        for raw in raw_records:
            if raw.get("measurement_scope") == "VOLTAGE_ONLY":
                continue
            labels = raw["module_ids"].split(",")
            values = []
            for label in labels:
                col = "0" if len(labels) == 1 else label.removeprefix("Module")
                value = raw.get("I_module" + col + "_avg_mA")
                if value is None or value == "":
                    self.assertEqual(len(labels), 1)
                    value = raw["I_source_avg_mA"]
                values.append(Decimal(str(value)))
            expected = sum(values)
            run = self.runs[raw["run_id"]]
            self.assertAlmostEqual(float(expected), run["I_sum_mA"], places=10, msg=raw["run_id"])
            self.assertAlmostEqual(float(expected * Decimal(str(raw["V_source_avg_V"]))), run["P_output_est_mW"], places=9)

    def test_n1_column_zero_is_selected_label_and_legacy_source_fallback(self):
        m1 = self.branches[("PS01_N1_F200_MAX_M1_USB_RX_R1", "M1")]
        self.assertEqual(m1["source_column"], 0)
        self.assertAlmostEqual(m1["I_recorded_mA"], 20.110)
        self.assertAlmostEqual(m1["V_recorded_V"], 3.250)
        self.assertNotIn((m1["run_id"], "M0"), self.branches)
        old = self.branches[("PS01_N1_F200_ZERO_M1_R1", "M1")]
        self.assertAlmostEqual(old["I_recorded_mA"], 8.119)
        self.assertIn("fallback", old["current_source_field"])
        m3 = self.branches[("PS01_N2_F200_ZERO_M2-M3_USB_RX_R1", "M3")]
        self.assertEqual(m3["source_column"], 3)

    def test_prediction_and_load_headlines_use_independent_solo_runs(self):
        predicted = {(r["load"], r["combo"]): r for r in self.summary["predictions"] if r["state"] == analysis.CONTINUOUS}
        self.assertEqual(len(predicted), 10)
        expected_zero = {"M0+M1": (36.540, 36.016), "M2+M3": (36.760, 36.534),
                         "M0+M1+M2": (54.900, 54.481), "M1+M2+M3": (55.140, 54.851),
                         "M0+M1+M2+M3": (73.300, 72.513)}
        for combo, (prediction, observed) in expected_zero.items():
            result = predicted[("ZERO", combo)]
            self.assertAlmostEqual(result["predicted_I_mA"], prediction, places=9)
            self.assertAlmostEqual(result["observed_I_mA"], observed, places=9)
            self.assertAlmostEqual(result["residual_percent"], (observed-prediction)/prediction*100, places=9)
            self.assertTrue(all(self.runs[rid]["N"] == 1 for rid in result["reference_run_ids"]))
        self.assertTrue(all(p["comparability"] == "conditional_load_equivalence" for (load, _), p in predicted.items() if load == "MAX"))
        pairs = [p for p in self.summary["load_pairs"] if p["state"] == analysis.CONTINUOUS]
        self.assertEqual(len(pairs), 9)
        self.assertTrue(all(p["delta_I_mA"] > 0 for p in pairs))
        n4 = next(p for p in pairs if p["N"] == 4)
        self.assertAlmostEqual(n4["delta_I_mA"], 6.207, places=10)
        self.assertAlmostEqual(n4["P_loaded_est_mW"], 257.65056, places=8)

    def test_absent_evidence_is_not_converted_to_sd_or_verified_zero(self):
        new = [r for r in self.runs.values() if r["state"] == analysis.CONTINUOUS]
        for r in new:
            self.assertEqual(r["n_repeat"], 1)
            self.assertIsNone(r["SD_repeat_mA"])
            self.assertFalse(r["fault_zero_observation_verified"])
            self.assertFalse(r["duration_verified"])
            self.assertFalse(r["temperature_equilibrium_verified"])
            self.assertIsNone(r["date_recorded"])
            self.assertIsNone(r["operator_recorded"])
            self.assertIn("not_verified_time_average", r["reading_semantics"])
            if r["load"] == "MAX":
                self.assertIsNone(r["load_area_recorded_mm2"])
                self.assertFalse(r["load_equivalence_verified"])
        for g in self.summary["groups"]:
            self.assertIsNone(g["SD_repeat_mA"])
        for load in ("ZERO", "MAX"):
            groups = [g for g in self.summary["groups"] if g["state"] == analysis.CONTINUOUS and g["load"] == load]
            self.assertEqual([g["n_combinations"] for g in groups], [4, 2, 2, 1])
            self.assertIsNotNone(groups[0]["SD_between_combinations_mA"])
            self.assertIsNone(groups[-1]["SD_between_combinations_mA"])

    def test_rounding_and_voltage_qc_retain_measured_fields(self):
        rounding = [q for q in self.summary["qc_issues"] if q["code"] == "CURRENT_REPRESENTATIVE_OUTSIDE_MINMAX" and q["state"] == analysis.CONTINUOUS]
        self.assertEqual(len(rounding), 5)
        m1 = self.branches[("PS01_N4_F200_ZERO_M0-M1-M2-M3_USB_RX_R1", "M1")]
        self.assertEqual(m1["I_recorded_mA"], 18.302)
        self.assertEqual(m1["I_max_recorded_mA"], 18.30)
        lowest = min(b["V_min_recorded_V"] for b in self.branches.values() if b["state"] == analysis.CONTINUOUS)
        self.assertEqual(lowest, 3.224)
        self.assertAlmostEqual((lowest - 3.135)*1000, 89)

    def test_descriptive_fits_equal_weight_four_module_counts(self):
        fits = [f for f in self.summary["descriptive_fits"] if f["state"] == analysis.CONTINUOUS]
        self.assertEqual(len(fits), 4)
        current_zero = next(f for f in fits if f["load"] == "ZERO" and f["metric"] == "I_sum_mA")
        self.assertAlmostEqual(current_zero["slope_per_module"], 18.0955, places=9)
        self.assertAlmostEqual(current_zero["intercept"], 0.206, places=9)
        self.assertEqual([p["N"] for p in current_zero["points"]], [1, 2, 3, 4])
        self.assertIn("descriptive only", current_zero["inference"])

    def test_legacy_analysis_directory_is_protected(self):
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            analysis.analyze(self.root, self.root / "DATA/analysis")

    def test_voltage_only_supplements_are_explicitly_excluded_without_fabrication(self):
        paths = self.summary["provenance"]["excluded_voltage_only_yaml_paths"]
        self.assertEqual(len(paths), 7)
        for path in paths:
            record = yaml.safe_load((self.root / path).read_text(encoding="utf-8"))
            self.assertNotIn(record["run_id"], self.runs)
            self.assertEqual(record["measurement_scope"], "VOLTAGE_ONLY")
            measured = record.get("measured_module_ids", record["module_ids"]).split(",")
            for label in record["module_ids"].split(","):
                column = label.removeprefix("Module")
                self.assertIsNone(record.get(f"I_module{column}_avg_mA"))
                if label in measured:
                    self.assertIsNotNone(record[f"V_module{column}_avg_V"])
                else:
                    self.assertIsNone(record[f"V_module{column}_avg_V"])

    def test_historical_reproduction_carries_subsequent_supply_fault_disclosure(self):
        events = self.summary["quality_events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "USER_CONFIRMED_SUPPLY_WIRE_OR_CONNECTOR_CONTACT_FAULT")
        self.assertIn(events[0]["affected_run_id"], self.runs)
        self.assertEqual(events[0]["replacement_M0_voltage_V"]["main"], 3.241)
        self.assertFalse(events[0]["drop_recalculation_allowed_with_old_source"])
        self.assertEqual(events[0]["affected_voltage_points"], ["M0"])
        self.assertEqual(events[0]["confirmed_unaffected_voltage_points"], ["SOURCE", "M1", "M2"])
        self.assertTrue(events[0]["retained_voltage_values_user_confirmed_unchanged"])
        self.assertFalse(events[0]["accepted_voltage_configuration"]["counts_as_additional_independent_run"])

    def test_unmarked_missing_current_still_fails(self):
        rows, _ = analysis.load_sources(self.root)
        raw = dict(next(r for r in rows if r["run_id"] == "PS01_N2_F200_ZERO_M0-M1_USB_RX_R1"))
        raw["I_module0_avg_mA"] = None
        with self.assertRaisesRegex(ValueError, "Missing current"):
            analysis.derive(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
