import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.urls import reverse
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict
from apps.engagements.models import EngagementMembership
from apps.engagements.permissions import Permission, get_engagement, get_scoped_object, has_permission
from apps.engagements.services import change_membership, grant_membership, revoke_membership

EXPECTED = {
    "lead": {"manage_assets", "write_test_notes", "view", "manage_members", "edit_engagement", "write_notes", "manage_milestones", "write_tests", "write_findings", "review_findings", "attach_evidence", "download_evidence", "generate_reports", "view_audit"},
    "tester": {"manage_assets", "write_test_notes", "view", "write_notes", "write_tests", "write_findings", "attach_evidence", "download_evidence", "generate_reports"},
    "reviewer": {"write_test_notes", "view", "write_notes", "review_findings", "download_evidence", "generate_reports", "view_audit"},
    "viewer": {"view", "download_evidence"},
    "outsider": set(),
}


@pytest.mark.django_db
@pytest.mark.parametrize("role", list(EXPECTED) + ["admin"])
@pytest.mark.parametrize("permission", list(Permission))
def test_capability_matrix(access_setup, role, permission):
    users, engagement, _ = access_setup
    assert has_permission(users[role], engagement.pk, permission) == (role == "admin" or permission.value in EXPECTED[role])
    assert not has_permission(users[role], engagement.pk, "unknown_permission")


@pytest.mark.django_db
@pytest.mark.parametrize("role,status", [("lead", 200), ("tester", 403), ("reviewer", 403), ("viewer", 403), ("outsider", 404), ("admin", 200)])
@pytest.mark.parametrize("htmx", [False, True])
def test_membership_page_matrix(client, access_setup, role, status, htmx):
    users, first, _ = access_setup
    client.force_login(users[role])
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    assert client.get(reverse("engagements:members", args=[first.pk]), **headers).status_code == status


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["tester", "reviewer", "viewer"])
def test_direct_services_and_forged_posts_cannot_escalate(client, access_setup, role):
    users, first, _ = access_setup
    client.force_login(users[role])
    assert client.post(reverse("engagements:members", args=[first.pk]), {"user": users["outsider"].pk, "role": "lead"}).status_code == 403
    with pytest.raises(PermissionDenied):
        grant_membership(actor=users[role], engagement_id=first.pk, user_id=users["outsider"].pk, role="lead")
    assert client.get(reverse("accounts:users")).status_code == 403
    assert client.post(reverse("accounts:user_create"), {"is_superuser": True}).status_code == 403


@pytest.mark.django_db
def test_cross_engagement_ids_and_different_roles(client, access_setup):
    users, first, second = access_setup
    client.force_login(users["lead"])
    assert has_permission(users["lead"], first.pk, Permission.MANAGE_MEMBERS)
    assert not has_permission(users["lead"], second.pk, Permission.MANAGE_MEMBERS)
    assert client.get(reverse("engagements:members", args=[second.pk])).status_code == 403
    foreign = second.memberships.get(user=users["outsider"])
    assert client.post(reverse("engagements:member_change", args=[first.pk, foreign.pk]), {"role": "viewer", "version": 1}).status_code == 404
    with pytest.raises(Http404):
        change_membership(actor=users["lead"], engagement_id=first.pk, membership_id=foreign.pk, role="viewer", version=1)
    with pytest.raises(Http404):
        get_scoped_object(users["lead"], first.pk, EngagementMembership.objects.all(), pk=foreign.pk)
    with pytest.raises(Http404):
        get_engagement(users["viewer"], second.pk)
    foreign.refresh_from_db()
    assert foreign.role == "lead"


@pytest.mark.django_db
def test_membership_stale_edits_and_revocation(client, access_setup):
    users, first, _ = access_setup
    member = first.memberships.get(user=users["tester"])
    change_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, role="reviewer", version=1)
    with pytest.raises(EditConflict):
        change_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, role="lead", version=1)
    with pytest.raises(EditConflict):
        revoke_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, version=1)
    client.force_login(users["tester"])
    revoke_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, version=2)
    assert client.get(reverse("engagements:detail", args=[first.pk])).status_code == 404
    assert AuditEvent.objects.filter(action="membership.changed").count() == 1
    assert AuditEvent.objects.filter(action="membership.revoked").count() == 1


@pytest.mark.django_db
def test_no_self_escalation_or_last_lead_removal(access_setup):
    users, first, _ = access_setup
    member = first.memberships.get(user=users["lead"])
    with pytest.raises(PermissionDenied):
        change_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, role="viewer", version=1)
    with pytest.raises(ValidationError):
        revoke_membership(actor=users["admin"], engagement_id=first.pk, membership_id=member.pk, version=1)


@pytest.mark.django_db
def test_role_validation_and_duplicate_grant(access_setup):
    users, first, _ = access_setup
    with pytest.raises(ValidationError):
        grant_membership(actor=users["lead"], engagement_id=first.pk, user_id=users["outsider"].pk, role="system_admin")
    with pytest.raises(EditConflict):
        grant_membership(actor=users["lead"], engagement_id=first.pk, user_id=users["tester"].pk, role="lead")


@pytest.mark.django_db
def test_deactivated_actor_and_staff_are_denied(client, access_setup):
    users, first, _ = access_setup
    actor = users["lead"]
    client.force_login(actor)
    type(actor).objects.filter(pk=actor.pk).update(is_active=False)
    assert client.get(reverse("engagements:detail", args=[first.pk])).status_code == 302
    assert not has_permission(actor, first.pk, Permission.VIEW)  # A stale service object cannot retain access.
    users["outsider"].is_staff = True
    users["outsider"].save()
    assert not has_permission(users["outsider"], first.pk, Permission.VIEW)


@pytest.mark.django_db
def test_audit_failure_rolls_back_role_change(access_setup, monkeypatch):
    users, first, _ = access_setup
    member = first.memberships.get(user=users["tester"])
    def broken(**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr("apps.engagements.services.record_event", broken)
    with pytest.raises(RuntimeError):
        change_membership(actor=users["lead"], engagement_id=first.pk, membership_id=member.pk, role="reviewer", version=1)
    member.refresh_from_db()
    assert (member.role, member.version) == ("tester", 1)


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 302), ("tester", 403), ("reviewer", 403), ("viewer", 403), ("outsider", 404), ("admin", 302)])
@pytest.mark.parametrize("operation", ["grant", "change", "revoke"])
@pytest.mark.parametrize("headers", [{}, {"HTTP_HX_REQUEST": "true"}])
def test_mutating_endpoint_matrix(client, access_setup, role, expected, operation, headers):
    users, first, _ = access_setup
    client.force_login(users[role])
    member = first.memberships.get(user=users["tester"])
    if operation == "grant":
        url = reverse("engagements:members", args=[first.pk])
        data = {"user": users["outsider"].pk, "role": "reviewer"}
    else:
        url = reverse(f"engagements:member_{operation}", args=[first.pk, member.pk])
        data = {"version": 1, "role": "reviewer"}
    response = client.post(url, data, **headers)
    assert response.status_code == (204 if headers and expected == 302 else expected)
    if headers and expected == 302:
        assert response['HX-Redirect'] == reverse('engagements:members', args=[first.pk])
