"""Independent checks of module identity, event scope, provenance, and coverage."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import summarize_voltage_review as review


class VoltageReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="voltage_review_test_")
        cls.output = Path(cls.temp.name) / "derived"
        cls.summary = review.review(output=cls.output)
        with (cls.output / "module_voltages.csv").open(newline="", encoding="utf-8") as handle:
            cls.rows = list(csv.DictReader(handle))
        with (cls.output / "coverage.csv").open(newline="", encoding="utf-8") as handle:
            cls.coverage = {(row["load"], row["combo"]): row for row in csv.DictReader(handle)}
        cls.points = {(row["run_id"], row["module_id"]): row for row in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_inputs_and_points_present(self):
        self.assertEqual(self.summary["counts"], {
            "input_runs": 25, "module_voltage_points": 51,
            "known_supply_contact_fault_runs": 1, "excluded_fault_condition_module_points": 3,
            "no_reported_supply_contact_fault_module_points": 48,
        })
        self.assertEqual(len(self.summary["provenance"]["sources"]), 26)

    def test_single_module_zero_column_maps_to_physical_module(self):
        run_id = "PS01_N1_F200_ZERO_M2_USB_RX_R1"
        row = self.points[(run_id, "M2")]
        self.assertEqual(row["source_column"], "0")
        self.assertEqual(Decimal(row["module_main_V"]), Decimal("3.249"))
        self.assertNotIn((run_id, "M0"), self.points)
        row = self.points[("PS01_N3_F200_ZERO_M1-M2-M3_USB_RX_R1", "M3")]
        self.assertEqual(row["source_column"], "3")

    def test_supply_fault_excludes_entire_original_run_but_preserves_rows(self):
        affected = self.summary["quality_event"]["affected_run_id"]
        points = [row for row in self.rows if row["run_id"] == affected]
        self.assertEqual({row["module_id"] for row in points}, {"M0", "M1", "M2"})
        self.assertTrue(all(row["quality_class"] == review.FAULT for row in points))
        self.assertTrue(all(row["included_no_reported_supply_contact_fault"] == "False" for row in points))
        self.assertEqual(Decimal(self.points[(affected, "M0")]["module_main_V"]), Decimal("3.224"))
        self.assertEqual(Decimal(self.points[(affected, "M0")]["source_to_module_drop_mV"]), Decimal("52"))
        historical = self.summary["summaries"]["raw_historical_including_known_fault"]["ALL"]
        no_reported = self.summary["summaries"][review.UNREPORTED]["ALL"]
        self.assertEqual(historical["minimum_module_main_V"]["value"], "3.224")
        self.assertEqual(no_reported["minimum_module_main_V"]["value"], "3.231")
        self.assertEqual(self.summary["summaries"][review.UNREPORTED]["ZERO"]["minimum_module_main_V"]["value"], "3.234")

    def test_partial_repair_cannot_inherit_old_source_or_other_modules(self):
        repaired = self.summary["quality_event"]["replacement_run_id"]
        points = [row for row in self.rows if row["run_id"] == repaired]
        self.assertEqual(len(points), 1)
        point = points[0]
        self.assertEqual(point["module_id"], "M0")
        self.assertEqual(point["module_count"], "3")
        self.assertEqual(point["measured_module_count"], "1")
        self.assertEqual(point["source_main_V"], "")
        self.assertEqual(point["source_to_module_drop_mV"], "")
        self.assertEqual(point["complete_voltage_record"], "False")
        self.assertEqual(point["independent_repeat_of_original_condition"], "False")
        self.assertEqual(Decimal(point["module_main_V"]), Decimal("3.241"))
        self.assertEqual(self.summary["summaries"][review.UNREPORTED]["ALL"]["module_points_with_same_record_drop"], 47)

    def test_decimal_drops_use_only_each_record(self):
        for row in self.rows:
            if row["source_main_V"]:
                expected = (Decimal(row["source_main_V"]) - Decimal(row["module_main_V"])) * 1000
                self.assertEqual(Decimal(row["source_to_module_drop_mV"]), expected)
            else:
                self.assertEqual(row["source_to_module_drop_mV"], "")

    def test_coverage_distinguishes_full_partial_and_fault(self):
        zero = self.summary["coverage"]["ZERO"]
        self.assertEqual(zero["ALL"], {"nominal_subsets": 15, "complete_subsets": 14,
                                       "partial_subsets": 1, "missing_subsets": 0,
                                       "known_supply_contact_fault_run_count": 1})
        self.assertEqual(zero["2"]["complete_subsets"], 6)
        self.assertEqual(zero["3"]["complete_subsets"], 3)
        self.assertEqual(zero["3"]["partial_subsets"], 1)
        affected = self.coverage[("ZERO", "M0+M1+M2")]
        self.assertEqual(affected["historical_complete_voltage_record_count"], "1")
        self.assertEqual(affected["no_reported_supply_contact_fault_complete_record_count"], "0")
        self.assertEqual(affected["no_reported_supply_contact_fault_partial_record_count"], "1")
        self.assertEqual(affected["repair_records_counted_as_same_condition_repeats"], "0")
        self.assertEqual(self.summary["coverage"]["MAX"]["ALL"]["missing_subsets"], 6)

    def test_protected_input_hashes_revalidated(self):
        self.assertTrue(self.summary["provenance"]["source_files_verified_unchanged"])
        for source in self.summary["provenance"]["sources"]:
            self.assertEqual(review.sha(review.ROOT / source["path"]), source["sha256"])
        test_source = Path(self.temp.name) / "hash_guard_test.txt"
        test_source.write_text("original", encoding="utf-8")
        before = {test_source: review.sha(test_source)}
        test_source.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Protected input changed"):
            review.verify_unchanged(before)

    def test_frozen_or_raw_output_target_rejected(self):
        for target in ("DATA/analysis", "DATA/reference/analysis_v2_1", "DATA/raw/canonical/power_experiment_records"):
            with self.assertRaisesRegex(ValueError, "output must be"):
                review.review(output=review.ROOT / target)

    def test_json_round_trip(self):
        self.assertEqual(json.loads((self.output / "summary.json").read_text(encoding="utf-8")), self.summary)


if __name__ == "__main__":
    unittest.main()
