"""Independent checks of module identity, event scope, provenance, and coverage."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
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
        with (cls.output / "accepted_configuration_voltage.csv").open(newline="", encoding="utf-8") as handle:
            cls.accepted = list(csv.DictReader(handle))
        cls.points = {(row["run_id"], row["module_id"]): row for row in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_inputs_and_points_present(self):
        self.assertEqual(self.summary["counts"], {
            "input_runs": 25, "module_voltage_points": 51,
            "known_supply_contact_fault_runs": 1, "excluded_fault_condition_module_points": 1,
            "no_reported_supply_contact_fault_module_points": 50,
            "accepted_complete_voltage_configurations": 24,
            "user_confirmed_pointwise_corrected_configurations": 1,
            "additional_independent_runs_from_correction": 0,
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

    def test_supply_fault_excludes_only_original_M0_and_retains_other_points(self):
        affected = self.summary["quality_event"]["affected_run_id"]
        points = [row for row in self.rows if row["run_id"] == affected]
        self.assertEqual({row["module_id"] for row in points}, {"M0", "M1", "M2"})
        self.assertEqual([row["module_id"] for row in points if row["quality_class"] == review.FAULT], ["M0"])
        self.assertEqual(self.points[(affected, "M0")]["included_no_reported_supply_contact_fault"], "False")
        for module, value in (("M1", "3.250"), ("M2", "3.246")):
            point = self.points[(affected, module)]
            self.assertEqual(point["quality_class"], review.UNREPORTED)
            self.assertEqual(point["included_no_reported_supply_contact_fault"], "True")
            self.assertEqual(point["module_main_V"], value)
            self.assertEqual(point["source_main_V"], "3.276")
            self.assertEqual(point["source_quality_class"], review.UNREPORTED)
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
        self.assertEqual(self.summary["summaries"][review.UNREPORTED]["ALL"]["module_points_with_same_record_drop"], 49)

    def test_decimal_drops_use_only_each_record(self):
        for row in self.rows:
            if row["source_main_V"]:
                expected = (Decimal(row["source_main_V"]) - Decimal(row["module_main_V"])) * 1000
                self.assertEqual(Decimal(row["source_to_module_drop_mV"]), expected)
            else:
                self.assertEqual(row["source_to_module_drop_mV"], "")

    def test_coverage_distinguishes_full_partial_and_fault(self):
        zero = self.summary["coverage"]["ZERO"]
        self.assertEqual(zero["ALL"], {"nominal_subsets": 15, "complete_subsets": 15,
                                       "partial_subsets": 0, "missing_subsets": 0,
                                       "same_record_complete_subsets": 14,
                                       "user_confirmed_pointwise_corrected_subsets": 1,
                                       "known_supply_contact_fault_run_count": 1})
        self.assertEqual([zero[str(count)]["complete_subsets"] for count in range(1, 5)], [4, 6, 4, 1])
        self.assertEqual(zero["3"]["same_record_complete_subsets"], 3)
        self.assertEqual(zero["3"]["partial_subsets"], 0)
        affected = self.coverage[("ZERO", "M0+M1+M2")]
        self.assertEqual(affected["historical_complete_voltage_record_count"], "1")
        self.assertEqual(affected["no_reported_supply_contact_fault_complete_record_count"], "0")
        self.assertEqual(affected["no_reported_supply_contact_fault_partial_record_count"], "2")
        self.assertEqual(affected["accepted_configuration_coverage"], "COMPLETE")
        self.assertEqual(affected["accepted_configuration_kind"], review.CORRECTION)
        self.assertEqual(affected["historical_run_count"], "2")
        self.assertEqual(affected["repair_records_counted_as_same_condition_repeats"], "0")
        self.assertEqual(self.summary["coverage"]["MAX"]["ALL"]["missing_subsets"], 6)

    def test_corrected_configuration_preserves_point_provenance_and_drop_semantics(self):
        event = self.summary["quality_event"]
        corrected = {row["point_id"]: row for row in self.accepted if row["configuration_id"] == "ZERO:M0+M1+M2"}
        self.assertEqual(set(corrected), {"SOURCE", "M0", "M1", "M2"})
        expected_values = {"SOURCE": "3.276", "M0": "3.241", "M1": "3.250", "M2": "3.246"}
        for point, row in corrected.items():
            self.assertEqual(row["main_V"], expected_values[point])
            self.assertEqual(row["configuration_kind"], review.CORRECTION)
            self.assertEqual(row["same_record_complete"], "False")
            self.assertEqual(row["counts_as_additional_independent_run"], "False")
            self.assertEqual(row["simultaneous_new_acquisition_claimed"], "False")
            expected_run = event["replacement_run_id"] if point == "M0" else event["affected_run_id"]
            self.assertEqual(row["point_source_run_id"], expected_run)
            self.assertEqual(review.sha(review.ROOT / row["point_source_path"]), row["point_source_sha256"])
            self.assertIn("_avg_V", row["point_source_fields"])
        M0 = corrected["M0"]
        self.assertEqual(Decimal(M0["source_to_point_drop_mV"]), Decimal("35"))
        self.assertEqual(M0["drop_uses_same_record"], "False")
        self.assertEqual(M0["drop_basis"], "user_confirmed_unchanged_source_minus_retested_module_estimate_not_same_record")
        self.assertTrue(M0["photo_paths"].endswith("/M0_new.jpg"))
        self.assertEqual(review.sha(review.ROOT / M0["photo_paths"]), M0["photo_sha256"])
        for point in ("SOURCE", "M1", "M2"):
            self.assertEqual(corrected[point]["point_acceptance_basis"], "user_confirmed_unchanged")
            self.assertEqual(corrected[point]["photo_mapping_basis"], "not_mapped_in_original_record")
        self.assertEqual(corrected["M1"]["drop_uses_same_record"], "True")
        self.assertEqual(corrected["M2"]["drop_uses_same_record"], "True")
        self.assertEqual(len(self.summary["runs"]), 25)
        self.assertEqual(len(self.accepted), 74)

    def test_correction_requires_the_explicit_scope_and_same_condition_mapping(self):
        import copy
        event = copy.deepcopy(self.summary["quality_event"])
        event["accepted_voltage_configuration"]["point_source_run_ids"]["M1"] = event["replacement_run_id"]
        with self.assertRaisesRegex(ValueError, "provenance conflicts"):
            review.build_accepted_configurations(review.ROOT, self.summary["runs"], [], {}, event)

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
