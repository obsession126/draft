import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from chatbot.server import (
    ChatbotError,
    _chat_with_gemini,
    build_grounded_context,
    ensure_synthetic_only,
    load_local_env,
    validate_model_result,
)


def sample_profile_data():
    dashboard = {
        "profile": {
            "profile_id": "crew-01",
            "display_name": "Crew Member 01",
            "mission_name": "Demo mission",
            "mission_phase": "transit",
        },
        "sync_status": "current",
        "latest": {
            "payload": {
                "schema_version": "1.0",
                "event_id": "crew-01-0001",
                "measured_at": "2026-11-14T09:00:00Z",
                "recorded_at": "2026-11-14T09:00:02Z",
                "source": "synthetic-simulator",
                "is_synthetic": True,
                "context": {
                    "mission_elapsed_min": 60,
                    "mission_phase": "transit",
                    "link_online": True,
                },
                "measurements": {
                    "hr_bpm": {
                        "value": 72.0,
                        "unit": "bpm",
                        "quality": "good",
                        "source": "simulated",
                    },
                    "spo2_percent": {
                        "value": None,
                        "unit": "%",
                        "quality": "missing",
                        "source": "simulated",
                    },
                },
                "analysis": {
                    "status": "data_quality_review",
                    "explanation": "A signal is missing.",
                    "data_quality": {"status": "review"},
                },
            }
        },
    }
    report = {
        "profile": dashboard["profile"],
        "window": {
            "sample_count": 8,
            "baseline_ready_metric_count": 1,
            "baseline_minimum_samples": 6,
            "is_synthetic": True,
        },
        "summary": {
            "current_quality_issue_count": 1,
            "latest_analysis_status": "data_quality_review",
            "interpretation_note": "Synthetic telemetry only.",
        },
        "metrics": [
            {
                "name": "hr_bpm",
                "label": "Heart rate",
                "unit": "bpm",
                "category": "cardiovascular",
                "latest_value": 72.0,
                "latest_quality": "good",
                "sample_count": 8,
                "baseline_sample_count": 6,
                "reference_median": 70.0,
                "reference_mad": 2.0,
                "delta_from_reference": 2.0,
                "change_fraction": 0.03,
                "robust_deviation": 0.67,
                "recent_median": 72.0,
                "recent_window_delta": 2.0,
                "trend_direction": "stable",
                "trend_model": {
                    "model": "xgboost-profile-trend-v1",
                    "status": "ready",
                    "direction": "rising",
                    "forecast_value": 74.0,
                    "holdout_median_absolute_error": 1.2,
                },
                "status": "within_observed_range",
                "history": [
                    {
                        "measured_at": "2026-11-14T09:00:00Z",
                        "value": 72.0,
                        "quality": "good",
                        "analysis_status": "normal",
                    }
                ],
            }
        ],
        "insights": [
            {
                "code": "data_quality",
                "severity": "review",
                "title": "A signal is missing",
                "summary": "The latest oxygen saturation signal is unavailable.",
                "interaction_summary": None,
                "evidence": ["SpO2 was missing."],
                "recommended_actions": ["Check sensor contact and repeat the reading."],
                "metric_names": ["spo2_percent"],
                "event_id": "crew-01-0001",
            }
        ],
    }
    return dashboard, report


class GroundedContextTests(unittest.TestCase):
    def test_local_env_loads_values_without_overriding_shell_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "# local chatbot settings\nGEMINI_API_KEY=file-key\n"
                "GEMINI_MODEL='gemini-test'\nexport CHATBOT_PORT=8767\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GEMINI_API_KEY": "shell-key"}, clear=True):
                load_local_env(env_path)

                self.assertEqual(os.environ["GEMINI_API_KEY"], "shell-key")
                self.assertEqual(os.environ["GEMINI_MODEL"], "gemini-test")
                self.assertEqual(os.environ["CHATBOT_PORT"], "8767")

    def test_gemini_transport_errors_are_logged_without_returning_provider_details(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("chatbot.server.urlopen", side_effect=URLError("certificate failure")):
                with self.assertLogs("chatbot", level="WARNING") as logs:
                    with self.assertRaisesRegex(ChatbotError, "Cannot reach the Google Gemini API"):
                        _chat_with_gemini("hello", [], {}, [], [])

        self.assertIn("certificate failure", logs.output[0])

    def test_context_retains_quality_baseline_and_report_actions_as_citations(self):
        dashboard, report = sample_profile_data()
        context, citations, actions, summary = build_grounded_context(dashboard, report)
        citation_ids = {item["id"] for item in citations}

        self.assertEqual(context["latest_measurements"]["spo2_percent"]["quality"], "missing")
        self.assertEqual(context["report"]["metrics"][0]["reference_median"], 70.0)
        self.assertEqual(
            context["report"]["metrics"][0]["trend_model"]["forecast_value"], 74.0
        )
        self.assertIn("insight.0", citation_ids)
        self.assertEqual(actions, [{"id": "action.0", "text": "Check sensor contact and repeat the reading."}])
        self.assertEqual(summary["analysis_status"], "data_quality_review")
        self.assertTrue(summary["is_synthetic"])

    def test_model_cannot_return_unrecognized_evidence_or_actions(self):
        dashboard, report = sample_profile_data()
        _, citations, actions, _ = build_grounded_context(dashboard, report)
        result = validate_model_result(
            {
                "answer": "The signal is missing.",
                "evidence_ids": ["measurement.spo2_percent", "made-up-evidence"],
                "action_ids": ["action.0", "made-up-action"],
            },
            citations,
            actions,
        )

        self.assertEqual([item["id"] for item in result["evidence"]], ["measurement.spo2_percent"])
        self.assertEqual([item["id"] for item in result["actions"]], ["action.0"])

    def test_empty_model_answer_is_rejected(self):
        with self.assertRaisesRegex(ChatbotError, "empty or invalid answer"):
            validate_model_result(
                {"answer": "  ", "evidence_ids": [], "action_ids": []},
                [],
                [],
            )

    def test_real_latest_telemetry_is_blocked_from_external_model(self):
        dashboard, report = sample_profile_data()
        dashboard["latest"]["payload"]["is_synthetic"] = False

        with self.assertRaisesRegex(ChatbotError, "Real health telemetry is not sent"):
            ensure_synthetic_only(dashboard, report)

    def test_report_with_real_samples_is_blocked_even_without_latest_payload(self):
        dashboard, report = sample_profile_data()
        dashboard["latest"] = None
        report["window"]["is_synthetic"] = False

        with self.assertRaisesRegex(ChatbotError, "Real health telemetry is not sent"):
            ensure_synthetic_only(dashboard, report)


if __name__ == "__main__":
    unittest.main()
