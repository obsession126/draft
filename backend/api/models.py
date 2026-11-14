import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class CrewProfile(models.Model):
    profile_id = models.SlugField(max_length=80, primary_key=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="crew_profiles",
    )
    display_name = models.CharField(max_length=120)
    mission_name = models.CharField(max_length=120, blank=True)
    mission_phase = models.CharField(max_length=40, default="transit")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("profile_id",)

    def __str__(self):
        return f"{self.display_name} ({self.profile_id})"


class TelemetryEvent(models.Model):
    class AnalysisStatus(models.TextChoices):
        NORMAL = "normal", "Normal relative to synthetic baseline"
        ANOMALY_REVIEW = "anomaly_review", "Anomaly review"
        DATA_QUALITY_REVIEW = "data_quality_review", "Data quality review"
        INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"

    event_id = models.CharField(max_length=160, primary_key=True)
    profile = models.ForeignKey(
        CrewProfile,
        on_delete=models.CASCADE,
        related_name="telemetry_events",
    )
    measured_at = models.DateTimeField(db_index=True)
    source_recorded_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=80)
    is_synthetic = models.BooleanField(default=True)
    analysis_status = models.CharField(
        max_length=32,
        choices=AnalysisStatus.choices,
        db_index=True,
    )
    anomaly_score = models.FloatField(null=True, blank=True)
    scenario = models.CharField(max_length=40)
    link_online = models.BooleanField()
    data_quality = models.CharField(max_length=16)
    payload = models.JSONField()
    payload_digest = models.CharField(max_length=64, blank=True, default="")
    aggregated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ("-measured_at", "-event_id")
        indexes = [
            models.Index(fields=("profile", "-measured_at"), name="api_event_profile_time"),
            models.Index(
                fields=("profile", "analysis_status", "-measured_at"),
                name="api_event_profile_status",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(anomaly_score__isnull=True)
                | (Q(anomaly_score__gte=0.0) & Q(anomaly_score__lte=1.0)),
                name="api_anomaly_score_between_0_1",
            )
        ]

    def __str__(self):
        return self.event_id


class TelemetryTrendBucket(models.Model):
    profile = models.ForeignKey(
        CrewProfile,
        on_delete=models.CASCADE,
        related_name="trend_buckets",
    )
    bucket_start = models.DateTimeField()
    event_count = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict)
    context_stats = models.JSONField(default=dict)
    analysis_status_counts = models.JSONField(default=dict)
    source_counts = models.JSONField(default=dict)
    synthetic_event_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("bucket_start",)
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "bucket_start"),
                name="api_trend_profile_minute",
            )
        ]
        indexes = [
            models.Index(
                fields=("profile", "-bucket_start"),
                name="api_trend_profile_time",
            )
        ]


class HealthAlert(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    alert_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        CrewProfile,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    event = models.OneToOneField(
        TelemetryEvent,
        on_delete=models.CASCADE,
        related_name="alert",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=160)
    explanation = models.TextField()
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-alert_id")
        indexes = [
            models.Index(fields=("profile", "status", "-created_at"), name="api_alert_profile_state"),
        ]


class SyncBatch(models.Model):
    batch_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="telemetry_sync_batches",
    )
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    payload_digest = models.CharField(max_length=64)
    event_ids = models.JSONField(default=list)
    created_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("submitted_by", "idempotency_key"),
                condition=Q(idempotency_key__isnull=False),
                name="api_sync_user_idempotency",
            )
        ]
