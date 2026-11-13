from rest_framework import serializers

from api.contracts import validate_telemetry_event
from api.models import CrewProfile, HealthAlert, SyncBatch, TelemetryEvent


class CrewProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrewProfile
        fields = (
            "profile_id",
            "display_name",
            "mission_name",
            "mission_phase",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class TelemetryEventInputSerializer(serializers.Serializer):
    event = serializers.JSONField()

    def validate_event(self, event):
        errors = validate_telemetry_event(event)
        if errors:
            details = []
            for error in errors[:20]:
                location = ".".join(str(part) for part in error.absolute_path) or "$"
                details.append({"path": location, "message": error.message})
            raise serializers.ValidationError(
                {"schema_version": "Event does not match telemetry schema 1.0.", "details": details}
            )

        names = event["feature_names"]
        measurements = event["measurements"]
        vector = event["feature_vector"]
        for index, name in enumerate(names):
            measurement_value = measurements[name]["value"]
            if vector[index] != measurement_value:
                raise serializers.ValidationError(
                    {
                        "feature_vector": (
                            f"Position {index} for '{name}' does not match "
                            "measurements[name].value."
                        )
                    }
                )
        return event


class TelemetryBatchInputSerializer(serializers.Serializer):
    events = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        max_length=250,
    )

    def validate_events(self, events):
        event_serializer = TelemetryEventInputSerializer(
            many=True,
            data=[{"event": event} for event in events],
        )
        event_serializer.is_valid(raise_exception=True)
        return [item["event"] for item in event_serializer.validated_data]


class TelemetryEventSerializer(serializers.ModelSerializer):
    profile_id = serializers.CharField(source="profile.profile_id", read_only=True)
    measured_at = serializers.DateTimeField(read_only=True)
    source_recorded_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TelemetryEvent
        fields = (
            "event_id",
            "profile_id",
            "measured_at",
            "source_recorded_at",
            "received_at",
            "analysis_status",
            "anomaly_score",
            "scenario",
            "link_online",
            "data_quality",
            "is_synthetic",
            "payload",
        )
        read_only_fields = fields


class HealthAlertSerializer(serializers.ModelSerializer):
    profile_id = serializers.CharField(source="profile.profile_id", read_only=True)
    event_id = serializers.CharField(source="event.event_id", read_only=True)
    measured_at = serializers.DateTimeField(source="event.measured_at", read_only=True)

    class Meta:
        model = HealthAlert
        fields = (
            "alert_id",
            "profile_id",
            "event_id",
            "measured_at",
            "status",
            "title",
            "explanation",
            "evidence",
            "created_at",
            "acknowledged_at",
            "resolved_at",
        )
        read_only_fields = fields


class SyncBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncBatch
        fields = (
            "batch_id",
            "event_ids",
            "created_count",
            "duplicate_count",
            "created_at",
        )
        read_only_fields = fields


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    api_version = serializers.CharField()
    telemetry_schema_version = serializers.CharField()
    timestamp = serializers.DateTimeField()


class EventIngestResponseSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    profile_id = serializers.CharField()
    created = serializers.BooleanField()
    duplicate = serializers.BooleanField()
    analysis_status = serializers.CharField()
    received_at = serializers.DateTimeField()
    schema_version = serializers.CharField()


class SyncBatchResponseSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    event_ids = serializers.ListField(child=serializers.CharField())
    created_count = serializers.IntegerField()
    duplicate_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    schema_version = serializers.CharField()
    idempotent_replay = serializers.BooleanField()

    class Meta:
        fields = (
            "batch_id",
            "event_ids",
            "created_count",
            "duplicate_count",
            "created_at",
            "schema_version",
            "idempotent_replay",
        )


class FeatureSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    unit = serializers.CharField()
    category = serializers.CharField()


class ParameterCatalogResponseSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    features = FeatureSerializer(many=True)


class DashboardResponseSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    profile = CrewProfileSerializer()
    latest = TelemetryEventSerializer(allow_null=True)
    open_alerts = HealthAlertSerializer(many=True)
    event_count = serializers.IntegerField()
    last_sync_at = serializers.DateTimeField(allow_null=True)
    sync_status = serializers.ChoiceField(choices=("no_data", "stale", "current"))


class SeriesPointSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    measured_at = serializers.DateTimeField()
    value = serializers.FloatField(allow_null=True)
    unit = serializers.CharField()
    quality = serializers.CharField()
    analysis_status = serializers.CharField()


class SeriesResponseSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    profile_id = serializers.CharField()
    feature = FeatureSerializer()
    points = SeriesPointSerializer(many=True)
    count = serializers.IntegerField()


class ReportProfileSerializer(serializers.Serializer):
    profile_id = serializers.CharField()
    display_name = serializers.CharField()
    mission_name = serializers.CharField()
    mission_phase = serializers.CharField()


class ReportWindowSerializer(serializers.Serializer):
    sample_count = serializers.IntegerField()
    recent_sample_count = serializers.IntegerField()
    baseline_sample_count = serializers.IntegerField()
    first_measured_at = serializers.DateTimeField(allow_null=True)
    last_measured_at = serializers.DateTimeField(allow_null=True)
    baseline_source = serializers.CharField()
    baseline_method = serializers.CharField()
    baseline_ready_metric_count = serializers.IntegerField()
    baseline_minimum_samples = serializers.IntegerField()
    is_synthetic = serializers.BooleanField()


class ReportSummarySerializer(serializers.Serializer):
    latest_analysis_status = serializers.CharField(allow_null=True)
    recent_event_count = serializers.IntegerField()
    recent_anomaly_review_count = serializers.IntegerField()
    recent_data_quality_review_count = serializers.IntegerField()
    recent_insufficient_data_count = serializers.IntegerField()
    current_quality_issue_count = serializers.IntegerField()
    historical_shift_metric_count = serializers.IntegerField()
    historical_shift_metrics = serializers.ListField(child=serializers.CharField())
    latest_analysis = serializers.JSONField(allow_null=True)
    interpretation_note = serializers.CharField()


class MetricHistoryPointSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    measured_at = serializers.DateTimeField()
    value = serializers.FloatField(allow_null=True)
    quality = serializers.CharField()
    analysis_status = serializers.CharField()


class MetricReportSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    unit = serializers.CharField()
    category = serializers.CharField()
    latest_value = serializers.FloatField(allow_null=True)
    latest_quality = serializers.CharField()
    sample_count = serializers.IntegerField()
    baseline_sample_count = serializers.IntegerField()
    reference_median = serializers.FloatField(allow_null=True)
    reference_mad = serializers.FloatField(allow_null=True)
    delta_from_reference = serializers.FloatField(allow_null=True)
    change_fraction = serializers.FloatField(allow_null=True)
    robust_deviation = serializers.FloatField(allow_null=True)
    recent_median = serializers.FloatField(allow_null=True)
    recent_window_delta = serializers.FloatField(allow_null=True)
    trend_direction = serializers.CharField()
    status = serializers.CharField()
    history = MetricHistoryPointSerializer(many=True)


class ReportInsightSerializer(serializers.Serializer):
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=("review", "watch", "context", "info"))
    title = serializers.CharField()
    summary = serializers.CharField()
    interaction_summary = serializers.CharField(allow_null=True)
    evidence = serializers.ListField(child=serializers.CharField())
    recommended_actions = serializers.ListField(child=serializers.CharField())
    event_id = serializers.CharField(allow_null=True)
    metric_names = serializers.ListField(child=serializers.CharField())
    interaction_labels = serializers.ListField(child=serializers.CharField())


class ProfileReportSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    profile = ReportProfileSerializer()
    generated_at = serializers.DateTimeField()
    window = ReportWindowSerializer()
    summary = ReportSummarySerializer()
    metrics = MetricReportSerializer(many=True)
    insights = ReportInsightSerializer(many=True)
