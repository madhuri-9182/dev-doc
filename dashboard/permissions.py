from rest_framework.permissions import BasePermission
from core.models import Role


class CanDeleteUpdateUser(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.CLIENT_OWNER:
            return obj.user.role in [
                Role.CLIENT_ADMIN,
                Role.CLIENT_USER,
                Role.AGENCY,
            ]
        if request.user.role == Role.CLIENT_ADMIN:
            return obj.user.role in [Role.CLIENT_USER, Role.AGENCY]
        return False


class UserRoleDeleteUpdateClientData(BasePermission):
    def has_object_permission(self, request, view, obj):
        user_role = request.user.role
        if user_role in (Role.CLIENT_ADMIN, Role.CLIENT_OWNER):
            return True

        view_name = view.__class__.__name__
        if view_name == "JobView" and user_role == Role.CLIENT_USER:
            return obj.clients.filter(id=request.user.clientuser.id).exists()
        elif view_name == "CandidateView" and user_role in (
            Role.CLIENT_USER,
            Role.AGENCY,
        ):
            if user_role == Role.AGENCY and request.method == "DELETE":
                return True
            return obj.designation.clients.filter(
                id=request.user.clientuser.id
            ).exists()

        return False
