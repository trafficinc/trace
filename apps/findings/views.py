from apps.core.http import render_page as render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Case, When, IntegerField, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers
from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from apps.engagements.permissions import Permission as P, get_engagement, has_permission, is_system_admin, require_system_admin, visible_engagements
from .models import FindingTemplate, FindingStatus as S, Severity
from .forms import FindingForm, EditFindingForm, TemplateForm, EditTemplateForm, TransitionForm, CopyTemplateForm, FINDING_FIELDS, TEMPLATE_FIELDS, NARRATIVES
from .formatting import render_narrative
from . import services

ERRORS = (ValidationError, EditConflict, IntegrityError, OperationalError)


def narratives(record):
    return [(record._meta.get_field(f).verbose_name.capitalize(), render_narrative(getattr(record, f))) for f in NARRATIVES]


@login_required
@require_GET
@vary_on_headers('HX-Request')
def finding_list(request, engagement_id):
    engagement = get_engagement(request.user, engagement_id)
    records = engagement.findings.select_related('author', 'reviewer')
    if request.GET.get('open') == '1':
        from apps.core.dashboards import OPEN_FINDINGS
        records = records.filter(status__in=OPEN_FINDINGS)
    query = request.GET.get('q', '')[:200]
    if query:
        records = records.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(technical_details__icontains=query))
    for field, choices in [('severity', Severity.values), ('status', S.values)]:
        if request.GET.get(field) in choices:
            records = records.filter(**{field: request.GET[field]})
    sort = request.GET.get('sort', '-updated_at')
    if sort not in {'title', '-title', 'severity', 'status', '-updated_at', 'created_at'}:
        sort = '-updated_at'
    records = records.annotate(severity_rank=Case(*[When(severity=v, then=i) for i, v in enumerate(Severity.values)], output_field=IntegerField()))
    records = records.order_by('severity_rank' if sort == 'severity' else sort, 'id')
    context = dict(engagement=engagement, page=Paginator(records, 20).get_page(request.GET.get('page')), query=query, sort=sort,
                   severities=Severity.choices, statuses=S.choices, can_write=not engagement.is_read_only and has_permission(request.user, engagement_id, P.WRITE_FINDINGS))
    return render(request, 'components/finding_results.html' if request.headers.get('HX-Request') == 'true' else 'pages/finding_list.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def finding_detail(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id)
    finding = get_object_or_404(engagement.findings.select_related('author', 'reviewer'), pk=pk)
    targets = []
    if not engagement.is_read_only:
        for target in services.TRANSITIONS.get(finding.status, set()):
            permission = P.WRITE_FINDINGS if target == S.UNDER_REVIEW else P.REVIEW_FINDINGS
            if has_permission(request.user, engagement_id, permission) and not (target in {S.CONFIRMED, S.REMEDIATED, S.ACCEPTED_RISK} and request.user.pk == finding.author_id):
                targets.append((target, S(target).label))
    form = TransitionForm(request.POST if request.method == 'POST' else None, initial={'version': finding.version})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.transition_finding(actor=request.user, engagement_id=engagement_id, finding_id=pk, **form.cleaned_data)
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('findings:detail', args=[engagement_id, pk]), message='Finding status updated.')
    form.fields['target'].choices = targets
    return render(request, 'pages/finding_detail.html', dict(engagement=engagement, finding=finding, narratives=narratives(finding), form=form, targets=targets, related_evidence=finding.evidence.filter(deleted_at__isnull=True, engagement=engagement),
                  can_write=not engagement.is_read_only and finding.status == S.DRAFT and has_permission(request.user, engagement_id, P.WRITE_FINDINGS)), status=status)


@login_required
@require_http_methods(['GET', 'POST'])
@vary_on_headers('HX-Request')
def finding_edit(request, engagement_id, pk=None):
    engagement = get_engagement(request.user, engagement_id, P.WRITE_FINDINGS)
    finding = get_object_or_404(engagement.findings, pk=pk) if pk else None
    if request.method == 'GET' and (engagement.is_read_only or finding and finding.status != S.DRAFT):
        raise PermissionDenied('Only writable drafts can be edited.')
    cls = EditFindingForm if finding else FindingForm
    form = cls(request.POST if request.method == 'POST' else None, instance=finding, engagement=engagement, initial={'version': finding.version} if finding else {})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.save_finding(actor=request.user, engagement_id=engagement_id, finding_id=pk, version=form.cleaned_data.get('version'), data={f: form.cleaned_data[f] for f in FINDING_FIELDS})
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('findings:detail', args=[engagement_id, saved.pk]), message='Changes saved.')
    return render(request, 'components/engagement_editor.html' if request.headers.get('HX-Request') == 'true' else 'pages/engagement_editor.html', dict(engagement=engagement, form=form, title='Edit finding' if pk else 'New finding', enhance_htmx=True), status=status)


@login_required
@require_GET
def template_list(request):
    records = FindingTemplate.objects.all() if is_system_admin(request.user) else FindingTemplate.objects.filter(is_active=True)
    query = request.GET.get('q', '')[:200]
    records = records.filter(Q(title__icontains=query) | Q(description__icontains=query)) if query else records
    return render(request, 'pages/finding_template_list.html', {'page': Paginator(records, 20).get_page(request.GET.get('page')), 'query': query, 'can_manage': is_system_admin(request.user)})


@login_required
@require_http_methods(['GET', 'POST'])
def template_edit(request, pk=None):
    require_system_admin(request.user)
    template = get_object_or_404(FindingTemplate, pk=pk) if pk else None
    cls = EditTemplateForm if template else TemplateForm
    form = cls(request.POST if request.method == 'POST' else None, instance=template, initial={'version': template.version} if template else {})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.save_template(actor=request.user, template_id=pk, version=form.cleaned_data.get('version'), data={f: form.cleaned_data[f] for f in TEMPLATE_FIELDS})
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('finding_templates:detail', args=[saved.pk]), message='Changes saved.')
    return render(request, 'pages/engagement_editor.html', {'form': form, 'title': 'Finding template'}, status=status)


@login_required
@require_GET
def template_detail(request, pk):
    records = FindingTemplate.objects.all() if is_system_admin(request.user) else FindingTemplate.objects.filter(is_active=True)
    template = get_object_or_404(records, pk=pk)
    return render(request, 'pages/finding_template_detail.html', {'record': template, 'narratives': narratives(template), 'can_manage': is_system_admin(request.user), 'destinations': [e for e in visible_engagements(request.user) if not e.is_read_only and has_permission(request.user, e.pk, P.WRITE_FINDINGS)]})


@login_required
@require_http_methods(['GET', 'POST'])
def template_copy(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id, P.WRITE_FINDINGS)
    template = get_object_or_404(FindingTemplate.objects.filter(is_active=True), pk=pk)
    form = CopyTemplateForm(request.POST if request.method == 'POST' else None, initial={'version': template.version})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.copy_template(actor=request.user, engagement_id=engagement_id, template_id=pk, version=form.cleaned_data['version'])
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('findings:edit', args=[engagement_id, saved.pk]), message='Changes saved.')
    return render(request, 'pages/engagement_editor.html', {'engagement': engagement, 'form': form, 'title': 'Create finding from ' + template.title}, status=status)
