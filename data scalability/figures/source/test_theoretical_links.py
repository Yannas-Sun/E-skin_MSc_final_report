"""Verify figure 02 equations and existing exports without regenerating any files."""
import csv
import hashlib
import json
import math
import unittest

import generate_figures as model
from PIL import Image


class LinkTheoryTests(unittest.TestCase):
    def test_mean_delta_is_a_replacement_mixture(self):
        self.assertAlmostEqual(model.mean_delta_module_bytes(27, 0), 138)
        self.assertAlmostEqual(model.mean_delta_module_bytes(27, .005), 142.53)
        self.assertAlmostEqual(model.mean_delta_module_bytes(27, 1), 1044)
        # One ESKF plus two ordinary ESKD with K=20 and K=30: conditional mean K=25.
        self.assertAlmostEqual(model.mean_delta_module_bytes(25, 1/3), (1044+124+144)/3)
        for q in [0, .005, .05, 1]:
            self.assertAlmostEqual(model.mean_delta_module_bytes(480, q), 1044)
        for n in [1, 4, 50]:
            self.assertAlmostEqual(model.mean_delta_frame_bytes(n, 27, 0), model.delta_frame_bytes(n, 27))
            self.assertAlmostEqual(model.mean_delta_frame_bytes(n, 27, 1), model.full_frame_bytes(n))
            self.assertAlmostEqual(model.mean_delta_frame_bytes(n, 27, .005)-model.mean_host_spi_delta_round_bytes(n, 27, .005),
                                   model.round_overhead_bytes(model.minimum_configured_slots(n)))
        for k, q in [(-1, 0), (481, 0), (27, -.01), (27, 1.1), (math.nan, .1)]:
            with self.assertRaises(ValueError):
                model.mean_delta_module_bytes(k, q)

    def test_nominal_periodic_reference_is_frequency_dependent_and_finite(self):
        self.assertEqual(model.periodic_reference_q(0), 0)
        self.assertEqual(model.periodic_reference_q(.5), 1)
        self.assertEqual(model.periodic_reference_q(1), 1)
        self.assertAlmostEqual(model.periodic_reference_q(200), .005)
        self.assertAlmostEqual(model.periodic_reference_q(700), 1/700)
        # Explicit continuous-cycle approximation, not the ceil(1.1)=2 scan rule.
        self.assertAlmostEqual(model.periodic_reference_q(1.1), 1/1.1)
        self.assertEqual(model.theoretical_mbit(model.mean_delta_frame_bytes(4, 27, model.periodic_reference_q(0)), 0), 0)
        for f, period in [(-1, 1), (math.inf, 1), (200, 0)]:
            with self.assertRaises(ValueError):
                model.periodic_reference_q(f, period)

    def test_mean_spi_crossings_include_all_eskf(self):
        for rate, expected, integer in [(10, 43.85041745597418, 43), (40, 175.40166982389673, 175)]:
            n = model.mean_host_spi_crossing_modules(200, rate, 27, .005)
            self.assertAlmostEqual(n, expected)
            self.assertEqual(math.floor(n), integer)
            self.assertAlmostEqual(model.theoretical_mbit(model.mean_host_spi_delta_round_bytes(n, 27, .005), 200), rate)
            self.assertLessEqual(model.theoretical_mbit(model.mean_host_spi_delta_round_bytes(integer, 27, .005), 200), rate)
            self.assertGreater(model.theoretical_mbit(model.mean_host_spi_delta_round_bytes(integer+1, 27, .005), 200), rate)
            self.assertAlmostEqual(model.mean_host_spi_crossing_modules(200, rate, 27, 0),
                                   model.host_spi_crossing_modules(200, rate, 27))
        self.assertAlmostEqual(model.theoretical_mbit(model.mean_delta_frame_bytes(4, 27, .005), 200), .976192)
        self.assertAlmostEqual(model.theoretical_mbit(model.mean_host_spi_delta_round_bytes(4, 27, .005), 200), .912192)

    def test_usb_wrapper_depends_on_configured_m_not_active_n(self):
        self.assertEqual(model.round_overhead_bytes(4), 40)
        self.assertEqual(model.round_overhead_bytes(8), 56)
        for n in [1, 2, 4, 7]:
            self.assertEqual(model.full_frame_bytes(n, m=8) - 1044 * n, 56)
            self.assertEqual(model.delta_frame_bytes(n, 0, m=8) - 84 * n, 56)
        self.assertEqual(model.delta_frame_bytes(1, 0, m=4), 124)
        self.assertEqual(model.delta_frame_bytes(1, 0, m=8), 140)
        with self.assertRaises(ValueError):
            model.full_frame_bytes(5, m=4)

    def test_extrapolation_selects_minimum_configured_capacity_explicitly(self):
        for n, expected_m in [(1, 4), (4, 4), (5, 5), (100, 100), (500, 500)]:
            self.assertEqual(model.minimum_configured_slots(n), expected_m)
            self.assertEqual(model.full_frame_bytes(n), model.full_frame_bytes(n, m=expected_m))
        self.assertEqual(model.delta_frame_bytes(1, 0), 124)

    def test_four_module_200hz_anchors(self):
        self.assertAlmostEqual(model.theoretical_mbit(model.full_frame_bytes(4), 200), 6.7456)
        self.assertAlmostEqual(model.theoretical_mbit(model.delta_frame_bytes(4, 0), 200), 0.6016)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(4, 0), 200), 0.5376)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(4, 240), 200), 3.6096)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(4, 480), 200), 6.6816)

    def test_500_module_endpoints(self):
        self.assertAlmostEqual(model.theoretical_mbit(model.full_frame_bytes(500), 200), 838.4384)
        self.assertAlmostEqual(model.theoretical_mbit(model.delta_frame_bytes(500, 240), 200), 454.4384)
        self.assertAlmostEqual(model.theoretical_mbit(model.delta_frame_bytes(500, 0), 200), 70.4384)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(500, 0), 200), 67.2)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(500, 240), 200), 451.2)
        self.assertAlmostEqual(model.theoretical_mbit(model.host_spi_delta_round_bytes(500, 480), 200), 835.2)

    def test_usb_delta_adds_only_the_usb_wrapper(self):
        for n in [1, 4, 5, 100, 500]:
            self.assertEqual(model.delta_frame_bytes(n, 0) - model.host_spi_delta_round_bytes(n, 0),
                             model.round_overhead_bytes(model.minimum_configured_slots(n)))
            self.assertEqual(model.full_frame_bytes(n), model.delta_frame_bytes(n, 480))

    def test_usb_crossings_invert_the_usb_model(self):
        for payload in [84, 564, 1044]:
            for n in [1, 4, 5, 100, 500]:
                rate = model.theoretical_mbit(model.round_overhead_bytes(model.minimum_configured_slots(n)) + payload * n, 200)
                self.assertAlmostEqual(model.usb_crossing_modules(payload, 200, rate), n)
        self.assertAlmostEqual(model.usb_crossing_modules(1044, 200, 480), 286.23664122137404)
        for n in [1, 4, 8]:
            rate = model.theoretical_mbit(56 + 1044 * n, 200)
            self.assertAlmostEqual(model.usb_crossing_modules(1044, 200, rate, m=8), n)

    def test_spi_crossings_invert_selected_delta_payload(self):
        for rate in [10, 40]:
            for k in [0, 27, 240, 480]:
                n = model.host_spi_crossing_modules(200, rate, k)
                self.assertAlmostEqual(
                    model.theoretical_mbit(model.host_spi_delta_round_bytes(n, k), 200),
                    rate,
                )
        self.assertAlmostEqual(model.host_spi_crossing_modules(200, 10, 480), 5.98659003831418)
        self.assertAlmostEqual(model.host_spi_crossing_modules(200, 40, 480), 23.946360153256705)
        self.assertAlmostEqual(model.host_spi_crossing_modules(200, 10, 27), 45.289855072463766)
        self.assertAlmostEqual(model.host_spi_crossing_modules(200, 40, 27), 181.15942028985506)

    def test_host_spi_uses_only_delta_bytes(self):
        for n in [1, 4, 20, 30]:
            self.assertEqual(model.host_spi_delta_round_bytes(n, 480), 1044 * n)
            self.assertLess(model.host_spi_delta_round_bytes(n, 0), 1044 * n)
            self.assertLess(model.host_spi_delta_round_bytes(n, 240), 1044 * n)

    def read_csv(self, name):
        with (model.TABLE_DIR / name).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            return reader.fieldnames, list(reader)

    def test_usb_exports_have_no_spi_columns_and_match_formula(self):
        for name, expected_count, max_n, max_f in [
            ("02_usb_theoretical_3d.csv", 2900, 100, 700),
            ("02b_usb_theoretical_200hz.csv", 700, 700, 200),
        ]:
            fields, rows = self.read_csv(name)
            self.assertFalse(any("spi" in field.lower() for field in fields))
            self.assertEqual(len(rows), expected_count)
            self.assertEqual(max(int(row["N"]) for row in rows), max_n)
            self.assertEqual(max(int(row["frequency_Hz"]) for row in rows), max_f)
            for row in rows:
                n, f = int(row["N"]), int(row["frequency_Hz"])
                self.assertEqual(int(row["M_configured_slots"]), max(4, n))
                self.assertAlmostEqual(float(row["FULL_Mbit_s"]), model.theoretical_mbit(model.full_frame_bytes(n), f))
                for k in [0, 240, 480]:
                    self.assertAlmostEqual(float(row[f"DELTA_K{k}_Mbit_s"]),
                                           model.theoretical_mbit(model.mean_delta_frame_bytes(n, k, model.periodic_reference_q(f)), f))
                    self.assertAlmostEqual(float(row[f"DELTA_K{k}_no_ESKF_bound_Mbit_s"]),
                                           model.theoretical_mbit(model.delta_frame_bytes(n, k), f))
                self.assertAlmostEqual(float(row["q_ESKF_total"]), model.periodic_reference_q(f))

    def test_spi_exports_have_only_delta_columns_and_no_usb_columns(self):
        for name, expected_count, max_n in [
            ("02c_host_spi_theoretical_3d.csv", 290, 10),
            ("02d_host_spi_theoretical_200hz.csv", 30, 30),
        ]:
            fields, rows = self.read_csv(name)
            self.assertFalse(any("usb" in field.lower() for field in fields))
            self.assertEqual(len(rows), expected_count)
            self.assertEqual(max(int(row["N"]) for row in rows), max_n)
            for row in rows:
                n, f = int(row["N"]), int(row["frequency_Hz"])
                for k in [0, 240, 480]:
                    self.assertAlmostEqual(float(row[f"DELTA_K{k}_SPI_Mbit_s"]),
                                           model.theoretical_mbit(model.mean_host_spi_delta_round_bytes(n, k, model.periodic_reference_q(f)), f))
                    self.assertAlmostEqual(float(row[f"DELTA_K{k}_no_ESKF_bound_SPI_Mbit_s"]),
                                           8 * (84 + 2 * k) * n * f / 1e6)
                self.assertAlmostEqual(float(row["q_ESKF_total"]), model.periodic_reference_q(f))

    def test_crossing_table_compares_each_link_to_its_own_reference(self):
        _, rows = self.read_csv("02_bandwidth_intersections_200Hz.csv")
        self.assertEqual(len(rows), 27)
        self.assertEqual(sum(row["link"] == "USB" for row in rows), 9)
        for row in rows:
            n, rate = float(row["continuous_N"]), float(row["raw_Mbit_s"])
            payload = float(row["payload_B_per_module"])
            q = float(row["q_ESKF_total"])
            if row["mean_K_D_per_ESKD"]:
                self.assertAlmostEqual(payload, model.mean_delta_module_bytes(float(row["mean_K_D_per_ESKD"]), q))
            else:
                self.assertEqual(payload, 1044)
            if row["link"] == "USB":
                self.assertEqual(rate, 480)
                self.assertAlmostEqual(model.usb_crossing_modules(payload, 200, rate), n)
            else:
                self.assertEqual(row["link"], "HOST_SPI")
                self.assertIn(rate, [10, 40])
                self.assertAlmostEqual(8 * payload * n * 200 / 1e6, rate)
                integer_n = int(row["integer_modules_at_reference"])
                self.assertEqual(integer_n, math.floor(n))
                self.assertLessEqual(8 * payload * integer_n * 200 / 1e6, rate)
                self.assertGreater(8 * payload * (integer_n + 1) * 200 / 1e6, rate)
                self.assertIn("FULL bursts", row["assumptions"])
                self.assertIn("USB envelope excluded", row["assumptions"])
                self.assertIn("M=max(4,N)", row["M_policy"])
            if row["q_basis"] == "nominal_periodic_only":
                self.assertAlmostEqual(q, .005)
                self.assertIn("not measurement", row["assumptions"])
            elif row["q_basis"] == "no_ESKF_bound":
                self.assertEqual(q, 0)
            expected_domain = 700 if row["link"] == "USB" else 30
            self.assertEqual(row["within_figure_domain"], str(1 <= n <= expected_domain))

    def test_manifest_has_four_separate_figure_exports(self):
        with (model.FIGURES_DIR / "figure_manifest.json").open(encoding="utf-8") as stream:
            section = json.load(stream)["figure_02"]
        for key, expected_link, max_n in [
            ("02A", "USB", 100), ("02B", "USB", 700),
            ("02C", "HOST_SPI", 10), ("02D", "HOST_SPI", 30),
        ]:
            spec = section[key]
            self.assertEqual(spec["link"], expected_link)
            self.assertEqual(spec["N"], [1, max_n])
            self.assertEqual(spec["frequency_Hz"], 200 if key in ["02B", "02D"] else [0, 700])
            self.assertEqual(spec["references_Mbit_s"], [480] if expected_link == "USB" else [10, 40])
            for suffix in ["png", "pdf"]:
                self.assertGreater((model.EXPORT_DIR / f"{spec['stem']}.{suffix}").stat().st_size, 1000)
            with Image.open(model.EXPORT_DIR / f"{spec['stem']}.png") as image:
                self.assertEqual(image.mode, "RGB")
        self.assertEqual(section["overview"]["stem"], "02_four_panel_overview")

    def test_report_pdf_copies_match_all_theory_exports(self):
        for path in model.EXPORT_DIR.glob("02*.pdf"):
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),
                             hashlib.sha256((model.REPORT_FIGURE_DIR / path.name).read_bytes()).digest())

    def test_manifest_distinguishes_configured_slots_and_tested_clock(self):
        manifest = json.loads((model.FIGURES_DIR / "figure_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["overhead_B"], "H(M) = 24 + 4*M")
        self.assertIn("current M=4", manifest["configured_slots_M"])
        self.assertEqual(manifest["SPI_reference"]["clock_Hz"], 40_000_000)
        self.assertIn("not hardware-tested", manifest["SPI_reference"]["source"])
        self.assertEqual(manifest["SPI_current"]["clock_Hz"], 10_000_000)
        self.assertIn("User confirmed", manifest["SPI_current"]["validation"])
        self.assertEqual(manifest["periodic_reference"]["q_at_200Hz"], .005)
        self.assertEqual(manifest["periodic_reference"]["q_other"], 0)
        self.assertIn("not measured", manifest["periodic_reference"]["interpretation"])
        self.assertIn("1/ceil(f*T)", manifest["periodic_reference"]["cycle_approximation"])
        self.assertIn("not an added frame", manifest["q_definition"])

    def test_four_panel_overview_is_a_single_rgb_page(self):
        with Image.open(model.EXPORT_DIR / "02_four_panel_overview.png") as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (7560, 5400))
        self.assertGreater((model.EXPORT_DIR / "02_four_panel_overview.pdf").stat().st_size, 1000)

    def test_delta_usb_k_overview_matches_theory(self):
        fields, rows = self.read_csv("02e_delta_usb_k_overview_200hz.csv")
        self.assertEqual(len(rows), 100 * 481)
        self.assertEqual(fields, [
            "N", "M_configured_slots", "mean_K_D_per_ESKD", "frequency_Hz",
            "DELTA_USB_Mbit_s", "FULL_USB_Mbit_s", "q_ESKF_total", "T_sync_s", "DELTA_no_ESKF_bound_USB_Mbit_s",
        ])
        for row in [rows[0], rows[-1]]:
            n, k, f = int(row["N"]), int(row["mean_K_D_per_ESKD"]), int(row["frequency_Hz"])
            self.assertEqual(int(row["M_configured_slots"]), max(4, n))
            self.assertEqual(f, 200)
            self.assertAlmostEqual(
                float(row["DELTA_USB_Mbit_s"]),
                model.theoretical_mbit(model.mean_delta_frame_bytes(n, k, model.periodic_reference_q(f)), f),
            )
            self.assertAlmostEqual(float(row["DELTA_no_ESKF_bound_USB_Mbit_s"]), model.theoretical_mbit(model.delta_frame_bytes(n, k), f))
            self.assertAlmostEqual(
                float(row["FULL_USB_Mbit_s"]),
                model.theoretical_mbit(model.full_frame_bytes(n), f),
            )
        with (model.FIGURES_DIR / "figure_manifest.json").open(encoding="utf-8") as stream:
            spec = json.load(stream)["figure_02"]["02E"]
        self.assertEqual(spec["N"], [0, 100])
        self.assertEqual(spec["K"], [0, 480])
        self.assertEqual(spec["frequency_Hz"], 200)
        for suffix in ["png", "pdf"]:
            self.assertGreater(
                (model.EXPORT_DIR / f"{spec['stem']}.{suffix}").stat().st_size,
                1000,
            )
        with Image.open(model.EXPORT_DIR / f"{spec['stem']}.png") as image:
            self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
