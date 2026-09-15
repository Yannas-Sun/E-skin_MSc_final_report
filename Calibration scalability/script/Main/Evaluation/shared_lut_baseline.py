"""A shared inverse LUT from the frozen model's mean training ADC response.

Training ADC values were averaged across cells at each load before the common
PAVA/LUT fitting procedure. This is not the mean of the 256 inverse functions.
Validation loads never participate in construction of this baseline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from portable_paths import calibration_root, portable_path, resolve_recorded_path  # noqa: E402

PROTOCOL_ID = "whole_layer_shared_endpoints_v3"
METHOD = "GLOBAL_LUT"


def _resolve_project_recorded_path(value: str, root: Path) -> Path:
    """Resolve a legacy absolute or project-relative provenance path."""
    raw = Path(value)
    # A relative path in a model is relative to the calibration project, not
    # to whichever directory happened to be the caller's working directory.
    if not raw.is_absolute():
        candidate = (root / raw).resolve()
        if candidate.exists():
            return candidate
    return resolve_recorded_path(raw, root / "__path_anchor__.json", root=root)


def _portable_existing_or_original(value: Any, resolved: Path, root: Path) -> str | None:
    """Serialize in-project files portably while preserving external fixtures."""
    if value is None:
        return None
    if resolved.exists():
        try:
            resolved.relative_to(root)
        except ValueError:
            return Path(str(value)).as_posix()
        return portable_path(resolved, root=root)
    return Path(str(value)).as_posix()


def _load_range(value: Any) -> tuple[float, float]:
    try:
        if len(value) != 2:
            raise ValueError
        lower, upper = map(float, value)
    except (TypeError, ValueError) as error:
        raise ValueError("Shared LUT requires a load range [0, U]") from error
    if lower != 0 or not np.isfinite(upper) or upper <= 0:
        raise ValueError("Shared LUT requires finite U > 0 and lower load 0")
    return lower, upper


def _lut_arrays(lut: Any, bounds: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(lut, dict):
        raise ValueError("Shared LUT must contain x and y arrays")
    try:
        x = np.asarray(lut["x"], dtype=float)
        y = np.asarray(lut["y"], dtype=float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Shared LUT must contain numeric x and y arrays") from error
    if x.ndim != 1 or y.ndim != 1 or x.size < 2 or x.size != y.size:
        raise ValueError("Shared LUT needs at least two matching 1-D ADC/load knots")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("Shared LUT knots must be finite")
    if np.any(np.diff(x) <= 0):
        raise ValueError("Shared LUT ADC knots must be strictly increasing")
    if np.any(np.diff(y) < 0):
        raise ValueError("Shared LUT load knots must be nondecreasing")
    if np.any(y < bounds[0]) or np.any(y > bounds[1]):
        raise ValueError("Shared LUT load knots fall outside the common calibration range")
    return x, y


def build_shared_lut(record: dict[str, Any]) -> dict[str, Any]:
    """Read and verify the exact FIT model recorded by a matched capture.

    ``record`` is the result of ``load_matched_batch``. No validation load,
    prediction, or RAW value is used to construct the shared function.
    """
    bounds = _load_range(record.get("load_range_g"))
    provenance = record.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("Shared LUT requires recorded FIT model provenance")
    path_value = provenance.get("fit")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("Shared LUT requires the recorded FIT model path")
    expected = provenance.get("fit_sha256")
    if not isinstance(expected, str):
        raise ValueError("Shared LUT requires the recorded FIT model SHA-256")
    expected = expected.strip().lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError("Recorded FIT model SHA-256 must contain 64 hexadecimal characters")
    project_root = calibration_root()
    model_path = _resolve_project_recorded_path(path_value, project_root).resolve(strict=True)
    raw = model_path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise ValueError("Recorded FIT model SHA-256 mismatch; refusing a changed shared baseline")
    model = json.loads(raw)
    if not isinstance(model, dict) or model.get("format") != "e-skin-fsr-pressure-response-monotonic-model":
        raise ValueError("Shared LUT requires the monotonic pressure-response model format")
    if model.get("version") != 3 or model.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("Shared LUT requires the frozen shared-endpoint version 3 model")
    if _load_range(model.get("load_range_g")) != bounds:
        raise ValueError("Shared LUT model range differs from the validation condition")
    module_id, fsr = record.get("module_id"), record.get("fsr")
    if module_id not in (0, 1, 2, 3) or fsr not in ("FSR1", "FSR2"):
        raise ValueError("Shared LUT record must identify module 0..3 and FSR1 or FSR2")
    if model.get("source_module_id") != module_id or model.get("source_fsr") != fsr:
        raise ValueError("Shared LUT model module or FSR differs from the validation condition")
    fitted = model.get("fit")
    mean_cell = fitted.get("mean_cell") if isinstance(fitted, dict) else None
    lut = mean_cell.get("pressure_from_adc") if isinstance(mean_cell, dict) else None
    if not isinstance(lut, dict) or lut.get("type") != "linear_lut":
        raise ValueError("Frozen mean training response must contain a linear inverse LUT")
    x, y = _lut_arrays(lut, bounds)
    training_value = model.get("source_file")
    training_path = None
    if isinstance(training_value, str) and training_value.strip():
        training_path = _resolve_project_recorded_path(training_value, project_root)
    return {
        "format": "e-skin-shared-mean-training-adc-lut-baseline", "version": 1,
        "method": METHOD, "label": "Shared LUT", "protocol_id": PROTOCOL_ID,
        "module_id": module_id, "fsr": fsr, "load_range_g": list(bounds), "unit": "g",
        "lut": {"x": x.tolist(), "y": y.tolist()},
        "source_model": {"path": _portable_existing_or_original(path_value, model_path, project_root), "sha256": observed, "version": model["version"],
                         "lut_location": "fit.mean_cell.pressure_from_adc"},
        "training_sweep": {"path": _portable_existing_or_original(training_value, training_path, project_root) if training_path is not None else None,
                           "sha256": model.get("source_sha256"),
                           "verification": "provenance copied from the hash-verified frozen FIT model; training sweep not reread"},
        "definition": "Average the 256 training RAW ADC values at each load, then apply the same PAVA and inverse-LUT construction; not the mean of 256 inverse functions",
        "prediction_rule": "Apply the one shared ADC-to-g LUT separately to each validation cell, then clamp predictions to [0,U]; preserve nonfinite RAW as NaN",
        "aggregation_rule": "Any summary is computed after per-cell prediction, never by predicting the mean validation RAW first",
        "validation_used_for_construction": False,
        "model_rebuilt": False,
    }


def predict_shared_lut(raw: Any, baseline: dict[str, Any]) -> np.ndarray:
    """Apply the shared nonlinear inverse separately to every finite ADC cell."""
    values = np.asarray(raw, dtype=float)
    if values.shape != (16, 16):
        raise ValueError("Shared LUT prediction requires one 16x16 RAW ADC matrix")
    bounds = _load_range(baseline.get("load_range_g"))
    x, y = _lut_arrays(baseline.get("lut"), bounds)
    result = np.full((16, 16), np.nan, dtype=float)
    finite = np.isfinite(values)
    result[finite] = np.clip(np.interp(values[finite], x, y), bounds[0], bounds[1])
    return result
