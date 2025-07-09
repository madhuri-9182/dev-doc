from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from .models import Role


SAFE_METHOD = ["OPTIONS", "HEAD"]


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.SUPER_ADMIN


class IsModerator(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.MODERATOR


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.ADMIN


class IsClientAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.CLIENT_ADMIN


class IsClientOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.CLIENT_OWNER


class IsClientUser(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.CLIENT_USER


class IsInterviewer(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.INTERVIEWER


class IsAgency(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == Role.AGENCY


class HasRole(BasePermission):
    def has_permission(self, request, view):
        roles_mapping = getattr(view, "roles_mapping", {})

        roles = roles_mapping.get(request.method, [])

        if "__all__" in roles or request.method in SAFE_METHOD:
            return True

        return any(request.user.role == role for role in roles)
