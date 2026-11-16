import os
import subprocess
import sys

import pytest
from django.utils.crypto import salted_hmac
from apps.accounts.security import username_fingerprint


@pytest.mark.parametrize("configuration", ["trace", "legacy", "both"])
def test_configuration_rename_preserves_existing_installations(tmp_path, configuration):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("TRACE_", "TDT_"))}
    secret = "compatibility-test-key-" + "a7c9" * 20
    prefix = "TDT_" if configuration == "legacy" else "TRACE_"
    environment.update({prefix + "SECRET_KEY": secret, prefix + "ALLOWED_HOSTS": "trace.example.test",
                        prefix + "STORAGE_ROOT": str(tmp_path), prefix + "TRUST_PROXY": "1"})
    if configuration == "both":
        # Explicit TRACE configuration wins over conflicting legacy values.
        environment.update({"TDT_SECRET_KEY": "too-short", "TDT_ALLOWED_HOSTS": "old.example.test",
                            "TDT_STORAGE_ROOT": str(tmp_path / "old"), "TDT_TRUST_PROXY": "0"})
    code = '''
from pathlib import Path
from config.settings import production as settings
assert settings.SECRET_KEY == "compatibility-test-key-" + "a7c9" * 20
assert settings.ALLOWED_HOSTS == ["trace.example.test"]
assert settings.STORAGE_ROOT == Path(__import__("sys").argv[1])
assert settings.DATABASES["default"]["NAME"] == settings.STORAGE_ROOT / "db" / "tdt.sqlite3"
assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.django_db
def test_rebrand_preserves_persisted_authentication_identifiers(access_setup):
    users, _, _ = access_setup
    user = users["tester"]
    expected_session_hash = salted_hmac("tdt.accounts.User.session_auth",
        f"{user.password}:{user.session_version}", algorithm="sha256").hexdigest()
    assert user.get_session_auth_hash() == expected_session_hash
    expected_bucket = salted_hmac("tdt.auth.account", "tester", algorithm="sha256").hexdigest()
    assert username_fingerprint("Tester") == expected_bucket
