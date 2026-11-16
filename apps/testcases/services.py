from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.exceptions import EditConflict
from apps.core.concurrency import cas_update, cas_delete
from apps.engagements.permissions import Permission, get_writable_engagement, require_system_admin, has_permission
from .forms import (BLUEPRINT_FIELDS, CASE_FIELDS, TEMPLATE_FIELDS, CreateTestCaseForm, EditTestCaseForm,
                    TemplateForm, TestNoteForm, ReferenceForm)
from .models import TestCaseStatus, TestCaseTemplate, TestCaseAsset

S = TestCaseStatus
TERMINAL = {S.PASSED, S.FAILED, S.NOT_APPLICABLE}
TRANSITIONS = {
    S.NOT_STARTED: {S.IN_PROGRESS, S.BLOCKED, S.NOT_APPLICABLE},
    S.IN_PROGRESS: {S.BLOCKED, S.PASSED, S.FAILED, S.NOT_APPLICABLE},
    S.BLOCKED: {S.IN_PROGRESS, S.NOT_APPLICABLE},
    S.PASSED: {S.IN_PROGRESS}, S.FAILED: {S.IN_PROGRESS}, S.NOT_APPLICABLE: {S.IN_PROGRESS},
}


def _allow(data, fields):
    if set(data) - set(fields):
        raise ValidationError("Unrecognized fields in this operation.")


def _form(form_class, data, **kwargs):
    form = form_class(data, **kwargs)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    return form


@transaction.atomic
def create_test_case(*, actor, engagement_id, data):
    engagement = get_writable_engagement(actor, engagement_id, Permission.WRITE_TESTS)
    _allow(data, CASE_FIELDS + ["assets", "source_template", "template_version"])
    values = dict(data)
    template = None
    if values.get("source_template"):
        template = get_object_or_404(TestCaseTemplate.objects.filter(is_active=True), pk=values["source_template"])
        if values.get("template_version"):
            try:
                expected_template_version = int(values["template_version"])
            except (ValueError, TypeError) as exc:
                raise ValidationError("Invalid template version.") from exc
            if expected_template_version != template.version:
                raise EditConflict(current=template)
        for field in BLUEPRINT_FIELDS:
            values.setdefault(field, getattr(template, field))
    form = _form(CreateTestCaseForm, values, engagement=engagement)
    case = form.save(commit=False)
    case.status, case.started_at, case.completed_at = S.NOT_STARTED, None, None
    case.created_by = actor
    case.source_template = template
    case.source_template_version = template.version if template else None
    case.save()
    _replace_assets(case, form.cleaned_data["assets"])
    record_event(action=AuditEvent.Action.TEST_CREATED, actor=actor, engagement=engagement, subject_id=case.pk, metadata={"version": 1})
    return case


def _replace_assets(case, assets):
    # Explicit through rows are also guarded by SQLite triggers for bulk/raw ORM writes.
    case.asset_links.all().delete()
    TestCaseAsset.objects.bulk_create([TestCaseAsset(test_case=case, asset=asset) for asset in assets])


@transaction.atomic
def update_test_case(*, actor, engagement_id, test_case_id, data, version):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, Permission.WRITE_TESTS)
    _allow(data, CASE_FIELDS + ["assets", "status"])
    case = get_object_or_404(engagement.test_cases, pk=test_case_id)
    if case.version != version:
        raise EditConflict(current=case)
    previous_status = case.status
    form = _form(EditTestCaseForm, {**data, "version": version}, instance=case, engagement=engagement)
    candidate = form.save(commit=False)
    target = candidate.status
    if target != previous_status and target not in TRANSITIONS.get(previous_status, set()):
        raise ValidationError("This test status transition is not allowed. Resume a blocked or finished test before recording a new outcome.")
    now = timezone.now()
    if target != previous_status:
        if target == S.IN_PROGRESS and candidate.started_at is None:
            candidate.started_at = now
        candidate.completed_at = now if target in TERMINAL else None
    candidate.full_clean()
    values = {field: getattr(candidate, field) for field in CASE_FIELDS + ["status", "started_at", "completed_at"]}
    before = cas_update(engagement.test_cases.filter(pk=case.pk), version=version, **values, updated_at=now)
    _replace_assets(case, form.cleaned_data["assets"])
    record_event(action=AuditEvent.Action.TEST_UPDATED, actor=actor, engagement=engagement, subject_id=case.pk,
                 metadata={"version": version + 1, "status": target, "previous_status": previous_status}, before=before)
    case.refresh_from_db()
    return case


@transaction.atomic
def save_template(*, actor, data, template_id=None, version=None):
    before = None
    require_system_admin(actor)
    _allow(data, TEMPLATE_FIELDS)
    template = get_object_or_404(TestCaseTemplate, pk=template_id) if template_id else None
    form = _form(TemplateForm, data, instance=template)
    candidate = form.save(commit=False)
    if template is None:
        candidate.created_by = actor
        candidate.save()
        action = AuditEvent.Action.TEST_TEMPLATE_CREATED
    else:
        values = {field: getattr(candidate, field) for field in TEMPLATE_FIELDS}
        before = cas_update(TestCaseTemplate.objects.filter(pk=template_id), version=version, **values, updated_at=timezone.now())
        action = AuditEvent.Action.TEST_TEMPLATE_UPDATED
    candidate.refresh_from_db()
    record_event(action=action, actor=actor, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate


def can_edit_test_note(actor, engagement, note):
    return has_permission(actor, engagement.pk, Permission.WRITE_TEST_NOTES) and (
        actor.pk == note.created_by_id or has_permission(actor, engagement.pk, Permission.EDIT_ENGAGEMENT))


@transaction.atomic
def save_test_note(*, actor, engagement_id, test_case_id, body, note_id=None, version=None):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, Permission.WRITE_TEST_NOTES)
    case = get_object_or_404(engagement.test_cases, pk=test_case_id)
    note = get_object_or_404(case.note_entries, pk=note_id) if note_id else None
    if note and not can_edit_test_note(actor, engagement, note):
        raise PermissionDenied("Only the author, a Lead or a System Admin can change this note.")
    candidate = _form(TestNoteForm, {"body": body}, instance=note).save(commit=False)
    if note is None:
        candidate.test_case, candidate.created_by = case, actor
        candidate.save()
    else:
        before = cas_update(case.note_entries.filter(pk=note.pk), version=version, body=candidate.body, updated_at=timezone.now())
    candidate.refresh_from_db()
    record_event(action=AuditEvent.Action.TEST_NOTE_SAVED, actor=actor, engagement=engagement, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate


@transaction.atomic
def save_reference(*, actor, engagement_id, test_case_id, data, reference_id=None, version=None):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, Permission.WRITE_TESTS)
    case = get_object_or_404(engagement.test_cases, pk=test_case_id)
    _allow(data, ["label", "url", "citation"])
    reference = get_object_or_404(case.references, pk=reference_id) if reference_id else None
    candidate = _form(ReferenceForm, data, instance=reference).save(commit=False)
    if reference is None:
        candidate.test_case, candidate.created_by = case, actor
        candidate.save()
    else:
        before = cas_update(case.references.filter(pk=reference.pk), version=version, label=candidate.label,
                   url=candidate.url, citation=candidate.citation, updated_at=timezone.now())
    candidate.refresh_from_db()
    record_event(action=AuditEvent.Action.TEST_REFERENCE_SAVED, actor=actor, engagement=engagement, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate


@transaction.atomic
def delete_test_child(*, actor, engagement_id, test_case_id, child_id, kind, version):
    before = None
    if kind not in {"note", "reference"}:
        raise ValidationError("Unknown record type.")
    permission = Permission.WRITE_TEST_NOTES if kind == "note" else Permission.WRITE_TESTS
    engagement = get_writable_engagement(actor, engagement_id, permission)
    case = get_object_or_404(engagement.test_cases, pk=test_case_id)
    queryset = case.note_entries if kind == "note" else case.references
    child = get_object_or_404(queryset, pk=child_id)
    if kind == "note" and not can_edit_test_note(actor, engagement, child):
        raise PermissionDenied
    before = cas_delete(queryset.filter(pk=child.pk), version=version)
    record_event(action=AuditEvent.Action.TEST_CHILD_DELETED, actor=actor, engagement=engagement, subject_id=child_id, metadata={"version": version}, before=before)
