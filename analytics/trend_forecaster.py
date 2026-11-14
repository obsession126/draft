"""Per-feature, profile-history trend forecasts using XGBoost."""

from __future__ import annotations

import math
import statistics
from typing import Any, Sequence

import numpy as np


MODEL_VERSION = "xgboost-profile-trend-v1"
LOOKBACK_SAMPLES = 8
MIN_HISTORY_SAMPLES = 36
TREND_WINDOW_SAMPLES = 12
NON_NUMERIC_UNITS = {"category_code"}
MISSION_CONTEXT_FEATURES = (
    "mission_elapsed_min",
    "eva_active",
    "link_online",
    "activity_intensity_0_1",
    "radiation_dose_rate_usv_h",
)
MEASUREMENT_CONTEXT_FEATURES = {"activity_intensity_0_1", "radiation_dose_rate_usv_h"}


def forecast_feature(
    values: Sequence[float | None],
    *,
    unit: str,
    feature_name: str | None = None,
    contexts: Sequence[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Forecast one sample from a quality-filtered feature history."""
    context_values = [None] * len(values) if contexts is None else contexts
    if len(context_values) != len(values):
        raise ValueError("contexts must have the same number of entries as values.")
    valid_pairs = [
        (float(value), context)
        for value, context in zip(values, context_values, strict=True)
        if value is not None and math.isfinite(float(value))
    ]
    valid_values = [value for value, _ in valid_pairs]
    valid_contexts = [context for _, context in valid_pairs]
    base = {
        "model": MODEL_VERSION,
        "history_samples": len(valid_values),
        "minimum_history_samples": MIN_HISTORY_SAMPLES,
        "forecast_horizon_samples": 1,
        "forecast_value": None,
        "holdout_median_absolute_error": None,
        "normalized_trend": None,
        "direction": "unknown",
        "status": "building_history",
        "unit": unit,
        "context_features": list(_context_features_for_target(feature_name)),
    }

    if len(valid_values) < MIN_HISTORY_SAMPLES:
        return base

    values_array = np.asarray(valid_values, dtype=np.float64)
    if unit in NON_NUMERIC_UNITS:
        if not np.all(np.equal(values_array, np.round(values_array))):
            return {**base, "status": "invalid_category_data"}
        return _forecast_category(
            values_array.astype(np.int64),
            _context_matrix(valid_contexts, feature_name),
            base,
        )
    return _forecast_numeric(
        values_array,
        _context_matrix(valid_contexts, feature_name),
        base,
    )


def _forecast_numeric(
    values: np.ndarray, contexts: np.ndarray, base: dict[str, Any]
) -> dict[str, Any]:
    target_count = len(values) - LOOKBACK_SAMPLES
    split = max(LOOKBACK_SAMPLES + 4, int(target_count * 0.8))
    if split >= target_count or target_count - split < 3:
        return {**base, "status": "building_history"}
    training_values = values[:split + LOOKBACK_SAMPLES]
    center = float(np.median(training_values))
    mad = float(np.median(np.abs(training_values - center)))
    scale = 1.4826 * mad
    if scale <= 1e-9:
        q25, q75 = np.quantile(training_values, [0.25, 0.75])
        scale = float(q75 - q25) / 1.349
    if scale <= 1e-9:
        scale = max(abs(center) * 1e-6, 1e-6)
    normalized = (values - center) / scale
    features, targets = _lagged_samples(normalized, contexts)

    model = _regressor()
    model.fit(features[:split], targets[:split])
    holdout_predictions = model.predict(features[split:])
    holdout_error = float(np.median(np.abs(holdout_predictions - targets[split:])) * scale)

    current_features = np.hstack(
        (normalized[-LOOKBACK_SAMPLES:], contexts[-1])
    ).reshape(1, -1)
    next_value = float(model.predict(current_features)[0] * scale + center)
    normalized_trend = _normalized_recent_trend(values[-TREND_WINDOW_SAMPLES:])
    direction = (
        "rising" if normalized_trend >= 0.75 else
        "falling" if normalized_trend <= -0.75 else
        "stable"
    )

    return {
        **base,
        "forecast_value": next_value,
        "holdout_median_absolute_error": holdout_error,
        "normalized_trend": float(normalized_trend),
        "direction": direction,
        "status": "ready",
    }


def _forecast_category(
    labels: np.ndarray, contexts: np.ndarray, base: dict[str, Any]
) -> dict[str, Any]:
    features, targets = _lagged_samples(labels.astype(np.float64), contexts)
    split = max(LOOKBACK_SAMPLES + 4, int(len(targets) * 0.8))
    if split >= len(targets) or len(targets) - split < 3:
        return {**base, "status": "building_history"}

    classes, train_targets = np.unique(
        targets[:split].astype(np.int64), return_inverse=True
    )
    if len(classes) < 2:
        return {**base, "status": "categorical_not_forecast"}

    model = _classifier()
    model.fit(features[:split], train_targets)
    current_features = np.hstack(
        (labels[-LOOKBACK_SAMPLES:].astype(np.float64), contexts[-1])
    ).reshape(1, -1)
    predicted_class = int(
        model.predict(current_features)[0]
    )
    prediction = int(classes[predicted_class])
    recent_mode = statistics.mode(labels[-TREND_WINDOW_SAMPLES:].tolist())
    return {
        **base,
        "forecast_value": prediction,
        "holdout_median_absolute_error": None,
        "normalized_trend": None,
        "direction": "category_changed" if prediction != recent_mode else "stable",
        "status": "ready",
    }


def _lagged_samples(
    values: np.ndarray, contexts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray(
        [
            np.hstack(
                (
                    values[index - LOOKBACK_SAMPLES:index],
                    contexts[index - 1],
                )
            )
            for index in range(LOOKBACK_SAMPLES, len(values))
        ],
        dtype=np.float64,
    )
    targets = values[LOOKBACK_SAMPLES:].astype(np.float64)
    return features, targets


def _context_features_for_target(feature_name: str | None) -> tuple[str, ...]:
    return tuple(
        name
        for name in MISSION_CONTEXT_FEATURES
        if name != feature_name
    )


def _context_matrix(
    contexts: Sequence[dict[str, Any] | None], feature_name: str | None
) -> np.ndarray:
    names = _context_features_for_target(feature_name)
    rows = []
    for context in contexts:
        context = context or {}
        row = []
        for name in names:
            if name in MEASUREMENT_CONTEXT_FEATURES:
                measurements = context.get("measurements")
                measurement = measurements.get(name) if isinstance(measurements, dict) else None
                value = (
                    measurement.get("value")
                    if isinstance(measurement, dict)
                    and measurement.get("quality") == "good"
                    else None
                )
            else:
                value = context.get(name)
            if isinstance(value, bool):
                row.append(float(value))
            elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                row.append(float(value))
            else:
                row.append(np.nan)
        rows.append(row)
    return np.asarray(rows, dtype=np.float64).reshape(len(contexts), len(names))


def _median_slope(values: np.ndarray) -> float:
    slopes = [
        (float(values[right]) - float(values[left])) / (right - left)
        for left in range(len(values) - 1)
        for right in range(left + 1, len(values))
    ]
    return float(statistics.median(slopes)) if slopes else 0.0


def _normalized_recent_trend(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    slope = _median_slope(values)
    positions = np.arange(len(values), dtype=np.float64)
    intercept = float(np.median(values - slope * positions))
    residuals = values - (intercept + slope * positions)
    residual_center = float(np.median(residuals))
    noise = 1.4826 * float(np.median(np.abs(residuals - residual_center)))
    if noise <= 1e-9:
        noise = max(abs(float(np.median(values))) * 1e-6, 1e-6)
    return slope * (len(values) - 1) / noise


def _regressor():
    from xgboost import XGBRegressor

    return XGBRegressor(
        objective="reg:squarederror",
        n_estimators=48,
        max_depth=2,
        learning_rate=0.05,
        min_child_weight=3,
        reg_lambda=5.0,
        subsample=1.0,
        colsample_bytree=1.0,
        tree_method="hist",
        n_jobs=1,
        random_state=42,
        verbosity=0,
    )


def _classifier():
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=48,
        max_depth=2,
        learning_rate=0.05,
        min_child_weight=3,
        reg_lambda=5.0,
        subsample=1.0,
        colsample_bytree=1.0,
        tree_method="hist",
        n_jobs=1,
        random_state=42,
        eval_metric="mlogloss",
        verbosity=0,
    )
