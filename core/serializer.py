import hmac
import hashlib
from django.core.exceptions import ValidationError
from django.conf import settings
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import password_validation, authenticate
from django.contrib.auth.hashers import check_password
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken
from django_rest_passwordreset import models
from django_rest_passwordreset.serializers import (
    PasswordTokenSerializer,
)
from .models import User, Role, FeedbackAndImprovement
from hiringdogbackend.utils import validate_incoming_data, validate_attachment


def get_user_id_hash(user_id):
    api_key = settings.TAWKTO_API
    user_id_hash = hmac.new(
        key=api_key.encode(),
        msg=str(user_id).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return user_id_hash


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    data = {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "id": user.id,
        "role": user.role,
        "name": user.profile.name,
        "is_password_change": user.is_password_change,
        "is_policy_and_tnc_accepted": user.is_policy_and_tnc_accepted,
        "is_email_verified": user.email_verified,
        "user_id_hash": get_user_id_hash(user.id),
    }
    if user.role == Role.INTERVIEWER:
        data["is_bank_account_updated"] = user.interviewer.is_bank_account_updated
    return data


class UserSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True, required=False)
    name = serializers.CharField(max_length=100, required=False)

    class Meta:
        model = User
        fields = ("name", "email", "password", "confirm_password", "phone")
        extra_kwargs = {
            "email": {"required": False},
            "password": {"required": False},
            "phone": {"required": False},
        }

    def validate(self, data):
        errors = validate_incoming_data(data, list(self.fields.keys()))

        if errors:
            raise serializers.ValidationError({"errors": errors})

        password = data.get("password")
        confirm_password = data.get("confirm_password")

        if password != confirm_password:
            raise serializers.ValidationError(
                {"errors": "Password and confirm_password are not the same."}
            )
        password_validation.validate_password(password)
        return data

    def create(self, validated_data):
        validated_data.pop("confirm_password", None)
        name = validated_data.pop("name", None)
        user = User.objects.create_user(**validated_data)
        user.profile.name = name
        user.profile.save()
        return user


class UserLoginSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()

    def validate(self, data):
        request = self.context["request"]
        errors = validate_incoming_data(
            self.initial_data,
            ["email", "password"],
            ["csrfmiddlewaretoken", "is_policy_and_tnc_accepted"],
        )

        if errors:
            raise serializers.ValidationError({"errors": errors})
        user = authenticate(request, **data)

        if not user:
            errors.setdefault("credentials", []).append(
                "Invalid email or password. Please check your credentials and try again."
            )

        is_accepted = data.get("is_policy_and_tnc_accepted")
        if user and user.login_count > 0 and is_accepted is not None:
            errors.setdefault("is_policy_and_tnc_accepted", []).append("Invalid key.")

        if user and hasattr(user, "clientuser"):
            client_user = user.clientuser

            if not user.is_active:
                errors.setdefault("account", []).append(
                    f"Your account is being deactivated. Kindly contact {user.clientuser.organization.name} Admin"
                )

            if (
                user.role not in ["client_admin", "client_owner"]
                and client_user.status != "ACT"
            ):
                errors.setdefault("account", []).append(
                    "Your account is not activated. Please check your organization invitation email for activation link."
                )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        user.login_count += 1
        user.last_login = timezone.now()
        if is_accepted:
            user.is_policy_and_tnc_accepted = is_accepted
        user.save(
            update_fields=["login_count", "last_login", "is_policy_and_tnc_accepted"]
        )

        tokens = get_tokens_for_user(user)
        data["tokens"] = tokens

        return data

    class Meta:
        model = User
        fields = ("email", "password")
        extra_kwargs = {
            "email": {"required": False},
            "password": {"write_only": True, "required": False},
        }


class CookieTokenRefreshSerializer(TokenRefreshSerializer):
    refresh = None

    def validate(self, data):
        data["refresh"] = self.context.get("request").COOKIES.get("refresh_token")

        if data["refresh"]:
            try:
                token = RefreshToken(data["refresh"])
                user_id = token.payload.get("user_id")

                user_obj = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                raise ValidationError({"errors": "Invalid User ID"})
            except Exception:
                raise ValidationError({"errors": "Invalid Token"})
            data = super().validate(data)
            data["id"] = user_obj.id
            data["email"] = user_obj.email
            data["role"] = user_obj.role
            data["name"] = user_obj.profile.name
            data["is_password_change"] = user_obj.is_password_change
            data["is_policy_and_tnc_accepted"] = user_obj.is_policy_and_tnc_accepted
            data["is_email_verified"] = user_obj.email_verified
            data["user_id_hash"] = get_user_id_hash(user_obj.id)
            if user_obj.role == Role.INTERVIEWER:
                data["is_bank_account_updated"] = (
                    user_obj.interviewer.is_bank_account_updated
                )
            return data

        raise ValidationError({"errors": "No valid token found in cookie"})


class ResetPasswordConfirmSerailizer(PasswordTokenSerializer):
    def validate(self, data):
        try:
            reset_password_token = get_object_or_404(
                models.ResetPasswordToken, key=data.get("token")
            )
        except (
            TypeError,
            ValueError,
            ValidationError,
            Http404,
            models.ResetPasswordToken.DoesNotExist,
        ):
            raise Http404(
                _("The OTP password entered is not valid. Please check and try again.")
            )

        if check_password(data.get("password"), reset_password_token.user.password):
            raise ValidationError(
                {
                    "errors": "The new password cannot be the same as your current password. Please choose a different password."
                }
            )

        return super().validate(data)


class GoogleAuthCallbackSerializer(serializers.Serializer):
    state = serializers.CharField(max_length=255)
    authorization_response = serializers.URLField()


class ChangePasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        request = self.context.get("request")

        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError({"password": ["passwords are not same."]})

        if check_password(data["password"], request.user.password):
            raise serializers.ValidationError(
                {
                    "password": [
                        "The new password cannot be the same as your current password."
                    ]
                }
            )

        return data


class FeedbackAndImprovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackAndImprovement
        fields = ("context", "screenshot", "priority", "feedback_type")

    def validate(self, data):
        errors = validate_incoming_data(
            self.initial_data,
            ["context", "priority", "feedback_type"],
            ["screenshot"],
            partial=self.partial,
            original_data=data,
            form=True,
        )

        if data.get("screenshot"):
            errors.update(
                validate_attachment(
                    "screenshot",
                    data.get("screenshot"),
                    allowed_extensions=["png", "jpeg"],
                    max_size_mb=3,
                )
            )

        if errors:
            raise serializers.ValidationError(errors)

        return data
