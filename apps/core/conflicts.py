"""HTML-only conflict review. User drafts never enter sessions, URLs or audit logs."""
from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from apps.engagements.permissions import get_engagement, Permission
from .editing import editor_kind, engagement_id_for, resolve_editor

SALT = 'trace.manual-merge'


def _target(request, context, form):
    record = getattr(form, 'conflict_current', None)
    if record is None:
        record = getattr(form, 'instance', None)
        if record is not None and record._state.adding:
            record = None
    if record is None and request.resolver_match.namespace == 'accounts' and request.resolver_match.url_name == 'password_change':
        record = request.user
    if record is None and request.method == 'POST' and 'version' in form.fields:
        match = request.resolver_match
        if match.namespace == 'engagements':
            engagement = context.get('engagement')
            if match.url_name in {'member_change', 'member_revoke'}:
                record = engagement.memberships.filter(pk=match.kwargs['membership_id']).first()
            elif match.url_name == 'milestone_complete':
                record = engagement.milestones.filter(pk=match.kwargs['milestone_id']).first()
            elif match.url_name in {'activate', 'pause', 'complete', 'archive'}:
                record = engagement
        elif match.namespace == 'findings' and match.url_name == 'detail':
            record = context.get('finding')
        record = record or context.get('child')
    if record is None and getattr(form, 'edit_conflict', False):
        record = next((context[key] for key in ('child', 'finding', 'evidence', 'engagement') if context.get(key) is not None), None)
    if record is None:
        return None
    kind = editor_kind(record)
    if not kind:
        return None
    if kind in {'test-template', 'finding-template', 'report-template'} and getattr(getattr(form, '_meta', None), 'model', None) is not type(record):
        engagement = context.get('engagement')
        if engagement is None:
            return None
        get_engagement(request.user, engagement.pk, Permission.WRITE_TESTS if kind == 'test-template' else (Permission.GENERATE_REPORTS if kind == 'report-template' else Permission.WRITE_FINDINGS))
        current = type(record).objects.filter(pk=record.pk, is_active=True).first()
        if current is None:
            return None
        form.source_only_conflict = True
        return current, None
    return resolve_editor(actor=request.user, kind=kind, object_id=record.pk,
                          engagement_id=engagement_id_for(record))


def _value(record, name):
    if name == 'target':
        name = 'status'
    if not hasattr(record, name):
        return '—'
    value = getattr(record, name)
    if hasattr(value, 'all'):
        return '\n'.join(f'{item} ({item.pk})' for item in value.all()) or '—'
    display = getattr(record, f'get_{name}_display', None)
    return str(display() if display else value) if value is not None else '—'


def _rows(form, record):
    rows = []
    for field in form:
        if field.name == 'version' or isinstance(field.field.widget, forms.PasswordInput) or isinstance(field.field, forms.FileField):
            continue
        submitted = field.value()
        if isinstance(submitted, (tuple, list)):
            submitted = '\n'.join(map(str, submitted))
        rows.append({'label': field.label, 'submitted': submitted if submitted is not None else '', 'current': _value(record, field.name)})
    if hasattr(record, 'status') and 'status' not in form.fields:
        rows.append({'label': 'Saved status', 'submitted': '—', 'current': _value(record, 'status')})
    return rows


def editor_context(request, context):
    """Resolve only an existing editor form; lists/create forms are not polled."""
    candidates = [value for value in context.values() if isinstance(value, forms.BaseForm)]
    form = next((value for value in candidates if 'version' in value.fields), None)
    conflicted = next((value for value in candidates if getattr(value, 'edit_conflict', False)), None)
    form = conflicted or form
    primary = context.get('form')
    if context.get('version_form') is not None and primary is not None:
        # Password edits carry their version in a separate form. Preserve the
        # password form (with blank secure widgets), never substitute status fields.
        form = primary
    if form is None:
        return None
    target = _target(request, context, form)
    if target is None:
        return {'form': form} if conflicted else None
    record, engagement = target
    kind = editor_kind(record)
    args = [kind, record.pk]
    if engagement:
        status_url = reverse('core:engagement_editor_status', args=[engagement.pk, *args])
        presence_url = reverse('core:engagement_editor_presence', args=[engagement.pk, *args])
    else:
        status_url = reverse('core:editor_status', args=args)
        presence_url = reverse('core:editor_presence', args=args)
    loaded = request.POST.get('version') if form.is_bound else form.initial.get('version', record.version)
    try:
        stale = form.is_bound and int(loaded) != record.version
    except (TypeError, ValueError):
        stale = False
    return {'form': form, 'record': record, 'engagement': engagement, 'kind': kind, 'loaded_version': loaded,
            'stale': stale, 'conflicted': bool(conflicted), 'status_url': status_url, 'presence_url': presence_url}


def conflict_context(request, editor):
    form, record = editor['form'], editor.get('record')
    context = {'form': form, 'conflict': True, 'conflict_rows': [], 'merge_ready': False, 'reload_url': request.path}
    if record is None:
        return context
    try:
        resolve_editor(actor=request.user, kind=editor['kind'], object_id=record.pk,
                       engagement_id=engagement_id_for(record), writable=True)
        writable = True
    except (Http404, PermissionDenied):
        writable = False
    token_values = {'actor': request.user.pk, 'path': request.path, 'kind': editor['kind'], 'id': str(record.pk), 'version': record.version}
    sensitive = any(isinstance(f.widget, forms.PasswordInput) for f in form.fields.values())
    can_merge = not getattr(form, 'source_only_conflict', False) and writable and 'version' in form.fields and not sensitive
    if can_merge and request.POST.get('_prepare_merge'):
        try:
            reviewed = signing.loads(request.POST['_prepare_merge'], salt=SALT, max_age=900)
        except signing.BadSignature:
            reviewed = None
        if reviewed == token_values:
            # Explicit review prepares a draft only. The next Save performs a fresh
            # CAS against this reviewed version; there is no automatic save/retry.
            data = form.data.copy()
            data['version'] = str(record.version)
            form.data = data
            form._errors = None
            context['merge_ready'] = True
    context.update(conflict_rows=_rows(form, record), current_version=record.version,
                   submitted_version=editor['loaded_version'], can_merge=can_merge,
                   merge_token=signing.dumps(token_values, salt=SALT) if can_merge else '',
                   current_label=str(record), editor=editor, sensitive_conflict=sensitive)
    # POST-only actions need a safe GET destination for the comparison link.
    match = request.resolver_match
    if match.namespace == 'accounts' and match.url_name == 'user_status':
        context['reload_url'] = reverse('accounts:users')
    elif match.namespace == 'engagements' and match.url_name in {'member_change', 'member_revoke'}:
        context['reload_url'] = reverse('engagements:members', args=[editor['engagement'].pk])
    elif match.namespace == 'engagements' and match.url_name == 'milestone_complete':
        context['reload_url'] = reverse('engagements:detail', args=[editor['engagement'].pk])
    return context
