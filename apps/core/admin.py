from django.contrib.admin import AdminSite


class ServerAdminSite(AdminSite):
    site_header = "TRACE administration"
    site_title = "TRACE"

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def login(self, request, extra_context=None):
        response = super().login(request, extra_context)
        if request.method == "POST" and response.status_code == 200:
            from apps.accounts.throttling import record_unhandled_failure
            record_unhandled_failure(request)
        if getattr(request, "trace_login_retry_after", 0):
            response.status_code = 429
            response["Retry-After"] = str(request.trace_login_retry_after)
        return response
