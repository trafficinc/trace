"""Runnable without Django: python -m unittest discover -s tests -p test_logging.py."""
import json
import logging
import unittest
from apps.core.logging import JsonFormatter, request_id


class LoggingTests(unittest.TestCase):
    def test_sensitive_framework_content_is_not_emitted(self):
        for name in ("django.request", "django.server", "django.security.csrf", "thirdparty"):
            record = logging.LogRecord(name, logging.ERROR, "", 0,
                "GET /?password=secret&sessionid=token %s", ("private body",), None)
            record.request = {"password": "private body"}
            value = JsonFormatter().format(record)
            self.assertNotIn("secret", value)
            self.assertNotIn("token", value)
            self.assertNotIn("private body", value)
            self.assertNotIn("password", value)

    def test_only_known_events_and_safe_metadata_are_emitted(self):
        record = logging.LogRecord("trace.http", logging.INFO, "", 0, "http_request", (), None)
        record.status_code, record.method, record.duration_ms = 200, "GET", 1.5
        record.password = "never-record"
        token = request_id.set("a" * 32)
        try:
            data = json.loads(JsonFormatter().format(record))
        finally:
            request_id.reset(token)
        self.assertEqual(data["event"], "http_request")
        self.assertEqual(data["request_id"], "a" * 32)
        self.assertEqual(data["status_code"], 200)
        self.assertNotIn("password", data)

    def test_exception_text_and_unknown_messages_are_dropped(self):
        exception = ValueError("sensitive-request")
        record = logging.LogRecord("apps.example", logging.ERROR, "", 0,
                                   "sensitive-request", (), (ValueError, exception, None))
        record.duration_ms = float("nan")
        result = JsonFormatter().format(record)
        self.assertNotIn("sensitive-request", result)
        self.assertNotIn("duration_ms", result)
