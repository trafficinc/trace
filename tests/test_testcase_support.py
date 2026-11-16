import json
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.urls import reverse
from apps.audit.models import AuditEvent
from apps.testcases import services


@pytest.fixture
def cases(access_setup):
    users, first, second = access_setup
    own = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data={"title": "Own test", "category": "Auth"})
    another = services.create_test_case(actor=users["tester"], engagement_id=first.pk, data={"title": "Another test", "category": "Auth"})
    foreign = services.create_test_case(actor=users["outsider"], engagement_id=second.pk, data={"title": "Secret test", "category": "Private"})
    return users, first, second, own, another, foreign


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("lead", 200), ("tester", 200), ("reviewer", 200), ("viewer", 403), ("outsider", 404), ("admin", 200)])
def test_test_note_creation_matrix(client, cases, role, expected):
    users, first, _, own, _, _ = cases
    client.force_login(users[role])
    response = client.post(reverse("testcases:note_create", args=[first.pk, own.pk]), {"body": "Reviewer context"}, HTTP_HX_REQUEST="true")
    assert response.status_code == expected
    if expected == 200:
        assert b"Reviewer context" in response.content and b"<html" not in response.content


@pytest.mark.django_db
def test_note_authority_formatting_conflicts_and_confirmation(client, cases):
    users, first, _, own, _, _ = cases
    body = "  <script>private-review</script>\n    Indented note\n"
    note = services.save_test_note(actor=users["reviewer"], engagement_id=first.pk, test_case_id=own.pk, body=body)
    assert note.body == body
    with pytest.raises(PermissionDenied):
        services.save_test_note(actor=users["tester"], engagement_id=first.pk, test_case_id=own.pk, note_id=note.pk, body="Not mine", version=1)
    client.force_login(users["reviewer"])
    detail = client.get(reverse("testcases:detail", args=[first.pk, own.pk]))
    assert b"&lt;script&gt;private-review&lt;/script&gt;" in detail.content
    edit = reverse("testcases:note_edit", args=[first.pk, own.pk, note.pk])
    assert client.get(edit).status_code == 200
    assert client.post(edit, {"body": "Updated note", "version": 1}).status_code == 302
    response = client.post(edit, {"body": "Stale draft", "version": 1}, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and b"Stale draft" in response.content
    delete = reverse("testcases:note_delete", args=[first.pk, own.pk, note.pk])
    assert client.get(delete).status_code == 200
    assert client.post(delete, {"version": 1}).status_code == 409
    assert client.post(delete, {"version": 2}).status_code == 302
    assert not own.note_entries.exists()
    assert "private-review" not in json.dumps(list(AuditEvent.objects.values("metadata")), default=str)
    assert "private-review" in json.dumps(list(AuditEvent.objects.values("after")), default=str)


@pytest.mark.django_db
def test_reference_crud_safe_links_and_role_enforcement(client, cases):
    users, first, _, own, _, _ = cases
    for url in ("javascript:alert(1)", "file:///etc/passwd", "ftp://example.test/file"):
        with pytest.raises(ValidationError):
            services.save_reference(actor=users["tester"], engagement_id=first.pk, test_case_id=own.pk,
                data={"label": "Unsafe", "url": url})
    with pytest.raises(ValidationError):
        services.save_reference(actor=users["tester"], engagement_id=first.pk, test_case_id=own.pk, data={"label": "Empty"})
    with pytest.raises(PermissionDenied):
        services.save_reference(actor=users["reviewer"], engagement_id=first.pk, test_case_id=own.pk, data={"label": "No write", "citation": "Section 1"})
    client.force_login(users["tester"])
    response = client.post(reverse("testcases:reference_create", args=[first.pk, own.pk]),
        {"label": "Review policy", "url": "https://example.test/policy", "citation": "  Local document\n    Section 4\n"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b"<html" not in response.content
    reference = own.references.get()
    assert reference.citation == "  Local document\n    Section 4\n"
    edit = reverse("testcases:reference_edit", args=[first.pk, own.pk, reference.pk])
    assert client.get(edit).status_code == 200
    assert client.post(edit, {"label": "Updated", "citation": "Section 5", "version": 1}).status_code == 302
    assert client.post(edit, {"label": "Stale", "citation": "Section 6", "version": 1}).status_code == 409
    delete = reverse("testcases:reference_delete", args=[first.pk, own.pk, reference.pk])
    assert client.get(delete).status_code == 200
    assert client.post(delete, {"version": 2}).status_code == 302
    assert not own.references.exists()


@pytest.mark.django_db
def test_supporting_records_cannot_cross_case_or_engagement(client, cases):
    users, first, second, own, another, foreign = cases
    note = services.save_test_note(actor=users["reviewer"], engagement_id=first.pk, test_case_id=another.pk, body="Other case")
    reference = services.save_reference(actor=users["outsider"], engagement_id=second.pk, test_case_id=foreign.pk, data={"label": "Private", "citation": "Secret citation"})
    client.force_login(users["lead"])
    for route, child, data in [("note_edit", note, {"body": "Forged", "version": 1}), ("note_delete", note, {"version": 1}),
                               ("reference_edit", reference, {"label": "Forged", "citation": "Section 1", "version": 1}),
                               ("reference_delete", reference, {"version": 1})]:
        assert client.post(reverse(f"testcases:{route}", args=[first.pk, own.pk, child.pk]), data, HTTP_HX_REQUEST="true").status_code == 404
    with pytest.raises(Http404):
        services.delete_test_child(actor=users["lead"], engagement_id=first.pk, test_case_id=own.pk, child_id=note.pk, kind="note", version=1)
    with pytest.raises(Http404):
        services.save_reference(actor=users["lead"], engagement_id=first.pk, test_case_id=own.pk, reference_id=reference.pk, data={"label": "Forged", "citation": "Local"}, version=1)


@pytest.mark.django_db
def test_discussion_and_reference_pagination(client, cases):
    users, first, _, own, _, _ = cases
    for index in range(11):
        services.save_test_note(actor=users["reviewer"], engagement_id=first.pk, test_case_id=own.pk, body=f"Note {index}")
    client.force_login(users["viewer"])
    response = client.get(reverse("testcases:detail", args=[first.pk, own.pk]), {"panel": "notes", "note_page": 2}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and len(response.context["note_page"]) == 1 and b"<html" not in response.content
    assert b"Add note" not in response.content
