"""Fail-closed deployment settings; select explicitly for management commands."""
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F403
from .base import CSRF_TRUSTED_ORIGINS, env_bool, env_value

if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("trace-development", "tdt-development")):  # noqa: F405
    raise ImproperlyConfigured("Set TRACE_SECRET_KEY to a private random value of at least 50 characters.")
if not ALLOWED_HOSTS or any("*" in host or host.startswith(".") for host in ALLOWED_HOSTS):  # noqa: F405
    raise ImproperlyConfigured("Set explicit TRACE_ALLOWED_HOSTS in production; wildcards are not allowed.")
if (STORAGE_ROOT == STATIC_ROOT or STORAGE_ROOT in STATIC_ROOT.parents  # noqa: F405
        or STATIC_ROOT in STORAGE_ROOT.parents  # noqa: F405
        or STORAGE_ROOT == BASE_DIR / "static" or BASE_DIR / "static" in STORAGE_ROOT.parents):  # noqa: F405
    raise ImproperlyConfigured("Private storage must be outside public static directories.")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
TRACE_REQUIRE_VENDOR = True
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")
TRACE_TRUST_PROXY = env_bool("TRACE_TRUST_PROXY")
TRACE_PROXY_IP = env_value("TRACE_PROXY_IP", "127.0.0.1")
if TRACE_TRUST_PROXY:  # noqa: F405
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if TRACE_TRUST_PROXY:
    import ipaddress
    try:
        ipaddress.ip_address(TRACE_PROXY_IP)
    except ValueError as exc:
        raise ImproperlyConfigured("TRACE_PROXY_IP must identify exactly one trusted proxy IP, never a wildcard.") from exc
if any(not origin.startswith("https://") or "*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Production CSRF origins must be explicit HTTPS origins.")

# Minimal local readiness remains usable without spoofing proxy headers.
SECURE_REDIRECT_EXEMPT = [r"^health/$"]

# A private host must not assert HTTPS policy for unrelated subdomains or request
# public browser preload. All other deployment checks remain enabled.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
