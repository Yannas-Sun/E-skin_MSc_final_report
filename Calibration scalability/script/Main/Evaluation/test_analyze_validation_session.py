"""Automatic validation analysis tests. All captures are synthetic fixtures."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import analyze_validation_session as pipeline
from test_new_protocol_evaluation import capture


class ValidationSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.evaluation_dir = self.root / "DATA/module_1/FSR1/evaluation/view_distribution"
        self.template = capture(self.root / "models", upper=4000)
        self.template.update(status="COMPLETE", source_frames={"count": 200, "target_count": 200})
        self.template["source_models"].update(
            normalized_calibration_sha256="a" * 64, fitted_response_sha256="b" * 64)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, data=None):
        path = self.evaluation_dir / name / "view_distribution_capture.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.template if data is None else data), encoding="utf-8")
        return path.resolve()

    def changed(self, **changes):
        data = copy.deepcopy(self.template)
        data.update(changes)
        return data

    @staticmethod
    def hashes(paths):
        return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}

    def test_plan_selects_same_condition_across_loads_and_model_copy_paths(self):
        anchor = self.save("anchor")
        repeat = self.save("repeat")
        zero_data = self.changed(actual_load={"value": 0, "unit": "g"})
        zero = self.save("zero", zero_data)
        copied = self.changed()
        copied["source_models"]["normalized_calibration"] = str(self.root / "copies/endpoints.json")
        copied["source_models"]["fitted_response"] = str(self.root / "copies/fit.json")
        copied["calibration_snapshot"]["source_path"] = copied["source_models"]["normalized_calibration"]
        copied_path = self.save("same_models_copied", copied)
        before = self.hashes([anchor, repeat, zero, copied_path])

        plan = pipeline.build_plan(anchor)

        self.assertEqual(Path(plan["anchor"]), anchor)
        self.assertEqual(Path(plan["evaluation_dir"]), self.evaluation_dir.parent.resolve())
        self.assertEqual(set(map(Path, plan["capture_paths"])), {anchor, repeat, zero, copied_path})
        self.assertEqual(plan["source_sha256"], before)
        self.assertEqual(plan["condition"]["load_range_g"], [0, 4000])
        self.assertEqual(plan["condition"]["module_id"], 1)
        self.assertEqual(plan["condition"]["fsr"], "FSR1")
        self.assertEqual(plan["condition"]["gamma"], 2)
        self.assertEqual(len(plan["condition_id"]), 16)
        self.assertEqual(plan["excluded"], [])
        self.assertEqual(self.hashes([anchor, repeat, zero, copied_path]), before)
        self.assertFalse((anchor.parent / "analysis").exists())

    def test_plan_reports_foreign_conditions_legacy_incomplete_and_invalid(self):
        anchor = self.save("anchor")
        excluded = []
        for field, value in (("normalized_gamma", 3),
                             ("normalized_calibration_sha256", "c" * 64),
                             ("fitted_response_sha256", "c" * 64)):
            data = self.changed()
            data["source_models"][field] = value
            excluded.append(self.save(field, data))
        other_range = capture(self.root / "models", upper=4500)
        other_range.update(status="COMPLETE", source_frames={"count": 200, "target_count": 200})
        excluded.append(self.save("different_range", other_range))
        excluded.append(self.save("different_module", self.changed(module_id=2)))
        excluded.append(self.save("different_layer", self.changed(fsr="FSR2")))
        excluded.append(self.save("partial", self.changed(status="INCOMPLETE",
                                                          source_frames={"count": 37, "target_count": 200})))
        legacy = self.changed(version=2)
        for key in ("protocol_id", "load_range_g", "evaluation_policy"):
            legacy.pop(key)
        excluded.append(self.save("legacy", legacy))
        invalid = self.save("invalid_json")
        invalid.write_text("{broken")
        excluded.append(invalid)

        plan = pipeline.build_plan(anchor)

        self.assertEqual(list(map(Path, plan["capture_paths"])), [anchor])
        self.assertEqual({Path(item["source"]) for item in plan["excluded"]}, set(excluded))
        self.assertTrue(all(isinstance(item["reason"], str) and item["reason"]
                            for item in plan["excluded"]))

    def test_invalid_anchor_raises_before_creating_outputs(self):
        cases = {
            "partial": self.changed(status="INCOMPLETE", source_frames={"count": 37}),
            "false_complete": self.changed(source_frames={"count": 199, "target_count": 200}),
            "outside_range": self.changed(actual_load={"value": 4001, "unit": "g"}),
            "negative_load": self.changed(actual_load={"value": -1, "unit": "g"}),
            "legacy": self.changed(version=2, protocol_id="old_protocol"),
        }
        no_cells = self.changed()
        no_cells["views"]["FIT_PRESS"]["values"] = [[None] * 16 for _ in range(16)]
        cases["zero_common_cells"] = no_cells
        for name, data in cases.items():
            anchor = self.save(name, data)
            with self.subTest(name=name):
                with self.assertRaises((ValueError, RuntimeError)):
                    pipeline.build_plan(anchor)
                with self.assertRaises((ValueError, RuntimeError)):
                    pipeline.run(anchor)
                self.assertFalse((anchor.parent / "analysis").exists())

    def test_run_passes_explicit_selected_paths_and_keeps_sources_unchanged(self):
        anchor, repeat = self.save("anchor"), self.save("repeat")
        foreign = self.changed()
        foreign["source_models"]["normalized_gamma"] = 4
        other = self.save("foreign_gamma", foreign)
        before = self.hashes([anchor, repeat, other])

        def fake_capture(path, output):
            output = Path(output)
            output.mkdir(parents=True, exist_ok=True)
            summary = output / "summary.json"
            summary.write_text(json.dumps({"source": str(path)}))
            return {"summary": summary}

        def fake_batch(evaluation_dir, output, *, kind, capture_paths, include_shared_lut=False):
            output = Path(output)
            output.mkdir(parents=True, exist_ok=True)
            summary = output / "summary.json"
            summary.write_text(json.dumps({"kind": kind, "count": len(capture_paths)}))
            return {"summary": summary}

        with patch.object(pipeline, "analyze_capture", side_effect=fake_capture) as single, \
             patch.object(pipeline, "analyze_batch", side_effect=fake_batch) as batch:
            result = pipeline.run(anchor)

        self.assertEqual(single.call_count, 1)
        self.assertEqual(Path(single.call_args.args[0]), anchor)
        self.assertEqual(batch.call_count, 2)
        self.assertEqual({call.kwargs["kind"] for call in batch.call_args_list},
                         {"accuracy", "dispersion"})
        for call in batch.call_args_list:
            self.assertEqual(Path(call.args[0]), self.evaluation_dir.parent.resolve())
            self.assertEqual(set(map(Path, call.kwargs["capture_paths"])), {anchor, repeat})
            if call.kwargs["kind"] == "accuracy":
                self.assertIs(call.kwargs["include_shared_lut"], True)
            else:
                self.assertNotIn("include_shared_lut", call.kwargs)
        output = Path(result["output_dir"])
        self.assertEqual(output.parent, anchor.parent / "analysis")
        manifest = Path(result["manifest"])
        self.assertEqual(manifest, output / "analysis_manifest.json")
        self.assertTrue(manifest.is_file())
        recorded = json.loads(manifest.read_text())
        self.assertEqual(set(map(Path, recorded["source_captures"])), {anchor, repeat})
        self.assertEqual(recorded["source_sha256"], {str(p): before[str(p)] for p in (anchor, repeat)})
        self.assertEqual(self.hashes([anchor, repeat, other]), before)
        self.assertEqual(set(result["outputs"]), {"capture", "error", "dispersion"})
        latest = json.loads(Path(result["latest_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(latest["condition_id"], result["condition_id"])
        self.assertEqual(latest["snapshot_manifest"], result["manifest"])
        for section in ("capture", "error", "dispersion"):
            published = Path(result["published_outputs"][section]["summary"])
            original = Path(result["outputs"][section]["summary"])
            self.assertEqual(published.read_bytes(), original.read_bytes())
            expected = anchor.parent if section == "capture" else self.evaluation_dir.parent / "analysis" / section
            self.assertEqual(published.parent, expected)

    def test_real_batch_counts_repeated_loads_with_figure_writes_mocked(self):
        anchor = self.save("repeat_1")
        self.save("repeat_2")
        low = self.changed(actual_load={"value": 1000, "unit": "g"})
        self.save("other_load", low)
        self.save("partial", self.changed(status="INCOMPLETE", source_frames={"count": 23}))
        with patch("matplotlib.figure.Figure.savefig"):
            result = pipeline.run(anchor, publish=False, include_shared_lut=False)
        for name in ("error", "dispersion"):
            summary = json.loads(Path(result["outputs"][name]["summary"]).read_text())
            groups = {group["actual_load_g"]: group for group in summary["groups"]}
            self.assertEqual(groups[3200]["methods"]["FIT_PRESS"]["mean"]["n"], 2)
            self.assertEqual(groups[1000]["methods"]["FIT_PRESS"]["mean"]["n"], 1)
        self.assertEqual(len(result["excluded"]), 1)

    def test_source_mutation_during_analysis_is_detected(self):
        anchor = self.save("anchor")
        original = anchor.read_bytes()
        def mutate_capture(path, output):
            anchor.write_bytes(original + b"\n")
            return {}
        with patch.object(pipeline, "analyze_capture", side_effect=mutate_capture), \
             patch.object(pipeline, "analyze_batch", return_value={}):
            with self.assertRaises((ValueError, RuntimeError)):
                pipeline.run(anchor)
        self.assertFalse(list((anchor.parent / "analysis").glob("*/analysis_manifest.json")))

    def test_missing_shared_model_fails_without_success_or_publication(self):
        anchor = self.save("anchor")
        before = self.hashes([anchor])
        latest = self.evaluation_dir.parent / "analysis/latest_analysis.json"
        latest.parent.mkdir(parents=True)
        latest.write_text('{"previous_success": true}', encoding="utf-8")
        previous = latest.read_bytes()
        with patch.object(pipeline, "analyze_capture", return_value={}), \
             patch.object(pipeline, "analyze_batch", side_effect=ValueError("shared mean LUT model unavailable")) as batch, \
             patch.object(pipeline, "publish_outputs") as publish:
            with self.assertRaisesRegex(ValueError, "shared mean LUT"):
                pipeline.run(anchor)
        self.assertEqual(batch.call_count, 1)
        self.assertEqual(batch.call_args.kwargs["kind"], "accuracy")
        self.assertIs(batch.call_args.kwargs["include_shared_lut"], True)
        publish.assert_not_called()
        self.assertEqual(latest.read_bytes(), previous)
        self.assertEqual(self.hashes([anchor]), before)
        self.assertFalse(list((anchor.parent / "analysis").glob("*/analysis_manifest.json")))

    def test_cli_shared_curve_default_and_explicit_legacy_compatibility(self):
        anchor = self.save("anchor")
        for flags, expected in (([], True), (["--no-shared-lut"], False)):
            with self.subTest(flags=flags), \
                 patch.object(sys, "argv", ["analyze_validation_session.py", "--capture", str(anchor), *flags]), \
                 patch.object(pipeline, "run", return_value={}) as run, redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.main(), 0)
            self.assertEqual(Path(run.call_args.args[0]), anchor)
            self.assertIs(run.call_args.kwargs["include_shared_lut"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
