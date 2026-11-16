from datetime import timedelta
import io
import json
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction, connection
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from apps.assets.services import save_asset
from apps.core.exceptions import EditConflict
from apps.engagements.services import transition_engagement
from apps.testcases.models import TestCase as Case, TestCaseAsset as Link, TestCaseTemplate as Blueprint, TestCaseStatus as Status
from apps.testcases import services


def case_data(**changes):
    return {"title": "Review access boundaries", "description": "  Description\n    Detail\n", "category": "Authorization",
        "objective": "Confirm isolation", "methodology": "Manual review", "procedure": "  1. Verify scope\n    - Check boundary\n\n2. Record results\n",
        "expected_result": "Access denied outside scope", "actual_result": "", "assigned_tester": "", "notes": "", "assets": [], **changes}


def edit_data(**changes):
    return {**case_data(), "status": "not_started", **changes}


def template_data(**changes):
    return {"name": "Boundary review", "title": "Review access boundaries", "category": "Authorization", "description": "Reusable procedure",
        "objective": "Confirm isolation", "methodology": "Manual review", "procedure": "  1. Verify scope\n    - Check boundary\n",
        "expected_result": "Access denied outside scope", "is_active": True, **changes}


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 302), ("tester", 302), ("admin", 302), ("reviewer", 403), ("viewer", 403), ("outsider", 404)])
def test_case_http_write_matrix(client, access_setup, role, expected):
    users, first, _ = access_setup
    client.force_login(users[role])
    assert client.post(reverse("testcases:create", args=[first.pk]), case_data()).status_code == expected


@pytest.mark.django_db
def test_case_model_validation_and_assignment_scope(access_setup):
    users, first, _ = access_setup
    for role in ("lead", "tester"):
        case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(assigned_tester=users[role].pk))
        assert case.assigned_tester == users[role]
        case.full_clean()
    for role in ("reviewer", "viewer", "outsider", "admin"):
        with pytest.raises(ValidationError):
            services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(assigned_tester=users[role].pk))
        with pytest.raises(ValidationError):
            Case(engagement=first, title="Invalid", category="Auth", assigned_tester=users[role]).full_clean()
    type(users["tester"]).objects.filter(pk=users["tester"].pk).update(is_active=False)
    with pytest.raises(ValidationError):
        services.create_test_case(actor=users["lead"], engagement_id=first.pk, data=case_data(assigned_tester=users["tester"].pk))


ALLOWED = {("not_started", "in_progress"), ("not_started", "blocked"), ("not_started", "not_applicable"),
    ("in_progress", "blocked"), ("in_progress", "passed"), ("in_progress", "failed"), ("in_progress", "not_applicable"),
    ("blocked", "in_progress"), ("blocked", "not_applicable"), ("passed", "in_progress"),
    ("failed", "in_progress"), ("not_applicable", "in_progress")}


@pytest.mark.django_db
@pytest.mark.parametrize("source", Status.values)
@pytest.mark.parametrize("target", Status.values)
def test_state_transition_contract(access_setup, source, target):
    users, first, _ = access_setup
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data())
    started = timezone.now() - timedelta(hours=1)
    terminal = source in {"passed", "failed", "not_applicable"}
    Case.objects.filter(pk=case.pk).update(status=source, actual_result="Observed result",
        started_at=started if source != "not_started" else None, completed_at=timezone.now() if terminal else None)
    payload = edit_data(status=target, actual_result="Observed result")
    if source == target or (source, target) in ALLOWED:
        saved = services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=payload, version=1)
        assert saved.status == target and saved.version == 2
        if target in {"passed", "failed", "not_applicable"}:
            assert saved.completed_at is not None
        else:
            assert saved.completed_at is None
        if target == "in_progress":
            assert saved.started_at is not None
    else:
        with pytest.raises(ValidationError):
            services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=payload, version=1)
        case.refresh_from_db()
        assert case.status == source and case.version == 1


@pytest.mark.django_db
def test_outcomes_require_results_and_reopening_preserves_start(access_setup):
    users, first, _ = access_setup
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data())
    case = services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=edit_data(status="in_progress"), version=1)
    started = case.started_at
    for result in ("", "  \n  "):
        with pytest.raises(ValidationError):
            services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=edit_data(status="passed", actual_result=result), version=2)
    case = services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk,
        data=edit_data(status="passed", actual_result="Access denied as expected"), version=2)
    assert case.completed_at >= case.started_at
    case = services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk,
        data=edit_data(status="in_progress", actual_result=case.actual_result), version=3)
    assert case.started_at == started and case.completed_at is None
    assert case.actual_result == "Access denied as expected"
    with pytest.raises(ValidationError):
        Case(engagement=first, title="Invalid", category="Auth", status="passed", actual_result="").full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        Case.objects.create(engagement=first, title="Invalid", category="Auth", status="passed")


@pytest.mark.django_db
def test_structured_text_escaping_conflicts_and_protected_fields(client, access_setup):
    users, first, second = access_setup
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk,
        data=case_data(description="<script>alert(1)</script>"))
    assert case.procedure == case_data()["procedure"]
    client.force_login(users["tester"])
    original = client.get(reverse("testcases:detail", args=[first.pk, case.pk]))
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in original.content
    url = reverse("testcases:edit", args=[first.pk, case.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, {**edit_data(title="Saved"), "version": 1}, HTTP_HX_REQUEST="true").status_code == 204
    response = client.post(url, {**edit_data(title="Unsaved draft"), "version": 1}, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and b"Unsaved draft" in response.content and b"<html" not in response.content
    response = client.get(reverse("testcases:detail", args=[first.pk, case.pk]))
    assert response.status_code == 200 and b"1. Verify scope\n    - Check boundary" in response.content
    with pytest.raises(ValidationError):
        services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, version=2,
                                  data=edit_data(engagement=second.pk))
    assert client.get(reverse("testcases:detail", args=[second.pk, case.pk])).status_code == 404


@pytest.mark.django_db
def test_cross_engagement_assets_rejected_at_all_layers(client, access_setup):
    users, first, second = access_setup
    own = save_asset(actor=users["lead"], engagement_id=first.pk, data={"name": "Own", "asset_type": "other", "scope_status": "in_scope"})
    foreign = save_asset(actor=users["outsider"], engagement_id=second.pk, data={"name": "Foreign", "asset_type": "other", "scope_status": "in_scope"})
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(assets=[own.pk]))
    with pytest.raises(ValidationError):
        services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(assets=[foreign.pk]))
    with pytest.raises(ValidationError):
        services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk,
                                  data=edit_data(assets=[foreign.pk]), version=1)
    assert list(case.assets.all()) == [own]
    with pytest.raises(ValidationError):
        Link(test_case=case, asset=foreign).save()
    with pytest.raises(IntegrityError), transaction.atomic():
        Link.objects.bulk_create([Link(test_case=case, asset=foreign)])
    with pytest.raises(IntegrityError), transaction.atomic():
        case.assets.add(foreign)
    with pytest.raises(IntegrityError), transaction.atomic():
        type(own).objects.filter(pk=own.pk).update(engagement=second)
    with pytest.raises(IntegrityError), transaction.atomic():
        Case.objects.filter(pk=case.pk).update(engagement=second)
    client.force_login(users["tester"])
    response = client.post(reverse("testcases:create", args=[first.pk]), case_data(assets=[foreign.pk]))
    assert response.status_code == 200 and b"Select a valid choice" in response.content


@pytest.mark.django_db
def test_list_owner_status_category_asset_filters_and_progress(client, access_setup):
    users, first, second = access_setup
    asset = save_asset(actor=users["lead"], engagement_id=first.pk, data={"name": "Target", "asset_type": "other", "scope_status": "pending"})
    for index, status in enumerate(Status.values):
        case = services.create_test_case(actor=users["tester"], engagement_id=first.pk,
            data=case_data(title=f"Check {index}", category="Authorization" if index < 3 else "Network",
                           assigned_tester=users["tester"].pk, assets=[asset.pk] if index < 3 else []))
        Case.objects.filter(pk=case.pk).update(status=status, actual_result="Observed", completed_at=timezone.now() if index >= 3 else None)
    services.create_test_case(actor=users["outsider"], engagement_id=second.pk, data=case_data(title="Secret case"))
    client.force_login(users["viewer"])
    url = reverse("testcases:list", args=[first.pk])
    response = client.get(url)
    assert response.status_code == 200 and b"Secret case" not in response.content
    assert response.context["progress"]["total"] == 6 and response.context["progress"]["percent"] == 50
    assert len(response.context["progress"]["categories"]) == 2
    for filters, count in [({"owner": users["tester"].pk}, 6), ({"status": "passed"}, 1), ({"category": "Network"}, 3),
                           ({"asset": asset.pk}, 3), ({"q": "Check 0"}, 1), ({"owner": "invalid"}, 0), ({"asset": "invalid"}, 0)]:
        response = client.get(url, filters, HTTP_HX_REQUEST="true")
        assert response.status_code == 200 and response.context["page"].paginator.count == count
        assert b"<html" not in response.content
    Case.objects.bulk_create([Case(engagement=first, title=f"Extra {i}", category="Other") for i in range(20)])
    assert len(client.get(url, {"page": 2}).context["page"]) == 6


@pytest.mark.django_db
def test_template_snapshot_versioning_retirement_and_privilege(client, access_setup):
    users, first, _ = access_setup
    with pytest.raises(PermissionDenied):
        services.save_template(actor=users["lead"], data=template_data())
    blueprint = services.save_template(actor=users["admin"], data=template_data())
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data={"source_template": blueprint.pk, "template_version": 1})
    assert case.procedure == blueprint.procedure and case.source_template_version == 1
    assert case.status == "not_started" and case.assigned_tester is None and not case.assets.exists()
    services.save_template(actor=users["admin"], template_id=blueprint.pk, version=1, data=template_data(procedure="New procedure"))
    with pytest.raises(EditConflict):
        services.create_test_case(actor=users["tester"], engagement_id=first.pk, data={"source_template": blueprint.pk, "template_version": 1})
    case.refresh_from_db()
    assert case.procedure == template_data()["procedure"] and case.source_template_version == 1
    client.force_login(users["tester"])
    response = client.get(reverse("testcases:create", args=[first.pk]), {"template": blueprint.pk})
    assert response.status_code == 200 and b"New procedure" in response.content
    services.save_template(actor=users["admin"], template_id=blueprint.pk, version=2, data=template_data(is_active=False))
    with pytest.raises(Http404):
        services.create_test_case(actor=users["tester"], engagement_id=first.pk, data={"source_template": blueprint.pk})
    assert client.get(reverse("test_templates:detail", args=[blueprint.pk])).status_code == 404
    assert client.get(reverse("testcases:detail", args=[first.pk, case.pk])).status_code == 200


@pytest.mark.django_db
def test_template_screens_and_local_loader(client, access_setup, tmp_path):
    users, first, _ = access_setup
    output = io.StringIO()
    call_command("load_test_templates", admin="admin", stdout=output)
    assert Blueprint.objects.count() == 2
    call_command("load_test_templates", admin="admin", stdout=output)
    assert Blueprint.objects.count() == 2
    client.force_login(users["admin"])
    blueprint = Blueprint.objects.first()
    for url in (reverse("test_templates:list"), reverse("test_templates:create"), reverse("test_templates:edit", args=[blueprint.pk]), reverse("test_templates:detail", args=[blueprint.pk])):
        assert client.get(url).status_code == 200
    client.force_login(users["viewer"])
    assert client.get(reverse("test_templates:create")).status_code == 403
    assert client.get(reverse("test_templates:list"), {"engagement": "invalid"}).status_code == 404
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps([template_data(name="Would roll back"), {"name": "Invalid", "actual_result": "Forbidden"}]))
    with pytest.raises(CommandError):
        call_command("load_test_templates", str(path), admin="admin", stdout=output)
    assert not Blueprint.objects.filter(name="Would roll back").exists()


@pytest.mark.django_db
def test_audit_failures_roll_back_case_fields_and_links(access_setup, monkeypatch):
    users, first, _ = access_setup
    asset = save_asset(actor=users["lead"], engagement_id=first.pk, data={"name": "Target", "asset_type": "other", "scope_status": "pending"})
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(assets=[asset.pk]))
    def broken(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(services, "record_event", broken)
    with pytest.raises(RuntimeError):
        services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=edit_data(title="Rollback", assets=[]), version=1)
    case.refresh_from_db()
    assert case.title == case_data()["title"] and case.version == 1 and list(case.assets.all()) == [asset]
    with pytest.raises(RuntimeError):
        services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data(title="Rolled back new"))
    assert not first.test_cases.filter(title="Rolled back new").exists()


@pytest.mark.django_db
def test_closed_engagements_and_direct_service_permissions(access_setup):
    users, first, _ = access_setup
    case = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data=case_data())
    for role in ("reviewer", "viewer"):
        with pytest.raises(PermissionDenied):
            services.update_test_case(actor=users[role], engagement_id=first.pk, test_case_id=case.pk, data=edit_data(), version=1)
    transition_engagement(actor=users["lead"], engagement_id=first.pk, target="archived", version=1)
    with pytest.raises(ValidationError):
        services.update_test_case(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data=edit_data(), version=1)
    with pytest.raises(ValidationError):
        services.save_test_note(actor=users["reviewer"], engagement_id=first.pk, test_case_id=case.pk, body="Frozen")
    with pytest.raises(ValidationError):
        services.save_reference(actor=users["tester"], engagement_id=first.pk, test_case_id=case.pk, data={"label": "Frozen", "citation": "Section 1"})


@pytest.mark.django_db
def test_test_case_indexes_and_csrf(access_setup):
    users, first, _ = access_setup
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Case._meta.db_table)
    indexed_columns = {tuple(value["columns"]) for value in constraints.values() if value["index"]}
    for column in ("status", "assigned_tester_id", "category", "title", "updated_at"):
        assert ("engagement_id", column) in indexed_columns
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(users["tester"])
    assert protected.post(reverse("testcases:create", args=[first.pk]), case_data(), HTTP_HX_REQUEST="true").status_code == 403
    assert protected.post(reverse("assets:create", args=[first.pk]), {"name": "No CSRF"}).status_code == 403


@pytest.mark.django_db
def test_template_http_snapshot_flow_and_stale_drafts(client, access_setup):
    users, first, _ = access_setup
    client.force_login(users["admin"])
    assert client.post(reverse("test_templates:create"), template_data()).status_code == 302
    blueprint = Blueprint.objects.get()
    edit = reverse("test_templates:edit", args=[blueprint.pk])
    assert client.post(edit, {**template_data(procedure="Updated blueprint"), "version": 1}).status_code == 302
    response = client.post(edit, {**template_data(procedure="Unsaved blueprint"), "version": 1}, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and b"Unsaved blueprint" in response.content
    client.force_login(users["tester"])
    create = reverse("testcases:create", args=[first.pk])
    payload = case_data(procedure="  Customized step\n    Sub-step\n", source_template=blueprint.pk, template_version=1)
    response = client.post(create, payload, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and b"Customized step" in response.content
    response = client.post(create, {**payload, "template_version": 2, "status": "passed"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 204 and "HX-Redirect" in response
    case = first.test_cases.get()
    assert case.source_template_version == 2 and case.status == "not_started"
    assert case.procedure == payload["procedure"]
