from typing import Any
from datetime import timedelta
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import ngettext
from rangefilter.filters import (
    DateRangeFilter,
)

from .models import (
    InternalClient,
    ClientPointOfContact,
    Job,
    ClientUser,
    EngagementTemplates,
    Candidate,
    InternalInterviewer,
    Interview,
    InterviewerAvailability,
    InterviewFeedback,
    BillingRecord,
    BillingLog,
    BillPayments,
    CandidateToInterviewerFeedback,
    JobInterviewRounds,
)

admin.site.site_title = "HDIP Super Admin Center"
admin.site.site_header = "HDIP Super Admin"
admin.site.index_title = "HDIP Administration"


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_candidate_name",
        "get_interviewer_name",
        "get_organization_name",
        "created_at",
        "scheduled_time",
        "status",
        "archived",
    )
    list_filter = (
        "interviewer__name",
        "candidate__organization__name",
    )
    search_fields = (
        "candidate__name",
        "interviewer__name",
        "candidate__organization__name",
    )
    actions = ["mark_as_downloaded"]
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related(
            "candidate",
            "candidate__organization",
            "candidate__organization__internal_client",
            "interviewer",
        )

    def get_candidate_name(self, obj):
        return obj.candidate.name if hasattr(obj.candidate, "name") else None

    get_candidate_name.short_description = "Candidate"

    def get_interviewer_name(self, obj):
        return obj.interviewer.name if hasattr(obj.interviewer, "name") else None

    get_interviewer_name.short_description = "Interviewer"

    def get_organization_name(self, obj):
        return obj.candidate.organization.name

    get_organization_name.short_description = "Organization"

    @admin.action(description="Mark as Download")
    def mark_as_downloaded(self, request, queryset):
        updated_count = queryset.filter(status="CSCH").update(downloaded=True)
        self.message_user(
            request,
            ngettext(
                "%d record was successfully marked as downloaded.",
                "%d records were successfully marked as downloaded.",
                updated_count,
            )
            % updated_count,
            messages.SUCCESS,
        )


class BaseDetailedExperienceFilter(SimpleListFilter):
    """More detailed experience filter"""

    title = "Experience Level"
    parameter_name = "experience_level"
    experience_field_path = "total_experience_years"

    def lookups(self, request, model_admin):
        return (
            ("fresher", ("Fresher (1-2 years)")),
            ("junior", ("Junior (2-4 years)")),
            ("mid_junior", ("Mid-Junior (4-6 years)")),
            ("mid_senior", ("Mid-Senior (6-8 years)")),
            ("senior", ("Senior (8-12 years)")),
            ("principal", ("Principal (12-15 years)")),
            ("architect", ("Architect (15+ years)")),
        )

    def queryset(self, request, queryset):
        experience_ranges = {
            "fresher": (1, 2),
            "junior": (2, 4),
            "mid_junior": (4, 6),
            "mid_senior": (6, 8),
            "senior": (8, 12),
            "principal": (12, 15),
            "architect": (15, 50),
        }

        if self.value() in experience_ranges:
            min_exp, max_exp = experience_ranges[self.value()]
            filter_kwargs = {
                f"{self.experience_field_path}__gte": min_exp,
                f"{self.experience_field_path}__lte": max_exp,
            }

            return queryset.filter(**filter_kwargs)
        return queryset


class InterviewerDetailedExperienceFilter(BaseDetailedExperienceFilter):
    """Experience filter for InternalInterviewer admin"""

    title = "Experience Level"
    parameter_name = "interviewer_experience"
    experience_field_path = "total_experience_years"


@admin.register(InternalInterviewer)
class InternalInterviewerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "email",
        "phone_number",
        "total_experience_years",
        "total_experience_months",
        "archived",
    )
    search_fields = ("name", "email", "phone_number")
    list_filter = ("strength", "interviewer_level", InterviewerDetailedExperienceFilter)
    list_per_page = 20


@admin.register(InternalClient)
class InternalClientAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "gstin",
        "pan",
        "is_signed",
        "assigned_to",
        "archived",
    )
    list_filter = ("organization__name", "is_signed")
    search_fields = ("name", "gstin", "pan")
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related("organization", "assigned_to")


@admin.register(ClientPointOfContact)
class ClientPointOfContactAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "email", "phone", "client", "archived")
    search_fields = ("name", "email")
    list_per_page = 20

    def get_queryset(self, request):
        return ClientPointOfContact.object_all.all()


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "specialization",
        "get_organization",
        "mandatory_skills_csv",
        "archived",
    )
    list_per_page = 20
    list_filter = ("hiring_manager__organization",)
    search_fields = ("name", "hiring_manager__organization__name")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("hiring_manager", "hiring_manager__organization")
        )

    def get_organization(self, obj):
        return (
            obj.hiring_manager.organization.name
            if obj.hiring_manager and obj.hiring_manager.organization
            else "-"
        )

    get_organization.short_description = "Organization"

    def mandatory_skills_csv(self, obj):
        return ", ".join(obj.mandatory_skills or [])

    mandatory_skills_csv.short_description = "Mandatory Skills"


@admin.register(JobInterviewRounds)
class JobInterviewRoundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job",
        "name",
        "duration_minutes",
        "sequence_number",
        "archived",
    )
    list_per_page = 20
    search_fields = ("job__name", "name")
    readonly_fields = ["created_at", "updated_at"]
    list_filter = ("job__name", "job__hiring_manager__organization__name")

    def get_queryset(self, request):
        return self.model.object_all.select_related("job__hiring_manager__organization")


@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization",
        "user",
        "name",
        "invited_by",
        "status",
        "archived",
    )
    search_fields = ("organization__name", "name")
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related(
            "organization", "user", "invited_by"
        )


@admin.register(EngagementTemplates)
class EngagementTemplatesAdmin(admin.ModelAdmin):
    list_display = ("id", "template_name", "get_organization", "archived")
    list_per_page = 20
    search_fields = ("organization__name", "template_name")
    readonly_fields = ["created_at", "updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return EngagementTemplates.object_all.select_related("organization")

    def get_organization(self, obj):
        return obj.organization.name if obj.organization else "-"

    get_organization.short_description = "Organization"


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "specialization",
        "get_organization",
        "status",
        "archived",
    )
    search_fields = ("name", "organization__name")
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related("organization")

    def get_organization(self, obj):
        return obj.organization.name if obj.organization else "-"

    get_organization.short_description = "Organization"


class TomorrowAndLastMonthFilter(SimpleListFilter):
    title = "Tomorrow and Last Month"
    parameter_name = "tomorrow_lastmonth"

    def lookups(self, request, model_admin):
        if model_admin.model.__name__ == "BillingLog":
            return [("lastmonth", "Last Month")]
        return [("tomorrow", "Tomorrow")]

    def queryset(self, request, queryset):
        if self.value() == "tomorrow":
            return queryset.filter(date=timezone.now().date() + timedelta(days=1))
        if self.value() == "lastmonth":
            return queryset.filter(
                billing_month=(
                    timezone.now().date().replace(day=1) - timedelta(days=1)
                ).replace(day=1)
            )
        return queryset


class AvailabilityInterviewerExperienceFilter(BaseDetailedExperienceFilter):
    """Experience filter for InterviewerAvailability admin (through FK)"""

    title = "Interviewer Experience Level"
    parameter_name = "interviewer_experience"
    experience_field_path = "interviewer__total_experience_years"


@admin.register(InterviewerAvailability)
class InterviewerAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_interviewer_name",
        "date",
        "start_time",
        "end_time",
        "is_scheduled",
        "archived",
    )
    list_filter = (
        "interviewer__strength",
        "interviewer__interviewer_level",
        AvailabilityInterviewerExperienceFilter,
        ("date", DateRangeFilter),
        TomorrowAndLastMonthFilter,
    )
    search_fields = ("interviewer__name",)
    ordering = ("-id",)
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related("interviewer")

    def get_interviewer_name(self, obj):
        return obj.interviewer.name if hasattr(obj.interviewer, "name") else None

    get_interviewer_name.short_description = "Interviewer"


@admin.register(InterviewFeedback)
class InterviewFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_interview_name",
        "overall_remark",
        "overall_score",
        "is_submitted",
        "archived",
    )
    list_filter = ("is_submitted",)
    search_fields = ("interview__candidate__name", "interview__interviewer__name")
    list_per_page = 20

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "interview", "interview__candidate", "interview__interviewer"
            )
        )

    def get_interview_name(self, obj):
        if obj.interview:
            return f"{obj.interview.candidate.name} - {obj.interview.interviewer.name}"
        return "None"

    get_interview_name.short_description = "Interview"


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "amount_due",
        "due_date",
        "get_client_name",
        "get_interviewer_name",
        "created_at",
        "billing_month",
        "total_recv_w_tax",
        "total_recv_wo_tax",
        "archived",
    )
    list_filter = ("client__name", "interviewer__name")
    search_fields = ("client__name", "interviewer__name")
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related("client", "interviewer")

    def get_client_name(self, obj):
        return obj.client.name if hasattr(obj.client, "name") else None

    get_client_name.short_description = "Client"

    def get_interviewer_name(self, obj):
        return obj.interviewer.name if hasattr(obj.interviewer, "name") else None

    get_interviewer_name.short_description = "Interviewer"

    def total_recv_w_tax(self, obj):
        return obj.total_amount_received_with_tax

    total_recv_w_tax.short_description = "Total With Tax"

    def total_recv_wo_tax(self, obj):
        return obj.total_amount_received_without_tax

    total_recv_wo_tax.short_description = "Total Without Tax"


@admin.register(BillingLog)
class BillingLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_interview_name",
        "get_client_name",
        "get_interviewer_name",
        "amount_for_client",
        "amount_for_interviewer",
        "status",
        "reason",
        "billing_month",
        "is_billing_calculated",
        "archived",
    )
    list_filter = (
        "reason",
        "billing_month",
        TomorrowAndLastMonthFilter,
        "is_billing_calculated",
    )
    search_fields = ("interview__candidate__name", "client__name", "interviewer__name")
    actions = ["update_status_to_paid", "update_status_to_pending"]
    list_per_page = 20

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "interview",
                "client",
                "interviewer",
                "interview__candidate",
                "interview__interviewer",
            )
        )

    def get_interview_name(self, obj):
        return (
            f"{obj.interview.candidate.name} - {obj.interview.interviewer.name}"
            if obj.interview
            else "None"
        )

    get_interview_name.short_description = "Interview"

    def get_client_name(self, obj):
        return obj.client.name if obj.client else "None"

    get_client_name.short_description = "Client"

    def get_interviewer_name(self, obj):
        return obj.interviewer.name if obj.interviewer else "None"

    get_interviewer_name.short_description = "Interviewer"

    @admin.action(description="Mark Selected records as Paid")
    def update_status_to_paid(self, request, queryset):
        updated_count = queryset.filter(status="PED").update(status="PAI")
        self.message_user(
            request,
            ngettext(
                "%d record was successfully marked as paid.",
                "%d records were successfully marked as paid.",
                updated_count,
            )
            % updated_count,
            messages.SUCCESS,
        )

    @admin.action(description="Mark Selected records as Pending")
    def update_status_to_pending(self, request, queryset):
        updated_count = queryset.filter(status="PAI").update(status="PED")
        self.message_user(
            request,
            ngettext(
                "%d record was successfully marked as pending.",
                "%d records were successfully marked as pending.",
                updated_count,
            )
            % updated_count,
            messages.SUCCESS,
        )


@admin.register(BillPayments)
class BillPaymentsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_billing_record",
        "amount",
        "payment_link_id",
        "payment_status",
        "payment_date",
        "transaction_id",
        "link_expired_time",
        "cf_link_id",
        "order_id",
        "customer_name",
        "customer_email",
        "archived",
    )
    list_filter = ("payment_status", "payment_date")
    search_fields = (
        "billing_record__invoice_number",
        "payment_link_id",
        "transaction_id",
        "cf_link_id",
        "order_id",
        "customer_name",
        "customer_phone",
        "customer_email",
    )
    list_per_page = 20

    def get_queryset(self, request):
        return self.model.object_all.select_related("billing_record")

    def get_billing_record(self, obj):
        return obj.billing_record.invoice_number if obj.billing_record else "None"

    get_billing_record.short_description = "Billing Record"


@admin.register(CandidateToInterviewerFeedback)
class CandidateToInterviewerFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_candidate_name",
        "get_interviewer_name",
        "get_interview_id",
        "rating",
        "comments",
        "is_expired",
        "archived",
    )
    search_fields = ("interview__candidate__name", "interviewer__name")
    list_per_page = 20

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("interview", "interviewer", "interview__candidate")
        )

    def get_candidate_name(self, obj):
        return obj.interview.candidate.name

    get_candidate_name.short_description = "Candidate"

    def get_interviewer_name(self, obj):
        return obj.interviewer.name

    get_interviewer_name.short_description = "Interviewer"

    def get_interview_id(self, obj):
        return obj.interview.id

    get_interview_id.short_description = "Interview ID"
