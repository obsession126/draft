from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from analytics.engine import AnalyticsEngine
from analytics.simulator import SUPPORTED_SCENARIOS
from api.models import CrewProfile, TelemetryEvent
from api.services import ingest_event


class Command(BaseCommand):
    help = (
        "Run the synthetic sensor, nonlinear analysis, and durable backend ingestion "
        "pipeline as one process."
    )

    def add_arguments(self, parser):
        parser.add_argument("--profile-id", default="crew-01")
        parser.add_argument("--scenario", choices=SUPPORTED_SCENARIOS, default="demo")
        parser.add_argument("--interval", type=float, default=1.0)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument(
            "--max-events",
            type=int,
            default=0,
            help="Stop after this many newly persisted events; 0 runs until interrupted.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        max_events = options["max_events"]
        if interval <= 0:
            raise CommandError("--interval must be greater than zero.")
        if max_events < 0:
            raise CommandError("--max-events cannot be negative.")

        profile_id = options["profile_id"]
        try:
            profile = CrewProfile.objects.get(profile_id=profile_id)
        except CrewProfile.DoesNotExist as exc:
            raise CommandError(
                f"Crew profile '{profile_id}' does not exist. Create it first with setup_demo."
            ) from exc

        start_index = self._next_sample_index(profile)
        engine = AnalyticsEngine(
            seed=options["seed"],
            scenario=options["scenario"],
            interval_seconds=interval,
            profile_id=profile_id,
            start_index=start_index,
        )
        persisted = 0
        last_event_id = None
        self.stdout.write(
            f"Running {options['scenario']} sensor simulation for {profile_id}; "
            "events are analyzed and persisted by the backend. Press Ctrl+C to stop."
        )
        engine.start()
        try:
            while not max_events or persisted < max_events:
                event = engine.wait_for_event(last_event_id, timeout=2.0)
                if event is None:
                    continue
                close_old_connections()
                result = ingest_event(event)
                last_event_id = event["event_id"]
                if result.created:
                    persisted += 1
                self.stdout.write(
                    f"{event['event_id']}: {result.record.analysis_status} "
                    f"(score={result.record.anomaly_score}, persisted={result.created})"
                )
        except KeyboardInterrupt:
            self.stdout.write("Stopping mission simulation.")
        finally:
            engine.stop()
            close_old_connections()

    @staticmethod
    def _next_sample_index(profile):
        prefix = f"{profile.profile_id}-"
        next_index = 0
        for event_id in TelemetryEvent.objects.filter(
            profile=profile,
            event_id__startswith=prefix,
        ).values_list("event_id", flat=True):
            suffix = event_id[len(prefix) :]
            if suffix.isdigit():
                next_index = max(next_index, int(suffix) + 1)
        return next_index
