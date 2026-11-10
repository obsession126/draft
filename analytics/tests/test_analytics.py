from __future__ import annotations

import json
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

from analytics.contracts import ANALYSIS_VERSION, FEATURE_NAMES, SCHEMA_VERSION
from analytics.detector import NonlinearAnomalyDetector
from analytics.engine import AnalyticsEngine
from analytics.server import AnalyticsHTTPServer
from analytics.simulator import TelemetrySimulator


class AnomalyDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        calibration = TelemetrySimulator(seed=11)
        cls.detector = NonlinearAnomalyDetector(seed=11)
        cls.detector.fit([calibration.generate_normal_vector(i) for i in range(768)])

    def test_quadratic_interaction_shift_is_ranked_as_anomaly(self) -> None:
        simulator = TelemetrySimulator(seed=11)
        event = simulator.generate(
            20,
            "interaction_shift",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        values = {name: event["measurements"][name]["value"] for name in FEATURE_NAMES}
        quality = {name: event["measurements"][name]["quality"] for name in FEATURE_NAMES}

        result = self.detector.analyze(values, quality)

        self.assertEqual(result.status, "anomaly_review")
        self.assertGreaterEqual(result.score, result.threshold)
        self.assertTrue(
            any(
                item["label"].startswith("hr_bpm given activity_intensity_0_1")
                for item in result.top_contributors
            )
        )
        self.assertLessEqual(result.score, 1.0)

    def test_synthetic_radiation_spike_is_detected(self) -> None:
        simulator = TelemetrySimulator(seed=11)
        event = simulator.generate(0, "radiation_event")
        values = {name: event["measurements"][name]["value"] for name in FEATURE_NAMES}
        quality = {name: event["measurements"][name]["quality"] for name in FEATURE_NAMES}

        result = self.detector.analyze(values, quality)

        self.assertEqual(result.status, "anomaly_review")

    def test_low_quality_signal_never_returns_normal_status(self) -> None:
        simulator = TelemetrySimulator(seed=11)
        values = simulator.generate_normal_vector(1)
        quality = {name: "good" for name in FEATURE_NAMES}
        quality["spo2_percent"] = "low"

        result = self.detector.analyze(values, quality)

        self.assertEqual(result.status, "data_quality_review")
        self.assertIn("spo2_percent", result.data_quality["low_quality_features"])

    def test_baseline_vector_is_not_flagged(self) -> None:
        simulator = TelemetrySimulator(seed=11)
        event = simulator.generate(0, "normal")
        values = {name: event["measurements"][name]["value"] for name in FEATURE_NAMES}
        quality = {name: event["measurements"][name]["quality"] for name in FEATURE_NAMES}

        result = self.detector.analyze(values, quality)

        self.assertEqual(result.status, "normal")

    def test_baseline_stream_stays_within_demo_false_alarm_budget(self) -> None:
        simulator = TelemetrySimulator(seed=101)
        anomaly_count = 0
        for index in range(200):
            event = simulator.generate(index, "normal")
            values = {name: event["measurements"][name]["value"] for name in FEATURE_NAMES}
            quality = {name: event["measurements"][name]["quality"] for name in FEATURE_NAMES}
            anomaly_count += self.detector.analyze(values, quality).status == "anomaly_review"

        self.assertLessEqual(anomaly_count, 6)

    def test_excessive_missing_data_is_not_scored_as_normal(self) -> None:
        simulator = TelemetrySimulator(seed=11)
        values = simulator.generate_normal_vector(1)
        quality = {name: "good" for name in FEATURE_NAMES}
        for name in FEATURE_NAMES[:10]:
            values[name] = None
            quality[name] = "missing"

        result = self.detector.analyze(values, quality)

        self.assertEqual(result.status, "insufficient_data")
        self.assertIsNone(result.score)


class SimulatorContractTests(unittest.TestCase):
    def test_json_schema_feature_order_matches_runtime_contract(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "event.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["properties"]["feature_names"]["const"], list(FEATURE_NAMES))
        self.assertEqual(schema["properties"]["feature_vector"]["minItems"], len(FEATURE_NAMES))
        self.assertEqual(schema["properties"]["measurements"]["required"], list(FEATURE_NAMES))
        self.assertEqual(
            ANALYSIS_VERSION,
            schema["properties"]["analysis"]["properties"]["detector"]["const"],
        )

    def test_sample_has_all_features_and_explicit_synthetic_origin(self) -> None:
        simulator = TelemetrySimulator(seed=7)
        event = simulator.generate(
            0,
            "normal",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(event["schema_version"], SCHEMA_VERSION)
        self.assertTrue(event["is_synthetic"])
        self.assertEqual(event["feature_names"], list(FEATURE_NAMES))
        self.assertEqual(len(event["feature_vector"]), len(FEATURE_NAMES))
        self.assertEqual(set(event["measurements"]), set(FEATURE_NAMES))
        self.assertIn("link_online", event["context"])


class AnalyticsAPITests(unittest.TestCase):
    def test_event_stream_resumes_with_the_next_event(self) -> None:
        engine = AnalyticsEngine(
            seed=13,
            scenario="normal",
            interval_seconds=0.02,
            calibration_samples=768,
        )
        engine.start()
        try:
            first = engine.wait_for_event(None, timeout=2)
            self.assertIsNotNone(first)
            following = engine.wait_for_event(first["event_id"], timeout=2)
            self.assertIsNotNone(following)
            self.assertNotEqual(first["event_id"], following["event_id"])
        finally:
            engine.stop()

    def test_snapshot_and_history_are_json_serializable(self) -> None:
        engine = AnalyticsEngine(
            seed=13,
            scenario="normal",
            interval_seconds=0.02,
            calibration_samples=768,
        )
        server = AnalyticsHTTPServer(("127.0.0.1", 0), engine)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        engine.start()
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            self.assertIsNotNone(engine.wait_for_event(None, timeout=10))
            connection.request("GET", "/api/v1/snapshot")
            response = connection.getresponse()
            snapshot = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(snapshot["schema_version"], SCHEMA_VERSION)
            self.assertIsNotNone(snapshot["latest"])

            connection.request("GET", "/api/v1/history?limit=3")
            response = connection.getresponse()
            history = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertLessEqual(history["count"], 3)
            self.assertIn("analysis", history["items"][-1])

            connection.request("GET", "/api/v1/history?limit=bad")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            engine.stop()


if __name__ == "__main__":
    unittest.main()
