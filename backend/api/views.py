import json
import time
from datetime import timedelta

from django.db.models import Q, Sum
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.views import ObtainAuthToken
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)

from analytics.contracts import FEATURE_BY_NAME, SCHEMA_VERSION
from api.models import CrewProfile, HealthAlert, TelemetryEvent
from api.pagination import TelemetryPagination
from api.permissions import CanIngestProfile, IsProfileOwnerOrStaff
from api.serializers import (
    CrewProfileSerializer,
    DashboardResponseSerializer,
    EventIngestResponseSerializer,
    HealthResponseSerializer,
    HealthAlertSerializer,
    ParameterCatalogResponseSerializer,
    ProfileReportSerializer,
    SeriesResponseSerializer,
    SyncBatchSerializer,
    SyncBatchResponseSerializer,
    TelemetryBatchInputSerializer,
    TelemetryEventInputSerializer,
    TelemetryEventSerializer,
)
from api.services import (
    build_profile_report,
    build_profile_series,
    create_sync_batch,
    ingest_event,
)


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses=HealthResponseSerializer)
    def get(self, request):
        return Response(
            {
                "status": "ok",
                "api_version": "1",
                "telemetry_schema_version": SCHEMA_VERSION,
                "timestamp": timezone.now(),
            }
        )


class MissionTokenView(ObtainAuthToken):
    throttle_scope = "auth_token"


@extend_schema_view(
    retrieve=extend_schema(
        parameters=[OpenApiParameter("profile_id", OpenApiTypes.STR, OpenApiParameter.PATH)]
    )
)
class CrewProfileViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CrewProfileSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "profile_id"

    def get_queryset(self):
        queryset = CrewProfile.objects.select_related("owner")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(owner=self.request.user)


@extend_schema_view(
    retrieve=extend_schema(
        parameters=[OpenApiParameter("event_id", OpenApiTypes.STR, OpenApiParameter.PATH)]
    )
)
class TelemetryEventViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TelemetryEventSerializer
    permission_classes = [IsAuthenticated, IsProfileOwnerOrStaff]
    pagination_class = TelemetryPagination
    lookup_field = "event_id"
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["measured_at", "received_at", "anomaly_score"]
    ordering = ["-measured_at", "-event_id"]

    def get_queryset(self):
        queryset = TelemetryEvent.objects.select_related("profile", "profile__owner").filter(
            is_archived=False
        )
        if not self.request.user.is_staff:
            queryset = queryset.filter(profile__owner=self.request.user)
        params = self.request.query_params
        profile_id = params.get("profile_id")
        analysis_status = params.get("status")
        scenario = params.get("scenario")
        if profile_id:
            queryset = queryset.filter(profile_id=profile_id)
        if analysis_status:
            queryset = queryset.filter(analysis_status=analysis_status)
        if scenario:
            queryset = queryset.filter(scenario=scenario)
        since = _parse_query_datetime(params.get("since"), "since")
        until = _parse_query_datetime(params.get("until"), "until")
        if since and until and since > until:
            raise ValidationError({"since": "Must be earlier than or equal to until."})
        if since:
            queryset = queryset.filter(measured_at__gte=since)
        if until:
            queryset = queryset.filter(measured_at__lte=until)
        return queryset


class TelemetryIngestView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(
        request=TelemetryEventInputSerializer,
        responses={
            200: EventIngestResponseSerializer,
            201: EventIngestResponseSerializer,
        },
    )
    def post(self, request):
        serializer = TelemetryEventInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.validated_data["event"]
        profile = _get_ingest_profile(event["context"]["profile_id"])
        self.check_object_permissions(request, profile)
        result = ingest_event(event)
        return Response(
            {
                "event_id": result.record.event_id,
                "profile_id": result.record.profile_id,
                "created": result.created,
                "duplicate": not result.created,
                "analysis_status": result.record.analysis_status,
                "received_at": result.record.received_at,
                "schema_version": SCHEMA_VERSION,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class TelemetryBatchSyncView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(
        request=TelemetryBatchInputSerializer,
        responses={
            200: SyncBatchResponseSerializer,
            201: SyncBatchResponseSerializer,
        },
    )
    def post(self, request):
        serializer = TelemetryBatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        events = serializer.validated_data["events"]
        profile_ids = {event["context"]["profile_id"] for event in events}
        profiles = {
            profile.profile_id: profile
            for profile in CrewProfile.objects.filter(profile_id__in=profile_ids)
        }
        missing_profiles = sorted(profile_ids - profiles.keys())
        if missing_profiles:
            raise ValidationError(
                {"profile_id": f"Unknown crew profile(s): {', '.join(missing_profiles)}."}
            )
        for profile in profiles.values():
            self.check_object_permissions(request, profile)

        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key and (len(idempotency_key) > 128 or not idempotency_key.isprintable()):
            raise ValidationError({"Idempotency-Key": "Must be printable and at most 128 characters."})
        batch, created = create_sync_batch(
            request.user,
            events,
            idempotency_key=idempotency_key,
        )
        payload = SyncBatchSerializer(batch).data
        payload["schema_version"] = SCHEMA_VERSION
        payload["idempotent_replay"] = not created
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ProfileDashboardView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(responses=DashboardResponseSerializer)
    def get(self, request, profile_id):
        profile = _get_ingest_profile(profile_id)
        self.check_object_permissions(request, profile)
        latest = profile.telemetry_events.filter(is_archived=False).order_by(
            "-measured_at", "-event_id"
        ).first()
        open_alerts = profile.alerts.filter(status=HealthAlert.Status.OPEN).select_related(
            "event"
        )[:10]
        archived_count = profile.trend_buckets.aggregate(total=Sum("event_count"))[
            "total"
        ] or 0
        recent_count = profile.telemetry_events.filter(
            aggregated_at__isnull=True
        ).count()
        event_count = archived_count + recent_count
        has_archived_history = profile.trend_buckets.exists()
        last_sync_at = latest.received_at if latest else None
        if latest is None:
            sync_status = "stale" if has_archived_history else "no_data"
        elif timezone.now() - latest.received_at > timedelta(seconds=30):
            sync_status = "stale"
        else:
            sync_status = "current"
        return Response(
            {
                "schema_version": SCHEMA_VERSION,
                "profile": CrewProfileSerializer(profile).data,
                "latest": TelemetryEventSerializer(latest).data if latest else None,
                "open_alerts": HealthAlertSerializer(open_alerts, many=True).data,
                "event_count": event_count,
                "last_sync_at": last_sync_at,
                "sync_status": sync_status,
            }
        )


class ProfileSeriesView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(responses=SeriesResponseSerializer)
    def get(self, request, profile_id):
        profile = _get_ingest_profile(profile_id)
        self.check_object_permissions(request, profile)
        feature_name = request.query_params.get("feature")
        feature = FEATURE_BY_NAME.get(feature_name)
        if feature is None:
            raise ValidationError(
                {
                    "feature": (
                        "Provide a supported feature name. See "
                        "/api/v1/metadata/parameters/."
                    )
                }
            )
        limit = _parse_limit(request.query_params.get("limit", "200"))
        since = _parse_query_datetime(request.query_params.get("since"), "since")
        until = _parse_query_datetime(request.query_params.get("until"), "until")
        if since and until and since > until:
            raise ValidationError({"since": "Must be earlier than or equal to until."})
        points = build_profile_series(
            profile,
            feature,
            limit=limit,
            since=since,
            until=until,
        )
        return Response(
            {
                "schema_version": SCHEMA_VERSION,
                "profile_id": profile.profile_id,
                "feature": {
                    "name": feature.name,
                    "label": feature.label,
                    "unit": feature.unit,
                    "category": feature.category,
                },
                "points": points,
                "count": len(points),
            }
        )


class ProfileInsightsView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum number of recent events used for the report (1–500).",
            )
        ],
        responses=ProfileReportSerializer,
    )
    def get(self, request, profile_id):
        profile = _get_ingest_profile(profile_id)
        self.check_object_permissions(request, profile)
        limit = _parse_limit(request.query_params.get("limit", "120"))
        return Response(build_profile_report(profile, limit=limit))


class ParameterCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ParameterCatalogResponseSerializer)
    def get(self, request):
        from analytics.contracts import FEATURES

        return Response(
            {
                "schema_version": SCHEMA_VERSION,
                "features": [
                    {
                        "name": feature.name,
                        "label": feature.label,
                        "unit": feature.unit,
                        "category": feature.category,
                    }
                    for feature in FEATURES
                ],
            }
        )


@extend_schema_view(
    acknowledge=extend_schema(
        parameters=[OpenApiParameter("alert_id", OpenApiTypes.UUID, OpenApiParameter.PATH)]
    ),
    resolve=extend_schema(
        parameters=[OpenApiParameter("alert_id", OpenApiTypes.UUID, OpenApiParameter.PATH)]
    ),
)
class HealthAlertViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = HealthAlertSerializer
    permission_classes = [IsAuthenticated, IsProfileOwnerOrStaff]
    pagination_class = TelemetryPagination
    lookup_field = "alert_id"

    def get_queryset(self):
        queryset = HealthAlert.objects.select_related("profile", "profile__owner", "event")
        if not self.request.user.is_staff:
            queryset = queryset.filter(profile__owner=self.request.user)
        profile_id = self.request.query_params.get("profile_id")
        alert_status = self.request.query_params.get("status")
        if profile_id:
            queryset = queryset.filter(profile_id=profile_id)
        if alert_status:
            queryset = queryset.filter(status=alert_status)
        return queryset

    @action(detail=True, methods=["post"])
    @extend_schema(responses=HealthAlertSerializer)
    def acknowledge(self, request, alert_id=None):
        alert = self.get_object()
        if alert.status == HealthAlert.Status.RESOLVED:
            raise ValidationError({"status": "Resolved alerts cannot be acknowledged."})
        if alert.status == HealthAlert.Status.OPEN:
            alert.status = HealthAlert.Status.ACKNOWLEDGED
            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=("status", "acknowledged_at"))
        return Response(HealthAlertSerializer(alert).data)

    @action(detail=True, methods=["post"])
    @extend_schema(responses=HealthAlertSerializer)
    def resolve(self, request, alert_id=None):
        alert = self.get_object()
        if alert.status != HealthAlert.Status.RESOLVED:
            alert.status = HealthAlert.Status.RESOLVED
            alert.resolved_at = timezone.now()
            alert.save(update_fields=("status", "resolved_at"))
        return Response(HealthAlertSerializer(alert).data)


class TelemetryStreamView(APIView):
    permission_classes = [IsAuthenticated, CanIngestProfile]

    @extend_schema(
        responses={
            (200, "text/event-stream"): OpenApiResponse(
                description=(
                    "Server-Sent Events with id, event: telemetry, and data containing "
                    "the canonical telemetry event payload."
                )
            )
        }
    )
    def get(self, request):
        profile_id = request.query_params.get("profile_id")
        if not profile_id:
            raise ValidationError({"profile_id": "This query parameter is required."})
        profile = _get_ingest_profile(profile_id)
        self.check_object_permissions(request, profile)
        last_event_id = request.headers.get("Last-Event-ID")
        if last_event_id and not profile.telemetry_events.filter(event_id=last_event_id).exists():
            raise ValidationError({"Last-Event-ID": "Unknown event for this profile."})

        def events():
            cursor = last_event_id
            try:
                while True:
                    queryset = profile.telemetry_events.filter(is_archived=False).order_by(
                        "received_at", "event_id"
                    )
                    if cursor:
                        previous = profile.telemetry_events.filter(event_id=cursor).first()
                        if previous is None:
                            yield "event: reset\ndata: {\"reason\":\"cursor_expired\"}\n\n"
                            cursor = None
                        else:
                            queryset = queryset.filter(
                                Q(received_at__gt=previous.received_at)
                                | Q(received_at=previous.received_at, event_id__gt=previous.event_id)
                            )
                    records = list(queryset[:100])
                    for record in records:
                        event_data = json.dumps(
                            record.payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        yield f"id: {record.event_id}\nevent: telemetry\ndata: {event_data}\n\n"
                        cursor = record.event_id
                    if not records:
                        yield ": keep-alive\n\n"
                        time.sleep(2)
            except GeneratorExit:
                return

        response = StreamingHttpResponse(events(), content_type="text/event-stream; charset=utf-8")
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        return response


def _get_ingest_profile(profile_id):
    try:
        return CrewProfile.objects.get(profile_id=profile_id)
    except CrewProfile.DoesNotExist as exc:
        raise NotFound(f"Crew profile '{profile_id}' does not exist.") from exc


def _parse_query_datetime(value, field_name):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({field_name: "Use an ISO-8601 datetime with timezone."})
    if timezone.is_naive(parsed):
        raise ValidationError({field_name: "Datetime must include a timezone."})
    return parsed


def _parse_limit(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"limit": "Must be an integer between 1 and 500."}) from exc
    if not 1 <= parsed <= 500:
        raise ValidationError({"limit": "Must be an integer between 1 and 500."})
    return parsed
