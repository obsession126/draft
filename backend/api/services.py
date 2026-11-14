import hashlib
import json
import math
import statistics
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException

from analytics.contracts import FEATURE_BY_NAME, FEATURES, SCHEMA_VERSION
from analytics.trend_forecaster import MODEL_VERSION, forecast_feature
from api.models import (
    CrewProfile,
    HealthAlert,
    SyncBatch,
    TelemetryEvent,
    TelemetryTrendBucket,
)
from api.trend_buckets import (
    aggregate_event_payload,
    merge_aggregate_stats,
    metric_value,
    model_context,
)


class EventConflict(APIException):
    status_code = 409
    default_code = "event_conflict"
    default_detail = "An event with this event_id already exists with different content."


@dataclass(frozen=True)
class IngestResult:
    record: TelemetryEvent
    created: bool


REPORT_RECENT_WINDOW = 12
REPORT_MIN_BASELINE_SAMPLES = 5
REPORT_SHIFT_ROBUST_DEVIATIONS = 2.5
REPORT_FEATURE_HISTORY_LIMIT = 48
REPORT_TREND_MODEL_LIMIT = 2000
REPORT_NON_NUMERIC_UNITS = {"category_code"}


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
                payload_digest=canonical_digest(event),
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


def build_profile_report(profile, limit=120):
    records = list(
        profile.telemetry_events.filter(is_archived=False)
        .order_by("-measured_at", "-event_id")[:limit]
    )
    records.reverse()
    trend_samples = _build_profile_trend_samples(profile)
    latest = records[-1] if records else None
    recent_window_size = min(REPORT_RECENT_WINDOW, max(1, len(records) // 4))
    recent_records = records[-recent_window_size:] if records else []
    baseline_records = records[:-recent_window_size] if records else []
    baseline_normal_records = [
        record
        for record in baseline_records
        if record.analysis_status == TelemetryEvent.AnalysisStatus.NORMAL
        and record.aggregated_at is None
    ]
    latest_trend_sample = (
        trend_samples[FEATURES[0].name][-1]
        if trend_samples[FEATURES[0].name]
        else None
    )
    latest_record_is_current = (
        latest is not None
        and (
            latest_trend_sample is None
            or latest.aggregated_at is None
            or latest.measured_at
            >= latest_trend_sample["measured_at"] + timedelta(minutes=1)
        )
    )

    metrics = [
        _build_metric_report(
            feature,
            records,
            recent_records,
            baseline_normal_records,
            trend_samples[feature.name],
        )
        for feature in FEATURES
    ]
    insights = _build_report_insights(records, metrics, baseline_normal_records)
    recent_counts = Counter(record.analysis_status for record in recent_records)
    latest_analysis = (
        latest.payload["analysis"] if latest_record_is_current else None
    )
    latest_analysis_status = (
        latest.analysis_status
        if latest_record_is_current
        else latest_trend_sample["analysis_status"]
        if latest_trend_sample
        else None
    )
    baseline_value_count = sum(
        metric["baseline_sample_count"] >= REPORT_MIN_BASELINE_SAMPLES
        for metric in metrics
        if metric["unit"] not in REPORT_NON_NUMERIC_UNITS
    )
    current_quality_issue_count = sum(
        metric["latest_quality"] in {"low", "missing"} for metric in metrics
    )
    shifted_metrics = [
        metric["name"] for metric in metrics if metric["status"] == "shift"
    ]
    baseline_event_ids = {record.event_id for record in baseline_normal_records}
    recent_event_ids = {record.event_id for record in recent_records}
    baseline_sample_count = sum(
        sample["analysis_status"] == TelemetryEvent.AnalysisStatus.NORMAL
        and (
            sample["source_type"] == "minute_aggregate"
            or sample["event_id"] in baseline_event_ids
            or sample["event_id"] not in recent_event_ids
        )
        for sample in trend_samples[FEATURES[0].name]
    )
    bucket_counts = profile.trend_buckets.aggregate(
        event_count=Sum("event_count"),
        synthetic_event_count=Sum("synthetic_event_count"),
    )
    unaggregated_events = profile.telemetry_events.filter(aggregated_at__isnull=True)
    sample_count = (bucket_counts["event_count"] or 0) + unaggregated_events.count()
    bucket_first = profile.trend_buckets.order_by("bucket_start").values_list(
        "bucket_start", flat=True
    ).first()
    bucket_last = profile.trend_buckets.order_by("-bucket_start").values_list(
        "bucket_start", flat=True
    ).first()
    first_candidates = [record.measured_at for record in records]
    last_candidates = [record.measured_at for record in records]
    if bucket_first is not None:
        first_candidates.append(bucket_first)
    if bucket_last is not None:
        last_candidates.append(bucket_last)
    synthetic_exists = (
        (bucket_counts["synthetic_event_count"] or 0) > 0
        or unaggregated_events.filter(is_synthetic=True).exists()
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "mission_name": profile.mission_name,
            "mission_phase": profile.mission_phase,
        },
        "generated_at": timezone.now(),
        "window": {
            "sample_count": sample_count,
            "recent_sample_count": len(recent_records),
            "baseline_sample_count": baseline_sample_count,
            "first_measured_at": min(first_candidates) if first_candidates else None,
            "last_measured_at": max(last_candidates) if last_candidates else None,
            "baseline_source": "this_profile_prior_normal_quality_events_and_minute_aggregates",
            "baseline_method": "median and median absolute deviation",
            "baseline_ready_metric_count": baseline_value_count,
            "baseline_minimum_samples": REPORT_MIN_BASELINE_SAMPLES,
            "is_synthetic": synthetic_exists,
        },
        "summary": {
            "latest_analysis_status": latest_analysis_status,
            "recent_event_count": len(recent_records),
            "recent_anomaly_review_count": recent_counts[
                TelemetryEvent.AnalysisStatus.ANOMALY_REVIEW
            ],
            "recent_data_quality_review_count": recent_counts[
                TelemetryEvent.AnalysisStatus.DATA_QUALITY_REVIEW
            ],
            "recent_insufficient_data_count": recent_counts[
                TelemetryEvent.AnalysisStatus.INSUFFICIENT_DATA
            ],
            "current_quality_issue_count": current_quality_issue_count,
            "historical_shift_metric_count": len(shifted_metrics),
            "historical_shift_metrics": shifted_metrics,
            "trend_model_version": MODEL_VERSION,
            "trend_model_ready_metric_count": sum(
                metric["trend_model"]["status"] == "ready" for metric in metrics
            ),
            "trend_model_building_metric_count": sum(
                metric["trend_model"]["status"] == "building_history"
                for metric in metrics
            ),
            "latest_analysis": latest_analysis,
            "interpretation_note": (
                "This report includes exploratory per-feature trend forecasts and "
                "observed changes. They are not health probabilities, diagnoses, or "
                "medically validated thresholds."
            ),
        },
        "metrics": metrics,
        "insights": insights,
    }


def build_profile_series(profile, feature, *, limit, since=None, until=None):
    samples = _build_profile_trend_samples(
        profile,
        limit=limit,
        since=since,
        until=until,
    )[feature.name]
    return [
        {
            "event_id": sample["event_id"],
            "measured_at": sample["measured_at"],
            "value": sample["value"],
            "unit": feature.unit,
            "quality": sample["quality"],
            "analysis_status": sample["analysis_status"],
            "source_type": sample["source_type"],
            "sample_count": sample["sample_count"],
            "minimum_value": sample["minimum_value"],
            "maximum_value": sample["maximum_value"],
        }
        for sample in samples[-limit:]
    ]


def _build_metric_report(
    feature, records, recent_records, baseline_records, trend_samples
):
    history = [
        {
            "event_id": sample["event_id"],
            "measured_at": sample["measured_at"],
            "value": sample["value"],
            "quality": sample["quality"],
            "analysis_status": sample["analysis_status"],
            "source_type": sample["source_type"],
            "sample_count": sample["sample_count"],
            "minimum_value": sample["minimum_value"],
            "maximum_value": sample["maximum_value"],
        }
        for sample in trend_samples[-REPORT_FEATURE_HISTORY_LIMIT:]
    ]
    usable_values = []
    usable_contexts = []
    baseline_values = []
    recent_values = []
    latest_quality = "missing"
    latest_value = None
    baseline_event_ids = {record.event_id for record in baseline_records}
    recent_event_ids = {record.event_id for record in recent_records}

    for sample in trend_samples:
        value = sample["value"]
        if value is not None and sample["quality"] in {"good", "aggregated"}:
            usable_values.append(float(value))
            usable_contexts.append(sample["context"])
        if (
            sample["analysis_status"] == TelemetryEvent.AnalysisStatus.NORMAL
            and value is not None
            and sample["quality"] in {"good", "aggregated"}
            and (
                sample["source_type"] == "minute_aggregate"
                or sample["event_id"] in baseline_event_ids
                or sample["event_id"] not in recent_event_ids
            )
        ):
            baseline_values.append(float(value))

    latest_sample = trend_samples[-1] if trend_samples else None
    latest_record_selected = False
    if records:
        latest_record = records[-1]
        if (
            latest_sample is None
            or latest_record.aggregated_at is None
            or latest_record.measured_at
            >= latest_sample["measured_at"] + timedelta(minutes=1)
        ):
            latest_measurement = latest_record.payload["measurements"][feature.name]
            latest_value = latest_measurement["value"]
            latest_quality = latest_measurement["quality"]
            latest_record_selected = True
    if not latest_record_selected and latest_sample is not None:
        latest_value = latest_sample["value"]
        latest_quality = latest_sample["quality"]

    for record in recent_records:
        measurement = record.payload["measurements"][feature.name]
        value = measurement["value"]
        if (
            value is not None
            and measurement["quality"] == "good"
            and _is_finite_number(value)
        ):
            recent_values.append(float(value))

    reference_median = (
        float(statistics.median(baseline_values)) if baseline_values else None
    )
    reference_mad = (
        float(statistics.median(abs(value - reference_median) for value in baseline_values))
        if reference_median is not None
        else None
    )
    robust_scale = 1.4826 * reference_mad if reference_mad is not None else None
    robust_deviation = None
    delta_from_reference = None
    change_fraction = None
    recent_median = float(statistics.median(recent_values)) if recent_values else None
    trend_delta = (
        recent_median - reference_median
        if recent_median is not None and reference_median is not None
        else None
    )

    if (
        latest_value is not None
        and latest_quality in {"good", "aggregated"}
        and _is_finite_number(latest_value)
        and reference_median is not None
    ):
        delta_from_reference = float(latest_value) - reference_median
        if reference_median != 0:
            change_fraction = delta_from_reference / abs(reference_median)
        if robust_scale is not None and robust_scale > 0:
            robust_deviation = delta_from_reference / robust_scale

    enough_baseline = len(baseline_values) >= REPORT_MIN_BASELINE_SAMPLES
    is_numeric = feature.unit not in REPORT_NON_NUMERIC_UNITS
    trend_model = forecast_feature(
        usable_values,
        unit=feature.unit,
        feature_name=feature.name,
        contexts=usable_contexts,
    )
    if latest_quality in {"low", "missing"}:
        metric_status = "data_quality"
    elif not is_numeric:
        metric_status = "context"
    elif not enough_baseline or latest_value is None:
        metric_status = "insufficient_history"
    elif robust_deviation is not None and abs(robust_deviation) >= REPORT_SHIFT_ROBUST_DEVIATIONS:
        metric_status = "shift"
    else:
        metric_status = "within_observed_range"

    if trend_model["status"] == "ready":
        trend_direction = trend_model["direction"]
    elif trend_delta is None or not is_numeric or not enough_baseline:
        trend_direction = "unknown"
    elif robust_scale and robust_scale > 0:
        normalized_trend = trend_delta / robust_scale
        if normalized_trend >= REPORT_SHIFT_ROBUST_DEVIATIONS:
            trend_direction = "increasing"
        elif normalized_trend <= -REPORT_SHIFT_ROBUST_DEVIATIONS:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "stable" if trend_delta == 0 else "changed"

    return {
        "name": feature.name,
        "label": feature.label,
        "unit": feature.unit,
        "category": feature.category,
        "latest_value": latest_value,
        "latest_quality": latest_quality,
        "sample_count": len(usable_values),
        "baseline_sample_count": len(baseline_values),
        "reference_median": reference_median,
        "reference_mad": reference_mad,
        "delta_from_reference": delta_from_reference,
        "change_fraction": change_fraction,
        "robust_deviation": robust_deviation,
        "recent_median": recent_median,
        "recent_window_delta": trend_delta,
        "trend_direction": trend_direction,
        "trend_model": trend_model,
        "status": metric_status,
        "history": history,
    }


def _build_profile_trend_samples(
    profile, *, limit=REPORT_TREND_MODEL_LIMIT, since=None, until=None
):
    bucket_query = profile.trend_buckets.all()
    raw_query = profile.telemetry_events.filter(aggregated_at__isnull=True)
    if since is not None:
        bucket_query = bucket_query.filter(bucket_start__gte=since)
        raw_query = raw_query.filter(measured_at__gte=since)
    if until is not None:
        bucket_query = bucket_query.filter(bucket_start__lte=until)
        raw_query = raw_query.filter(measured_at__lte=until)
    buckets = list(bucket_query.order_by("-bucket_start")[:limit])
    buckets.reverse()
    raw_events = list(raw_query.order_by("-measured_at", "-event_id")[:limit])
    raw_events.reverse()

    rows_by_minute = {}
    if buckets:
        for bucket in buckets:
            rows_by_minute[bucket.bucket_start] = {
                "event_count": bucket.event_count,
                "metrics": deepcopy(bucket.metrics),
                "context_stats": deepcopy(bucket.context_stats),
                "analysis_status_counts": deepcopy(bucket.analysis_status_counts),
                "source_counts": deepcopy(bucket.source_counts),
                "synthetic_event_count": bucket.synthetic_event_count,
            }
        for event in raw_events:
            bucket_start = event.measured_at.replace(second=0, microsecond=0)
            incoming = aggregate_event_payload(event.payload)
            current = rows_by_minute.get(bucket_start)
            if current is None:
                rows_by_minute[bucket_start] = incoming
            else:
                merge_aggregate_stats(current, incoming)
        rows = [
            (
                bucket_start,
                stats,
                f"minute:{bucket_start.isoformat()}",
                "minute_aggregate",
                None,
            )
            for bucket_start, stats in sorted(rows_by_minute.items())
        ]
    else:
        rows = [
            (
                event.measured_at,
                aggregate_event_payload(event.payload),
                event.event_id,
                "event",
                event.analysis_status,
            )
            for event in raw_events
        ]

    result = {feature.name: [] for feature in FEATURES}
    for measured_at, stats, event_id, source_type, analysis_status in rows:
        context = model_context(stats["context_stats"])
        statuses = stats["analysis_status_counts"]
        only_normal = (
            len(statuses) == 1
            and statuses.get(TelemetryEvent.AnalysisStatus.NORMAL, 0)
            == stats["event_count"]
        )
        for feature in FEATURES:
            metric = stats["metrics"].get(feature.name)
            good_count = metric["good_count"] if metric else 0
            low_count = metric["low_count"] if metric else 0
            value = metric_value(metric, feature.unit)
            quality = (
                "aggregated"
                if source_type == "minute_aggregate" and good_count
                else "good"
                if good_count
                else "low"
                if low_count
                else "missing"
            )
            result[feature.name].append(
                {
                    "event_id": event_id,
                    "measured_at": measured_at,
                    "value": value,
                    "quality": quality,
                    "analysis_status": (
                        analysis_status
                        if analysis_status is not None
                        else TelemetryEvent.AnalysisStatus.NORMAL
                        if only_normal
                        else None
                    ),
                    "source_type": source_type,
                    "sample_count": good_count,
                    "minimum_value": metric["min"] if metric else None,
                    "maximum_value": metric["max"] if metric else None,
                    "context": context,
                }
            )
    return result


def _build_report_insights(records, metrics, baseline_normal_records):
    if not records:
        if any(metric["sample_count"] for metric in metrics):
            return [
                {
                    "code": "showing_aggregated_history",
                    "severity": "info",
                    "title": "Showing retained minute-level history",
                    "summary": (
                        "No recent raw telemetry is available. Trend charts and forecasts "
                        "are based on stored one-minute aggregates."
                    ),
                    "evidence": [],
                    "recommended_actions": [],
                    "interaction_summary": None,
                    "event_id": None,
                    "metric_names": [],
                    "interaction_labels": [],
                }
            ]
        return [
            {
                "code": "waiting_for_telemetry",
                "severity": "info",
                "title": "Waiting for the first telemetry sample",
                "summary": (
                    "Start the mission simulator or connect a validated telemetry source "
                    "to populate this profile."
                ),
                "evidence": [],
                "recommended_actions": [
                    "Confirm the simulator is running and publishing events for this profile."
                ],
                "interaction_summary": None,
                "event_id": None,
                "metric_names": [],
                "interaction_labels": [],
            }
        ]

    insights = []
    latest = records[-1]
    latest_payload = latest.payload
    analysis = latest_payload["analysis"]
    latest_context = latest_payload["context"]
    latest_measurements = latest_payload["measurements"]
    recent_window_size = min(REPORT_RECENT_WINDOW, max(1, len(records) // 4))
    recent_records = records[-recent_window_size:]

    if analysis["status"] == TelemetryEvent.AnalysisStatus.ANOMALY_REVIEW:
        contributors = analysis["top_contributors"]
        interaction_labels = [item["label"] for item in contributors]
        feature_names = sorted(
            {
                name
                for item in contributors
                for name in item["features"]
            }
        )
        interaction_summary, relationship_checks = _interpret_interaction(
            set(feature_names),
            interaction_labels,
        )
        evidence = [
            f"Detector {analysis['detector']} flagged this vector for review; "
            f"its empirical tail rank is {analysis['score']} of 1, not a probability."
        ]
        if interaction_summary:
            evidence.append(interaction_summary)
        if feature_names:
            evidence.append(
                "Contributing signals: "
                + ", ".join(
                    _describe_measurement(name, latest_measurements)
                    for name in feature_names
                )
                + "."
            )
        evidence.append(
            f"Mission context: scenario={latest_context['simulation_scenario']}, "
            f"phase={latest_context['mission_phase']}, "
            f"link_online={latest_context['link_online']}."
        )
        insights.append(
            {
                "code": "nonlinear_pattern_review",
                "severity": "review",
                "title": "A combination of signals differs from this model's baseline",
                "summary": analysis["explanation"],
                "evidence": evidence,
                "recommended_actions": [
                    "Check the quality and source of each contributing channel before interpreting the pattern.",
                    *relationship_checks,
                    "Treat this as a review prompt only; it is not a diagnosis or an autonomous treatment recommendation.",
                ],
                "interaction_summary": interaction_summary,
                "event_id": latest.event_id,
                "metric_names": feature_names,
                "interaction_labels": interaction_labels,
            }
        )

        interaction_counts = Counter(
            item["label"]
            for record in recent_records
            if record.payload["analysis"]["status"]
            == TelemetryEvent.AnalysisStatus.ANOMALY_REVIEW
            for item in record.payload["analysis"]["top_contributors"]
        )
        repeated_interactions = [
            label for label, count in interaction_counts.items() if count >= 2
        ]
        if repeated_interactions:
            insights.append(
                {
                    "code": "recurrent_interaction",
                    "severity": "review",
                    "title": "The same signal relationship recurs in recent samples",
                    "summary": (
                        f"{len(repeated_interactions)} detector contribution label(s) "
                        f"recurred across the last {len(recent_records)} stored samples."
                    ),
                    "evidence": [
                        f"{label}: flagged {interaction_counts[label]} times."
                        for label in repeated_interactions[:5]
                    ],
                    "recommended_actions": [
                        "Review the full time-aligned history for these channels and whether the same mission context is present.",
                        "Check for a repeated simulation scenario or shared source artifact before drawing a physiological conclusion.",
                    ],
                    "interaction_summary": (
                        "A repeated model contribution is evidence that the same feature relationship "
                        "was unusual in multiple samples, not evidence that the features caused one another."
                    ),
                    "event_id": latest.event_id,
                    "metric_names": sorted(
                        {
                            name
                            for item in contributors
                            if item["label"] in repeated_interactions
                            for name in item["features"]
                        }
                    ),
                    "interaction_labels": repeated_interactions[:5],
                }
            )
    elif analysis["status"] in {
        TelemetryEvent.AnalysisStatus.DATA_QUALITY_REVIEW,
        TelemetryEvent.AnalysisStatus.INSUFFICIENT_DATA,
    }:
        quality = analysis["data_quality"]
        affected = sorted(
            set(quality["missing_features"] + quality["low_quality_features"])
        )
        insights.append(
            {
                "code": "signal_quality_review",
                "severity": "review",
                "title": "Some channels are missing or low quality",
                "summary": analysis["explanation"],
                "evidence": [
                    _describe_measurement(name, latest_measurements)
                    for name in affected
                ]
                or [
                    f"Only {quality['valid_fraction']:.0%} of the feature vector was valid for this analysis."
                ],
                "recommended_actions": [
                    "Check the affected channel's connection, contact, and source metadata.",
                    "Keep missing or low-quality readings visibly unknown; do not replace them with a normal value.",
                    "Re-evaluate the trend after a fresh, good-quality sample arrives.",
                ],
                "interaction_summary": None,
                "event_id": latest.event_id,
                "metric_names": affected,
                "interaction_labels": [],
            }
        )

    if latest_context["simulation_scenario"] == "radiation_event":
        insights.append(
            {
                "code": "mission_environment_scenario",
                "severity": "context",
                "title": "Radiation-event scenario is active in the simulator",
                "summary": (
                    "The synthetic scenario raised the simulated dose-rate channels. "
                    "This is a scenario label, not a real environmental measurement."
                ),
                "evidence": [
                    _describe_measurement(
                        "radiation_dose_rate_usv_h", latest_measurements
                    ),
                    _describe_measurement("cumulative_dose_usv", latest_measurements),
                ],
                "recommended_actions": [
                    "For the demo, verify that the environment scenario and event timeline are displayed together.",
                    "For a future hardware adapter, route validated exposure thresholds through mission-approved procedures rather than inferring them from synthetic data.",
                ],
                "interaction_summary": None,
                "event_id": latest.event_id,
                "metric_names": ["radiation_dose_rate_usv_h", "cumulative_dose_usv"],
                "interaction_labels": [],
            }
        )

    shifted_metrics = [
        metric
        for metric in metrics
        if metric["status"] == "shift" and metric["robust_deviation"] is not None
    ]
    if shifted_metrics:
        shifted_metrics.sort(
            key=lambda metric: abs(metric["robust_deviation"]),
            reverse=True,
        )
        insights.append(
            {
                "code": "personal_history_shift",
                "severity": "watch",
                "title": "Recent readings differ from this profile's prior samples",
                "summary": (
                    f"{len(shifted_metrics)} signal(s) are at least "
                    f"{REPORT_SHIFT_ROBUST_DEVIATIONS:g} robust deviations from a "
                    "baseline built from earlier normal, good-quality samples."
                ),
                "evidence": [
                    _format_metric_shift(metric) for metric in shifted_metrics[:6]
                ],
                "recommended_actions": [
                    "Check whether the change persists in subsequent good-quality readings instead of reacting to one sample.",
                    "Review paired signals and recorded activity, sleep, and mission context alongside this profile's history.",
                    "The statistical comparison is exploratory and is not a medical threshold.",
                ],
                "interaction_summary": None,
                "event_id": latest.event_id,
                "metric_names": [metric["name"] for metric in shifted_metrics],
                "interaction_labels": [],
            }
        )

    if len(baseline_normal_records) < REPORT_MIN_BASELINE_SAMPLES:
        insights.append(
            {
                "code": "building_profile_baseline",
                "severity": "info",
                "title": "Building a profile-specific reference",
                "summary": (
                    f"{len(baseline_normal_records)} prior normal, good-quality events "
                    f"are available; at least {REPORT_MIN_BASELINE_SAMPLES} are needed "
                    "per signal for the exploratory comparison."
                ),
                "evidence": [
                    "Baseline values exclude low/missing channels and events already flagged for review."
                ],
                "recommended_actions": [
                    "Continue collecting samples; metrics remain marked as insufficient history until enough usable values exist.",
                    "The detector's synthetic calibration is not substituted for this profile's own history.",
                ],
                "interaction_summary": None,
                "event_id": latest.event_id,
                "metric_names": [],
                "interaction_labels": [],
            }
        )

    if not insights:
        insights.append(
            {
                "code": "no_current_rule_trigger",
                "severity": "info",
                "title": "No review pattern in the latest sample",
                "summary": (
                    "The latest vector was not flagged by the synthetic-baseline detector, "
                    "and no profile-history shift passed this report's exploratory rule."
                ),
                "evidence": [
                    f"Latest event {latest.event_id} has analysis status {analysis['status']} and data quality {analysis['data_quality']['status']}."
                ],
                "recommended_actions": [
                    "Continue monitoring trends and channel quality; this result does not certify a normal health state."
                ],
                "interaction_summary": None,
                "event_id": latest.event_id,
                "metric_names": [],
                "interaction_labels": [],
            }
        )

    return insights


def _describe_measurement(name, measurements):
    measurement = measurements[name]
    value = measurement["value"]
    formatted = "missing" if value is None else f"{value:g} {measurement['unit']}"
    return f"{name}: {formatted}, quality={measurement['quality']}."


def _interpret_interaction(feature_names, interaction_labels):
    observed_groups = {
        "cardiovascular": (
            "cardiovascular",
            "Review cardiovascular samples at the same time as their contributing channels.",
        ),
        "activity": (
            "activity",
            "Compare the flagged sample with activity intensity, movement, and the recorded countermeasure window.",
        ),
        "sleep": (
            "sleep",
            "Review sleep duration/timing with the same mission-time window.",
        ),
        "self_report": (
            "self-reported",
            "Keep subjective reports distinct from device-derived measurements and check their timestamps.",
        ),
        "respiratory": (
            "respiratory",
            "Verify respiratory channel quality and time alignment before interpreting the pattern.",
        ),
        "cabin_environment": (
            "cabin-environment",
            "Check that the contributing environment channels share a time window and source.",
        ),
        "radiation": (
            "radiation",
            "Verify scenario labels and units; do not treat simulated exposure values as an operational reading.",
        ),
    }
    categories = {
        FEATURE_BY_NAME[name].category for name in feature_names if name in FEATURE_BY_NAME
    }
    matched_groups = [
        observed_groups[category]
        for category in observed_groups
        if category in categories
    ]
    labels = "; ".join(interaction_labels[:3])
    groups_text = ", ".join(label for label, _ in matched_groups)
    if groups_text:
        summary = (
            f"The detector flags a joint pattern across {groups_text} channels. "
            "Its feature-contribution ranking does not establish cause, direction, or a health condition."
        )
    elif labels:
        summary = (
            f"The nonlinear detector ranked these feature relationships together: {labels}. "
            "Contribution describes the model's explanation, not causation."
        )
    else:
        summary = None
    checks = [check for _, check in matched_groups]
    return (
        summary,
        checks or [
            "Compare the listed channels at the same measurement time and against the mission context recorded with the event."
        ],
    )


def _format_metric_shift(metric):
    deviation = metric["robust_deviation"]
    direction = "above" if deviation > 0 else "below"
    return (
        f"{metric['label']}: latest {metric['latest_value']:g} {metric['unit']}, "
        f"profile reference median {metric['reference_median']:g} {metric['unit']} "
        f"({abs(deviation):.1f} robust deviations {direction}; "
        f"{metric['baseline_sample_count']} prior samples)."
    )


def _is_finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _existing_event_result(existing, event):
    if existing.payload_digest:
        matches = existing.payload_digest == canonical_digest(event)
    else:
        matches = existing.payload == event
    if not matches:
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
