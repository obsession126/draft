import unittest
from unittest.mock import patch

from analytics.trend_forecaster import (
    MIN_HISTORY_SAMPLES,
    MODEL_VERSION,
    forecast_feature,
)


class TrendForecasterTests(unittest.TestCase):
    def test_numeric_feature_reports_forecast_direction_and_holdout_error(self):
        values = [60.0 + index * 0.5 for index in range(MIN_HISTORY_SAMPLES + 12)]

        class FakeRegressor:
            def fit(self, features, targets):
                self.feature_count = len(features[0])
                return self

            def predict(self, features):
                return [0.0] * len(features)

        with patch(
            "analytics.trend_forecaster._regressor", side_effect=FakeRegressor
        ):
            result = forecast_feature(values, unit="bpm")

        self.assertEqual(result["model"], MODEL_VERSION)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["direction"], "rising")
        self.assertIsInstance(result["forecast_value"], float)
        self.assertIsInstance(result["holdout_median_absolute_error"], float)
        self.assertGreater(result["normalized_trend"], 0)

    def test_missing_and_non_finite_samples_are_excluded(self):
        values = [float(index) for index in range(MIN_HISTORY_SAMPLES + 8)]
        values[2] = None
        values[3] = float("nan")

        class FakeRegressor:
            def fit(self, features, targets):
                return self

            def predict(self, features):
                return [0.0] * len(features)

        with patch(
            "analytics.trend_forecaster._regressor", side_effect=FakeRegressor
        ):
            result = forecast_feature(values, unit="score")

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["history_samples"], len(values) - 2)

    def test_insufficient_history_does_not_make_a_forecast(self):
        result = forecast_feature([float(index) for index in range(12)], unit="bpm")

        self.assertEqual(result["status"], "building_history")
        self.assertIsNone(result["forecast_value"])

    def test_categorical_history_uses_classifier_for_multiple_classes(self):
        values = [float(index % 2) for index in range(MIN_HISTORY_SAMPLES + 12)]

        class FakeClassifier:
            def fit(self, features, targets):
                return self

            def predict(self, features):
                return [1]

        with patch(
            "analytics.trend_forecaster._classifier", return_value=FakeClassifier()
        ):
            result = forecast_feature(values, unit="category_code")

        self.assertEqual(result["status"], "ready")
        self.assertIn(result["forecast_value"], (0, 1))

    def test_single_class_categorical_series_does_not_make_fake_forecast(self):
        values = [0.0 for _ in range(MIN_HISTORY_SAMPLES + 12)]

        result = forecast_feature(values, unit="category_code")

        self.assertEqual(result["status"], "categorical_not_forecast")
        self.assertIsNone(result["forecast_value"])


if __name__ == "__main__":
    unittest.main()
