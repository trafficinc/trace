from apps.core.http import render_page as render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers
from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from apps.engagements.permissions import get_engagement, Permission as P, has_permission
from .forms import UploadEvidenceForm, EditEvidenceForm, VersionForm, FIELDS
from . import services, storage, quotas
from .validation import TYPES

ERRORS = (ValidationError, EditConflict, IntegrityError, OperationalError)


@login_required
@require_GET
@vary_on_headers('HX-Request')
def evidence_list(request, engagement_id):
    engagement = get_engagement(request.user, engagement_id, P.DOWNLOAD_EVIDENCE)
    records = engagement.evidence.filter(deleted_at__isnull=True).select_related('uploader')
    query=request.GET.get('q','').strip()[:200]
    if query: records=records.filter(Q(original_filename__icontains=query)|Q(description__icontains=query))
    kind=request.GET.get('kind','')
    if kind in TYPES: records=records.filter(kind=kind)
    sort=request.GET.get('sort','-created_at')
    if sort not in {'original_filename','-created_at','size','-size'}: sort='-created_at'
    records=records.order_by(sort,'pk')
    return render(request, 'components/evidence_results.html'  if request.headers.get('HX-Request') == 'true' else 'pages/evidence_list.html',
                  {'engagement': engagement, 'page': Paginator(records, 20).get_page(request.GET.get('page')),
                   'query': query, 'kind': kind, 'sort': sort, 'kinds': sorted(TYPES),
                   'quota_usage': quotas.usage(actor=request.user, engagement_id=engagement.pk),
                   'can_manage_quota': services.has_permission(request.user, engagement.pk, P.VIEW) and request.user.is_active and request.user.is_superuser,
                   'can_upload': not engagement.is_read_only and has_permission(request.user, engagement.pk, P.ATTACH_EVIDENCE)})


@login_required
@require_http_methods(['GET', 'POST'])
def evidence_detail(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id, P.DOWNLOAD_EVIDENCE)
    evidence = get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True).select_related('uploader'), pk=pk)
    status = 200
    if request.method == 'POST':
        try:
            result = services.verify_evidence(actor=request.user, engagement_id=engagement_id, evidence_id=pk)
        except ERRORS:
            messages.error(request, 'Integrity verification could not be completed.')
            status = 503
        else:
            if result == 'verified':
                messages.success(request, 'Integrity verified for the original file and any thumbnail.')
            else:
                messages.error(request, 'Integrity verification failed: file mismatch or unavailable private storage.')
            return saved_redirect(request, reverse('evidence:detail', args=[engagement_id, pk]))
    return render(request, 'pages/evidence_detail.html', {'engagement': engagement, 'evidence': evidence,
                  'can_manage': not engagement.is_read_only and services.can_manage(request.user, evidence)}, status=status)


@login_required
@require_http_methods(['GET', 'POST'])
def evidence_upload(request, engagement_id):
    engagement = get_engagement(request.user, engagement_id, P.ATTACH_EVIDENCE)
    if request.method == 'GET' and engagement.is_read_only:
        raise PermissionDenied('This engagement is read-only.')
    form = UploadEvidenceForm(request.POST if request.method == 'POST' else None,
                              request.FILES if request.method == 'POST' else None, engagement=engagement)
    status = 200
    if request.method == 'POST':
        error = getattr(request, 'evidence_upload_error', None)
        if error:
            form.is_valid()
            form.add_error(None, error)
            status = getattr(request, 'evidence_upload_status', 413)
        elif form.is_valid() and not request.POST.get('_prepare_merge'):
            try:
                saved = services.upload_evidence(actor=request.user, engagement_id=engagement_id, upload=form.cleaned_data['file'],
                                                  data={name: form.cleaned_data[name] for name in FIELDS})
            except quotas.CapacityError as exc:
                form.add_error(None, exc.messages[0])
                status = exc.status
            except ERRORS as exc:
                status = mutation_error(form, exc)
            except (OSError, storage.StorageError):
                form.add_error(None, 'Evidence could not be stored. Check private storage and select the file again.')
                status = 503
            else:
                return saved_redirect(request, reverse('evidence:detail', args=[engagement_id, saved.pk]), message='Evidence uploaded.')
    return render(request, 'pages/evidence_editor.html', {'engagement': engagement, 'form': form, 'title': 'Upload evidence', 'uploading': True,
        'quota_usage': quotas.usage(actor=request.user, engagement_id=engagement.pk)}, status=status)


@login_required
@require_http_methods(['GET', 'POST'])
def evidence_edit(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id, P.ATTACH_EVIDENCE)
    evidence = get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True), pk=pk)
    if not services.can_manage(request.user, evidence) or request.method == 'GET' and engagement.is_read_only:
        raise PermissionDenied('You cannot edit this evidence.')
    form = EditEvidenceForm(request.POST if request.method == 'POST' else None, instance=evidence,
                            engagement=engagement, initial={'version': evidence.version})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.update_evidence(actor=request.user, engagement_id=engagement_id, evidence_id=pk,
                                     version=form.cleaned_data['version'], data={name: form.cleaned_data[name] for name in FIELDS})
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('evidence:detail', args=[engagement_id, pk]), message='Changes saved.')
    return render(request, 'pages/evidence_editor.html', {'engagement': engagement, 'form': form, 'title': 'Edit evidence description and links'}, status=status)


@login_required
@require_http_methods(['GET', 'POST'])
def evidence_remove(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id, P.ATTACH_EVIDENCE)
    evidence = get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True), pk=pk)
    if not services.can_manage(request.user, evidence) or request.method == 'GET' and engagement.is_read_only:
        raise PermissionDenied('You cannot remove this evidence.')
    form = VersionForm(request.POST if request.method == 'POST' else None, initial={'version': evidence.version})
    status = 200
    if request.method == 'POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.remove_evidence(actor=request.user, engagement_id=engagement_id, evidence_id=pk, version=form.cleaned_data['version'])
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse('evidence:list', args=[engagement_id]), message='Record removed.')
    return render(request, 'pages/evidence_remove.html', {'engagement': engagement, 'evidence': evidence, 'form': form}, status=status)


@login_required
@require_GET
def evidence_download(request, engagement_id, pk, thumbnail=False):
    try:
        evidence, file = services.open_download(actor=request.user, engagement_id=engagement_id, evidence_id=pk, thumbnail=thumbnail)
    except (OSError, storage.StorageError):
        return render(request, 'pages/action_error.html', {'title': 'Evidence unavailable', 'message': 'The private file is unavailable or failed its integrity check.'}, status=409)
    except (IntegrityError, OperationalError):
        return render(request, 'pages/action_error.html', {'title': 'Evidence unavailable'}, status=503)
    filename = f'evidence-{evidence.pk}.{TYPES[evidence.kind][1]}'
    response = FileResponse(file, as_attachment=not thumbnail, filename='thumbnail.png' if thumbnail else filename,
                            content_type='image/png' if thumbnail else 'application/octet-stream')
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    response['Cache-Control'] = 'no-store, private'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
@vary_on_headers('HX-Request')
def quota_policy(request, engagement_id):
    from apps.engagements.permissions import require_system_admin
    from .forms import QuotaForm
    from .models import EvidenceQuota
    from . import quotas
    require_system_admin(request.user)
    engagement = get_engagement(request.user, engagement_id)
    current = EvidenceQuota.objects.filter(engagement=engagement).first()
    form = QuotaForm(request.POST if request.method == 'POST' else None,
                     initial={'limit_bytes': current.limit_bytes if current else None, 'version': current.version if current else 0})
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            quotas.set_quota(actor=request.user, engagement_id=engagement.pk,
                             limit_bytes=form.cleaned_data['limit_bytes'], version=form.cleaned_data['version'])
        except ERRORS as error:
            status = mutation_error(form, error)
            current = EvidenceQuota.objects.filter(engagement=engagement).first()
        else:
            return saved_redirect(request, reverse('evidence:quota', args=[engagement.pk]), message='Evidence quota saved.')
    from django.shortcuts import render as render_template
    return render_template(request, 'pages/evidence_quota.html', {'engagement': engagement, 'form': form, 'conflict': status == 409,
        'current_policy': current, 'current_version': current.version if current else 0,
        'quota_usage': quotas.usage(actor=request.user, engagement_id=engagement.pk)}, status=status)
