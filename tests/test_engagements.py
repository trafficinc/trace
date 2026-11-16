from datetime import date
import json
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.urls import reverse
from django.test import Client
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.exceptions import EditConflict
from apps.engagements.models import Engagement, EngagementStatus, EngagementMembership, EngagementNote
from apps.engagements import services


def metadata(**changes):
    return {"name": "Network assessment", "client": "Example organization", "description": "Context",
        "objectives": "Validate access boundaries", "scope_summary": "Internal LAN",
        "start_date": "2026-11-01", "end_date": "2026-11-30", "report_classification": "INTERNAL / TEAM ONLY", **changes}


@pytest.mark.django_db
def test_create_engagement_with_lead_provenance_and_audit(client, access_setup):
    users, _, _ = access_setup
    client.force_login(users["admin"])
    response = client.post(reverse("engagements:create"), {**metadata(), "lead": users["lead"].pk,
        "status": "completed", "created_by": users["viewer"].pk, "version": 55})
    assert response.status_code == 302
    engagement = Engagement.objects.get(name="Network assessment")
    assert engagement.created_by == users["admin"] and engagement.updated_by == users["admin"]
    assert engagement.status == "planned" and engagement.version == 1
    assert engagement.client == "Example organization" and engagement.start_date == date(2026, 11, 1)
    assert engagement.memberships.get().user == users["lead"]
    assert engagement.memberships.get().role == "lead"
    assert AuditEvent.objects.filter(engagement=engagement, action="engagement.created").exists()
    assert AuditEvent.objects.filter(engagement_ref=engagement.pk).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["lead", "tester", "reviewer", "viewer", "outsider"])
def test_only_system_admin_creates_engagements(client, access_setup, role):
    users, _, _ = access_setup
    client.force_login(users[role])
    assert client.get(reverse("engagements:create")).status_code == 403
    assert client.post(reverse("engagements:create"), metadata()).status_code == 403
    with pytest.raises(PermissionDenied):
        services.create_engagement(actor=users[role], name="Forbidden", lead_id=users[role].pk)


@pytest.mark.django_db
def test_edit_versions_date_validation_and_mass_assignment(client, access_setup):
    users, first, _ = access_setup
    client.force_login(users["lead"])
    url = reverse("engagements:edit", args=[first.pk])
    assert client.post(url, {**metadata(end_date="2026-10-01"), "version": 1}).status_code == 200
    first.refresh_from_db()
    assert first.version == 1
    assert client.post(url, {**metadata(), "version": 1, "status": "archived", "created_by": users["viewer"].pk}).status_code == 302
    response = client.post(url, {**metadata(name="Unsaved draft"), "version": 1})
    assert response.status_code == 409 and b"Unsaved draft" in response.content
    first.refresh_from_db()
    assert first.status == "planned" and first.created_by is None and first.version == 2
    assert first.updated_by == users["lead"]
    with pytest.raises(ValidationError):
        services.update_engagement(actor=users["lead"], engagement_id=first.pk, data=metadata(status="completed"), version=2)
    with pytest.raises(ValidationError):
        services.update_engagement(actor=users["lead"], engagement_id=first.pk, data=metadata(end_date="2026-01-01"), version=2)


@pytest.mark.django_db
def test_database_constraints_reject_invalid_dates_and_status(access_setup):
    _, first, _ = access_setup
    with pytest.raises(IntegrityError), transaction.atomic():
        Engagement.objects.filter(pk=first.pk).update(start_date="2026-12-01", end_date="2026-01-01")
    with pytest.raises(IntegrityError), transaction.atomic():
        Engagement.objects.filter(pk=first.pk).update(status="invalid")


@pytest.mark.django_db
def test_list_search_sort_filter_and_pagination_are_scoped(client, access_setup):
    users, first, second = access_setup
    first.client, first.scope_summary, first.status = "Visible organization", "Boundary scope", "active"
    first.save()
    second.name, second.client = "Secret mission", "Secret organization"
    second.save()
    client.force_login(users["viewer"])
    url = reverse("engagements:list")
    for query in ({"q": "organization"}, {"q": "Boundary"}, {"status": "active"}, {"sort": "name"}):
        response = client.get(url, query)
        assert response.status_code == 200
        assert b"First engagement" in response.content and b"Secret" not in response.content
    assert client.get(url, {"status": "paused"}).context["page"].paginator.count == 0
    assert client.get(url, {"q": "Secret"}).context["page"].paginator.count == 0
    assert client.get(url, {"sort": "name; DROP TABLE"}).context["sort"] == "-updated_at"
    engagements = Engagement.objects.bulk_create([Engagement(name=f"Mission {index:02d}") for index in range(25)])
    EngagementMembership.objects.bulk_create([EngagementMembership(engagement=item, user=users["viewer"], role="viewer") for item in engagements])
    response = client.get(url, {"sort": "name", "page": 2}, HTTP_HX_REQUEST="true")
    assert response.context["page"].paginator.count == 26
    assert len(response.context["page"]) == 6
    assert b"<html" not in response.content and b"eng-table" in response.content
    assert "HX-Request" in response["Vary"]
    assert client.get(url, {"page": "invalid"}).status_code == 200


VALID_TRANSITIONS = {("planned", "active"), ("planned", "archived"),
    ("active", "paused"), ("active", "completed"), ("active", "archived"),
    ("paused", "active"), ("paused", "completed"), ("paused", "archived"), ("completed", "archived")}


@pytest.mark.django_db
@pytest.mark.parametrize("source", EngagementStatus.values)
@pytest.mark.parametrize("target", EngagementStatus.values)
def test_lifecycle_transition_contract(access_setup, source, target):
    users, first, _ = access_setup
    first.status = source
    first.save()
    if (source, target) in VALID_TRANSITIONS:
        saved = services.transition_engagement(actor=users["lead"], engagement_id=first.pk, target=target, version=1)
        assert saved.status == target and saved.version == 2
        assert AuditEvent.objects.filter(engagement=first, action="engagement.status_changed").count() == 1
        if target == "completed":
            assert saved.completed_at is not None
        if target == "archived":
            assert saved.archived_at is not None
    else:
        with pytest.raises(ValidationError):
            services.transition_engagement(actor=users["lead"], engagement_id=first.pk, target=target, version=1)
        first.refresh_from_db()
        assert first.status == source and first.version == 1


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 302), ("admin", 302), ("tester", 403), ("reviewer", 403), ("viewer", 403), ("outsider", 404)])
@pytest.mark.parametrize("operation", ["edit", "activate", "milestone_create"])
def test_engagement_mutation_matrix(client, access_setup, role, expected, operation):
    users, first, _ = access_setup
    client.force_login(users[role])
    data = {**metadata(), "version": 1} if operation == "edit" else {"version": 1, "title": "Plan", "description": "", "due_date": ""}
    response = client.post(reverse(f"engagements:{operation}", args=[first.pk]), data)
    assert response.status_code == expected


@pytest.mark.django_db
def test_lifecycle_confirmation_freezing_and_access_maintenance(client, access_setup):
    users, first, _ = access_setup
    milestone = services.save_milestone(actor=users["lead"], engagement_id=first.pk, data={"title": "Open work"})
    client.force_login(users["lead"])
    activate = reverse("engagements:activate", args=[first.pk])
    assert client.get(activate).status_code == 200
    first.refresh_from_db()
    assert first.status == "planned"
    assert client.post(activate, {"version": 1}).status_code == 302
    complete = reverse("engagements:complete", args=[first.pk])
    assert client.post(complete, {"version": 1}).status_code == 409
    assert client.post(complete, {"version": 2}).status_code == 302
    assert client.post(reverse("engagements:edit", args=[first.pk]), {**metadata(), "version": 3}).status_code == 400
    assert client.get(reverse("engagements:edit", args=[first.pk])).status_code == 403
    assert client.post(reverse("engagements:note_create", args=[first.pk]), {"body": "Unsaved draft"}).status_code == 400
    with pytest.raises(ValidationError):
        services.set_milestone_completed(actor=users["lead"], engagement_id=first.pk, milestone_id=milestone.pk, completed=True, version=1)
    assert client.post(reverse("engagements:archive", args=[first.pk]), {"version": 3}).status_code == 302
    # Access revocation/grants remain available on closed engagements.
    assert client.post(reverse("engagements:members", args=[first.pk]), {"user": users["outsider"].pk, "role": "viewer"}).status_code == 302
    milestone.refresh_from_db()
    assert not milestone.completed


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 302), ("tester", 302), ("reviewer", 302), ("viewer", 403), ("outsider", 404), ("admin", 302)])
def test_note_creation_matrix(client, access_setup, role, expected):
    users, first, _ = access_setup
    client.force_login(users[role])
    assert client.post(reverse("engagements:note_create", args=[first.pk]), {"body": "Team note"}).status_code == expected


@pytest.mark.django_db
def test_note_authority_conflicts_escaping_and_delete(client, access_setup):
    users, first, _ = access_setup
    note = services.save_note(actor=users["tester"], engagement_id=first.pk, body="<script>private-note</script>\nDecision")
    client.force_login(users["reviewer"])
    url = reverse("engagements:note_edit", args=[first.pk, note.pk])
    assert client.get(url).status_code == 403
    with pytest.raises(PermissionDenied):
        services.save_note(actor=users["reviewer"], engagement_id=first.pk, note_id=note.pk, body="Not mine", version=1)
    client.force_login(users["tester"])
    overview = client.get(reverse("engagements:detail", args=[first.pk]))
    assert b"&lt;script&gt;private-note&lt;/script&gt;" in overview.content
    assert client.post(url, {"body": "Updated", "version": 1}).status_code == 302
    response = client.post(url, {"body": "Unsaved note", "version": 1})
    assert response.status_code == 409 and b"Unsaved note" in response.content
    delete = reverse("engagements:note_delete", args=[first.pk, note.pk])
    assert client.get(delete).status_code == 200
    assert client.post(delete, {"version": 1}).status_code == 409
    assert client.post(delete, {"version": 2}).status_code == 302
    assert not EngagementNote.objects.filter(pk=note.pk).exists()
    serialized = json.dumps(list(AuditEvent.objects.filter(engagement=first).values()), default=str)
    assert "private-note" in serialized and "Unsaved note" not in serialized
    assert "private-note" not in json.dumps(list(AuditEvent.objects.values("metadata")), default=str)


@pytest.mark.django_db
def test_milestone_crud_and_htmx_progress(client, access_setup):
    users, first, _ = access_setup
    client.force_login(users["lead"])
    response = client.post(reverse("engagements:milestone_create", args=[first.pk]),
        {"title": "Rules agreed", "description": "Approved scope", "due_date": "2026-11-20"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b'id="milestones"' in response.content and b"<html" not in response.content
    milestone = first.milestones.get()
    assert milestone.created_by == users["lead"]
    edit = reverse("engagements:milestone_edit", args=[first.pk, milestone.pk])
    assert client.get(edit).status_code == 200
    assert client.post(edit, {"title": "Rules approved", "version": 1}).status_code == 302
    toggle = reverse("engagements:milestone_complete", args=[first.pk, milestone.pk])
    response = client.post(toggle, {"version": 2, "completed": "on"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b"100%" in response.content
    assert client.post(toggle, {"version": 2}, HTTP_HX_REQUEST="true").status_code == 409
    milestone.refresh_from_db()
    assert milestone.completed and milestone.completed_at is not None and milestone.version == 3
    delete = reverse("engagements:milestone_delete", args=[first.pk, milestone.pk])
    assert client.get(delete).status_code == 200
    assert client.post(delete, {"version": 2}).status_code == 409
    assert client.post(delete, {"version": 3}).status_code == 302
    assert not first.milestones.exists()


@pytest.mark.django_db
def test_foreign_note_and_milestone_ids_cannot_cross_engagements(client, access_setup):
    users, first, second = access_setup
    note = services.save_note(actor=users["outsider"], engagement_id=second.pk, body="Secret note")
    milestone = services.save_milestone(actor=users["outsider"], engagement_id=second.pk, data={"title": "Secret work"})
    client.force_login(users["lead"])
    for route, child_id, data in [("note_edit", note.pk, {"body": "Forged", "version": 1}),
                                  ("note_delete", note.pk, {"version": 1}),
                                  ("milestone_edit", milestone.pk, {"title": "Forged", "version": 1}),
                                  ("milestone_complete", milestone.pk, {"completed": "on", "version": 1}),
                                  ("milestone_delete", milestone.pk, {"version": 1})]:
        assert client.post(reverse(f"engagements:{route}", args=[first.pk, child_id]), data, HTTP_HX_REQUEST="true").status_code == 404
    with pytest.raises(Http404):
        services.delete_note(actor=users["lead"], engagement_id=first.pk, note_id=note.pk, version=1)
    with pytest.raises(Http404):
        services.set_milestone_completed(actor=users["lead"], engagement_id=first.pk, milestone_id=milestone.pk, completed=True, version=1)
    client.force_login(users["viewer"])
    assert client.get(reverse("engagements:detail", args=[second.pk]), {"panel": "notes"}, HTTP_HX_REQUEST="true").status_code == 404


@pytest.mark.django_db
def test_overview_team_scope_timeline_and_progress(client, access_setup):
    users, first, _ = access_setup
    first = services.update_engagement(actor=users["lead"], engagement_id=first.pk, data=metadata(), version=1)
    milestone = services.save_milestone(actor=users["lead"], engagement_id=first.pk, data={"title": "Ready"})
    services.set_milestone_completed(actor=users["lead"], engagement_id=first.pk, milestone_id=milestone.pk, completed=True, version=1)
    services.save_milestone(actor=users["lead"], engagement_id=first.pk, data={"title": "Remaining"})
    client.force_login(users["viewer"])
    response = client.get(reverse("engagements:detail", args=[first.pk]))
    assert response.status_code == 200 and response.context["progress"] == {"total": 2, "done": 1, "percent": 50}
    for text in (b"Example organization", b"Internal LAN", b"INTERNAL / TEAM ONLY", b"Engagement team", b"Nov 1, 2026"):
        assert text in response.content
    assert b"Manage memberships" not in response.content and b"Add note" not in response.content


@pytest.mark.django_db
def test_protection_and_deliberate_archived_purge_preserve_audit(client, access_setup):
    users, first, _ = access_setup
    note = services.save_note(actor=users["lead"], engagement_id=first.pk, body="Keep until purge")
    services.save_milestone(actor=users["lead"], engagement_id=first.pk, data={"title": "Milestone"})
    with pytest.raises(ProtectedError):
        first.delete()
    with pytest.raises(ValidationError):
        services.purge_engagement(actor=users["admin"], engagement_id=first.pk, version=1, confirmation=str(first.pk), reason="duplicate")
    archived = services.transition_engagement(actor=users["lead"], engagement_id=first.pk, target="archived", version=1)
    for confirmation, version in [("wrong", 2), (str(first.pk), 1)]:
        with pytest.raises((ValidationError, EditConflict)):
            services.purge_engagement(actor=users["admin"], engagement_id=first.pk, version=version, confirmation=confirmation, reason="duplicate")
    with pytest.raises(PermissionDenied):
        services.purge_engagement(actor=users["lead"], engagement_id=first.pk, version=2, confirmation=str(first.pk), reason="duplicate")
    client.force_login(users["admin"])
    assert client.post(f"/engagements/{first.pk}/delete/").status_code == 404
    pk = first.pk
    services.purge_engagement(actor=users["admin"], engagement_id=pk, version=archived.version, confirmation=str(pk), reason="test-data")
    assert not Engagement.objects.filter(pk=pk).exists() and not EngagementNote.objects.filter(pk=note.pk).exists()
    events = AuditEvent.objects.filter(engagement_ref=pk)
    assert events.filter(action="engagement.purged").exists() and not events.filter(engagement__isnull=False).exists()


@pytest.mark.django_db
def test_audit_only_engagement_cannot_be_deleted():
    engagement = Engagement.objects.create(name="Audit only")
    record_event(action=AuditEvent.Action.ENGAGEMENT_CREATED, engagement=engagement, subject_id=engagement.pk)
    with pytest.raises(ProtectedError):
        Engagement.objects.filter(pk=engagement.pk).delete()


@pytest.mark.django_db
def test_multi_model_create_and_edit_rollback_on_audit_failure(access_setup, monkeypatch):
    users, first, _ = access_setup
    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(services, "record_event", unavailable)
    with pytest.raises(RuntimeError):
        services.create_engagement(actor=users["admin"], name="Rolled back", lead_id=users["lead"].pk)
    assert not Engagement.objects.filter(name="Rolled back").exists()
    with pytest.raises(RuntimeError):
        services.update_engagement(actor=users["lead"], engagement_id=first.pk, data=metadata(), version=1)
    first.refresh_from_db()
    assert first.name == "First engagement" and first.version == 1


@pytest.mark.django_db
def test_new_mutations_require_csrf(access_setup):
    users, first, _ = access_setup
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(users["lead"])
    for operation, data in [("edit", {**metadata(), "version": 1}),
                            ("activate", {"version": 1}), ("note_create", {"body": "No token"}),
                            ("milestone_create", {"title": "No token"})]:
        assert protected.post(reverse(f"engagements:{operation}", args=[first.pk]), data, HTTP_HX_REQUEST="true").status_code == 403


@pytest.mark.django_db
def test_direct_mutating_services_deny_nonlead_roles(access_setup):
    users, first, _ = access_setup
    for role in ("tester", "reviewer", "viewer"):
        with pytest.raises(PermissionDenied):
            services.update_engagement(actor=users[role], engagement_id=first.pk, data=metadata(), version=1)
        with pytest.raises(PermissionDenied):
            services.transition_engagement(actor=users[role], engagement_id=first.pk, target="active", version=1)
        with pytest.raises(PermissionDenied):
            services.save_milestone(actor=users[role], engagement_id=first.pk, data={"title": "Forbidden"})
    with pytest.raises(PermissionDenied):
        services.save_note(actor=users["viewer"], engagement_id=first.pk, body="Forbidden")


@pytest.mark.django_db
def test_partial_note_validation_and_full_page_fallback(client, access_setup):
    users, first, _ = access_setup
    client.force_login(users["tester"])
    url = reverse("engagements:note_create", args=[first.pk])
    response = client.post(url, {"body": ""}, HTTP_HX_REQUEST="true")
    assert response.status_code == 400 and b"This field is required" in response.content
    assert b"<html" not in response.content
    response = client.post(url, {"body": "HTMX note"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b"HTMX note" in response.content and b"<html" not in response.content
    assert client.post(url, {"body": "No JS note"}).status_code == 302


@pytest.mark.django_db
def test_failed_purge_rolls_back_related_records_and_audit_links(access_setup, monkeypatch):
    users, first, _ = access_setup
    note = services.save_note(actor=users["lead"], engagement_id=first.pk, body="Retained")
    archived = services.transition_engagement(actor=users["lead"], engagement_id=first.pk, target="archived", version=1)
    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(services, "record_event", unavailable)
    with pytest.raises(RuntimeError):
        services.purge_engagement(actor=users["admin"], engagement_id=first.pk, version=archived.version, confirmation=str(first.pk), reason="retention")
    assert Engagement.objects.filter(pk=first.pk).exists()
    assert EngagementNote.objects.filter(pk=note.pk).exists()
    assert first.memberships.count() == 4
    assert AuditEvent.objects.filter(engagement=first).count() == 2


@pytest.mark.django_db
def test_unauthenticated_htmx_requests_redirect_the_whole_page(client, access_setup):
    response = client.get(reverse("engagements:list"), HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response["HX-Redirect"].startswith(reverse("accounts:login"))
    assert response["Cache-Control"] == "no-store, private"


@pytest.mark.django_db
def test_unsaved_classification_change_does_not_replace_saved_banner(client, access_setup):
    users, first, _ = access_setup
    services.update_engagement(actor=users["lead"], engagement_id=first.pk,
                               data=metadata(report_classification="SAVED HANDLING"), version=1)
    client.force_login(users["lead"])
    response = client.post(reverse("engagements:edit", args=[first.pk]),
        {**metadata(report_classification="DRAFT HANDLING"), "version": 1})
    assert response.status_code == 409
    assert b'aria-label="Classification and handling marking">SAVED HANDLING' in response.content
    assert b'value="DRAFT HANDLING"' in response.content
