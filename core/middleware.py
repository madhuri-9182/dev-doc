from django.contrib.auth.middleware import get_user
from django.utils.functional import SimpleLazyObject
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from django.http import JsonResponse
from rest_framework import status


class VerificationMiddleWare:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return None

        view_class = getattr(view_func, "view_class", None)
        if view_class and view_class.__name__ == "ResendEmailVerificationView":
            return None

        if not request.user.email_verified or not request.user.phone_verified:
            return JsonResponse(
                {
                    "status": "failed",
                    "message": "Please verify your email and phone.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return None


class AuthenticationMiddlewareJWT:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        user = SimpleLazyObject(lambda: self.__class__.get_jwt_user(request))
        if isinstance(user, InvalidToken):
            return JsonResponse(
                {
                    "status": "failed",
                    "message:": "Either token is invalid or expired or not present in cookie",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        request.user = user
        return self.get_response(request)

    @staticmethod
    def get_jwt_user(request):
        user = get_user(request)
        if user.is_authenticated:
            return user
        try:
            jwt_user = JWTAuthentication().authenticate(Request(request))
            if jwt_user is not None:
                return jwt_user[0]
        except Exception as e:
            return e
        return user
