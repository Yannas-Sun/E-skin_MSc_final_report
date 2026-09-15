import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / "pc" / "recording_plots.py"
spec = importlib.util.spec_from_file_location("recording_plots", MODULE)
plots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plots)


def row(t, length=124, crc=True, parse=True, alg="DELTA,NONE,NONE,NONE", received=None):
    return {"elapsed_s": t, "received_bytes": length if received is None else received,
            "declared_length": length, "outer_crc_ok": crc,
            "parse_ok": parse, "algorithms": alg}


def fixture(folder, rows, duration=2.5, completed=True, targets=None):
    folder = Path(folder)
    valid = [r for r in rows if r["outer_crc_ok"] and r["received_bytes"] == r["declared_length"]]
    size = sum(r["received_bytes"] for r in valid)
    main = {"start_elapsed_s": 0, "end_elapsed_s": duration,
            "actual_duration_seconds": duration, "status": "PASS", "review_reasons": [],
            "valid_outer_packet_bytes": size,
            "Lmean_valid_packet_B": size / len(valid) if valid else None,
            "packet_completion_Mbit_per_s": size * 8 / duration / 1e6 if duration else None,
            "counts": {"valid_outer_packets": len(valid)}}
    summary = {"schema_version": 2, "run_id": "TEST", "duration_seconds": duration,
               "settle_seconds": 10, "requested_duration_seconds": 40,
               "completed_requested_duration": completed,
               "metadata": {"target_modules": [0] if targets is None else targets,
                            "M": 4, "target_mode": "DELTA"},
               "scopes": {"main": main, "full_run": {"status": "CHECK REQUIRED", "review_reasons": ["initial_delta_prefix"]}}}
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with (folder / "packet_log.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row(0)))
        writer.writeheader()
        writer.writerows(rows)
    for name in ("raw.bin", "module_log.csv", "events.jsonl", "run_metadata.json"):
        (folder / name).write_bytes(b"original sentinel")
    return folder


class RecordingPlotsTests(unittest.TestCase):
    def test_import_does_not_import_matplotlib_or_select_backend(self):
        code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('p',sys.argv[1]); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "assert not any(n=='matplotlib' or n.startswith('matplotlib.') for n in sys.modules)")
        subprocess.run([sys.executable, "-B", "-c", code, str(MODULE)], check=True)

    def test_repeated_times_empty_bins_and_partial_bin(self):
        packets = [{"time_s": .2, "bytes": 100}, {"time_s": .2, "bytes": 200},
                   {"time_s": 2.4, "bytes": 300}, {"time_s": 2.5, "bytes": 100}]
        bins = plots.bin_packet_bytes(packets, 2.5)
        self.assertEqual([b["bytes"] for b in bins], [300, 0, 400])
        self.assertEqual([b["width_s"] for b in bins], [1, 1, .5])
        self.assertAlmostEqual(bins[-1]["Mbit_per_s"], .0064)
        self.assertEqual(sum(b["packets"] for b in bins), 4)

    def test_ESKF_and_inner_errors_count_but_bad_outer_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            run = fixture(temp, [row(.1), row(.2, 1084, alg="DELTA_SYNC,NONE,NONE,NONE"),
                                 row(.3, 140, parse=False), row(.4, 500, crc=False),
                                 row(.5, 600, received=200)])
            data = plots.load_plot_data(run)
            self.assertEqual(data["counts"]["plotted_outer_valid_bytes"], 1348)
            self.assertEqual(data["counts"]["invalid_candidates"], 2)
            self.assertEqual(data["counts"]["outer_valid_parse_not_ok"], 1)
            self.assertAlmostEqual(data["main_calculated"]["Lmean_valid_packet_B"], 1348 / 3)
            self.assertEqual(sum(b["bytes"] for b in data["bins"]), 1348)
            self.assertEqual(data["valid"][1]["algorithms"][0], "DELTA_SYNC")
            self.assertEqual(data["errors"], [])

    def test_reference_uses_targets_not_observed(self):
        with tempfile.TemporaryDirectory() as temp:
            data = plots.load_plot_data(fixture(temp, [row(.1)], targets=[0, 1, 2, 3]))
            self.assertEqual(len(data["target_modules"]), 4)
            self.assertEqual(data["wrapper_bytes"], 40)

    def test_invalid_time_and_summary_disagreement_are_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            data = plots.load_plot_data(fixture(temp, [row(7)]))
            self.assertEqual(data["counts"]["invalid_completion_time"], 1)
            self.assertTrue(any("summary/CSV mismatch" in e for e in data["errors"]))

    def test_cli_render_keeps_all_six_sources_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            run = fixture(temp, [row(.1), row(2.4, 1084, alg="DELTA_SYNC,NONE,NONE,NONE")], completed=False)
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir()}
            result = subprocess.run([sys.executable, "-B", str(MODULE), str(run)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            status = json.loads((run / "plot_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["recording_status"]["full_run"], "CHECK REQUIRED")
            self.assertTrue(any("stopped early" in s for s in status["warnings"]))
            self.assertTrue(all(s["unchanged"] for s in status["sources"].values()))
            for name, digest in hashes.items():
                self.assertEqual(hashlib.sha256((run / name).read_bytes()).hexdigest(), digest)
            for name in plots.PLOT_NAMES:
                self.assertTrue((run / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_empty_zero_duration_capture_generates_explanatory_plots(self):
        with tempfile.TemporaryDirectory() as temp:
            run = fixture(temp, [], duration=0, completed=False)
            result = subprocess.run([sys.executable, "-B", str(MODULE), str(run)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            status = json.loads((run / "plot_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["bins"], [])
            self.assertEqual(status["counts"]["plotted_outer_valid_packets"], 0)
            self.assertEqual(len(status["outputs"]), 2)

    def test_invalid_schema_writes_error_status(self):
        with tempfile.TemporaryDirectory() as temp:
            run = fixture(temp, [])
            (run / "summary.json").write_text('{"schema_version": 1}', encoding="utf-8")
            status = plots.render_run(run)
            self.assertEqual(status["status"], "ERROR")
            self.assertTrue((run / "plot_status.json").is_file())


if __name__ == "__main__":
    unittest.main()
