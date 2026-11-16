"""Shared configuration; production and development make explicit security choices."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]


def env_value(name, default=""):
    """Prefer TRACE configuration while accepting existing TDT deployments."""
    if name in os.environ:
        return os.environ[name]
    if name.startswith("TRACE_"):
        return os.environ.get("TDT_" + name.removeprefix("TRACE_"), default)
    return os.environ.get(name, default)


def env_list(name, default=""):
    return [item.strip() for item in env_value(name, default).split(",") if item.strip()]


def env_bool(name, default=False):
    value = env_value(name, str(int(default))).strip().lower()
    if value not in {"1", "0", "true", "false"}:
        raise ImproperlyConfigured(f"{name} must be 1, 0, true or false.")
    return value in {"1", "true"}


SECRET_KEY = env_value("TRACE_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("TRACE_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("TRACE_CSRF_TRUSTED_ORIGINS")
INSTALLED_APPS = [
    "apps.core.apps.TRACEAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.engagements.apps.EngagementsConfig",
    "apps.assets.apps.AssetsConfig",
    "apps.testcases.apps.TestcasesConfig",
    "apps.findings.apps.FindingsConfig",
    "apps.evidence.apps.EvidenceConfig",
    "apps.reports.apps.ReportsConfig",
    "apps.audit.apps.AuditConfig",
    "apps.core.apps.CoreConfig",
]
MIDDLEWARE = [
    "apps.core.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.core.context_processors.application",
    ]},
}]

STORAGE_ROOT = Path(env_value("TRACE_STORAGE_ROOT", BASE_DIR / "storage")).expanduser().resolve()
DATABASE_ROOT = STORAGE_ROOT / "db"
EVIDENCE_ROOT = STORAGE_ROOT / "evidence"
REPORT_ROOT = STORAGE_ROOT / "reports"
BACKUP_ROOT = STORAGE_ROOT / "backups"
for directory in (DATABASE_ROOT, EVIDENCE_ROOT, REPORT_ROOT, BACKUP_ROOT):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

DATABASE_ENGINE = env_value("TRACE_DB_ENGINE", "sqlite")
if DATABASE_ENGINE == "sqlite":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3", "NAME": DATABASE_ROOT / "tdt.sqlite3",
        "OPTIONS": {"timeout": 10, "transaction_mode": "IMMEDIATE"},
        "CONN_MAX_AGE": 0, "ATOMIC_REQUESTS": False,
    }}
elif DATABASE_ENGINE == "postgresql":
    if not env_value("TRACE_DB_NAME") or not env_value("TRACE_DB_USER"):
        raise ImproperlyConfigured("PostgreSQL requires TRACE_DB_NAME and TRACE_DB_USER.")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_value("TRACE_DB_NAME"), "USER": env_value("TRACE_DB_USER"),
        "PASSWORD": env_value("TRACE_DB_PASSWORD"),
        "HOST": env_value("TRACE_DB_HOST", "127.0.0.1"), "PORT": env_value("TRACE_DB_PORT", "5432"),
        "OPTIONS": {"sslmode": env_value("TRACE_DB_SSLMODE", "prefer"), "connect_timeout": 10, "options": "-c lock_timeout=10000 -c statement_timeout=120000"},
        "CONN_MAX_AGE": 0, "ATOMIC_REQUESTS": False,
    }}
else:
    raise ImproperlyConfigured("TRACE_DB_ENGINE must be sqlite or postgresql.")

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.RateLimitedModelBackend"]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
TRACE_LOGIN_WINDOW_SECONDS = 900
TRACE_LOGIN_ACCOUNT_LIMIT = 5
TRACE_LOGIN_SOURCE_LIMIT = 30
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_HTTPONLY = False  # HTMX may read it for future same-origin POST requests.
CSRF_COOKIE_SAMESITE = "Lax"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = EVIDENCE_ROOT
# No public media route. Evidence is served only through authorized application endpoints.
TRACE_EVIDENCE_MAX_BYTES = int(env_value("TRACE_EVIDENCE_MAX_BYTES", 50 * 1024 * 1024))
TRACE_EVIDENCE_ALLOWED_TYPES = env_list("TRACE_EVIDENCE_ALLOWED_TYPES", "png,jpeg,pdf,text,pcap")
TRACE_EVIDENCE_IMAGE_PIXELS = int(env_value("TRACE_EVIDENCE_IMAGE_PIXELS", 12_000_000))
TRACE_EVIDENCE_IMAGE_SIDE = int(env_value("TRACE_EVIDENCE_IMAGE_SIDE", 8192))
TRACE_EVIDENCE_IMAGE_MEMORY = 512 * 1024 * 1024
FILE_UPLOAD_HANDLERS = ["apps.evidence.uploads.BoundedUploadHandler"]
DATA_UPLOAD_MAX_NUMBER_FILES = 1
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
TRACE_REQUIRE_VENDOR = False
TRACE_REPORT_MAX_FINDINGS = int(env_value("TRACE_REPORT_MAX_FINDINGS", 200))
TRACE_REPORT_MAX_TESTS = int(env_value("TRACE_REPORT_MAX_TESTS", 1000))
TRACE_REPORT_MAX_EVIDENCE = int(env_value("TRACE_REPORT_MAX_EVIDENCE", 500))
TRACE_REPORT_MAX_IMAGES = int(env_value("TRACE_REPORT_MAX_IMAGES", 20))
TRACE_REPORT_MAX_IMAGE_BYTES = int(env_value("TRACE_REPORT_MAX_IMAGE_BYTES", 8 * 1024 * 1024))
TRACE_REPORT_MAX_SNAPSHOT_BYTES = int(env_value("TRACE_REPORT_MAX_SNAPSHOT_BYTES", 16 * 1024 * 1024))
TRACE_REPORT_MAX_ARTIFACT_BYTES = int(env_value("TRACE_REPORT_MAX_ARTIFACT_BYTES", 100 * 1024 * 1024))
TRACE_REPORT_RENDER_TIMEOUT = int(env_value("TRACE_REPORT_RENDER_TIMEOUT", 90))
TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES = env_value("TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES", "/opt/homebrew/lib" if Path("/opt/homebrew/lib").is_dir() else "")
TRACE_EDITOR_PRESENCE_ENABLED = env_bool("TRACE_EDITOR_PRESENCE_ENABLED", True)

LOG_LEVEL = env_value("TRACE_LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    raise ImproperlyConfigured("Invalid TRACE_LOG_LEVEL.")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.server": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# History is private engagement data, independently bounded from upload storage.
TRACE_AUDIT_MAX_EVENT_BYTES = int(env_value("TRACE_AUDIT_MAX_EVENT_BYTES", 2 * 1024 * 1024))
TRACE_AUDIT_RETENTION_DAYS = int(env_value("TRACE_AUDIT_RETENTION_DAYS", 365))
TRACE_AUDIT_EXPORT_LIMIT = int(env_value("TRACE_AUDIT_EXPORT_LIMIT", 10000))
TRACE_AUDIT_EXPORT_MAX_BYTES = int(env_value("TRACE_AUDIT_EXPORT_MAX_BYTES", 32 * 1024 * 1024))

FORM_RENDERER = "apps.core.forms.BootstrapFormRenderer"

TRACE_REPORT_CONCURRENT_EXPORTS = int(env_value("TRACE_REPORT_CONCURRENT_EXPORTS", 1))

# Evidence budgets count originals + thumbnails, including pending allocations.
TRACE_EVIDENCE_TOTAL_QUOTA_BYTES = int(env_value('TRACE_EVIDENCE_TOTAL_QUOTA_BYTES', 20 * 1024**3))
TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES = int(env_value('TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES', 5 * 1024**3))
TRACE_STORAGE_MIN_FREE_BYTES = int(env_value('TRACE_STORAGE_MIN_FREE_BYTES', 1024**3))
TRACE_STORAGE_WARNING_PERCENT = int(env_value('TRACE_STORAGE_WARNING_PERCENT', 20))
TRACE_UPLOAD_TEMP_MIN_FREE_BYTES = int(env_value('TRACE_UPLOAD_TEMP_MIN_FREE_BYTES', 16 * 1024**2))
