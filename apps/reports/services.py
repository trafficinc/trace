from copy import deepcopy
import hashlib
from importlib.metadata import version as package_version
import logging
import os
import time
import uuid
from django.core.exceptions import ValidationError
from django.db import connection, transaction, DatabaseError
from django.db.models import Max
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.services import record_event
from apps.core.concurrency import cas_update
from apps.core.exceptions import EditConflict
from apps.engagements.permissions import Permission as P, get_engagement, get_writable_engagement, require_system_admin
from .forms import ReportForm, TemplateForm, REPORT_FIELDS, TEMPLATE_FIELDS
from .models import ReportTemplate, ReportFinding, ReportEvidence, ReportRevision, ReportArtifact, default_sections, validate_sections
from .snapshots import collect_snapshot, materialize_images, canonical_json
from .rendering import render_all, RenderError
from . import storage
from apps.evidence.validation import verify_stream

logger=logging.getLogger('trace.reports')


def _outside():
    if connection.in_atomic_block:
        raise RuntimeError('Report generation/file operations must run outside write transactions.')


def _event(action, actor, engagement, subject, before=None, **metadata):
    record_event(action=action,actor=actor,engagement=engagement,subject_id=subject,metadata=metadata,before=before)


@transaction.atomic
def save_template(*, actor, data, template_id=None, version=None):
    before = None
    require_system_admin(actor)
    if set(data)-set(TEMPLATE_FIELDS): raise ValidationError('Unrecognized template fields.')
    current=get_object_or_404(ReportTemplate,pk=template_id) if template_id else None
    values=dict(data)
    if isinstance(values.get('sections'),list):
        validate_sections(values['sections'])
        values['sections']='\n'.join(values['sections'])
    form=TemplateForm(values,instance=current)
    if not form.is_valid(): raise ValidationError(form.errors.as_data())
    result=form.save(commit=False)
    if current is None:
        result.created_by=actor; result.save()
    else:
        before = cas_update(ReportTemplate.objects.filter(pk=current.pk),version=version,
            **{f:getattr(result,f) for f in TEMPLATE_FIELDS},updated_at=timezone.now())
        result.refresh_from_db()
    record_event(action='report_template.saved',actor=actor,subject_id=result.pk,metadata={'version':result.version}, before=before)
    return result


@transaction.atomic
def save_report(*, actor, engagement_id, data, finding_ids, report_id=None, version=None, template_id=None, template_version=None, evidence_ids=None):
    before = None
    engagement=get_writable_engagement(actor,engagement_id,P.GENERATE_REPORTS)
    if set(data)-set(REPORT_FIELDS): raise ValidationError('Unrecognized report fields.')
    current=get_object_or_404(engagement.reports,pk=report_id) if report_id else None
    if evidence_ids is None:
        evidence_ids = list(current.additional_evidence.values_list('pk', flat=True)) if current else []
    try: evidence_ids = [uuid.UUID(str(pk)) for pk in evidence_ids]
    except (ValueError, TypeError) as exc: raise ValidationError('Invalid evidence selection.') from exc
    if len(evidence_ids) != len(set(evidence_ids)) or len(evidence_ids) > 500:
        raise ValidationError('Choose each evidence item once, with at most 500 selections.')
    form=ReportForm({**data, 'additional_evidence': evidence_ids},instance=current,engagement=engagement)
    if not form.is_valid(): raise ValidationError(form.errors.as_data())
    try: ids=[uuid.UUID(str(pk)) for pk in finding_ids]
    except (ValueError,TypeError) as exc: raise ValidationError('Invalid finding selection.') from exc
    if len(ids)!=len(set(ids)) or len(ids)>500: raise ValidationError('Choose each finding once, with at most 500 selections.')
    if engagement.findings.filter(pk__in=ids).count()!=len(ids): raise ValidationError('Findings must belong to this engagement.')
    result=form.save(commit=False)
    if current is None:
        result.created_by=actor
        if template_id:
            template=get_object_or_404(ReportTemplate.objects.filter(is_active=True),pk=template_id)
            if template.version!=template_version: raise EditConflict(current=template)
            result.source_template=template; result.source_template_version=template.version
            result.template_snapshot={'name':template.name,'palette':template.palette,'sections':deepcopy(template.sections)}
        else:
            result.template_snapshot={'name':'Standard','palette':'blue','sections':default_sections()}
        result.save()
    else:
        if template_id is not None: raise ValidationError('Existing reports retain their copied template. Create a new report to use another template.')
        before = cas_update(engagement.reports.filter(pk=current.pk),version=version,
            **{f:getattr(result,f) for f in REPORT_FIELDS},updated_at=timezone.now())
        result.refresh_from_db()
    result.finding_links.all().delete()
    ReportFinding.objects.bulk_create([ReportFinding(report=result,finding_id=pk,position=i+1) for i,pk in enumerate(ids)])
    result.evidence_links.all().delete()
    ReportEvidence.objects.bulk_create([ReportEvidence(report=result,evidence_id=pk) for pk in evidence_ids])
    _event('report.saved',actor,engagement,result.pk,version=result.version, before=before)
    return result


@transaction.atomic
def _reserve(*, actor, engagement_id, report_id, version, renderer_versions=None):
    # Exporting is a derived read operation, including on closed engagements.
    # Setup/content mutations still use get_writable_engagement above.
    engagement=get_engagement(actor,engagement_id,P.GENERATE_REPORTS,for_update=True)
    report=get_object_or_404(engagement.reports,pk=report_id)
    if report.version!=version: raise EditConflict(current=report)
    number=(report.revisions.aggregate(number=Max('number'))['number'] or 0)+1
    revision=ReportRevision.objects.create(engagement=engagement,report=report,number=number,report_version=version,generated_by=actor,
        renderer_versions=renderer_versions or {'schema':1})
    _event('report.started',actor,engagement,revision.pk,version=revision.version,status='rendering')
    return revision


def _failed(revision, actor, code):
    before = None
    try:
        with transaction.atomic():
            # Internal failure cleanup changes only this already-authorized pending
            # job, even after revocation. It cannot publish files or change sources.
            scoped=ReportRevision.objects.filter(pk=revision.pk,engagement_id=revision.engagement_id,status='rendering')
            before = cas_update(scoped,version=1,status='failed',failure_code=code,completed_at=timezone.now())
            _event('report.failed',actor,revision.engagement,revision.pk,version=2,status='failed', before=before)
    except (DatabaseError,EditConflict,Http404): logger.warning('report_cleanup_deferred')


def _remove(engagement_id, keys):
    for key in keys:
        try: storage.remove_file(engagement_id,key)
        except (OSError,storage.StorageError): logger.warning('report_cleanup_deferred')


def generate_report(*, actor, engagement_id, report_id, version):
    _outside()
    get_engagement(actor, engagement_id, P.GENERATE_REPORTS)
    from .capacity import render_slot
    with render_slot():
        return _generate_report(actor=actor, engagement_id=engagement_id, report_id=report_id, version=version)


def _generate_report(*, actor, engagement_id, report_id, version):
    before = None
    _outside()
    versions={'schema':1,'report_engine':'1','python-docx':package_version('python-docx'),'WeasyPrint':package_version('WeasyPrint'),'Pillow':package_version('Pillow')}
    revision=_reserve(actor=actor,engagement_id=engagement_id,report_id=report_id,version=version,renderer_versions=versions)
    files, handles, published=[],[],False
    try:
        snapshot=collect_snapshot(actor=actor,engagement_id=engagement_id,report_id=report_id,revision=revision)
        snapshot=materialize_images(actor=actor,engagement_id=engagement_id,snapshot=snapshot)
        payloads=render_all(snapshot)
        payloads['snapshot']=canonical_json(snapshot)
        from django.conf import settings
        for kind,payload in payloads.items():
            if not payload or len(payload)>settings.TRACE_REPORT_MAX_ARTIFACT_BYTES: raise RenderError('Report artifact exceeds the configured size limit.')
            key,file=storage.create_file(engagement_id); handles.append(file)
            files.append(dict(format=kind,storage_key=key,sha256=hashlib.sha256(payload).hexdigest(),size=len(payload)))
            file.write(payload); storage.sync_file(file,engagement_id)
        with transaction.atomic():
            engagement=get_engagement(actor,engagement_id,P.GENERATE_REPORTS,for_update=True)
            get_object_or_404(engagement.reports,pk=report_id)
            before = cas_update(engagement.report_revisions.filter(pk=revision.pk,report_id=report_id,status='rendering'),version=1,
                status='ready',completed_at=timezone.now())
            ReportArtifact.objects.bulk_create([ReportArtifact(revision=revision,engagement=engagement,**values) for values in files])
            _event('report.ready',actor,engagement,revision.pk,version=2,status='ready', before=before)
        published=True
        revision.refresh_from_db()
        return revision
    except Exception:
        _failed(revision,actor,'generation_failed')
        raise
    finally:
        for file in handles:
            try: file.close()
            except OSError: logger.warning('report_cleanup_deferred')
        if not published and files:
            try:
                referenced=set(ReportArtifact.objects.filter(storage_key__in=[f['storage_key'] for f in files]).values_list('storage_key',flat=True))
            except DatabaseError: logger.warning('report_cleanup_deferred')
            else: _remove(engagement_id,[f['storage_key'] for f in files if f['storage_key'] not in referenced])


def open_artifact(*, actor, engagement_id, revision_id, format):
    _outside()
    if format not in {'html','pdf','docx'}: raise Http404
    engagement=get_engagement(actor,engagement_id,P.GENERATE_REPORTS)
    artifact=get_object_or_404(ReportArtifact.objects.filter(engagement=engagement,revision__engagement=engagement,revision__status='ready'),revision_id=revision_id,format=format)
    file=storage.open_file(engagement_id,artifact.storage_key)
    try:
        if not verify_stream(file,size=artifact.size,digest=artifact.sha256): raise storage.StorageError('Report integrity check failed.')
        with transaction.atomic():
            engagement=get_engagement(actor,engagement_id,P.GENERATE_REPORTS,for_update=True)
            _event('report.downloaded',actor,engagement,revision_id,version=artifact.revision.version)
        return artifact,file
    except BaseException:
        file.close(); raise


def cleanup_orphans(*, older_than_seconds=86400):
    _outside()
    if older_than_seconds<3600: raise ValidationError('Use an orphan grace period of at least one hour.')
    removed=deferred=0
    with storage.root_directory() as root:
        for name in os.listdir(root):
            if name.startswith('.render-slot-'):
                continue
            try:
                engagement_id=uuid.UUID(hex=name)
                if engagement_id.hex!=name: continue
                with storage.engagement_directory(engagement_id) as directory: keys=os.listdir(directory)
                for key in keys:
                    try:
                        with storage.open_file(engagement_id,key,exclusive=True) as file:
                            if os.fstat(file.fileno()).st_mtime>time.time()-older_than_seconds: continue
                            if ReportArtifact.objects.filter(engagement_id=engagement_id,storage_key=key).exists(): continue
                            with storage.engagement_directory(engagement_id) as directory:
                                info=os.stat(key,dir_fd=directory,follow_symlinks=False)
                                if info.st_ino!=os.fstat(file.fileno()).st_ino: raise storage.StorageError('Report file changed.')
                                os.unlink(key,dir_fd=directory); os.fsync(directory)
                            removed+=1
                    except (OSError,storage.StorageError): deferred+=1
            except (ValueError,OSError,storage.StorageError): deferred+=1
    return removed,deferred
