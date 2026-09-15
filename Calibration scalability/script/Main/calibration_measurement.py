"""FULL-only 200-frame validation with immutable calibration model snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import threading
import time

import numpy as np

from Utility.portable_paths import portable_path

FRAME_COUNT = 200
TIMEOUT_SECONDS = 20.0
PROTOCOL_ID = "whole_layer_shared_endpoints_v3"


def _json_array(values):
    """Use JSON null for invalid predictions, never a nonstandard NaN literal."""
    array = np.asarray(values, dtype=float)
    return np.where(np.isfinite(array), array, None).tolist()


def freeze_model(path, module_id, layer, *, endpoint=False):
    path = Path(path).resolve()
    contents = path.read_bytes()
    data = json.loads(contents)
    module_key, fsr_key = (("module_id", "fsr") if endpoint else
                           ("source_module_id", "source_fsr"))
    if data.get(module_key) != module_id or data.get(fsr_key) != layer:
        raise ValueError(f"model identity differs from M{module_id}/{layer}")
    bounds = data.get("load_range_g", [])
    if (data.get("protocol_id") != PROTOCOL_ID or data.get("version") != 3
            or len(bounds) != 2 or bounds[0] != 0
            or not np.isfinite(bounds[1]) or bounds[1] <= 0):
        raise ValueError("only shared-endpoint models with finite [0,U] are accepted")
    return {"path": path, "bytes": contents, "data": data,
            "sha256": hashlib.sha256(contents).hexdigest()}


def predict_frozen(raw, snapshot, gamma):
    """Return paired 0--U g predictions and unclipped-input diagnostics."""
    raw = np.asarray(raw, dtype=float)
    if raw.shape != (16, 16):
        raise ValueError("expected a 16x16 raw matrix")
    fit = snapshot["fitted"]["data"]
    upper = float(fit["load_range_g"][1])
    fitted = np.full((16, 16), np.nan)
    fit_clipped = np.zeros((16, 16), dtype=bool)
    seen = set()
    for cell in fit["fit"]["cells"]:
        r, c = int(cell["row"]) - 1, int(cell["column"]) - 1
        if not (0 <= r < 16 and 0 <= c < 16) or (r, c) in seen:
            raise ValueError("fitted model has duplicate or invalid cell coordinates")
        seen.add((r, c))
        inverse = cell["pressure_from_adc"]
        x, y = np.asarray(inverse["x"], float), np.asarray(inverse["y"], float)
        if (x.ndim != 1 or y.ndim != 1 or len(x) != len(y)
                or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
                or (len(x) > 1 and not np.all(np.diff(x) > 0))):
            raise ValueError("invalid fitted inverse LUT")
        if len(x) < 2:
            continue  # a constant response has no identifiable inverse
        fit_clipped[r, c] = raw[r, c] < x[0] or raw[r, c] > x[-1]
        fitted[r, c] = np.clip(np.interp(raw[r, c], x, y), 0, upper)
    if len(seen) != 256:
        raise ValueError("fitted model must identify all 256 cells")
    result = {"FIT_PRESS": fitted, "fit_input_clipped": fit_clipped}
    if "endpoint" in snapshot:
        if not np.isfinite(gamma) or gamma <= 0:
            raise ValueError("gamma must be finite and positive")
        endpoint = snapshot["endpoint"]["data"]
        if (endpoint["load_range_g"] != fit["load_range_g"]
                or not endpoint.get("source_sha256")
                or endpoint["source_sha256"] != fit.get("source_sha256")):
            raise ValueError("endpoint and fitted models must share the same sweep SHA and range")
        calibration = endpoint["calibration"]
        low = np.asarray(calibration["interval_low_zero"], float)
        high = np.asarray(calibration["interval_high_full"], float)
        if low.shape != (16, 16) or high.shape != (16, 16):
            raise ValueError("invalid endpoint matrix shape")
        span = high - low
        valid = np.isfinite(low) & np.isfinite(high) & (span > 0)
        u = np.full((16, 16), np.nan)
        np.divide(raw - low, span, out=u, where=valid)
        ratio = np.clip(u, 0, 1)
        result.update(LINEAR=upper * ratio,
                      GAMMA=upper * np.power(ratio, gamma),
                      endpoint_input_clipped=valid & ((u < 0) | (u > 1)))
        result["common_finite_mask"] = (
            np.isfinite(result["LINEAR"]) & np.isfinite(result["GAMMA"])
            & np.isfinite(fitted)
        )
    return result


class CalibrationMeasurementMixin:
    """Reuse the existing buttons/queues while freezing models before capture."""

    def _measurement_error(self, message, *, current_load=False):
        status = self.load_status if current_load else self.view_distribution_status
        status.set_color("#fca5a5")
        status.set_text(message[:105])
        self.figure.canvas.draw_idle()

    def _measurement_can_start(self):
        checker = getattr(self, "_experiment_busy", None)
        if checker is not None and checker():
            return False
        return not (self.load_capture_busy or self.view_distribution_busy)

    def _freeze_layer(self, layer, *, endpoint=True):
        frozen = {}
        if endpoint:
            frozen["endpoint"] = freeze_model(
                self._load_calibration(layer), self.module_id, layer, endpoint=True)
        frozen["fitted"] = freeze_model(
            self._load_pressure_model(layer), self.module_id, layer)
        # Validate the same immutable bytes that later produce predictions.
        predict_frozen(np.zeros((16, 16)), frozen, self.calibration_gamma)
        return frozen

    def _begin_measurement(self, layers, *, endpoint):
        self._measurement_snapshots = {
            layer: self._freeze_layer(layer, endpoint=endpoint) for layer in layers
        }
        self._measurement_module_id = self.module_id
        self._measurement_gamma = float(self.calibration_gamma)
        self._measurement_last_sequence = (
            int(self.latest.sequence) if self.latest is not None
            and self.latest.module_id == self.module_id else None
        )
        self._measurement_started_utc = datetime.now(timezone.utc).isoformat()
        self._measurement_errors_start = int(self.stats.parse_errors)
        self._measurement_skipped = 0
        self._clear_measurement_frames()

    def _is_measurement_frame(self, frame):
        return (frame.module_id is not None and frame.module_status == 0
                and frame.cache_valid and frame.marker == "ESKF"
                and frame.family == "FULL" and not (frame.flags & 0x60)
                and all(np.asarray(m).shape == (16, 16)
                        and np.all(np.isfinite(m)) and np.all(np.asarray(m) >= 0)
                        and np.all(np.asarray(m) <= 4095)
                        for m in (frame.fsr1, frame.fsr2)))

    def _capture_view_distributions(self, _event):
        if not self._measurement_can_start():
            self._measurement_error("Validation: finish the active experiment first")
            return
        try:
            actual = float(self.view_distribution_load_box.text.strip())
            if not np.isfinite(actual) or actual < 0:
                raise ValueError("actual load must be finite and nonnegative")
            if self.mode not in {"FSR1", "FSR2", "All"}:
                raise ValueError("select an FSR view")
            if self.measurement_frames is None:
                raise ValueError("measurement queue is unavailable")
            layers = (self.mode,) if self.mode != "All" else ("FSR1", "FSR2")
            self._begin_measurement(layers, endpoint=True)
            for layer in layers:
                upper = self._measurement_snapshots[layer]["fitted"]["data"]["load_range_g"][1]
                if actual > upper:
                    raise ValueError(f"actual load exceeds {layer} calibrated upper load {upper:g} g")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._measurement_error(f"Validation: {error}")
            return
        self.view_distribution_busy = self.view_distribution_collecting = True
        self.view_distribution_layers = layers
        self.view_distribution_actual_load_g = actual
        self.view_distribution_frames = []
        self.view_distribution_started_at = time.monotonic()
        self.view_distribution_button.label.set_text("Capturing 0/200")
        self.view_distribution_status.set_color("#fbbf24")
        self.view_distribution_status.set_text("Validation: waiting for 200 fresh FULL frames")
        self._clear_view_distribution_input()
        self.figure.canvas.draw_idle()

    def _consume_measurement_frames(self):
        active = self.load_capture_busy or self.view_distribution_collecting
        if self.measurement_frames is not None:
            while True:
                try:
                    frame = self.measurement_frames.get_nowait()
                except queue.Empty:
                    break
                if not active:
                    continue
                if (frame.module_id != self._measurement_module_id
                        or not self._is_measurement_frame(frame)):
                    self._measurement_skipped += 1
                    continue
                sequence = int(frame.sequence)
                last = self._measurement_last_sequence
                if last is not None and not 0 < ((sequence - last) & 0xffffffff) < 0x80000000:
                    self._measurement_skipped += 1
                    continue
                self._measurement_last_sequence = sequence
                target = (self.load_capture_frames if self.load_capture_busy
                          else self.view_distribution_frames)
                target.append(frame)
                if len(target) == FRAME_COUNT:
                    if self.load_capture_busy:
                        self._finish_current_load_capture()
                    else:
                        self._finish_view_distribution_capture()
                    active = False
        if self.load_capture_busy:
            if time.monotonic() - self.load_capture_started_at >= TIMEOUT_SECONDS:
                self._finish_current_load_capture()
            else:
                self.load_status.set_text(f"Load: {len(self.load_capture_frames)}/200 FULL frames")
        if self.view_distribution_collecting:
            if time.monotonic() - self.view_distribution_started_at >= TIMEOUT_SECONDS:
                self._finish_view_distribution_capture()
            else:
                count = len(self.view_distribution_frames)
                self.view_distribution_status.set_text(f"Validation: {count}/200 FULL frames")

    def _finish_view_distribution_capture(self):
        self.view_distribution_collecting = False
        frames, layers = self.view_distribution_frames, self.view_distribution_layers
        self.view_distribution_frames = []
        complete = len(frames) == FRAME_COUNT
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        load = self.view_distribution_actual_load_g
        jobs = []
        try:
            for layer in layers:
                snapshot = self._measurement_snapshots[layer]
                raw_frames = [np.asarray(getattr(frame, layer.lower()), dtype=np.uint16)
                              for frame in frames]
                raw = (np.median(np.stack(raw_frames), axis=0) if frames
                       else np.full((16, 16), np.nan))
                views = {"RAW": {"unit": "ADC code", "values": _json_array(raw)}}
                predictions = predict_frozen(raw, snapshot, self._measurement_gamma)
                for name in ("LINEAR", "GAMMA", "FIT_PRESS"):
                    views[name] = {"unit": "g",
                                   "values": _json_array(predictions[name])}
                token = f"{load:g}".replace(".", "p")
                folder = (self._calibration_directory() / "DATA" /
                          f"module_{self._measurement_module_id}" / layer / "evaluation" /
                          "view_distribution" / f"load_{token}g_{stamp}")
                folder.mkdir(parents=True, exist_ok=False)
                models_dir = folder / "models"
                models_dir.mkdir()
                model_paths = {}
                for name, frozen in snapshot.items():
                    target = models_dir / ("two_point_calibration.json" if name == "endpoint"
                                           else "pressure_response_model.json")
                    with target.open("xb") as handle:
                        handle.write(frozen["bytes"])
                    model_paths[name] = portable_path(target)
                endpoint = snapshot["endpoint"]["data"]
                load_range = endpoint["load_range_g"]
                payload = {
                    "format": "e-skin-fsr-view-distribution-capture", "version": 4,
                    "protocol_id": PROTOCOL_ID, "load_range_g": load_range,
                    "prediction_units": "g",
                    "status": "COMPLETE" if complete else "INCOMPLETE",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "module_id": self._measurement_module_id, "fsr": layer,
                    "actual_load": {"value": load, "unit": "g"},
                    "source_frames": {
                        "count": len(frames), "target_count": FRAME_COUNT,
                        "aggregation": "per-cell median of collected fresh FULL frames (target 200)",
                        "started_at": self._measurement_started_utc,
                        "elapsed_seconds": time.monotonic() - self.view_distribution_started_at,
                        "sequence_first": int(frames[0].sequence) if frames else None,
                        "sequence_last": int(frames[-1].sequence) if frames else None,
                        "sequences": [int(f.sequence) for f in frames],
                        "skipped_frame_count": self._measurement_skipped,
                        "protocol_errors": max(0, self.stats.parse_errors - self._measurement_errors_start),
                    },
                    "raw_frames": [matrix.astype(int).tolist() for matrix in raw_frames],
                    "source_models": {
                        "two_point": model_paths["endpoint"],
                        "fitted_response": model_paths["fitted"],
                        "two_point_original": portable_path(snapshot["endpoint"]["path"]),
                        "fitted_response_original": portable_path(snapshot["fitted"]["path"]),
                        "two_point_sha256": snapshot["endpoint"]["sha256"],
                        "fitted_response_sha256": snapshot["fitted"]["sha256"],
                        "gamma": self._measurement_gamma,
                        "shared_sweep_sha256": endpoint["source_sha256"],
                        "linear_formula_g": "U * clip((RAW-zero)/(full-zero),0,1)",
                        "gamma_formula_g": "U * clip((RAW-zero)/(full-zero),0,1)**gamma",
                    },
                    "calibration_snapshot": {
                        "protocol_id": PROTOCOL_ID, "load_range_g": load_range,
                        "interval_low_zero": endpoint["calibration"]["interval_low_zero"],
                        "interval_high_full": endpoint["calibration"]["interval_high_full"],
                        "problem_cells": endpoint.get("problem_cells", []),
                        "source_path": model_paths["endpoint"],
                    },
                    "evaluation_policy": {
                        "statistical_load_range_g": load_range,
                        "common_finite_mask": predictions["common_finite_mask"].tolist(),
                        "exclude_unstable_qc_cells": False,
                        "exclude_by_predicted_load": False,
                        "measurand": "equivalent whole-layer calibration mass in g",
                    },
                    "clipping": {
                        "endpoint_input_mask": predictions["endpoint_input_clipped"].tolist(),
                        "fitted_input_mask": predictions["fit_input_clipped"].tolist(),
                    },
                    "views": views,
                }
                path = folder / "view_distribution_capture.json"
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, allow_nan=False)
                    handle.write("\n")
                if complete:
                    jobs.append((path, folder))
                self.last_validation_capture_path = path
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self._measurement_error(f"Validation save failed: {error}")
            return
        if not complete:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self._measurement_error(f"INCOMPLETE: {len(frames)}/200 frames; partial RAW saved")
            return
        self.view_distribution_button.label.set_text("Plotting...")
        threading.Thread(target=self._run_view_distribution_analysis,
                         args=(jobs, layers, load), daemon=True).start()

    def _show_current_load(self, _event):
        if not self._measurement_can_start():
            self._measurement_error("Load: finish the active experiment first", current_load=True)
            return
        try:
            if self.mode not in {"FSR1", "FSR2", "All"} or self.measurement_frames is None:
                raise ValueError("select an FSR view with a measurement queue")
            layers = (self.mode,) if self.mode != "All" else ("FSR1", "FSR2")
            self._begin_measurement(layers, endpoint=False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._measurement_error(f"Load: {error}", current_load=True)
            return
        self.load_capture_busy = True
        self.load_capture_started_at = time.monotonic()
        self.load_capture_layers, self.load_capture_frames = layers, []
        self.load_value_text.set_text("... g")
        self.load_status.set_text("Load: waiting for 200 fresh FULL frames")
        self.figure.canvas.draw_idle()

    def _estimate_load_for_fsr(self, fsr_name, matrix):
        snapshots = getattr(self, "_measurement_snapshots", {})
        snapshot = snapshots.get(fsr_name) or self._freeze_layer(fsr_name, endpoint=False)
        predictions = predict_frozen(matrix, snapshot, self.calibration_gamma)
        values = predictions["FIT_PRESS"]
        finite = np.isfinite(values)
        if not np.any(finite):
            raise ValueError("no finite fitted estimates")
        return (float(np.mean(values[finite])), int(predictions["fit_input_clipped"].sum()),
                snapshot["fitted"]["path"], int((~finite).sum()))

    def _finish_current_load_capture(self):
        self.load_capture_busy = False
        frames, self.load_capture_frames = self.load_capture_frames, []
        if len(frames) != FRAME_COUNT:
            self.load_value_text.set_text("— g")
            self._measurement_error(f"Load: incomplete {len(frames)}/200 FULL frames", current_load=True)
            return
        try:
            estimates = []
            for layer in self.load_capture_layers:
                raw = np.median(np.stack([getattr(frame, layer.lower()) for frame in frames]), axis=0)
                estimates.append(self._estimate_load_for_fsr(layer, raw)[0])
            self.load_value_text.set_text(f"{np.mean(estimates):.1f} g")
            self.load_value_text.set_color("#86efac")
            self.load_status.set_text("FIT: 200-frame median; mean of finite cell estimates")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._measurement_error(f"Load: {error}", current_load=True)
        self.figure.canvas.draw_idle()
