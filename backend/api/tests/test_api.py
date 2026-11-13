import copy
import json
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.authtoken.models import Token
from django.core.management.base import CommandError
from rest_framework.test import APITestCase

from analytics.contracts import FEATURE_NAMES
from analytics.detector import NonlinearAnomalyDetector
from analytics.simulator import TelemetrySimulator
from api.models import CrewProfile, HealthAlert, TelemetryEvent
from api.management.commands.bridge_analytics import Command as AnalyticsBridgeCommand
from api.management.commands.run_mission_simulator import Command as MissionSimulatorCommand
from api.management.commands.setup_demo import Command as SetupDemoCommand


class MissionApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(username="crew", password="Strong-test-pass-98")
        cls.other_user = user_model.objects.create_user(
            username="other",
            password="Strong-test-pass-98",
        )
        cls.profile = CrewProfile.objects.create(
            profile_id="crew-01",
            owner=cls.user,
            display_name="Crew Member 01",
            mission_name="Demo mission",
        )
        cls.other_profile = CrewProfile.objects.create(
            profile_id="crew-02",
            owner=cls.other_user,
            display_name="Crew Member 02",
        )
        cls.token = Token.objects.create(user=cls.user)
        baseline = TelemetrySimulator(seed=42)
        cls.detector = NonlinearAnomalyDetector(seed=42)
        cls.detector.fit([baseline.generate_normal_vector(index) for index in range(768)])

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.simulator = TelemetrySimulator(seed=42)

    def event(self, index=1, scenario="normal"):
        event = self.simulator.generate(
            index,
            scenario,
            timestamp=datetime(2026, 11, 10, 12, 0, index % 59, tzinfo=timezone.utc),
        )
        values = {
            name: event["measurements"][name]["value"]
            for name in event["feature_names"]
        }
        qualities = {
            name: event["measurements"][name]["quality"]
            for name in event["feature_names"]
        }
        event["analysis"] = self.detector.analyze(values, qualities).to_dict()
        return event

    def test_health_is_public_and_identifies_schema_version(self):
        self.client.credentials()

        response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["telemetry_schema_version"], "1.0")

    def test_private_api_requires_authentication(self):
        self.client.credentials()

        response = self.client.get("/api/v1/profiles/")

        self.assertEqual(response.status_code, 401)

    def test_token_login_returns_a_drf_token(self):
        self.client.credentials()

        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "crew", "password": "Strong-test-pass-98"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["token"])

    def test_profiles_are_scoped_to_the_authenticated_owner(self):
        response = self.client.get("/api/v1/profiles/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["profile_id"] for item in response.data], ["crew-01"])

    def test_event_ingestion_is_idempotent_and_creates_review_alert(self):
        event = self.event(2, "interaction_shift")
        response = self.client.post(
            "/api/v1/telemetry/ingest/",
            {"event": event},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created"])
        self.assertEqual(TelemetryEvent.objects.count(), 1)
        self.assertEqual(HealthAlert.objects.count(), 1)
        self.assertEqual(HealthAlert.objects.get().evidence["top_contributors"], event["analysis"]["top_contributors"])

        repeated = self.client.post(
            "/api/v1/telemetry/ingest/",
            {"event": event},
            format="json",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.data["duplicate"])
        self.assertEqual(TelemetryEvent.objects.count(), 1)
        self.assertEqual(HealthAlert.objects.count(), 1)

    def test_event_id_reuse_with_different_content_is_conflict(self):
        event = self.event(3)
        self.client.post("/api/v1/telemetry/ingest/", {"event": event}, format="json")
        modified = copy.deepcopy(event)
        modified["measurements"]["hr_bpm"]["value"] += 1
        modified["feature_vector"][FEATURE_NAMES.index("hr_bpm")] += 1

        response = self.client.post(
            "/api/v1/telemetry/ingest/",
            {"event": modified},
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_invalid_contract_and_mismatched_vector_are_rejected(self):
        event = self.event(4)
        del event["measurements"]["hr_bpm"]
        response = self.client.post("/api/v1/telemetry/ingest/", {"event": event}, format="json")
        self.assertEqual(response.status_code, 400)

        event = self.event(5)
        event["feature_vector"][0] += 10
        response = self.client.post("/api/v1/telemetry/ingest/", {"event": event}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_ingest_or_read_another_profile(self):
        event = self.event(6)
        event["context"]["profile_id"] = self.other_profile.profile_id
        response = self.client.post("/api/v1/telemetry/ingest/", {"event": event}, format="json")
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/api/v1/profiles/crew-02/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_batch_sync_is_atomic_and_idempotent(self):
        first = self.event(7)
        second = self.event(8, "interaction_shift")
        response = self.client.post(
            "/api/v1/telemetry/sync/",
            {"events": [first, second]},
            format="json",
            HTTP_IDEMPOTENCY_KEY="offline-batch-001",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["created_count"], 2)
        self.assertEqual(response.data["event_ids"], [first["event_id"], second["event_id"]])
        self.assertEqual(TelemetryEvent.objects.count(), 2)

        replay = self.client.post(
            "/api/v1/telemetry/sync/",
            {"events": [first, second]},
            format="json",
            HTTP_IDEMPOTENCY_KEY="offline-batch-001",
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.data["idempotent_replay"])
        self.assertEqual(TelemetryEvent.objects.count(), 2)

        changed_replay = self.client.post(
            "/api/v1/telemetry/sync/",
            {"events": [first]},
            format="json",
            HTTP_IDEMPOTENCY_KEY="offline-batch-001",
        )
        self.assertEqual(changed_replay.status_code, 409)

    def test_batch_rolls_back_if_event_conflicts(self):
        existing = self.event(9)
        self.client.post("/api/v1/telemetry/ingest/", {"event": existing}, format="json")
        new_event = self.event(10, "interaction_shift")
        conflict = copy.deepcopy(existing)
        conflict["measurements"]["hr_bpm"]["value"] += 4
        conflict["feature_vector"][FEATURE_NAMES.index("hr_bpm")] += 4

        response = self.client.post(
            "/api/v1/telemetry/sync/",
            {"events": [new_event, conflict]},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(TelemetryEvent.objects.count(), 1)

    def test_dashboard_series_alert_lifecycle_and_event_filters(self):
        normal = self.event(11)
        anomaly = self.event(12, "interaction_shift")
        self.client.post("/api/v1/telemetry/ingest/", {"event": normal}, format="json")
        self.client.post("/api/v1/telemetry/ingest/", {"event": anomaly}, format="json")

        dashboard = self.client.get("/api/v1/profiles/crew-01/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.data["event_count"], 2)
        self.assertEqual(dashboard.data["latest"]["payload"]["event_id"], anomaly["event_id"])
        self.assertEqual(len(dashboard.data["open_alerts"]), 1)

        series = self.client.get(
            "/api/v1/profiles/crew-01/series/",
            {"feature": "hr_bpm", "limit": 10},
        )
        self.assertEqual(series.status_code, 200)
        self.assertEqual(series.data["feature"]["unit"], "bpm")
        self.assertEqual(series.data["count"], 2)
        self.assertEqual(series.data["points"][-1]["event_id"], anomaly["event_id"])

        filtered = self.client.get("/api/v1/telemetry/events/", {"status": "anomaly_review"})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.data["count"], 1)

        alerts = self.client.get("/api/v1/alerts/", {"profile_id": "crew-01"})
        alert_id = alerts.data["results"][0]["alert_id"]
        acknowledged = self.client.post(f"/api/v1/alerts/{alert_id}/acknowledge/")
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.data["status"], "acknowledged")
        resolved = self.client.post(f"/api/v1/alerts/{alert_id}/resolve/")
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.data["status"], "resolved")

    def test_profile_report_explains_all_features_and_nonlinear_patterns(self):
        for index in range(20, 28):
            event = self.event(index)
            response = self.client.post(
                "/api/v1/telemetry/ingest/",
                {"event": event},
                format="json",
            )
            self.assertEqual(response.status_code, 201)

        interaction = self.event(32, "interaction_shift")
        response = self.client.post(
            "/api/v1/telemetry/ingest/",
            {"event": interaction},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        report_response = self.client.get("/api/v1/profiles/crew-01/insights/")

        self.assertEqual(report_response.status_code, 200)
        report = report_response.data
        self.assertEqual(
            [metric["name"] for metric in report["metrics"]],
            list(FEATURE_NAMES),
        )
        heart_rate = next(
            metric for metric in report["metrics"] if metric["name"] == "hr_bpm"
        )
        self.assertGreaterEqual(heart_rate["baseline_sample_count"], 5)
        self.assertEqual(heart_rate["latest_value"], interaction["measurements"]["hr_bpm"]["value"])
        self.assertGreaterEqual(len(heart_rate["history"]), 8)
        nonlinear_insight = next(
            insight
            for insight in report["insights"]
            if insight["code"] == "nonlinear_pattern_review"
        )
        self.assertIn("hr_bpm", nonlinear_insight["metric_names"])
        self.assertTrue(nonlinear_insight["interaction_labels"])
        self.assertTrue(nonlinear_insight["interaction_summary"])
        self.assertIn("does not establish cause", nonlinear_insight["interaction_summary"])
        self.assertTrue(nonlinear_insight["evidence"])
        self.assertTrue(nonlinear_insight["recommended_actions"])
        self.assertIn("not a probability", " ".join(nonlinear_insight["evidence"]))
        self.assertTrue(
            all("interaction_summary" in insight for insight in report["insights"])
        )

    def test_profile_report_is_owner_scoped_and_handles_empty_history(self):
        empty_report = self.client.get("/api/v1/profiles/crew-01/insights/")
        self.assertEqual(empty_report.status_code, 200)
        self.assertEqual(empty_report.data["window"]["sample_count"], 0)
        self.assertEqual(
            empty_report.data["insights"][0]["code"],
            "waiting_for_telemetry",
        )
        self.assertIsNone(empty_report.data["insights"][0]["interaction_summary"])

        other_user = get_user_model().objects.get(username="other")
        self.client.force_authenticate(user=other_user)
        forbidden = self.client.get("/api/v1/profiles/crew-01/insights/")
        self.assertEqual(forbidden.status_code, 403)

    def test_authenticated_stream_emits_canonical_events_and_resumes(self):
        first = self.event(13)
        second = self.event(14, "interaction_shift")
        for event in (first, second):
            self.client.post("/api/v1/telemetry/ingest/", {"event": event}, format="json")

        response = self.client.get("/api/v1/telemetry/stream/?profile_id=crew-01")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/event-stream"))
        first_chunk = next(iter(response.streaming_content))
        if isinstance(first_chunk, bytes):
            first_chunk = first_chunk.decode("utf-8")
        self.assertIn(f"id: {first['event_id']}", first_chunk)
        self.assertIn('"schema_version":"1.0"', first_chunk)
        response.close()

        resumed = self.client.get(
            "/api/v1/telemetry/stream/?profile_id=crew-01",
            HTTP_LAST_EVENT_ID=first["event_id"],
        )
        self.assertEqual(resumed.status_code, 200)
        next_chunk = next(iter(resumed.streaming_content))
        if isinstance(next_chunk, bytes):
            next_chunk = next_chunk.decode("utf-8")
        self.assertIn(f"id: {second['event_id']}", next_chunk)
        resumed.close()

    def test_analytics_bridge_validates_and_forwards_sse_events(self):
        event = self.event(15)
        decoded = AnalyticsBridgeCommand._decode_event([json.dumps(event)])
        self.assertEqual(decoded["event_id"], event["event_id"])

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"event_id": event["event_id"]}
        ).encode("utf-8")
        with patch(
            "api.management.commands.bridge_analytics.urlopen",
            return_value=response,
        ) as urlopen:
            AnalyticsBridgeCommand._forward_event(
                "http://127.0.0.1:8000/api/v1/telemetry/ingest/",
                "test-token",
                event,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Token test-token")
        self.assertEqual(json.loads(request.data)["event"], event)
        with self.assertRaises(CommandError):
            AnalyticsBridgeCommand._decode_event(["{malformed"])

    def test_mission_simulator_runs_analysis_and_persists_events(self):
        output = StringIO()
        call_command(
            "run_mission_simulator",
            profile_id="crew-01",
            scenario="normal",
            interval=0.01,
            seed=42,
            max_events=2,
            stdout=output,
        )

        events = list(TelemetryEvent.objects.order_by("event_id"))
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [event.event_id for event in events],
            ["crew-01-00000000", "crew-01-00000001"],
        )
        self.assertTrue(all(event.payload["is_synthetic"] for event in events))
        self.assertTrue(all("analysis" in event.payload for event in events))
        self.assertTrue(all(len(event.payload["feature_vector"]) == 36 for event in events))
        self.assertEqual(MissionSimulatorCommand._next_sample_index(self.profile), 2)

    def test_setup_demo_is_repeatable_without_rotating_existing_password(self):
        output = StringIO()
        call_command(
            "setup_demo",
            username="demo-crew",
            password="Secure-local-demo-pass-98",
            profile_id="demo-crew-01",
            stdout=output,
        )
        call_command(
            "setup_demo",
            username="demo-crew",
            password="Secure-local-demo-pass-98",
            profile_id="demo-crew-01",
            stdout=output,
        )

        demo_user = get_user_model().objects.get(username="demo-crew")
        self.assertTrue(demo_user.check_password("Secure-local-demo-pass-98"))
        self.assertEqual(CrewProfile.objects.filter(profile_id="demo-crew-01").count(), 1)
        with self.assertRaises(CommandError):
            SetupDemoCommand().handle(
                username="demo-crew",
                password="wrong-password",
                profile_id="demo-crew-01",
                display_name="Crew Member 01",
                mission_name="Demo mission",
            )

    def test_catalog_matches_the_canonical_analytics_contract(self):
        response = self.client.get("/api/v1/metadata/parameters/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.data["features"]], list(FEATURE_NAMES))

    def test_openapi_schema_and_docs_are_available(self):
        schema = self.client.get("/api/schema/")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/v1/telemetry/ingest/", schema.data["paths"])

        docs = self.client.get("/api/docs/")
        self.assertEqual(docs.status_code, 200)
