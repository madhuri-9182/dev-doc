from django.urls import path
from .views import (
    UserSignupView,
    UserLoginView,
    CookieTokenRefreshView,
    LogoutView,
    LogoutAllView,
    PasswordResetView,
    PasswordResetConfirmView,
    GoogleAuthInitView,
    GoogleAuthCallbackView,
    GoogleCalenderGetEventView,
    VerifyEmailView,
    ChangePasswordView,
    AcceptTNCView,
    ResendEmailVerificationView,
    FeedbackAndImprovementView,
)

urlpatterns = [
    path("refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("login/", UserLoginView.as_view(), name="user_login"),
    path(
        "email-verify/<str:verification_uid>/",
        VerifyEmailView.as_view(),
        name="user_email_verification",
    ),
    path("signup/", UserSignupView.as_view(), name="user_signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("logout-all/", LogoutAllView.as_view(), name="logout-all"),
    path("password_reset/", PasswordResetView.as_view(), name="password_reset_token"),
    path(
        "password_reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "google-auth/init/",
        GoogleAuthInitView.as_view(),
        name="google_auth_initialization",
    ),
    path(
        "google-auth/callback/",
        GoogleAuthCallbackView.as_view(),
        name="google_call_back",
    ),
    path("events/", GoogleCalenderGetEventView.as_view(), name="google_events"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("tnc-accepted/", AcceptTNCView.as_view(), name="tnc_accepted"),
    path(
        "resend-verification-mail/",
        ResendEmailVerificationView.as_view(),
        name="resend_verification_mail",
    ),
    path(
        "feedback-and-improvement/",
        FeedbackAndImprovementView.as_view(),
        name="feedback_and_improvement",
    ),
]
