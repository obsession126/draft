from rest_framework.permissions import BasePermission, IsAuthenticated


class IsProfileOwnerOrStaff(IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        profile = getattr(obj, "profile", obj)
        return request.user.is_staff or profile.owner_id == request.user.id


class CanIngestProfile(IsAuthenticated):
    def has_object_permission(self, request, view, profile):
        return request.user.is_staff or profile.owner_id == request.user.id
