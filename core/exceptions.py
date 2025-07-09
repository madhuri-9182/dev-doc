from rest_framework.views import exception_handler
from rest_framework.exceptions import PermissionDenied, NotAuthenticated


def permission_denied_custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(exc, PermissionDenied):
            response.data = {
                "status": "failed",
                "message": "Permission denied",
                "errors": response.data.get("detail", "Permission denied"),
            }
        elif isinstance(exc, NotAuthenticated):
            response.data = {
                "status": "failed",
                "message": "Authentication required",
                "errors": response.data.get("detail"),
            }

    return response
