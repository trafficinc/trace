import json
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction, connection
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.urls import reverse
from apps.assets.models import Asset
from apps.assets.services import save_asset
from apps.audit.models import AuditEvent
from apps.engagements.services import transition_engagement, purge_engagement


def asset_data(**changes):
    return {"name": "Application server", "asset_type": "host", "hostname": "app01.internal", "ip_cidr": "192.0.2.10",
        "url": "", "description": "  Approved host\n    Internal scope\n", "environment": "Staging",
        "scope_status": "in_scope", "owner": "", **changes}


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 302), ("tester", 302), ("admin", 302), ("reviewer", 403), ("viewer", 403), ("outsider", 404)])
def test_asset_http_write_matrix(client, access_setup, role, expected):
    users, first, _ = access_setup
    client.force_login(users[role])
    assert client.post(reverse("assets:create", args=[first.pk]), asset_data()).status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize("kind,values", [("host", {"hostname": "app01"}), ("application", {"url": "https://app.example.test/"}),
    ("network", {"ip_cidr": "2001:db8::/64"}), ("service", {"hostname": "mail.internal"}), ("other", {})])
def test_asset_types_and_applicable_addresses(access_setup, kind, values):
    users, first, _ = access_setup
    asset = save_asset(actor=users["tester"], engagement_id=first.pk,
        data=asset_data(**{"asset_type": kind, "hostname": "", "ip_cidr": "", **values}))
    asset.full_clean()
    assert asset.asset_type == kind and asset.created_by == users["tester"]


@pytest.mark.django_db
@pytest.mark.parametrize("changes", [{"asset_type": "host", "hostname": "", "ip_cidr": ""},
    {"asset_type": "application", "url": ""}, {"asset_type": "network", "ip_cidr": ""},
    {"ip_cidr": "999.1.2.3"}, {"hostname": "bad host"}, {"url": "javascript:alert(1)"}, {"url": "ftp://example.test/file"},
    {"asset_type": "unknown"}, {"scope_status": "unknown"}])
def test_asset_validation_in_model_and_service(access_setup, changes):
    users, first, _ = access_setup
    with pytest.raises(ValidationError):
        save_asset(actor=users["tester"], engagement_id=first.pk, data=asset_data(**changes))
    with pytest.raises(ValidationError):
        Asset(engagement=first, **{key: value for key, value in asset_data(**changes).items() if key != "owner"}).full_clean()


@pytest.mark.django_db
def test_asset_owner_scope_mass_assignment_and_disabled_owner(access_setup):
    users, first, second = access_setup
    for owner in (users["outsider"].pk,):
        with pytest.raises(ValidationError):
            save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data(owner=owner))
    asset = save_asset(actor=users["tester"], engagement_id=first.pk, data=asset_data(owner=users["viewer"].pk))
    assert asset.owner == users["viewer"]
    type(users["viewer"]).objects.filter(pk=users["viewer"].pk).update(is_active=False)
    with pytest.raises(ValidationError):
        save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data(owner=users["viewer"].pk))
    with pytest.raises(ValidationError):
        save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data(engagement=second.pk))
    for role in ("reviewer", "viewer"):
        with pytest.raises((PermissionDenied, Http404)):
            save_asset(actor=users[role], engagement_id=first.pk, data=asset_data())


@pytest.mark.django_db
def test_asset_edits_conflicts_preserve_formatting_and_scope(client, access_setup):
    users, first, second = access_setup
    asset = save_asset(actor=users["tester"], engagement_id=first.pk, data=asset_data())
    assert asset.description == asset_data()["description"]
    client.force_login(users["tester"])
    url = reverse("assets:edit", args=[first.pk, asset.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, {**asset_data(name="Saved"), "version": 1}, HTTP_HX_REQUEST="true").status_code == 204
    response = client.post(url, {**asset_data(name="Draft"), "version": 1}, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and b'value="Draft"' in response.content and b"<html" not in response.content
    asset.refresh_from_db()
    assert asset.name == "Saved" and asset.version == 2
    assert client.get(reverse("assets:detail", args=[second.pk, asset.pk])).status_code == 404
    with pytest.raises(Http404):
        save_asset(actor=users["lead"], engagement_id=first.pk, asset_id=save_asset(actor=users["outsider"], engagement_id=second.pk, data=asset_data()).pk,
                   data=asset_data(), version=1)


@pytest.mark.django_db
def test_asset_list_filters_pagination_and_detail_are_scoped(client, access_setup):
    users, first, second = access_setup
    asset = save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data(owner=users["tester"].pk))
    save_asset(actor=users["outsider"], engagement_id=second.pk, data=asset_data(name="Secret asset", hostname="secret.internal"))
    client.force_login(users["viewer"])
    url = reverse("assets:list", args=[first.pk])
    for filters in ({"q": "app01"}, {"q": "192.0.2"}, {"owner": users["tester"].pk}, {"status": "in_scope"}, {"type": "host"}, {"environment": "Staging"}):
        response = client.get(url, filters, HTTP_HX_REQUEST="true")
        assert response.status_code == 200 and response.context["page"].paginator.count == 1
        assert b"Secret asset" not in response.content and b"<html" not in response.content
    assert client.get(url, {"owner": "invalid"}).context["page"].paginator.count == 0
    assert client.get(url, {"status": "out_of_scope"}).context["page"].paginator.count == 0
    Asset.objects.bulk_create([Asset(engagement=first, name=f"Other {index:02d}", asset_type="other") for index in range(22)])
    assert len(client.get(url, {"page": 2}).context["page"]) == 3
    assert client.get(reverse("assets:detail", args=[first.pk, asset.pk])).status_code == 200
    assert client.get(reverse("assets:detail", args=[second.pk, asset.pk])).status_code == 404


@pytest.mark.django_db
def test_asset_freeze_audit_rollback_and_retention_guard(access_setup, monkeypatch):
    users, first, _ = access_setup
    asset = save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data())
    def broken(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr("apps.assets.services.record_event", broken)
    with pytest.raises(RuntimeError):
        save_asset(actor=users["lead"], engagement_id=first.pk, asset_id=asset.pk, version=1, data=asset_data(name="Rollback"))
    asset.refresh_from_db()
    assert asset.name == "Application server" and asset.version == 1
    archived = transition_engagement(actor=users["lead"], engagement_id=first.pk, target="archived", version=1)
    with pytest.raises(ValidationError):
        save_asset(actor=users["lead"], engagement_id=first.pk, data=asset_data())
    with pytest.raises(ValidationError):
        purge_engagement(actor=users["admin"], engagement_id=first.pk, version=archived.version, confirmation=str(first.pk), reason="retention")
    with pytest.raises(ProtectedError):
        first.delete()
    serialized = json.dumps(list(AuditEvent.objects.filter(action__startswith="asset.").values("metadata")), default=str)
    assert "Approved host" not in serialized and "192.0.2.10" not in serialized


@pytest.mark.django_db
def test_asset_database_indexes(access_setup):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Asset._meta.db_table)
    indexed_columns = {tuple(value["columns"]) for value in constraints.values() if value["index"]}
    for column in ("name", "owner_id", "scope_status", "asset_type", "environment"):
        assert ("engagement_id", column) in indexed_columns
    _, first, _ = access_setup
    with pytest.raises(IntegrityError), transaction.atomic():
        Asset.objects.create(engagement=first, name="Invalid", asset_type="invalid")
