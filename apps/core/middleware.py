import logging
import time
import uuid
from django.conf import settings
from django.http import HttpResponse
from .logging import request_id

logger = logging.getLogger("trace.http")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request_id.set(uuid.uuid4().hex)
        start = time.monotonic()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            if not request.path.startswith(settings.STATIC_URL):
                if request.path == '/health/':
                    response.setdefault('Cache-Control', 'no-store')
                else:
                    response['Cache-Control'] = 'no-store, private'
            response["X-Request-ID"] = request_id.get()
            return response
        finally:
            logger.info("http_request", extra={"status_code": status, "method": request.method,
                        "duration_ms": round((time.monotonic() - start) * 1000, 2)})
            request_id.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.headers.get("HX-Request") == "true" and response.status_code == 302
                and not request.user.is_authenticated):
            match = request.resolver_match
            if (match and match.namespace == 'core' and match.url_name in {
                    'editor_status', 'editor_presence', 'engagement_editor_status', 'engagement_editor_presence'}) or (request.method == 'POST' and 'version' in request.POST):
                # A background poll must never navigate away from an unsaved draft.
                response = HttpResponse('<p role="status">Your session expired. Sign in in another tab; your draft remains here.</p>', status=401)
                response['Cache-Control'] = 'no-store, private'
                response['Vary'] = 'HX-Request'
            else:
                response["HX-Redirect"] = response["Location"]
                del response["Location"]
                response.status_code = 204
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Django admin uses its own scripts and inline presentation.
        if not request.path.startswith("/admin/"):
            response.setdefault("Content-Security-Policy", (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            ))
        if request.user.is_authenticated or request.path.startswith("/accounts/") or "HX-Redirect" in response:
            response["Cache-Control"] = "no-store, private"
        return response
