"""Refresh wrapper checks without hardware, model rebuilding, or real plotting."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import refresh_load_analysis as refresh
from test_new_protocol_evaluation import capture


class RefreshTests(unittest.TestCase):
    def test_empty_data_creates_no_output_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "DATA").mkdir()
            before = sorted(root.rglob("*"))
            output = io.StringIO()
            with patch.object(refresh, "ROOT", root), redirect_stdout(output):
                self.assertEqual(refresh.run(), [])
            self.assertIn("No new captures", output.getvalue())
            self.assertEqual(sorted(root.rglob("*")), before)

    def test_legacy_or_mixed_models_refused_before_any_batch_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "DATA/module_1/FSR1"
            other = root / "DATA/module_3/FSR1"
            data = capture(root, upper=4500)
            data["source_models"]["normalized_calibration_sha256"] = "a" * 64
            def save(base, run, payload):
                path = base / "evaluation/view_distribution" / run / "view_distribution_capture.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
                return path
            save(first, "valid", data)
            legacy = copy.deepcopy(data)
            legacy.update(version=2, module_id=3)
            for key in ("protocol_id", "load_range_g", "evaluation_policy"):
                legacy.pop(key)
            legacy_path = save(other, "old", legacy)
            with patch.object(refresh, "ROOT", root), patch.object(refresh, "analyze_capture") as single, patch.object(refresh, "analyze_batch") as batch:
                with self.assertRaisesRegex(ValueError, "legacy captures"):
                    refresh.run()
                single.assert_not_called()
                batch.assert_not_called()
            self.assertFalse((first / "evaluation/analysis").exists())
            legacy_path.unlink()
            mixed = copy.deepcopy(data)
            mixed["source_models"]["normalized_calibration_sha256"] = "b" * 64
            save(first, "different_model", mixed)
            with patch.object(refresh, "analyze_capture") as single, patch.object(refresh, "analyze_batch") as batch:
                with self.assertRaisesRegex(ValueError, "Mixed calibration models or gamma"):
                    refresh.run(first)
                single.assert_not_called()
                batch.assert_not_called()
            self.assertFalse((first / "evaluation/analysis").exists())


if __name__ == "__main__":
    unittest.main()
