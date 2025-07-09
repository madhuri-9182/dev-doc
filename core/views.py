import datetime
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.conf import settings
from django.utils.encoding import force_bytes
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)
from rest_framework.permissions import IsAuthenticated
from django_rest_passwordreset.views import (
    ResetPasswordRequestToken,
    ResetPasswordConfirm,
)
from .models import OAuthToken, User
from .serializer import (
    UserSerializer,
    UserLoginSerializer,
    CookieTokenRefreshSerializer,
    ResetPasswordConfirmSerailizer,
    GoogleAuthCallbackSerializer,
    ChangePasswordSerializer,
    FeedbackAndImprovementSerializer,
)
from rest_framework.request import Request
from drf_spectacular.utils import extend_schema

from externals.google.google_calendar import GoogleCalendar
from dashboard.tasks import send_mail
from hiringdogbackend.utils import log_action


def custom_404(request, exception):
    response_data = {"error": "Not Found", "message": "Invalid route.", "status": 404}
    return JsonResponse(response_data, status=404)


@extend_schema(tags=["Authentication"])
class UserSignupView(APIView):
    """
    View for handling user signup.

    This view allows new users to sign up by providing the necessary details.
    Upon successful signup, it returns a success message. If there are any
    validation errors, it raises an exception.
    """

    serializer_class = UserSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"status": "success", "message": "User signup sucessfully."},
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Authentication"])
class UserLoginView(APIView):
    """
    View for handling user login.

    This view authenticates a user based on the provided credentials.
    Upon successful authentication, it returns a success message along with
    user data and tokens. The refresh token is set as an HTTP-only cookie for
    enhanced security.

    Responses:
    200: Login successful
    400: Validation errors
    """

    serializer_class = UserLoginSerializer

    def post(self, request):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            custom_error = serializer.errors.pop("errors", None)
            return Response(
                {
                    "status": "failed",
                    "message": "Invalid data.",
                    "errors": serializer.errors if not custom_error else custom_error,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = {**serializer.data, **serializer.validated_data.get("tokens")}

        response = Response(
            {
                "status": "success",
                "message": "Login successful.",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )

        refresh_token = data.get("refresh")
        if refresh_token:
            cookie_max_age = 3600 * 24 * 15
            response.set_cookie(
                "refresh_token",
                refresh_token,
                max_age=cookie_max_age,
                httponly=True,
                samesite="None",
                secure=True,
            )
            del data["refresh"]
        return response


@extend_schema(tags=["Authentication"])
class CookieTokenRefreshView(TokenRefreshView):
    serializer_class = CookieTokenRefreshSerializer

    def finalize_response(self, request, response, *args, **kwargs):
        if isinstance(response.data, dict):
            refresh_token = response.data.pop("refresh", None)
            if refresh_token:
                cookie_max_age = 3600 * 24 * 15
                response.set_cookie(
                    "refresh_token",
                    refresh_token,
                    max_age=cookie_max_age,
                    httponly=True,
                    samesite="None",
                    secure=True,
                )
            if response.status_code == 200:
                response.data = {
                    "status": "success",
                    "message": "Access token refreshed successfully.",
                    "data": {**response.data},
                }
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Authentication"])
class LogoutView(APIView):
    """
    View for logging out a user by blacklisting their refresh token.

    This view checks for the presence of a refresh token in the request cookies.
    If found, it attempts to blacklist the token, effectively logging the user out.
    It responds with a success message upon successful logout, or an appropriate
    error message and status code if the token is missing or invalid.

    Responses:
    205: Logout successful
    400: Token errors
    401: Invalid request
    """

    permission_classes = (IsAuthenticated,)

    @extend_schema(
        request=None,
        responses={
            205: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "success"},
                    "message": {"type": "string", "example": "Logout successful"},
                },
            },
            401: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "fail"},
                    "message": {"type": "string", "example": "Invalid request"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "fail"},
                    "message": {"type": "string", "example": "Token errors"},
                },
            },
        },
    )
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get("refresh_token")
        if not refresh:
            return Response(
                {"status": "failed", "message": "Invalid request"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            refresh_obj = RefreshToken(refresh)
            refresh_obj.blacklist()
        except TokenError:
            return Response(
                {"status": "fail", "message": "Token errors"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"status": "success", "message": "Logout successful"},
            status=status.HTTP_205_RESET_CONTENT,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response.delete_cookie("refresh_token")
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Authentication"])
class LogoutAllView(APIView):
    """
    Logout user from all other sessions

    This API will log the user out of all other sessions.
    """

    permission_classes = (IsAuthenticated,)

    @extend_schema(
        request=None,
        responses={
            205: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "success"},
                    "message": {"type": "string", "example": "Logout successful"},
                },
            },
            401: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "fail"},
                    "message": {"type": "string", "example": "Invalid request"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "fail"},
                    "message": {"type": "string", "example": "Token errors"},
                },
            },
        },
    )
    def post(self, request):

        user = request.user
        outstanding_tokens = OutstandingToken.objects.filter(user=user).exclude(
            id__in=BlacklistedToken.objects.filter(token__user=user).values("token_id")
        )
        blacklisted_token_obj = [
            BlacklistedToken(token=token) for token in outstanding_tokens
        ]
        BlacklistedToken.objects.bulk_create(blacklisted_token_obj)

        return Response(
            {"status": "success", "message": "Logout sucessfull for all session"},
            status=status.HTTP_200_OK,
        )

    def finalize_response(self, request, response, *args, **kwargs):

        response.delete_cookie("refresh_token")
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Authentication"])
class PasswordResetView(ResetPasswordRequestToken):
    def finalize_response(self, request, response, *args, **kwargs):
        data = response.data
        if response.status_code == 200:
            data["status"] = "success"
            data["message"] = (
                "If an account with the provided email exists, a password reset link has been sent. Please check your inbox to proceed."
            )
        else:
            data["status"] = "failed"
            data["message"] = "Token creation failed"
            if data.get("detail"):
                data["errors"] = data["detail"]
                del data["detail"]
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(tags=["Authentication"])
class PasswordResetConfirmView(ResetPasswordConfirm):
    serializer_class = ResetPasswordConfirmSerailizer

    def finalize_response(self, request, response, *args, **kwargs):
        data = response.data
        if response.status_code == 200:
            data["status"] = "success"
            data["message"] = (
                "Your password has been reset successfully. You can now log in with your new credentials."
            )
        else:
            data["status"] = "failed"
            data["message"] = "Password reset failed. Please try again."
            if data.get("detail"):
                data["errors"] = [data["detail"]]
                del data["detail"]
        return super().finalize_response(request, response, *args, **kwargs)


@extend_schema(
    description="Initialize Google OAuth flow",
    responses={200: {"type": "string", "description": "Authorization URL"}},
    tags=["Authentication"],
)
class GoogleAuthInitView(APIView):
    serializer_class = None
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        try:
            google_calendar = GoogleCalendar()
            state, authorization_url = google_calendar.auth_init()
            previous_state = request.session.get("state")
            request.session["state"] = state
            log_action(
                f"Before: {previous_state}, After: {request.session.get('state')}",
                request
            )
            return Response(
                {
                    "status": "success",
                    "message": "Initialize successfully",
                    "data": {"url": authorization_url},
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "status": "failed",
                    "message": f"Error generating authorization URL: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema(
    description="Handle callback from Google OAuth flow",
    responses={
        200: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "success"},
                "message": {"type": "string", "example": "Authentication Successful"},
            },
        },
        400: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "fail"},
                "message": {"type": "string", "example": "Invalid state parameter"},
            },
        },
        500: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "fail"},
                "message": {
                    "type": "string",
                    "example": "Error during authentication callback",
                },
            },
        },
    },
    tags=["Authentication"],
)
class GoogleAuthCallbackView(APIView):
    serializer_class = GoogleAuthCallbackSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        state = request.session.get("state")

        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "status": "failed",
                    "message": "Invalid request",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated_data = serializer.validated_data
        received_state = validated_data.get("state")
        authorization_response = validated_data.get("authorization_response")

        # if not state or received_state != state:
        #     return Response(
        #         {
        #             "status": "failed",
        #             "message": "Invalid state parameter",
        #         },
        #         status=status.HTTP_400_BAD_REQUEST,
        #     )

        try:
            google_calendar = GoogleCalendar()
            access_token, refresh_token, expired_time = google_calendar.auth_callback(
                received_state, authorization_response
            )

            # Store tokens in DB
            OAuthToken.objects.update_or_create(
                user=request.user,
                defaults={
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expired_time,
                },
            )

            return Response(
                {
                    "status": "success",
                    "message": "Authentication Successful",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "status": "failed",
                    "message": f"Error during authentication callback: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema(
    tags=["Authentication"],
    responses={
        200: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "success"},
                "message": {
                    "type": "string",
                    "example": "Successfully retrieve event information",
                },
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "example": "123456789"},
                            "start": {
                                "type": "string",
                                "example": "2025-01-26T17:00:00+05:30",
                            },
                            "summary": {
                                "type": "string",
                                "example": "Interview Available Time",
                            },
                            "status": {"type": "string", "example": "confirmed"},
                        },
                    },
                },
            },
        },
        400: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "fail"},
                "message": {
                    "type": "string",
                    "example": "OAuth token not found for the user",
                },
            },
        },
    },
)
class GoogleCalenderGetEventView(APIView):
    serializer_class = None
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        page_token = request.query_params.get("page_token")
        try:
            oath_obj = OAuthToken.objects.get(user=request.user)
        except OAuthToken.DoesNotExist:
            return Response(
                {"status": "failed", "message": "OAuth token not found for the user"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        google_calendar = GoogleCalendar()
        try:
            events = google_calendar.get_events(
                oath_obj.access_token, oath_obj.refresh_token, request.user, page_token
            )
            return Response(
                {
                    "status": "success",
                    "message": "Successfully retrieve event information",
                    "data": events,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"status": "failed", "message": f"error occured. {e}"},
                status=(
                    status.HTTP_401_UNAUTHORIZED
                    if "revoked" or "expired" in str(e)
                    else status.HTTP_400_BAD_REQUEST
                ),
            )


class VerifyEmailView(APIView):
    serializer_class = None

    def post(self, request, verification_uid):
        try:
            user_id, expired_timestamp = force_str(
                urlsafe_base64_decode(verification_uid)
            ).split(":")
        except (ValueError, TypeError):
            return Response(
                {"status": "failed", "message": "Invalid verification_uid format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if datetime.datetime.now().timestamp() > float(expired_timestamp):
            return Response(
                {"status": "failed", "message": "Link expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = User.objects.filter(pk=user_id).update(
            email_verified=True,
            email_verified_date=datetime.date.today(),
            phone_verified=True,  # keep it for temporary will change it later
        )

        if updated:
            return Response(
                {"status": "success", "message": "User verified successfully."},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"status": "failed", "message": "User not found."},
            status=status.HTTP_404_NOT_FOUND,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            custom_error = serializer.errors.pop("errors", None)
            return Response(
                {
                    "status": "failed",
                    "message": "Invalid data.",
                    "errors": serializer.errors or custom_error,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        user.set_password(serializer.validated_data["password"])
        user.is_password_change = True
        user.save()
        return Response(
            {"status": "success", "message": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


class AcceptTNCView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user.is_policy_and_tnc_accepted = True
        user.save(update_fields=["is_policy_and_tnc_accepted"])
        return Response(
            {"status": "success", "message": "TNC Accepted successfully."},
            status=status.HTTP_200_OK,
        )


class ResendEmailVerificationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.email_verified:
            return Response(
                {"status": "failed", "message": "Email is already verified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        verification_data = (
            f"{user.id}:{int(datetime.datetime.now().timestamp() + 86400)}"
        )
        verification_data_uid = urlsafe_base64_encode(force_bytes(verification_data))
        send_mail.delay(
            to=user.email,
            subject="Verify your email address",
            template="email_verification.html",
            user_name=user.profile.name,
            site_domain=settings.SITE_DOMAIN,
            verification_link=f"/verification/{verification_data_uid}/",
        )
        return Response(
            {"status": "success", "message": "Verification email sent successfully."},
            status=status.HTTP_200_OK,
        )


class FeedbackAndImprovementView(APIView):
    serializer_class = FeedbackAndImprovementSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": "failed",
                    "message": "Invalid data",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        feedback = serializer.save(user=request.user)
        attachments = []
        if feedback.screenshot:
            attachments.append(
                {
                    "filename": feedback.screenshot.name.split("/")[-1],
                    "content": feedback.screenshot.read(),
                    "content_type": request.FILES.get("screenshot").content_type,
                }
            )
        send_mail.delay(
            to=settings.INTERNAL_SYSTEM_FEEDBACK_EMAIL,
            subject="New System Bug/Enhancement User Feedback Submitted",
            template="internal_feedback_notification.html",
            bcc=settings.INTERNAL_SYSTEM_FEEDBACK_BCC_EMAIL,
            user_name=request.user.profile.name,
            user_email=request.user.email,
            feedback_type=feedback.get_feedback_type_display(),
            feedback_content=feedback.context,
            has_screenshot=True if feedback.screenshot else False,
            attachments=attachments,
            priority=feedback.get_priority_display(),
            submission_date=datetime.datetime.now().strftime("%d/%m/%Y %I:%M %P"),
        )
        return Response(
            {"status": "success", "message": "Feedback submitted successfully."},
            status=status.HTTP_201_CREATED,
        )
