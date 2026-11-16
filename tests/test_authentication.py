from datetime import timedelta
import json
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import LoginThrottle
from apps.accounts.security import username_fingerprint
from apps.accounts.services import create_account, set_account_active, update_profile
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict

PASSWORD = "River-Atlas-47!Cobalt"


@pytest.fixture
def account(db):
    return get_user_model().objects.create_user("person", password=PASSWORD)


@pytest.mark.django_db
def test_login_logout_and_password_storage(client, account):
    assert identify_hasher(account.password).algorithm == "pbkdf2_sha256"
    assert account.password != PASSWORD
    assert client.get("/").status_code == 302
    assert client.post(reverse("accounts:login"), {"username": account.username, "password": PASSWORD}).status_code == 302
    assert client.get("/").status_code == 200
    assert client.get(reverse("accounts:logout")).status_code == 405
    assert client.post(reverse("accounts:logout")).status_code == 302
    assert client.get("/").status_code == 302
    assert AuditEvent.objects.filter(action="login.success", actor=account).count() == 1
    assert AuditEvent.objects.filter(action="logout", actor=account).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("next_url", ["https://evil.example/", "//evil.example/", "https://testserver/"])
def test_login_redirect_validation(client, account, next_url):
    response = client.post(reverse("accounts:login"), {"username": account.username, "password": PASSWORD, "next": next_url})
    # Django accepts an HTTPS URL on the same explicitly allowed host; external hosts fail closed.
    assert response.url == (next_url if next_url == "https://testserver/" else "/")


@pytest.mark.django_db
def test_disabled_accounts_cannot_login_and_sessions_are_denied(client, account):
    client.force_login(account)
    get_user_model().objects.filter(pk=account.pk).update(is_active=False)
    assert client.get("/").status_code == 302
    client.logout()
    response = client.post(reverse("accounts:login"), {"username": account.username, "password": PASSWORD})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert AuditEvent.objects.filter(action="login.failure").exists()


@pytest.mark.django_db
def test_csrf_public_registration_and_admin_boundary(client, account):
    protected = Client(enforce_csrf_checks=True)
    assert protected.post(reverse("accounts:login"), {"username": account.username, "password": PASSWORD}).status_code == 403
    for path in ("/register/", "/accounts/register/", "/accounts/signup/"):
        assert client.get(path).status_code == 404
    account.is_staff = True
    account.save()
    client.force_login(account)
    assert client.get("/admin/").status_code == 302
    assert client.get(reverse("accounts:users")).status_code == 403
    assert protected.post(reverse("accounts:logout")).status_code == 403


@pytest.mark.django_db
def test_rate_limit_covers_admin_and_application_and_has_no_credentials(client, settings):
    settings.TRACE_LOGIN_ACCOUNT_LIMIT = 2
    secret = "Never-Log-This-Password-123"
    data = {"username": "unknown-account", "password": secret}
    assert client.post(reverse("accounts:login"), data).status_code == 200
    assert client.post("/admin/login/", data).status_code == 200
    response = client.post(reverse("accounts:login"), data)
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
    assert client.post("/admin/login/", data).status_code == 429
    events = list(AuditEvent.objects.filter(action="login.failure").values())
    assert len(events) == 4
    serialized = json.dumps(events, default=str)
    assert secret not in serialized
    assert "unknown-account" not in serialized
    assert "127.0.0.1" not in serialized
    assert "sessionid" not in serialized
    assert all(event["subject_hash"] == username_fingerprint("unknown-account") for event in events)
    LoginThrottle.objects.update(window_started=timezone.now() - timedelta(seconds=901))
    assert client.post(reverse("accounts:login"), data).status_code == 200


@pytest.mark.django_db
def test_malformed_login_forms_are_audited_and_limited(client, settings):
    settings.TRACE_LOGIN_ACCOUNT_LIMIT = 1
    assert client.post(reverse("accounts:login"), {"username": "missing-password"}).status_code == 200
    assert client.post("/admin/login/", {"username": "missing-password"}).status_code == 429
    assert AuditEvent.objects.filter(action="login.failure").count() == 2


@pytest.mark.django_db
def test_successful_login_does_not_consume_failure_budget(client, account, settings):
    settings.TRACE_LOGIN_ACCOUNT_LIMIT = 1
    for _ in range(2):
        assert client.post(reverse("accounts:login"), {"username": account.username, "password": PASSWORD}).status_code == 302
        client.post(reverse("accounts:logout"))
    assert all(value == 0 for value in LoginThrottle.objects.values_list("attempts", flat=True))


@pytest.mark.django_db
def test_admin_creates_standard_user_and_weak_password_is_rejected(access_setup):
    users, _, _ = access_setup
    with pytest.raises(PermissionDenied):
        create_account(actor=users["lead"], data={})
    with pytest.raises(ValidationError):
        create_account(actor=users["admin"], data={"username": "new", "password1": "123", "password2": "123"})
    account = create_account(actor=users["admin"], data={"username": "new", "password1": PASSWORD,
        "password2": PASSWORD, "is_superuser": True, "is_staff": True})
    assert account.check_password(PASSWORD)
    assert not account.is_superuser and not account.is_staff
    assert not account.engagement_memberships.exists()


@pytest.mark.django_db
def test_profile_ignores_privilege_and_foreign_user_fields(client, account):
    client.force_login(account)
    url = reverse("accounts:profile")
    data = {"first_name": "Ada", "last_name": "User", "email": "ada@example.test", "version": 1,
            "username": "admin", "is_superuser": True, "is_staff": True, "user": 1}
    assert client.post(url, data).status_code == 302
    assert client.post(url, {**data, "first_name": "Stale draft"}).status_code == 409
    account.refresh_from_db()
    assert account.username == "person" and account.first_name == "Ada"
    assert not account.is_superuser and not account.is_staff


@pytest.mark.django_db
def test_password_change_preserves_own_session_invalidates_others(client, account):
    other = Client()
    client.force_login(account)
    other.force_login(account)
    response = client.post(reverse("accounts:password_change"), {"old_password": PASSWORD,
        "new_password1": "Updated-River-52!Cobalt", "new_password2": "Updated-River-52!Cobalt", "version": 1})
    assert response.status_code == 302
    assert client.get("/").status_code == 200
    assert other.get("/").status_code == 302
    account.refresh_from_db()
    assert account.check_password("Updated-River-52!Cobalt")
    assert AuditEvent.objects.filter(action="user.password_changed").count() == 1


@pytest.mark.django_db
def test_last_system_admin_and_stale_account_changes(access_setup):
    users, _, _ = access_setup
    with pytest.raises(ValidationError):
        set_account_active(actor=users["admin"], user_id=users["admin"].pk, active=False, version=1)
    set_account_active(actor=users["admin"], user_id=users["tester"].pk, active=False, version=1)
    with pytest.raises(EditConflict):
        set_account_active(actor=users["admin"], user_id=users["tester"].pk, active=True, version=1)
    with pytest.raises(PermissionDenied):
        update_profile(actor=users["tester"], data={"first_name": "x", "last_name": "", "email": ""}, version=2)


@pytest.mark.django_db
def test_disable_then_reactivate_does_not_revive_existing_sessions(client, access_setup):
    users, _, _ = access_setup
    client.force_login(users["tester"])
    set_account_active(actor=users["admin"], user_id=users["tester"].pk, active=False, version=1)
    set_account_active(actor=users["admin"], user_id=users["tester"].pk, active=True, version=2)
    # No request was made while disabled: an untouched old cookie is still invalid.
    assert client.get("/").status_code == 302


@pytest.mark.django_db
def test_session_hash_supports_secret_rotation(account, settings):
    old_hash = account.get_session_auth_hash()
    previous_secret = settings.SECRET_KEY
    settings.SECRET_KEY = "rotated-test-key-" + "a7c9" * 20
    settings.SECRET_KEY_FALLBACKS = [previous_secret]
    assert old_hash in list(account.get_session_auth_fallback_hash())
