from django.contrib import admin

from api.models import CrewProfile, HealthAlert, SyncBatch, TelemetryEvent


@admin.register(CrewProfile)
class CrewProfileAdmin(admin.ModelAdmin):
    list_display = ("profile_id", "display_name", "mission_name", "mission_phase", "owner")
    search_fields = ("profile_id", "display_name", "mission_name", "owner__username")
    list_filter = ("mission_phase",)


@admin.register(TelemetryEvent)
class TelemetryEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "profile",
        "measured_at",
        "analysis_status",
        "anomaly_score",
        "is_synthetic",
    )
    search_fields = ("event_id", "profile__profile_id")
    list_filter = ("analysis_status", "scenario", "is_synthetic", "link_online")
    readonly_fields = (
        "event_id",
        "profile",
        "measured_at",
        "source_recorded_at",
        "received_at",
        "source",
        "analysis_status",
        "anomaly_score",
        "payload",
    )


@admin.register(HealthAlert)
class HealthAlertAdmin(admin.ModelAdmin):
    list_display = ("alert_id", "profile", "title", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("profile__profile_id", "event__event_id", "title")
    readonly_fields = ("alert_id", "event", "evidence", "created_at")


@admin.register(SyncBatch)
class SyncBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "submitted_by", "created_count", "duplicate_count", "created_at")
    readonly_fields = (
        "batch_id",
        "submitted_by",
        "idempotency_key",
        "payload_digest",
        "event_ids",
        "created_count",
        "duplicate_count",
        "created_at",
    )
