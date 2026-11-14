"""Nonlinear, unsupervised anomaly detector with synthetic-only calibration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import PolynomialFeatures, RobustScaler

from analytics.contracts import ANALYSIS_VERSION, FEATURE_NAMES

CONDITIONAL_MODELS = {
    "hr_bpm": ("activity_intensity_0_1", "movement_rms_g", "activity_duration_min"),
    "hrv_ms": ("hr_bpm", "activity_intensity_0_1", "sleep_duration_min"),
    "respiratory_rate_bpm": ("hr_bpm", "activity_intensity_0_1", "movement_rms_g"),
    "spo2_percent": ("respiratory_rate_bpm", "o2_percent", "radiation_dose_rate_usv_h"),
    "sleep_quality_1_5": ("sleep_duration_min", "sleep_awakenings", "stress_self_report_0_10"),
}
UNIVARIATE_EXCLUDED_FEATURES = {"cumulative_dose_usv"}


@dataclass(frozen=True)
class Detection:
    status: str
    score: float | None
    threshold: float
    detector: str
    explanation: str
    top_contributors: list[dict[str, object]]
    data_quality: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "score": self.score,
            "score_kind": "empirical_tail_rank_not_probability",
            "threshold": self.threshold,
            "detector": self.detector,
            "explanation": self.explanation,
            "top_contributors": self.top_contributors,
            "data_quality": self.data_quality,
        }


class NonlinearAnomalyDetector:
    """Conditional residual and Isolation Forest ensemble for nonlinear outliers."""

    def __init__(
        self,
        *,
        seed: int = 42,
        threshold: float = 0.99,
        min_valid_fraction: float = 0.8,
        n_estimators: int = 160,
    ) -> None:
        if not 0.5 < threshold < 1.0:
            raise ValueError("threshold must be between 0.5 and 1.")
        if not 0.0 < min_valid_fraction <= 1.0:
            raise ValueError("min_valid_fraction must be in (0, 1].")
        self.threshold = threshold
        self.min_valid_fraction = min_valid_fraction
        self._seed = seed
        self._n_estimators = n_estimators
        self._raw_scaler = RobustScaler(quantile_range=(10.0, 90.0))
        self._polynomial = PolynomialFeatures(degree=2, include_bias=False)
        self._interaction_scaler = RobustScaler(quantile_range=(10.0, 90.0))
        self._model: IsolationForest | None = None
        self._conditional_models: dict[str, RandomForestRegressor] = {}
        self._conditional_scales: dict[str, float] = {}
        self._conditional_features: dict[str, list[str]] = {}
        self._univariate_centers: dict[str, float] = {}
        self._univariate_scales: dict[str, float] = {}
        self._component_centers: dict[str, float] = {}
        self._component_scales: dict[str, float] = {}
        self._training_scores: np.ndarray | None = None
        self._combined_calibration_scores: np.ndarray | None = None
        self._training_medians: np.ndarray | None = None
        self._explanation_names: list[str] | None = None

    def fit(self, normal_samples: Sequence[dict[str, float | None]]) -> None:
        if len(normal_samples) < 384:
            raise ValueError("At least 384 clean baseline samples are required.")
        matrix = self._matrix(normal_samples)
        if not np.isfinite(matrix).all():
            raise ValueError("Calibration samples must contain complete finite features.")
        permutation = np.random.default_rng(self._seed).permutation(len(matrix))
        matrix = matrix[permutation]
        raw_scaled = self._raw_scaler.fit_transform(matrix)
        predictor_count = len(matrix) // 2
        model_fit_end = len(matrix) * 3 // 4
        fit_values = raw_scaled[:predictor_count]
        model_fit_values = raw_scaled[predictor_count:model_fit_end]
        calibration_values = raw_scaled[model_fit_end:]
        self._fit_conditional_models(fit_values)
        expanded = self._polynomial.fit_transform(raw_scaled)
        calibration_residuals = self._conditional_residuals(calibration_values)
        self._fit_univariate_calibration(calibration_values)
        model_fit_residuals = self._conditional_residuals(model_fit_values)
        model_fit_expanded = np.column_stack(
            (expanded[predictor_count:model_fit_end], model_fit_residuals)
        )
        calibration_expanded = np.column_stack(
            (expanded[model_fit_end:], calibration_residuals)
        )
        model_fit_matrix = self._interaction_scaler.fit_transform(model_fit_expanded)
        calibration_matrix = self._interaction_scaler.transform(calibration_expanded)
        self._model = IsolationForest(
            n_estimators=self._n_estimators,
            max_samples=min(256, len(model_fit_matrix)),
            contamination="auto",
            random_state=self._seed,
            n_jobs=1,
        )
        self._model.fit(model_fit_matrix)
        self._training_scores = self._model.score_samples(calibration_matrix)
        self._training_medians = np.median(model_fit_matrix, axis=0)
        component_values = {
            "forest": -self._training_scores,
            "conditional": np.max(np.abs(calibration_residuals), axis=1),
            "univariate": np.asarray(
                [
                    self._univariate_component_magnitude(row)
                    for row in calibration_values
                ],
                dtype=float,
            ),
        }
        for name, values in component_values.items():
            center = float(np.median(values))
            mad = float(np.median(np.abs(values - center)))
            self._component_centers[name] = center
            self._component_scales[name] = max(1.4826 * mad, 1e-6)
        standardized_components = [
            (values - self._component_centers[name]) / self._component_scales[name]
            for name, values in component_values.items()
        ]
        self._combined_calibration_scores = np.sort(
            np.maximum.reduce(standardized_components)
        )
        self._explanation_names = list(
            self._polynomial.get_feature_names_out(FEATURE_NAMES)
        ) + list(self._conditional_models)

    def analyze(
        self,
        sample: dict[str, float | None],
        quality: dict[str, str],
    ) -> Detection:
        if (
            self._training_scores is None
            or self._training_medians is None
            or self._model is None
            or self._combined_calibration_scores is None
        ):
            raise RuntimeError("The anomaly detector must be fitted before analysis.")

        missing_features = [
            name for name in FEATURE_NAMES if quality.get(name) == "missing" or sample.get(name) is None
        ]
        low_quality_features = [
            name for name in FEATURE_NAMES if quality.get(name) == "low"
        ]
        invalid_features = [
            name
            for name in FEATURE_NAMES
            if sample.get(name) is not None
            and not np.isfinite(float(sample[name]))
        ]
        invalid_features = sorted(set(invalid_features) - set(missing_features))
        invalid_features = sorted(set(invalid_features) - set(low_quality_features))
        excluded_features = set(missing_features + low_quality_features + invalid_features)
        valid_count = len(FEATURE_NAMES) - len(excluded_features)
        valid_fraction = max(0.0, valid_count / len(FEATURE_NAMES))
        data_quality = {
            "valid_fraction": round(valid_fraction, 3),
            "missing_features": missing_features,
            "low_quality_features": low_quality_features,
            "invalid_features": invalid_features,
            "status": "good" if not excluded_features else "partial",
        }
        if valid_fraction < self.min_valid_fraction:
            return Detection(
                status="insufficient_data",
                score=None,
                threshold=self.threshold,
                detector=ANALYSIS_VERSION,
                explanation="Недостатньо якісних вимірів для надійного багатовимірного аналізу.",
                top_contributors=[],
                data_quality=data_quality,
            )

        raw_values = [
            self._raw_scaler.center_[index]
            if name in excluded_features
            else float(sample[name])
            for index, name in enumerate(FEATURE_NAMES)
        ]
        matrix = np.asarray([raw_values], dtype=float)
        raw_scaled = self._raw_scaler.transform(matrix)
        expanded = self._polynomial.transform(raw_scaled)
        conditional_residuals = self._conditional_residuals(raw_scaled)
        expanded_with_residuals = np.column_stack((expanded, conditional_residuals))
        model_matrix = self._interaction_scaler.transform(expanded_with_residuals)
        model_score = float(self._model.score_samples(model_matrix)[0])
        standardized_components = (
            self._standardize_component("forest", -model_score),
            self._standardize_component(
                "conditional",
                float(np.max(np.abs(conditional_residuals[0]))),
            ),
            self._standardize_component(
                "univariate",
                self._univariate_component_magnitude(raw_scaled[0]),
            ),
        )
        combined_component_score = max(standardized_components)
        score = float(np.mean(self._combined_calibration_scores <= combined_component_score))
        score = min(1.0, max(0.0, score))

        is_anomaly = score >= self.threshold
        has_quality_issue = bool(excluded_features)
        status = "anomaly_review" if is_anomaly else "normal"
        if has_quality_issue and not is_anomaly:
            status = "data_quality_review"

        contributors = self._rank_contributors(model_matrix[0])
        if is_anomaly:
            explanation = (
                "Комбінація векторних ознак відрізняється від синтетичного базлайну; "
                "це алгоритмічний сигнал для перевірки, не медичний висновок."
            )
        elif has_quality_issue:
            explanation = (
                "Частина сигналів відсутня або має низьку якість; "
                "нормальний стан за цим результатом не підтверджується."
            )
        else:
            explanation = "Вектор не перевищив демонстраційний поріг відносно синтетичного базлайну."

        return Detection(
            status=status,
            score=round(score, 4),
            threshold=self.threshold,
            detector=ANALYSIS_VERSION,
            explanation=explanation,
            top_contributors=contributors,
            data_quality=data_quality,
        )

    @staticmethod
    def _matrix(samples: Sequence[dict[str, float | None]]) -> np.ndarray:
        rows: list[list[float]] = []
        for sample in samples:
            row = []
            for name in FEATURE_NAMES:
                value = sample.get(name)
                if value is None:
                    raise ValueError(f"Calibration feature '{name}' is missing.")
                row.append(float(value))
            rows.append(row)
        return np.asarray(rows, dtype=float)

    def _fit_conditional_models(self, values: np.ndarray) -> None:
        for offset, (target, predictors) in enumerate(CONDITIONAL_MODELS.items()):
            target_index = FEATURE_NAMES.index(target)
            predictor_indices = [FEATURE_NAMES.index(name) for name in predictors]
            model = RandomForestRegressor(
                n_estimators=96,
                max_features=1.0,
                min_samples_leaf=8,
                random_state=self._seed + offset,
                n_jobs=1,
            )
            model.fit(values[:, predictor_indices], values[:, target_index])
            self._conditional_models[target] = model
            self._conditional_features[target] = [target, *predictors]

    def _conditional_residuals(self, values: np.ndarray) -> np.ndarray:
        residuals: list[np.ndarray] = []
        for target, model in self._conditional_models.items():
            target_index = FEATURE_NAMES.index(target)
            predictors = list(CONDITIONAL_MODELS[target])
            predictor_indices = [FEATURE_NAMES.index(name) for name in predictors]
            predicted = model.predict(values[:, predictor_indices])
            actual = values[:, target_index]
            residual = actual - predicted
            scale = self._conditional_scales.get(target)
            if scale is None:
                median = float(np.median(residual))
                mad = float(np.median(np.abs(residual - median)))
                scale = max(1.4826 * mad, 0.25)
                self._conditional_scales[target] = scale
            residuals.append(residual / scale)
        return np.column_stack(residuals)

    def _fit_univariate_calibration(self, values: np.ndarray) -> None:
        for index, name in enumerate(FEATURE_NAMES):
            if name in UNIVARIATE_EXCLUDED_FEATURES:
                continue
            center = float(np.median(values[:, index]))
            mad = float(np.median(np.abs(values[:, index] - center)))
            self._univariate_centers[name] = center
            self._univariate_scales[name] = max(1.4826 * mad, 0.25)

    def _univariate_component_magnitude(self, values: np.ndarray) -> float:
        deviations = []
        for index, name in enumerate(FEATURE_NAMES):
            if name in UNIVARIATE_EXCLUDED_FEATURES:
                continue
            deviation = abs(float(values[index]) - self._univariate_centers[name])
            deviations.append(deviation / self._univariate_scales[name])
        return max(deviations, default=0.0)

    def _standardize_component(self, name: str, value: float) -> float:
        return (value - self._component_centers[name]) / self._component_scales[name]

    def _rank_contributors(self, model_vector: np.ndarray) -> list[dict[str, object]]:
        assert self._training_medians is not None
        assert self._explanation_names is not None
        deviations = np.abs(model_vector - self._training_medians)
        ranked_indices = np.argsort(deviations)[::-1]
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        for index in ranked_indices:
            name = self._explanation_names[int(index)]
            if name in self._conditional_features:
                related_features = self._conditional_features[name]
                contributing_features = related_features[:2]
                label = f"{related_features[0]} given " + " × ".join(related_features[1:])
                kind = "interaction"
            else:
                contributing_features = [
                    feature for feature in FEATURE_NAMES if feature in name.split()
                ]
                if not contributing_features:
                    continue
                label = " × ".join(contributing_features)
                kind = "interaction" if len(contributing_features) > 1 else "feature"
            if label in seen:
                continue
            seen.add(label)
            results.append(
                {
                    "features": contributing_features,
                    "label": label,
                    "deviation_magnitude": round(float(deviations[index]), 3),
                    "kind": kind,
                }
            )
            if len(results) == 5:
                break
        return results
