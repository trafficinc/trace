"""Scoped editor metadata shared by conflict screens and informational polling."""
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from apps.engagements.permissions import Permission as P, get_engagement, has_permission, identity, require_system_admin

# Fixed application targets, never a submitted model name or arbitrary ORM lookup.
EDITORS = {
    'engagement': ('engagements.Engagement', P.EDIT_ENGAGEMENT, ''),
    'membership': ('engagements.EngagementMembership', P.MANAGE_MEMBERS, 'engagement'),
    'note': ('engagements.EngagementNote', P.WRITE_NOTES, 'engagement'),
    'milestone': ('engagements.EngagementMilestone', P.MANAGE_MILESTONES, 'engagement'),
    'asset': ('assets.Asset', P.MANAGE_ASSETS, 'engagement'),
    'test': ('testcases.TestCase', P.WRITE_TESTS, 'engagement'),
    'test-note': ('testcases.TestCaseNote', P.WRITE_TEST_NOTES, 'test_case__engagement'),
    'reference': ('testcases.TestCaseReference', P.WRITE_TESTS, 'test_case__engagement'),
    'finding': ('findings.Finding', P.WRITE_FINDINGS, 'engagement'),
    'evidence': ('evidence.Evidence', P.ATTACH_EVIDENCE, 'engagement'),
    'test-template': ('testcases.TestCaseTemplate', None, None),
    'finding-template': ('findings.FindingTemplate', None, None),
    'report': ('reports.Report', P.GENERATE_REPORTS, 'engagement'),
    'report-template': ('reports.ReportTemplate', None, None),
    'account': ('accounts.User', None, None),
}


def editor_kind(record):
    return next((kind for kind, (label, _, _) in EDITORS.items() if record._meta.label_lower == label.lower()), None)


def resolve_editor(*, actor, kind, object_id, engagement_id=None, writable=False):
    if kind not in EDITORS:
        raise Http404
    label, permission, relation = EDITORS[kind]
    model = apps.get_model(label)
    if relation is None and engagement_id is not None:
        raise Http404
    engagement = None
    if relation is not None:
        if not engagement_id:
            raise Http404
        if kind == 'finding' and has_permission(actor, engagement_id, P.REVIEW_FINDINGS):
            permission = P.VIEW
        engagement = get_engagement(actor, engagement_id, permission)
        scope = {'pk': engagement.pk} if not relation else {relation: engagement}
        queryset = model.objects.filter(**scope)
    elif kind == 'account':
        if identity(actor) is None:
            raise PermissionDenied
        if str(actor.pk) != str(object_id):
            require_system_admin(actor)
        queryset = model.objects.all()
    else:
        require_system_admin(actor)
        queryset = model.objects.all()
    try:
        record = get_object_or_404(queryset, pk=object_id)
    except (ValidationError, ValueError) as exc:
        raise Http404 from exc
    if kind in {'note', 'test-note', 'evidence', 'finding'} and engagement is None:
        raise Http404
    scope_id = engagement.pk if engagement is not None else None
    if kind in {'note', 'test-note'} and record.created_by_id != actor.pk and not has_permission(actor, scope_id, P.EDIT_ENGAGEMENT):
        raise PermissionDenied
    if kind == 'evidence':
        if record.deleted_at:
            raise Http404
        if record.uploader_id != actor.pk and not has_permission(actor, scope_id, P.EDIT_ENGAGEMENT):
            raise PermissionDenied
    if writable and kind == 'finding' and not has_permission(actor, scope_id, P.WRITE_FINDINGS):
        raise PermissionDenied
    if writable and engagement and (engagement.is_read_only and kind != 'membership' or kind == 'finding' and record.status != 'draft'):
        raise PermissionDenied('This record is read-only.')
    return record, engagement


def engagement_id_for(record):
    if record._meta.label_lower == 'engagements.engagement':
        return record.pk
    if hasattr(record, 'engagement_id'):
        return record.engagement_id
    if hasattr(record, 'test_case_id'):
        return record.test_case.engagement_id
    return None
