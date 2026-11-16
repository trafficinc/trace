from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables
from .throttling import release_success, reserve_attempt


class RateLimitedModelBackend(ModelBackend):
    @sensitive_variables("password", "kwargs")
    def authenticate(self, request, username=None, password=None, **kwargs):
        username = username or kwargs.get("username", "")
        if password is None:
            return None
        reservations, retry_after = reserve_attempt(username, request)
        if retry_after:
            if request is not None:
                request.trace_login_retry_after = retry_after
            raise PermissionDenied("Authentication temporarily limited")
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            release_success(reservations)
        return user
