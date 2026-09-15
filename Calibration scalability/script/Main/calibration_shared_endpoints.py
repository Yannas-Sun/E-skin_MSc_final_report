"""Whole-layer calibration with two-point endpoints derived from one sweep."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from Calibration.calibrate_fsr import build_from_sweep, save_calibration
from calibration_measurement import CalibrationMeasurementMixin

PROTOCOL = "whole_layer_shared_endpoints_v3"
FRAME_COUNT = 200
TIMEOUT = 20.0
MODEL_DIR = Path(__file__).resolve().parent / "Model"


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def save_sweep(root, *, module_id, fsr, points, source, started_at):
    loads = {float(p["pressure"]) for p in points}
    if len(loads) < 3 or 0.0 not in loads or max(loads) <= 0:
        raise ValueError("Record 0 g, intermediate load(s), and a final maximum load")
    if any(not np.isfinite(p) or p < 0 for p in loads):
        raise ValueError("All loads must be finite and nonnegative")
    if float(points[-1]["pressure"]) != max(loads):
        raise ValueError("The last recorded load must equal the maximum load")
    if float(points[0]["pressure"]) != 0:
        raise ValueError("The first recorded load must be 0 g")
    for point in points:
        frames = np.asarray(point["raw_frames"], dtype=float)
        raw = np.asarray(point["raw_adc"], dtype=float)
        if (frames.shape != (FRAME_COUNT, 16, 16) or not np.isfinite(frames).all()
                or np.any(frames < 0) or np.any(frames > 4095) or np.any(frames != np.floor(frames))):
            raise ValueError("Each load needs 200 complete FULL frames")
        if not np.array_equal(raw, np.median(frames, axis=0)):
            raise ValueError("Each load must use the per-cell median")
    data = {
        "format": "e-skin-fsr-pressure-response-sweep", "version": 3,
        "protocol_id": PROTOCOL, "load_range_g": [0, max(loads)],
        "capture_scope": "whole_layer", "created_at": now(), "started_at": started_at,
        "module_id": module_id, "fsr": fsr, "matrix": {"rows": 16, "columns": 16},
        "response": {"type": "raw_adc_code", "adc_bits": 12, "maximum_code": 4095},
        "pressure": {"unit": "g", "meaning": "applied whole-layer calibration mass"},
        "acquisition": {"frames_per_point": FRAME_COUNT, "aggregation": "per-cell median",
                        "accepted_family": "FULL", "loading_geometry": "fixed whole-layer fixture"},
        "source": source, "points": points,
    }
    directory = root / "DATA" / f"module_{module_id}" / fsr / "fit" / "raw"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{fsr}_pressure_sweep_{stamp()}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
    return path


def make_calibration_gui(base):
    class CalibrationGui(CalibrationMeasurementMixin, base):
        def __init__(self, *args, **kwargs):
            self.fit_pending = None
            self.fit_analysis_busy = False
            self.capture_deadline = 0.0
            self.phase_seen = set()
            self.phase_skipped = 0
            self.phase_last_sequence = None
            self.curve_jobs = queue.Queue()
            super().__init__(*args, **kwargs)
            self.figure.canvas.manager.set_window_title("E-SKIN Calibration | Shared Endpoints")
            self.normalized_calibration_button.label.set_text("Show Shared Endpoints")
            self.normalized_calibration_status.set_text("Auto: shared sweep endpoints")
            self.calibration_status.set_text("First: 0 g; last: maximum")
            self.calibration_pressure_label.set_text("Whole-layer mass (g)")
            self.gamma_label.set_text("Gamma > 0; set before test")
            self.experiment_status = self.figure.text(0.16, 0.012, "Ready: FULL mode; select module and FSR layer", fontsize=8, color="#94a3b8")
            self.normalized_button.label.set_text("GAMMA (g)")
            self.pressure_display_button.label.set_text("FIT (g)")
            self.view_distribution_button.label.set_text("Validate 3 Curves")
            self.normalized_button.ax.set_position((0.922, 0.650, 0.058, 0.028))
            linear_axis = self._panel_axis("display", (0.86, 0.650, 0.058, 0.028))
            self.linear_button = self._Button(linear_axis, "LINEAR (g)", color="#26324a")
            self.linear_button.label.set_fontsize(7)
            self.linear_button.on_clicked(lambda event: self._set_display_mode("LINEAR"))
            curves_axis = self._panel_axis("calibration", (0.86, 0.539, 0.12, 0.025))
            self.curves_button = self._Button(curves_axis, "Plot 3 Curves", color="#26324a")
            self.curves_button.label.set_fontsize(8)
            self.curves_button.on_clicked(self._plot_curves)
            self._toggle_panel("tools")
            self.title.set_text(f"Waiting for calibration frames from {self.source}...")
            self._update_display_buttons()

        def _set_calibration_status(self, message, color="#94a3b8"):
            if hasattr(self, "experiment_status"):
                self.experiment_status.set_text(textwrap.shorten(message, width=145, placeholder="..."))
                self.experiment_status.set_color(color)
            self.calibration_status.set_color(color)
            self.calibration_status.set_text("\n".join(textwrap.wrap(message, 27)[:2]))
            self.figure.canvas.draw_idle()

        def _experiment_busy(self):
            return (self.normalized_phase != "idle" or self.calibration_phase != "idle"
                    or self.fit_analysis_busy or self.load_capture_busy
                    or self.view_distribution_busy or self.view_distribution_collecting)

        def _select_module(self, label):
            if self._experiment_busy():
                self.module_radio.eventson = False
                self.module_radio.set_active(self.module_id)
                self.module_radio.eventson = True
                self._set_calibration_status("Finish the active capture before changing module", "#fbbf24")
                return
            super()._select_module(label)
            self.latest = self.latest_by_module.get(self.module_id)

        def _select_view(self, label):
            if self._experiment_busy():
                self.radio.eventson = False
                self.radio.set_active(("All", "FSR1", "FSR2", "ACC").index(self.mode))
                self.radio.eventson = True
                self._set_calibration_status("Finish the active capture before changing layer", "#fbbf24")
                return
            super()._select_view(label)

        def _start_pyocd_reset(self, event):
            if self._experiment_busy():
                self._set_calibration_status("Finish capture before resetting hardware", "#fbbf24")
                return
            super()._start_pyocd_reset(event)

        def _save_current_frame(self, event):
            frame = self.latest
            if frame is None or frame.module_id != self.module_id or not frame.cache_valid:
                self._set_calibration_status("Snapshot: waiting for the selected module", "#fca5a5")
                return
            layers = self._calibration_fsrs_for_view()
            if not layers:
                self._set_calibration_status("Snapshot: select an FSR view", "#fca5a5")
                return
            folder = self._calibration_directory() / "DATA" / f"module_{self.module_id}" / "snapshots" / stamp()
            try:
                folder.mkdir(parents=True, exist_ok=False)
                views = {}
                for layer in layers:
                    raw = np.asarray(getattr(frame, layer.lower()))
                    values = np.asarray(self._display_fsr(layer, raw), dtype=float)
                    views[layer] = {"raw_adc": raw.tolist(), "display_values": np.where(np.isfinite(values), values, None).tolist()}
                payload = {"format": "e-skin-display-snapshot", "protocol_id": PROTOCOL,
                           "purpose": "Single-frame display snapshot; not a calibration or validation capture",
                           "module_id": self.module_id, "sequence": int(frame.sequence),
                           "family": frame.family, "display_mode": self.display_mode,
                           "display_unit": "ADC code" if self.display_mode == "RAW" else "g",
                           "gamma": self.calibration_gamma, "matrix_orientation": "native row/column order",
                           "views": views}
                with (folder / "snapshot.json").open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, allow_nan=False)
                self.figure.savefig(folder / "heatmap.png", dpi=150, facecolor=self.figure.get_facecolor())
            except (OSError, ValueError) as error:
                self._set_calibration_status(f"Snapshot save failed: {error}", "#fca5a5")
                return
            self.frame_save_status.set_text("Saved snapshot JSON + PNG")
            self._set_calibration_status("Snapshot saved separately from training and validation data", "#86efac")
            print(f"Display snapshot: {folder}")

        def _fresh_capture(self):
            if self.calibration_frames is None:
                raise ValueError("Calibration queue is unavailable")
            while True:
                try:
                    self.calibration_frames.get_nowait()
                except queue.Empty:
                    break
            self.phase_seen = set()
            self.phase_skipped = 0
            latest = self.latest_by_module.get(self.module_id, self.latest)
            self.phase_last_sequence = (int(latest.sequence) if latest is not None
                                        and latest.module_id == self.module_id else None)
            self.capture_deadline = time.monotonic() + TIMEOUT

        def _ready_layer(self):
            if self.mode not in ("FSR1", "FSR2"):
                raise ValueError("Select one FSR layer first")
            frame = self.latest_by_module.get(self.module_id, self.latest)
            if frame is None or frame.module_id != self.module_id or not self._is_measurement_frame(frame):
                raise ValueError("Waiting for selected module in FULL mode")

        def _normalized_calibration_button_clicked(self, event):
            if self.mode not in ("FSR1", "FSR2"):
                self._set_calibration_status("Select one FSR layer", "#fca5a5")
                return
            try:
                path = self._load_calibration(self.mode)
                data = json.loads(path.read_text(encoding="utf-8"))
                upper = data["load_range_g"][1]
                self.normalized_calibration_status.set_text(f"Shared 0--{upper:g} g; QC: {data['problem_cell_count']}/256")
                self._set_calibration_status("Endpoints use the same sweep; no separate capture is needed", "#86efac")
            except (ValueError, OSError, KeyError) as error:
                self._set_calibration_status(f"Complete a multi-point sweep first: {str(error)[:45]}", "#fbbf24")

        def _consume_normalized_frames(self):
            if self.calibration_frames is None:
                return
            while True:
                try:
                    frame = self.calibration_frames.get_nowait()
                except queue.Empty:
                    break
                if self.fit_pending is None or frame.module_id != self.calibration_module_id:
                    continue
                key = int(frame.sequence)
                last = self.phase_last_sequence
                if (not self._is_measurement_frame(frame) or key in self.phase_seen
                        or (last is not None and not 0 < ((key - last) & 0xffffffff) < 0x80000000)):
                    self.phase_skipped += 1
                    continue
                raw = np.asarray(frame.fsr1 if self.calibration_fsr_name == "FSR1" else frame.fsr2)
                if (raw.shape != (16, 16) or not np.isfinite(raw).all()
                        or np.any(raw < 0) or np.any(raw > 4095) or np.any(raw != np.floor(raw))):
                    self.phase_skipped += 1
                    continue
                self.phase_seen.add(key)
                self.phase_last_sequence = key
                self.fit_pending["frames"].append(raw.copy())
                self.fit_pending["sequences"].append(key)
                if len(self.fit_pending["frames"]) == FRAME_COUNT:
                    self._finish_fit_point()
            if self.fit_pending is not None:
                count = len(self.fit_pending["frames"])
                self._set_calibration_status(f"{self.fit_pending['load']:g} g: {count}/200 FULL frames")
                if time.monotonic() > self.capture_deadline:
                    self.fit_pending = None
                    self._set_calibration_status("Timed out; incomplete point not saved. Check FULL stream and retry", "#fca5a5")

        def _calibration_button_clicked(self, event):
            if self.calibration_phase == "pressure_capture":
                self._finish_calibration()
                return
            if self._experiment_busy():
                self._set_calibration_status("Finish the active experiment first", "#fbbf24")
                return
            try:
                self._ready_layer()
            except ValueError as error:
                self._set_calibration_status(str(error), "#fca5a5")
                return
            self.calibration_module_id = self.module_id
            self.calibration_fsr_name = self.mode
            self.calibration_started_at = now()
            self.calibration_parse_errors_start = self.stats.parse_errors
            self.calibration_pressure_points = []
            self.calibration_phase = "pressure_capture"
            self.calibration_button.label.set_text("End Fit Cal")
            self._set_calibration_status("Record 0 g, intermediate loads, then maximum load; End Fit Cal")

        def _record_pressure_point(self, event=None):
            if self.calibration_phase != "pressure_capture" or self.fit_pending is not None:
                return
            text = event if isinstance(event, str) else self.calibration_pressure_box.text
            if not str(text).strip():
                return
            try:
                load = float(text)
                if not np.isfinite(load) or load < 0:
                    raise ValueError("Load must be finite and nonnegative")
                if not self.calibration_pressure_points and load != 0:
                    raise ValueError("The first recorded load must be 0 g")
                self._fresh_capture()
            except ValueError as error:
                self._set_calibration_status(str(error), "#fca5a5")
                return
            self.fit_pending = {"load": load, "frames": [], "sequences": [], "started_at": now()}
            self._clear_pressure_input()
            self._set_calibration_status(f"Keep {load:g} g stable: collecting 200 FULL frames")

        def _finish_fit_point(self):
            pending = self.fit_pending
            self.fit_pending = None
            frames = np.asarray(pending["frames"])
            self.calibration_pressure_points.append({
                "index": len(self.calibration_pressure_points) + 1, "pressure": pending["load"],
                "captured_at": now(), "started_at": pending["started_at"],
                "family": "FULL", "marker": "ESKF", "frame_count": FRAME_COUNT,
                "sequences": pending["sequences"], "skipped_frames": self.phase_skipped,
                "raw_adc": np.median(frames, axis=0).tolist(), "raw_frames": frames.tolist(),
                "p05": np.percentile(frames, 5, axis=0).tolist(),
                "p95": np.percentile(frames, 95, axis=0).tolist(),
            })
            self._set_calibration_status(f"Saved point {len(self.calibration_pressure_points)}: {pending['load']:g} g; enter next load", "#86efac")

        def _finish_calibration(self):
            if self.fit_pending is not None:
                self._set_calibration_status("Wait until the current 200-frame capture completes", "#fbbf24")
                return
            try:
                path = save_sweep(self._calibration_directory(), module_id=self.calibration_module_id,
                                  fsr=self.calibration_fsr_name, points=self.calibration_pressure_points,
                                  started_at=self.calibration_started_at,
                                  source={"port": self.source, "baud": self.baud,
                                          "protocol_errors": max(0, self.stats.parse_errors - self.calibration_parse_errors_start)})
            except (ValueError, OSError) as error:
                self._set_calibration_status(str(error), "#fca5a5")
                return
            try:
                endpoint = save_calibration(build_from_sweep(path, gamma=self.calibration_gamma), self._calibration_directory())
                self._load_calibration(self.calibration_fsr_name)
            except (ValueError, OSError, KeyError) as error:
                self._set_calibration_status(f"Sweep saved; endpoint generation failed: {str(error)[:60]}", "#fca5a5")
                return
            self.normalized_calibration_status.set_text(f"Shared range: 0--{max(p['pressure'] for p in self.calibration_pressure_points):g} g")
            print(f"Shared endpoint model: {endpoint}")
            self.calibration_phase = "idle"
            self.calibration_button.label.set_text("Start Fit Cal")
            self.fit_analysis_busy = True
            self._set_calibration_status("Sweep saved; fitting and plotting all 256 cells...", "#fbbf24")
            output = path.parent.parent / "analysis" / stamp()
            threading.Thread(target=self._run_pressure_analysis,
                             args=(path, output, "g", endpoint, self.calibration_gamma), daemon=True).start()

        def _run_pressure_analysis(self, sweep_path, analysis_dir, load_unit, endpoint=None, gamma=4.0):
            try:
                result = subprocess.run([sys.executable, "-B", str(MODEL_DIR / "plot_pressure_calibration_monotonic.py"),
                                         "--input", str(sweep_path), "--output-dir", str(analysis_dir),
                                         "--protocol", PROTOCOL], capture_output=True, text=True, timeout=240)
                if result.returncode:
                    raise RuntimeError(result.stderr[-1000:] or result.stdout[-1000:])
                print(result.stdout)
                if endpoint is not None:
                    comparison_dir = analysis_dir / "comparison"
                    plotted = subprocess.run([sys.executable, "-B", str(MODEL_DIR / "plot_calibration_comparison.py"),
                                               "--two-point", str(endpoint), "--model", str(analysis_dir / "pressure_response_model.json"),
                                               "--gamma", str(gamma), "--output-dir", str(comparison_dir)],
                                              capture_output=True, text=True, timeout=120)
                    if plotted.returncode:
                        raise RuntimeError("Fit saved, comparison failed: " + (plotted.stderr[-800:] or plotted.stdout[-800:]))
                    self.curve_jobs.put(comparison_dir / "calibration_comparison.png")
                self.calibration_analysis_results.put(("Sweep, shared endpoints and three curves saved", "#86efac"))
            except Exception as error:
                print(f"Fit analysis failed; raw sweep retained: {error}")
                self.calibration_analysis_results.put((f"Fit failed; raw retained: {str(error)[:65]}", "#fca5a5"))
            finally:
                self.fit_analysis_busy = False

        def _load_calibration(self, fsr_name, module_id=None):
            path = super()._load_calibration(fsr_name, module_id)
            data = json.loads(path.read_text(encoding="utf-8"))
            bounds = data.get("load_range_g", [])
            if data.get("protocol_id") != PROTOCOL or len(bounds) != 2 or bounds[0] != 0 or not np.isfinite(bounds[1]) or bounds[1] <= 0:
                self.calibration_data.pop(fsr_name, None)
                raise ValueError("Requires shared endpoints from the current sweep")
            cal = self.calibration_data[fsr_name]
            if not np.array_equal(cal["high"], np.asarray(data["full_load"]["median"])):
                raise ValueError("Upper endpoint must equal the maximum-load median")
            span = cal["high"] - cal["low"]
            cal["span"] = np.where(span > 0, span, np.nan)
            cal["upper_load_g"] = float(bounds[1])
            return path

        def _load_pressure_model(self, fsr_name, module_id=None):
            path = super()._load_pressure_model(fsr_name, module_id)
            data = json.loads(path.read_text(encoding="utf-8"))
            bounds = data.get("load_range_g", [])
            if data.get("protocol_id") != PROTOCOL or len(bounds) != 2 or bounds[0] != 0 or not np.isfinite(bounds[1]) or bounds[1] <= 0:
                self.pressure_model_data.pop(fsr_name, None)
                raise ValueError("Requires a new model fitted to the shared-endpoint sweep")
            return path

        def _apply_gamma(self, event):
            if self._experiment_busy():
                self.gamma_status.set_text("Finish experiment before changing gamma")
                return
            try:
                gamma = float(self.gamma_box.text)
                if not np.isfinite(gamma) or gamma <= 0:
                    raise ValueError()
            except ValueError:
                self.gamma_status.set_text("Gamma must be finite and > 0")
                return
            self.calibration_gamma = gamma
            self.gamma_status.set_text(f"gamma = {gamma:g}")
            if self.display_mode == "GAMMA":
                self._build_view()
            if self.latest is not None:
                self._render(self.latest)

        def _update_display_buttons(self):
            for mode, button in (("GAMMA", self.normalized_button), ("PRESSURE", self.pressure_display_button),
                                 ("RAW", self.raw_display_button)):
                active = self.display_mode == mode
                button.ax.set_facecolor("#28523a" if active else "#26324a")
                button.label.set_color("#86efac" if active else "white")
            if hasattr(self, "linear_button"):
                self.linear_button.ax.set_facecolor("#28523a" if self.display_mode == "LINEAR" else "#26324a")

        def _set_display_mode(self, requested_mode):
            if requested_mode not in {"RAW", "LINEAR", "GAMMA", "PRESSURE"}:
                raise ValueError("Display mode must be RAW, LINEAR, GAMMA or PRESSURE")
            required = self._calibration_fsrs_for_view()
            try:
                if requested_mode != "RAW" and not required:
                    raise ValueError("Select an FSR view")
                if requested_mode != "RAW":
                    for fsr in required:
                        if requested_mode == "PRESSURE":
                            self._load_pressure_model(fsr)
                        else:
                            self._load_calibration(fsr)
            except (KeyError, OSError, ValueError) as error:
                self._set_calibration_status(str(error), "#fca5a5")
                return
            self.display_mode = requested_mode
            self._update_display_buttons()
            self._build_view()
            if self.latest is not None:
                self._render(self.latest)
            label = "RAW ADC" if requested_mode == "RAW" else ("FIT (g)" if requested_mode == "PRESSURE" else f"{requested_mode} (g)")
            self._set_calibration_status(f"Display: {label} M{self.module_id}", "#86efac")

        def _show_normalized_display(self, event):
            # The inherited button hook now selects a gram-valued gamma curve.
            self._set_display_mode("GAMMA")

        def _two_point_load_values(self, fsr_name, raw, *, gamma=1.0):
            cal = self.calibration_data[fsr_name]
            fraction = np.clip((np.asarray(raw, dtype=float) - cal["low"]) / cal["span"], 0, 1)
            return cal["upper_load_g"] * fraction ** gamma

        def _display_fsr(self, fsr_name, raw):
            if self.display_mode == "RAW":
                return raw
            try:
                if self.display_mode == "LINEAR":
                    return self._two_point_load_values(fsr_name, raw)
                if self.display_mode == "GAMMA":
                    return self._two_point_load_values(fsr_name, raw, gamma=self.calibration_gamma)
                return self._fitted_fsr_values(fsr_name, raw)
            except (KeyError, ValueError):
                return np.full((16, 16), np.nan)

        def _fitted_fsr_values(self, fsr_name, raw):
            data = self.pressure_model_data[fsr_name]
            output = np.full((16, 16), np.nan)
            for row in range(16):
                for column in range(16):
                    cell = data["cells"][row][column]
                    if cell.get("type") != "linear_lut":
                        raise ValueError("Shared endpoint protocol requires an inverse LUT")
                    if len(cell["x"]) < 2:
                        continue
                    output[row, column] = np.clip(np.interp(raw[row, column], cell["x"], cell["y"]), 0, data["pressure_max"])
            return output

        def _run_view_distribution_analysis(self, jobs, layers, actual_load_g):
            # Automatic work is limited to this capture; cumulative analyses are manual.
            script = MODEL_DIR.parent / "Evaluation" / "analyze_view_distributions.py"
            try:
                for capture_path, capture_folder in jobs:
                    result = subprocess.run(
                        [sys.executable, "-B", str(script), "--input", str(capture_path),
                         "--output-dir", str(capture_folder)],
                        capture_output=True, text=True, timeout=120, check=False)
                    if result.returncode:
                        raise RuntimeError((result.stderr or result.stdout).strip()[-500:])
                    print(result.stdout.strip())
                    print(f"Single-capture distributions: {capture_folder}")
                print("Cumulative error and dispersion: run the analysis scripts manually when ready.")
                message = f"Capture + distributions saved: {'+'.join(layers)} at {actual_load_g:g} g; error/dispersion manual"
                color = "#86efac"
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as error:
                print(f"Single-capture plotting failed; captured RAW and predictions retained: {error}")
                message = f"Capture saved; distribution plotting failed: {str(error)[:60]}"
                color = "#fca5a5"
            try:
                self.view_distribution_results.put_nowait((message, color))
            except queue.Full:
                pass

        def _poll_view_distribution_result(self):
            super()._poll_view_distribution_result()
            if not self.view_distribution_busy:
                self.view_distribution_button.label.set_text("Validate 3 Curves")
                message = self.view_distribution_status.get_text()
                if len(message) > 32:
                    self._set_calibration_status(message, self.view_distribution_status.get_color())
                    self.view_distribution_status.set_text("\n".join(textwrap.wrap(message, 32)[:2]))

        def _measurement_error(self, message, *, current_load=False):
            super()._measurement_error(message, current_load=current_load)
            self._set_calibration_status(message, "#fca5a5")
            status = self.load_status if current_load else self.view_distribution_status
            status.set_text("\n".join(textwrap.wrap(message, 30)[:2]))

        def _add_fsr(self, spec, key, title, compact):
            super()._add_fsr(spec, key, title, compact)
            if self.display_mode != "RAW":
                upper = (self.pressure_model_data[key.upper()]["pressure_max"] if self.display_mode == "PRESSURE"
                         else self.calibration_data[key.upper()]["upper_load_g"])
                self.fsr_artists[key].set_clim(0, upper)
                self.content_axes[-1].set_ylabel("Equivalent whole-layer load (g)")
                label = {"LINEAR": "LINEAR", "GAMMA": f"GAMMA {self.calibration_gamma:g}", "PRESSURE": "FIT"}[self.display_mode]
                self.content_axes[-2].set_title(f"{title} / {label}", color="white", pad=16)

        def _build_view(self):
            self._remove_content()
            if self.mode == "All":
                grid = self.figure.add_gridspec(1, 2, left=0.17, right=0.78, bottom=0.07, top=0.86)
                self._add_fsr(grid[0, 0], "fsr1", "FSR1 / left", True)
                self._add_fsr(grid[0, 1], "fsr2", "FSR2 / right", True)
            elif self.mode in ("FSR1", "FSR2"):
                grid = self.figure.add_gridspec(1, 1, left=0.17, right=0.78, bottom=0.07, top=0.86)
                self._add_fsr(grid[0], self.mode.lower(), self.mode, False)
            else:
                grid = self.figure.add_gridspec(1, 1, left=0.17, right=0.78, bottom=0.07, top=0.86)
                self._add_acc_text(grid[0])

        def _plot_curves(self, event):
            if self._experiment_busy():
                self._set_calibration_status("Finish the active experiment first", "#fbbf24")
                return
            try:
                if self.mode not in ("FSR1", "FSR2"):
                    raise ValueError("Select one FSR layer")
                endpoint = self._load_calibration(self.mode)
                model = self._load_pressure_model(self.mode)
            except (ValueError, OSError, KeyError) as error:
                self._set_calibration_status(str(error), "#fca5a5")
                return
            output = endpoint.parent.parent / "comparison" / stamp()
            gamma = self.calibration_gamma
            self.fit_analysis_busy = True
            self._set_calibration_status("Plotting linear / gamma / multi-point curves...")
            def run():
                try:
                    result = subprocess.run([sys.executable, "-B", str(MODEL_DIR / "plot_calibration_comparison.py"),
                                             "--two-point", str(endpoint), "--model", str(model),
                                             "--gamma", str(gamma), "--output-dir", str(output)],
                                            capture_output=True, text=True, timeout=120)
                    if result.returncode:
                        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])
                    print(f"Comparison curves: {output}")
                    self.curve_jobs.put(output / "calibration_comparison.png")
                    self.calibration_analysis_results.put(("Three curves saved as PNG/PDF; preview opened", "#86efac"))
                except Exception as error:
                    print(f"Comparison failed: {error}")
                    self.calibration_analysis_results.put((f"Comparison failed: {str(error)[:70]}", "#fca5a5"))
                finally:
                    self.fit_analysis_busy = False
            threading.Thread(target=run, daemon=True).start()

        def _poll_pressure_analysis_result(self):
            super()._poll_pressure_analysis_result()
            try:
                path = self.curve_jobs.get_nowait()
            except queue.Empty:
                return
            figure, axis = self.plt.subplots(figsize=(12, 6))
            axis.imshow(self.plt.imread(path))
            axis.axis("off")
            figure.tight_layout()
            figure.show()

    return CalibrationGui
