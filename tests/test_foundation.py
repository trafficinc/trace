import io
from unittest.mock import patch
import pytest
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import OperationalError, connection
from django.urls import reverse


def test_custom_user_and_domain_scaffolds():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert apps.get_app_config("findings").get_model("Finding") is not None
    assert apps.get_app_config("evidence").get_model("Evidence") is not None
    assert apps.get_app_config("reports").get_model("Report") is not None
    assert not settings.DATABASES["default"].get("ATOMIC_REQUESTS", False)
    assert settings.MEDIA_ROOT != settings.STATIC_ROOT
    assert settings.STATIC_ROOT not in settings.MEDIA_ROOT.parents


@pytest.mark.django_db
def test_health_is_minimal_and_handles_database_failure(client):
    response = client.get(reverse("core:health"))
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"
    with patch("apps.core.views.connection.cursor", side_effect=OperationalError("password=secret/path")):
        response = client.get(reverse("core:health"))
    assert response.status_code == 503 and response.json() == {"status": "unavailable"}
    assert b"secret" not in response.content


@pytest.mark.django_db
def test_dashboard_headers_and_private_routes(client, access_setup):
    users, first, second = access_setup
    client.force_login(users["viewer"])
    response = client.get("/?session_token=never-log-this", HTTP_X_REQUEST_ID="forged")
    assert response.status_code == 200
    assert b"First engagement" in response.content
    assert b"Second engagement" not in response.content
    assert response["Cache-Control"] == "no-store, private"
    assert "default-src 'self'" in response["Content-Security-Policy"]
    assert len(response["X-Request-ID"]) == 32 and response["X-Request-ID"] != "forged"
    for path in ("/media/proof.txt", "/storage/evidence/proof.txt", "/reports/", "/findings/"):
        assert client.get(path).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_sqlite_wal_and_timeout():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite-specific setup")
    output = io.StringIO()
    call_command("configure_sqlite", stdout=output)
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode")
        assert cursor.fetchone()[0] == "wal"
        cursor.execute("PRAGMA busy_timeout")
        assert cursor.fetchone()[0] == 10000


@pytest.mark.django_db
def test_administrative_and_account_pages_render(client, access_setup):
    users, first, _ = access_setup
    client.force_login(users["admin"])
    for url in (reverse("accounts:users"), reverse("accounts:user_create"),
                reverse("accounts:profile"), reverse("accounts:password_change"),
                reverse("engagements:detail", args=[first.pk]), reverse("engagements:members", args=[first.pk])):
        assert client.get(url).status_code == 200
