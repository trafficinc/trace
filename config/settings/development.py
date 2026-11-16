"""Loopback development only. manage.py uses these settings by default."""
from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "tdt-development-key-never-use-in-production"  # noqa: F405
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1", "[::1]"]  # noqa: F405
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

TRACE_TRUST_PROXY = False
TRACE_PROXY_IP = "127.0.0.1"
