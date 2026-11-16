"""Disposable test configuration. Never select for a deployed service."""
import os
import tempfile

# Always select disposable SQLite BEFORE importing base settings. An operator's
# PostgreSQL environment must never become pytest's default database.
os.environ["TRACE_DB_ENGINE"] = "sqlite"
# Isolate generated test files from the operator's configured application storage.
os.environ["TRACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="trace-tests-")
from .development import *  # noqa: F403, E402

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES["default"]["TEST"] = {"NAME": DATABASE_ROOT / "test.sqlite3"}  # noqa: F405
