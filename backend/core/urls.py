from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from api.views import (
    CrewProfileViewSet,
    HealthAlertViewSet,
    HealthView,
    MissionTokenView,
    ParameterCatalogView,
    ProfileDashboardView,
    ProfileSeriesView,
    TelemetryBatchSyncView,
    TelemetryEventViewSet,
    TelemetryIngestView,
    TelemetryStreamView,
)

router = DefaultRouter()
router.register("profiles", CrewProfileViewSet, basename="profile")
router.register("telemetry/events", TelemetryEventViewSet, basename="telemetry-event")
router.register("alerts", HealthAlertViewSet, basename="alert")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", HealthView.as_view(), name="health"),
    path("api/v1/auth/token/", MissionTokenView.as_view(), name="auth-token"),
    path("api/v1/telemetry/ingest/", TelemetryIngestView.as_view(), name="telemetry-ingest"),
    path("api/v1/telemetry/sync/", TelemetryBatchSyncView.as_view(), name="telemetry-sync"),
    path("api/v1/telemetry/stream/", TelemetryStreamView.as_view(), name="telemetry-stream"),
    path(
        "api/v1/profiles/<slug:profile_id>/dashboard/",
        ProfileDashboardView.as_view(),
        name="profile-dashboard",
    ),
    path(
        "api/v1/profiles/<slug:profile_id>/series/",
        ProfileSeriesView.as_view(),
        name="profile-series",
    ),
    path("api/v1/metadata/parameters/", ParameterCatalogView.as_view(), name="parameter-catalog"),
    path("api/v1/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
]
