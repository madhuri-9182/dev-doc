from django.urls import path
from ..views import (
    InternalClientView,
    InternalClientDetailsView,
    InterviewerDetails,
    InterviewerView,
    OrganizationAgreementView,
    OrganizationAgreementDetailView,
    OrganizationView,
    InternalDashboardView,
    InternalClientUserView,
    HDIPUsersViews,
    DomainDesignationView,
    InternalClientDomainView,
    InternalEngagementView,
    FinanceView,
)

urlpatterns = [
    path("internal-client/", InternalClientView.as_view(), name="internal-client"),
    path(
        "internal-client/<int:pk>/",
        InternalClientDetailsView.as_view(),
        name="internal-client-details",
    ),
    path("interviewers/", InterviewerView.as_view(), name="interviewer"),
    path(
        "interviewer/<int:pk>/",
        InterviewerDetails.as_view(),
        name="interviewer-details",
    ),
    path("agreements/", OrganizationAgreementView.as_view(), name="agreement"),
    path(
        "agreement/<int:organization_id>/",
        OrganizationAgreementDetailView.as_view(),
        name="agreement-details",
    ),
    path("organizations/", OrganizationView.as_view(), name="organizations"),
    path(
        "agreement-organization/",
        OrganizationView.as_view(),
        name="agreement-organization",
    ),
    path("dashboard/", InternalDashboardView.as_view(), name="dashboard"),
    path("hdip-users/", HDIPUsersViews.as_view(), name="hdip-user"),
    path("hdip-user/<int:pk>/", HDIPUsersViews.as_view(), name="hdip-user-details"),
    path(
        "internal-client-user/", InternalClientUserView.as_view(), name="internal-user"
    ),
    path(
        "internal-client-user/<int:pk>/",
        InternalClientUserView.as_view(),
        name="internal-user",
    ),
    path(
        "domain-designation/",
        DomainDesignationView.as_view(),
        name="domain-designation",
    ),
    path(
        "client-domains/",
        InternalClientDomainView.as_view(),
        name="client-domains",
    ),
    path(
        "engagements/",
        InternalEngagementView.as_view(),
        name="engagements",
    ),
    path("finance/", FinanceView.as_view(), name="internal-finance"),
]
