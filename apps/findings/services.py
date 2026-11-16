from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.services import record_event
from apps.core.exceptions import EditConflict
from apps.core.concurrency import cas_update
from apps.engagements.permissions import Permission as P, get_writable_engagement, require_system_admin
from .forms import FindingForm, TemplateForm, FINDING_FIELDS, TEMPLATE_FIELDS, DEFINITION_FIELDS
from .models import Finding, FindingTemplate, FindingStatus as S, FindingAsset, FindingTestCase

TRANSITIONS = {S.DRAFT: {S.UNDER_REVIEW}, S.UNDER_REVIEW: {S.DRAFT, S.CONFIRMED}, S.CONFIRMED: {S.UNDER_REVIEW, S.REMEDIATED, S.ACCEPTED_RISK}, S.REMEDIATED: {S.UNDER_REVIEW}, S.ACCEPTED_RISK: {S.UNDER_REVIEW}}


def _form(cls, data, fields, **kwargs):
    if set(data) - set(fields):
        raise ValidationError('Unrecognized fields.')
    form = cls(data, **kwargs)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    return form


def _audit(action, actor, finding, *, before=None):
    record_event(action=action, actor=actor, engagement=finding.engagement, subject_id=finding.pk,
                 metadata={'version': finding.version, 'status': finding.status}, before=before)


@transaction.atomic
def save_finding(*, actor, engagement_id, data, finding_id=None, version=None):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, P.WRITE_FINDINGS)
    finding = get_object_or_404(engagement.findings, pk=finding_id) if finding_id else None
    if finding and finding.version != version:
        raise EditConflict(current=finding)
    if finding and finding.status != S.DRAFT:
        raise ValidationError('Return the finding to draft through review before editing.')
    form = _form(FindingForm, data, FINDING_FIELDS, instance=finding, engagement=engagement)
    candidate = form.save(commit=False)
    if finding is None:
        candidate.author = actor
        candidate.save()
        action = 'finding.created'
    else:
        values = {name: getattr(candidate, name) for name in DEFINITION_FIELDS}
        before = cas_update(engagement.findings.filter(pk=finding_id), version=version, **values,
                   reviewer=None, reviewed_at=None, updated_at=timezone.now())
        action = 'finding.updated'
    candidate.asset_links.all().delete()
    candidate.test_case_links.all().delete()
    FindingAsset.objects.bulk_create([FindingAsset(finding=candidate, asset=a) for a in form.cleaned_data['assets']])
    FindingTestCase.objects.bulk_create([FindingTestCase(finding=candidate, test_case=c) for c in form.cleaned_data['test_cases']])
    candidate.refresh_from_db()
    _audit(action, actor, candidate, before=before)
    return candidate


@transaction.atomic
def transition_finding(*, actor, engagement_id, finding_id, target, version):
    before = None
    permission = P.WRITE_FINDINGS if target == S.UNDER_REVIEW else P.REVIEW_FINDINGS
    engagement = get_writable_engagement(actor, engagement_id, permission)
    finding = get_object_or_404(engagement.findings, pk=finding_id)
    if finding.version != version:
        raise EditConflict(current=finding)
    if target not in TRANSITIONS.get(finding.status, set()):
        raise ValidationError('This finding status transition is not allowed.')
    if target in {S.CONFIRMED, S.REMEDIATED, S.ACCEPTED_RISK} and finding.author_id == actor.pk:
        raise PermissionDenied('A different reviewer must approve this finding.')
    now = timezone.now()
    before = cas_update(engagement.findings.filter(pk=finding.pk), version=version, status=target,
               reviewer=actor if target != S.UNDER_REVIEW else None,
               reviewed_at=now if target != S.UNDER_REVIEW else None, updated_at=now)
    finding.refresh_from_db()
    _audit('finding.status_changed', actor, finding, before=before)
    return finding


@transaction.atomic
def save_template(*, actor, data, template_id=None, version=None):
    before = None
    require_system_admin(actor)
    template = get_object_or_404(FindingTemplate, pk=template_id) if template_id else None
    candidate = _form(TemplateForm, data, TEMPLATE_FIELDS, instance=template).save(commit=False)
    if template is None:
        candidate.created_by = actor
        candidate.save()
    else:
        before = cas_update(FindingTemplate.objects.filter(pk=template_id), version=version,
                   **{f: getattr(candidate, f) for f in TEMPLATE_FIELDS}, updated_at=timezone.now())
    candidate.refresh_from_db()
    record_event(action='finding_template.saved', actor=actor, subject_id=candidate.pk, metadata={'version': candidate.version}, before=before)
    return candidate


@transaction.atomic
def copy_template(*, actor, engagement_id, template_id, version):
    engagement = get_writable_engagement(actor, engagement_id, P.WRITE_FINDINGS)
    template = get_object_or_404(FindingTemplate.objects.filter(is_active=True), pk=template_id)
    if template.version != version:
        raise EditConflict(current=template)
    # Deliberately copy definition fields only. No customer relationships, review or authorship.
    finding = Finding(engagement=engagement, author=actor, source_template=template, source_template_version=template.version,
                      **{f: getattr(template, f) for f in DEFINITION_FIELDS})
    finding.full_clean()
    finding.save()
    _audit('finding.created', actor, finding)
    return finding
