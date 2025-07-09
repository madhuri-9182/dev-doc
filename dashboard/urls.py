from django.urls import path, include
from .views import (
    InternalClientView,
    InternalClientDetailsView,
    InterviewerView,
    InterviewerDetails,
    InterviewerAvailabilityView,
)


urlpatterns = [
    path("client/", include("dashboard.URLs.ClientUrls")),
    path("internal/", include("dashboard.URLs.InternalUrls")),
    path("interviewer/", include("dashboard.URLs.InterviewerUrls")),
]
