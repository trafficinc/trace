"""Allowlisted JSON events: no request bodies, URLs, credentials or tracebacks."""
import json
import logging
import math
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str | None] = ContextVar("trace_request_id", default=None)
EVENTS = frozenset({"startup_failed", "http_request", "health_database_unavailable", "evidence_cleanup_deferred", "evidence_capacity_blocked", "report_cleanup_deferred"})


class JsonFormatter(logging.Formatter):
    def format(self, record):
        if record.name.startswith("django.security"):
            event = "security_event"
        elif record.name == "django.request":
            event = "http_error"
        elif record.name == "django.server":
            event = "development_server_event"
        elif isinstance(record.msg, str) and record.msg in EVENTS and not record.args:
            event = record.msg
        else:
            event = "application_event"
        result = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
        }
        if request_id.get():
            result["request_id"] = request_id.get()
        for name in ("status_code", "duration_ms"):
            value = getattr(record, name, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                result[name] = value
        method = getattr(record, "method", None)
        if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            result["method"] = method
        return json.dumps(result, ensure_ascii=True, allow_nan=False)
