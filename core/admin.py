from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from .models import User, FeedbackAndImprovement


class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "phone")


admin.site.register(User, UserAdmin)

admin.site.register(Permission)
admin.site.register(ContentType)


@admin.register(FeedbackAndImprovement)
class FeedbackAndImprovementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "user",
        "context",
        "screenshot",
        "priority",
        "feedback_type",
        "is_fixed",
    )
    list_filter = ("priority", "feedback_type")
    search_fields = ("context",)
    date_hierarchy = "created_at"
    list_per_page = 25
