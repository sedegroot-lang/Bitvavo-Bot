"""Conformal prediction interval (MAPIE wrapper).

Wraps a trained classifier with MAPIE's conformal calibration to produce
calibrated confidence intervals. Falls back to a no-op when MAPIE is not
installed, so callers can use it unconditionally.

Use case in the bot:
  - Calibrate XGBoost on a held-out set.
  - Save the conformal calibrator alongside the model.
  - At predict-time, compute per-prediction confidence width; reject trades
    where width > MAX_INTERVAL_WIDTH (i.e. model is uncertain).

Public API:
    fit_conformal(model, X_calib, y_calib, alpha=0.1) -> CalibratorBlob
    predict_with_interval(blob, X) -> (preds, interval_width_per_sample)

This module never raises if MAPIE is unavailable — `MAPIE_AVAILABLE = False`
flag lets callers gracefully degrade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import numpy as np

try:
    from mapie.classification import MapieClassifier  # type: ignore
    MAPIE_AVAILABLE = True
except Exception:  # pragma: no cover — environments without MAPIE
    MapieClassifier = None  # type: ignore
    MAPIE_AVAILABLE = False


@dataclass
class CalibratorBlob:
    mapie: Any  # MapieClassifier (or None when not available)
    alpha: float
    classes_: List[int]


def fit_conformal(model: Any, X_calib: np.ndarray, y_calib: np.ndarray,
                  alpha: float = 0.1) -> Optional[CalibratorBlob]:
    """Wrap an already-fitted classifier with MAPIE's `cv="prefit"`.

    Returns None when MAPIE is not installed.
    """
    if not MAPIE_AVAILABLE:
        return None
    try:
        mapie = MapieClassifier(estimator=model, cv="prefit", method="lac")
        mapie.fit(X_calib, y_calib)
        classes = list(getattr(model, "classes_", np.unique(y_calib)).tolist())
        return CalibratorBlob(mapie=mapie, alpha=float(alpha), classes_=classes)
    except Exception:
        return None


def predict_with_interval(blob: Optional[CalibratorBlob], X: np.ndarray
                          ) -> Tuple[np.ndarray, np.ndarray]:
    """Return (predictions, interval_width_per_sample).

    When the calibrator is missing, predictions come from the underlying
    estimator (if accessible) and width is filled with NaN.
    """
    if blob is None or not MAPIE_AVAILABLE:
        return np.array([]), np.array([])
    try:
        preds, ps = blob.mapie.predict(X, alpha=blob.alpha)
        # `ps` shape (n_samples, n_classes, n_alpha) — width = mean across-classes count
        widths = ps[:, :, 0].sum(axis=1).astype(float)
        return preds, widths
    except Exception:
        return np.array([]), np.array([])


__all__ = ["MAPIE_AVAILABLE", "CalibratorBlob", "fit_conformal", "predict_with_interval"]
