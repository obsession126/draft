from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.services import canonical_digest
from api.models import TelemetryEvent, TelemetryTrendBucket
from api.trend_buckets import aggregate_event_payload, merge_aggregate_stats


RETENTION_DAYS = 7
LATE_EVENT_GRACE = timedelta(minutes=2)
CHUNK_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Roll telemetry into one-minute trend buckets and redact eligible raw payloads "
        "older than seven days."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        completed_before = (now - LATE_EVENT_GRACE).replace(second=0, microsecond=0)
        retention_cutoff = now - timedelta(days=RETENTION_DAYS)
        compacted_count = 0
        bucket_count = 0
        while True:
            with transaction.atomic():
                events = list(
                    TelemetryEvent.objects.filter(
                        measured_at__lt=completed_before,
                        aggregated_at__isnull=True,
                    )
                    .only("event_id", "profile_id", "measured_at", "payload")
                    .order_by("measured_at", "event_id")
                    .select_for_update()[:CHUNK_SIZE]
                )
                if not events:
                    break
                groups = {}
                for event in events:
                    bucket_start = event.measured_at.replace(second=0, microsecond=0)
                    key = (event.profile_id, bucket_start)
                    event_stats = aggregate_event_payload(event.payload)
                    if key not in groups:
                        groups[key] = event_stats
                    else:
                        merge_aggregate_stats(groups[key], event_stats)
                self._flush(groups, [event.event_id for event in events], now)
                compacted_count += len(events)
                bucket_count += len(groups)

        archived_count = 0
        archive_queryset = TelemetryEvent.objects.filter(
            measured_at__lt=retention_cutoff,
            aggregated_at__isnull=False,
            alert__isnull=True,
            is_archived=False,
        ).only("event_id", "payload", "payload_digest")
        archive_batch = []
        for event in archive_queryset.iterator(chunk_size=CHUNK_SIZE):
            event.payload_digest = event.payload_digest or canonical_digest(event.payload)
            event.payload = {}
            event.is_archived = True
            archive_batch.append(event)
            if len(archive_batch) >= CHUNK_SIZE:
                archived_count += TelemetryEvent.objects.bulk_update(
                    archive_batch,
                    ("payload_digest", "payload", "is_archived"),
                    batch_size=CHUNK_SIZE,
                )
                archive_batch = []
        if archive_batch:
            archived_count += TelemetryEvent.objects.bulk_update(
                archive_batch,
                ("payload_digest", "payload", "is_archived"),
                batch_size=CHUNK_SIZE,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Aggregated {compacted_count} events into {bucket_count} minute buckets; "
                f"redacted {archived_count} raw payloads older than {RETENTION_DAYS} days. "
                "Alert-linked raw evidence was preserved."
            )
        )

    @staticmethod
    def _flush(groups, event_ids, aggregated_at):
        with transaction.atomic():
            for (profile_id, bucket_start), incoming in groups.items():
                bucket, _ = TelemetryTrendBucket.objects.get_or_create(
                    profile_id=profile_id,
                    bucket_start=bucket_start,
                    defaults={
                        "event_count": 0,
                        "metrics": {},
                        "context_stats": {},
                        "analysis_status_counts": {},
                        "source_counts": {},
                        "synthetic_event_count": 0,
                    },
                )
                bucket = TelemetryTrendBucket.objects.select_for_update().get(
                    pk=bucket.pk
                )
                target = {
                    "event_count": bucket.event_count,
                    "metrics": bucket.metrics,
                    "context_stats": bucket.context_stats,
                    "analysis_status_counts": bucket.analysis_status_counts,
                    "source_counts": bucket.source_counts,
                    "synthetic_event_count": bucket.synthetic_event_count,
                }
                merge_aggregate_stats(target, incoming)
                bucket.event_count = target["event_count"]
                bucket.metrics = target["metrics"]
                bucket.context_stats = target["context_stats"]
                bucket.analysis_status_counts = target["analysis_status_counts"]
                bucket.source_counts = target["source_counts"]
                bucket.synthetic_event_count = target["synthetic_event_count"]
                bucket.save()
            TelemetryEvent.objects.filter(event_id__in=event_ids).update(
                aggregated_at=aggregated_at
            )
