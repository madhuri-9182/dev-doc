from typing import Any
from django.core.management import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.db.models import Q


class Command(BaseCommand):
    help = "Add Role and respective permission."

    def handle(self, *args: Any, **options: Any):
        roles = {
            "super_admin": Group.objects.get_or_create(name="super_admin")[0],
            "moderator": Group.objects.get_or_create(name="moderator")[0],
            "client_admin": Group.objects.get_or_create(name="client_admin")[0],
            "client_user": Group.objects.get_or_create(name="client_user")[0],
            "user": Group.objects.get_or_create(name="user")[0],
            "agency": Group.objects.get_or_create(name="agency")[0],
            "interviewer": Group.objects.get_or_create(name="interviewer")[0],
        }
        all_permission_qs = Permission.objects.exclude(codename__contains="delete")
        all_app_level_permission_qs = all_permission_qs.filter(
            content_type__app_label__in=[
                "django_rest_passwordreset",
                "organizations",
                "core",
                "dashboard",
                "auth",
            ]
        )
        roles["super_admin"].permissions.set(all_app_level_permission_qs)
        moderator_permission_qs = all_app_level_permission_qs.exclude(
            Q(
                content_type__model__in=[
                    "organizationinvitation",
                    "organizationowner",
                    "organizationuser",
                    "clientcustomrole",
                    "clientuser",
                ]
            )
            | Q(content_type__app_label__in=["auth", "django_rest_passwordreset"])
        )
        roles["moderator"].permissions.set(moderator_permission_qs)
        client_admin_permissions_qs = all_permission_qs.filter(
            Q(content_type__app_label__in=["core", "django_rest_passwordreset"])
            | Q(
                content_type__model__in=[
                    "clientuser",
                    "organizationinvitation",
                    "organizationuser",
                    "organizationowner",
                ],
            )
        )
        roles["client_admin"].permissions.set(client_admin_permissions_qs)
        client_user_permission_qs = client_admin_permissions_qs.none()
        roles["client_user"].permissions.set(client_user_permission_qs)
        self.stdout.write(
            self.style.SUCCESS("Roles and permissions added successfully.")
        )
