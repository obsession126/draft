import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException

from api.models import CrewProfile, HealthAlert, SyncBatch, TelemetryEvent


class EventConflict(APIException):
    status_code = 409
    default_code = "event_conflict"
    default_detail = "An event with this event_id already exists with different content."


@dataclass(frozen=True)
class IngestResult:
    record: TelemetryEvent
    created: bool


def canonical_digest(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def ingest_event(event):
    existing = TelemetryEvent.objects.filter(event_id=event["event_id"]).first()
    if existing is not None:
        return _existing_event_result(existing, event)

    profile = CrewProfile.objects.get(profile_id=event["context"]["profile_id"])
    measured_at = _parse_timestamp(event["measured_at"])
    recorded_at = _parse_timestamp(event["recorded_at"])
    analysis = event["analysis"]
    link_online = event["context"]["link_online"]
    try:
        with transaction.atomic():
            record = TelemetryEvent.objects.create(
                event_id=event["event_id"],
                profile=profile,
                measured_at=measured_at,
                source_recorded_at=recorded_at,
                source=event["source"],
                is_synthetic=event["is_synthetic"],
                analysis_status=analysis["status"],
                anomaly_score=analysis["score"],
                scenario=event["context"]["simulation_scenario"],
                link_online=link_online,
                data_quality=analysis["data_quality"]["status"],
                payload=event,
            )
    except IntegrityError:
        existing = TelemetryEvent.objects.filter(event_id=event["event_id"]).first()
        if existing is None:
            raise
        return _existing_event_result(existing, event)

    if analysis["status"] != TelemetryEvent.AnalysisStatus.NORMAL:
        _create_alert(record, analysis)
    return IngestResult(record=record, created=True)


def create_sync_batch(user, events, idempotency_key=None):
    digest = canonical_digest(events)
    if idempotency_key:
        previous = SyncBatch.objects.filter(
            submitted_by=user,
            idempotency_key=idempotency_key,
        ).first()
        if previous is not None:
            if previous.payload_digest != digest:
                raise EventConflict(
                    detail="This Idempotency-Key was already used for a different batch."
                )
            return previous, False

    event_ids = []
    created_count = 0
    duplicate_count = 0
    try:
        with transaction.atomic():
            if idempotency_key:
                previous = SyncBatch.objects.select_for_update().filter(
                    submitted_by=user,
                    idempotency_key=idempotency_key,
                ).first()
                if previous is not None:
                    return _existing_batch_result(previous, digest)

            for event in events:
                result = ingest_event(event)
                event_ids.append(result.record.event_id)
                if result.created:
                    created_count += 1
                else:
                    duplicate_count += 1
            batch = SyncBatch.objects.create(
                submitted_by=user,
                idempotency_key=idempotency_key,
                payload_digest=digest,
                event_ids=event_ids,
                created_count=created_count,
                duplicate_count=duplicate_count,
            )
    except IntegrityError:
        if not idempotency_key:
            raise
        previous = SyncBatch.objects.filter(
            submitted_by=user,
            idempotency_key=idempotency_key,
        ).first()
        if previous is None:
            raise
        return _existing_batch_result(previous, digest)
    return batch, True


def _existing_event_result(existing, event):
    if existing.payload != event:
        raise EventConflict()
    return IngestResult(record=existing, created=False)


def _existing_batch_result(previous, digest):
    if previous.payload_digest != digest:
        raise EventConflict(detail="This Idempotency-Key was already used for a different batch.")
    return previous, False


def _create_alert(record, analysis):
    status = analysis["status"]
    titles = {
        TelemetryEvent.AnalysisStatus.ANOMALY_REVIEW: "Unusual telemetry pattern",
        TelemetryEvent.AnalysisStatus.DATA_QUALITY_REVIEW: "Telemetry data quality needs review",
        TelemetryEvent.AnalysisStatus.INSUFFICIENT_DATA: "Insufficient telemetry for analysis",
    }
    HealthAlert.objects.create(
        profile=record.profile,
        event=record,
        title=titles[status],
        explanation=analysis["explanation"],
        evidence={
            "score": analysis["score"],
            "score_kind": analysis["score_kind"],
            "threshold": analysis["threshold"],
            "detector": analysis["detector"],
            "top_contributors": analysis["top_contributors"],
            "data_quality": analysis["data_quality"],
            "mission_context": record.payload["context"],
        },
    )


def _parse_timestamp(value):
    parsed: datetime | None = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid event timestamp: {value}")
    return parsed
