from django.urls import path
from ..views import (
    InterviewerAvailabilityView,
    InterviewerReqeustView,
    InterviewerRequestResponseView,
    InterviewerAcceptedInterviewsView,
    InterviewerPendingFeedbackView,
    InterviewerInterviewHistoryView,
    InterviewFeedbackView,
    FinanceView,
    InterviewerBankAccountView,
)

urlpatterns = [
    path(
        "block-calendar/",
        InterviewerAvailabilityView.as_view(),
        name="calendar-blocking",
    ),
    path(
        "interviewer-request-notification/",
        InterviewerReqeustView.as_view(),
        name="interviewer-request-notification",
    ),
    path(
        "interviewer-requst-confirmation/<str:request_id>/",
        InterviewerRequestResponseView.as_view(),
        name="interviewer-request-confirmation",
    ),
    path(
        "accepted-interviews/",
        InterviewerAcceptedInterviewsView.as_view(),
        name="accepted-interviews",
    ),
    path(
        "pending-feedback/",
        InterviewerPendingFeedbackView.as_view(),
        name="pending-feedback",
    ),
    path(
        "interview-history/",
        InterviewerInterviewHistoryView.as_view(),
        name="interview-history",
    ),
    path(
        "interview-feedback/",
        InterviewFeedbackView.as_view(),
        name="interview-feedback",
    ),
    path(
        "interview-feedback/<int:interview_id>/",
        InterviewFeedbackView.as_view(),
        name="interview-feedback",
    ),
    path("finance/", FinanceView.as_view(), name="interviewer-finance"),
    path("bank-account/", InterviewerBankAccountView.as_view(), name="bank-account"),
]
