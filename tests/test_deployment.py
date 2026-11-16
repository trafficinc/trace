import os
import subprocess
import sys
import pytest


@pytest.mark.parametrize("secret,hosts", [("", "localhost"), ("too-short", "localhost"), ("x" * 64, ""), ("x" * 64, "*")])
def test_production_rejects_unsafe_configuration(tmp_path, secret, hosts):
    environment = {**os.environ, "TRACE_SECRET_KEY": secret, "TRACE_ALLOWED_HOSTS": hosts, "TRACE_STORAGE_ROOT": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", "import config.settings.production"], env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_production_enables_secure_cookies_and_https(tmp_path):
    environment = {**os.environ, "TRACE_SECRET_KEY": "test-only-configuration-key-" + "a7c9" * 20,
                   "TRACE_ALLOWED_HOSTS": "trace.example.test", "TRACE_STORAGE_ROOT": str(tmp_path)}
    code = "from config.settings import production as s; assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT and not s.DEBUG"
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_unknown_database_configuration_is_rejected(tmp_path):
    environment = {**os.environ, "TRACE_DB_ENGINE": "postgres", "TRACE_STORAGE_ROOT": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", "import config.settings.development"], env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "TRACE_DB_ENGINE must be sqlite or postgresql" in result.stderr


@pytest.mark.parametrize('origin',['http://trace.example.test','https://*.example.test'])
def test_production_rejects_insecure_csrf_origin(tmp_path,origin):
    environment={**os.environ,'TRACE_STORAGE_ROOT':str(tmp_path),'TRACE_SECRET_KEY':'private-test-only-'+'a9'*32,
                 'TRACE_ALLOWED_HOSTS':'trace.example.test','TRACE_CSRF_TRUSTED_ORIGINS':origin}
    result=subprocess.run([sys.executable,'-c','import config.settings.production'],env=environment,capture_output=True)
    assert result.returncode!=0


def test_postgresql_uses_standard_backend_and_requires_identity(tmp_path):
    environment={**os.environ,'TRACE_STORAGE_ROOT':str(tmp_path),'TRACE_DB_ENGINE':'postgresql','TRACE_DB_NAME':'trace','TRACE_DB_USER':'trace'}
    code="from config.settings import development as s; assert s.DATABASES['default']['ENGINE']=='django.db.backends.postgresql'; assert 'transaction_mode' not in s.DATABASES['default']['OPTIONS']"
    result=subprocess.run([sys.executable,'-c',code],env=environment,capture_output=True)
    assert result.returncode==0,result.stderr.decode()
