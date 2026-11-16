"""Collect ORM data in a bounded, read-only SQLite snapshot; never render under a write lock."""
import base64
from contextlib import contextmanager
from copy import deepcopy
import json
from collections import Counter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from apps.core.exceptions import EditConflict
from apps.engagements.models import Engagement
from apps.engagements.permissions import Permission, get_engagement
from apps.evidence import storage as evidence_storage
from apps.evidence.validation import verify_stream, image_thumbnail
from apps.findings.models import Severity
from .models import Report, validate_sections

NARRATIVES = ['description', 'technical_details', 'impact', 'reproduction_steps', 'remediation', 'references']


def canonical_json(data):
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@contextmanager
def read_snapshot():
    alias = 'trace_report_snapshot'
    if hasattr(connections._connections, alias):
        raise RuntimeError('Nested report snapshots are not supported.')
    wrapper = connections['default'].copy(alias=alias)
    wrapper.settings_dict = deepcopy(wrapper.settings_dict)
    if wrapper.vendor == 'sqlite':
        wrapper.settings_dict['OPTIONS']['transaction_mode'] = 'DEFERRED'
    connections[alias] = wrapper
    try:
        with wrapper.cursor() as cursor:
            if wrapper.vendor == 'sqlite': cursor.execute('PRAGMA query_only = ON')
        with transaction.atomic(using=alias):
            if wrapper.vendor == 'postgresql':
                with wrapper.cursor() as cursor: cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            yield alias
    finally:
        wrapper.close()
        del connections[alias]


def _bounded(queryset, limit, label):
    rows = list(queryset[:limit + 1])
    if len(rows) > limit:
        raise ValidationError(f'Too many {label} for a single report. Narrow the selection or raise the reviewed export limits.')
    return rows


def collect_snapshot(*, actor, engagement_id, report_id, revision):
    get_engagement(actor, engagement_id, Permission.GENERATE_REPORTS)
    with read_snapshot() as alias:
        # Every ORM query in this block uses the same read transaction/connection.
        engagement = get_object_or_404(Engagement.objects.using(alias), pk=engagement_id)
        report = get_object_or_404(Report.objects.using(alias), pk=report_id, engagement_id=engagement_id)
        if report.version != revision.report_version:
            raise EditConflict(current=report)
        template = deepcopy(report.template_snapshot)
        validate_sections(template['sections'])
        if template.get('palette') not in {'blue', 'graphite', 'aubergine'}:
            raise ValidationError('Invalid report palette.')
        links = _bounded(report.finding_links.using(alias).select_related('finding').order_by('position', 'id'), settings.TRACE_REPORT_MAX_FINDINGS, 'findings')
        if any(link.finding.engagement_id != engagement.pk for link in links):
            raise ValidationError('A report relationship is outside this engagement.')
        selected = [link.finding for link in links]
        cases = _bounded(engagement.test_cases.using(alias).order_by('title', 'id'), settings.TRACE_REPORT_MAX_TESTS, 'test cases')
        finding_ids = [f.pk for f in selected]
        related_case_ids = set()
        findings = []
        for finding in selected:
            linked_cases = list(finding.test_cases.using(alias).filter(engagement_id=engagement.pk).order_by('id').values_list('pk', flat=True))
            related_case_ids.update(linked_cases)
            findings.append(dict(id=str(finding.pk), version=finding.version, title=finding.title, severity=finding.severity,
                status=finding.get_status_display(), cvss_vector=finding.cvss_vector, cvss_score=str(finding.cvss_score) if finding.cvss_score is not None else '',
                assets=list(finding.assets.using(alias).filter(engagement_id=engagement.pk).order_by('name','id').values('name','hostname','ip_cidr','url')),
                test_cases=[str(v) for v in linked_cases], **{field:getattr(finding,field) for field in NARRATIVES}))
        evidence = _bounded(engagement.evidence.using(alias).filter(deleted_at__isnull=True).filter(
            Q(finding_links__finding_id__in=finding_ids) | Q(test_case_links__test_case_id__in=related_case_ids) |
            Q(pk__in=report.additional_evidence.using(alias).filter(engagement_id=engagement.pk).values('pk'))).distinct().order_by('created_at','id'), settings.TRACE_REPORT_MAX_EVIDENCE, 'evidence references')
        evidence_rows = [dict(id=str(e.pk), version=e.version, filename=e.original_filename, description=e.description, kind=e.kind,
            sha256=e.sha256, size=e.size, thumbnail_key=e.thumbnail_key, thumbnail_size=e.thumbnail_size, thumbnail_sha256=e.thumbnail_sha256) for e in evidence]
        logo = None
        if report.logo_id:
            logo_record = engagement.evidence.using(alias).filter(deleted_at__isnull=True, kind__in=['png','jpeg'],pk=report.logo_id).first()
            if logo_record is None:
                raise ValidationError('The selected logo is unavailable. Update the report setup before generating.')
            logo = dict(id=str(logo_record.pk), thumbnail_key=logo_record.thumbnail_key, thumbnail_size=logo_record.thumbnail_size, thumbnail_sha256=logo_record.thumbnail_sha256)
        counts = Counter(f['severity'] for f in findings)
        summary = [{'severity': severity, 'label': label, 'count': counts[severity]} for severity, label in Severity.choices]
        tests = [dict(id=str(c.pk), version=c.version, title=c.title, category=c.category, status=c.get_status_display(), methodology=c.methodology, actual_result=c.actual_result) for c in cases]
        test_counts = dict(sorted(Counter(c['status'] for c in tests).items()))
        executive = report.executive_summary or f'This assessment records {len(tests)} test cases and {len(findings)} selected findings. ' + '; '.join(f"{r['label']}: {r['count']}" for r in summary) + '.'
        result = dict(schema_version=1, engagement=dict(id=str(engagement.pk), version=engagement.version, name=engagement.name,
            client=engagement.client, scope=engagement.scope_summary, objectives=engagement.objectives, description=engagement.description,
            start_date=str(engagement.start_date or ''), end_date=str(engagement.end_date or ''), status=engagement.get_status_display()),
            report=dict(id=str(report.pk), version=report.version, title=report.title, executive_summary=executive,
                methodology=report.methodology, recommendations=report.recommendations, header=report.header, footer=report.footer,
                marking=report.marking, template=template, source_template=str(report.source_template_id or ''), source_template_version=report.source_template_version),
            revision=dict(id=str(revision.pk), number=revision.number, generated_at=revision.created_at.isoformat(), generated_by=actor.get_username()),
            findings=findings, severity_summary=summary, tests=tests, test_counts=test_counts,
            evidence=evidence_rows, logo=logo, include_images=report.include_images)
    if len(canonical_json(result)) > settings.TRACE_REPORT_MAX_SNAPSHOT_BYTES:
        raise ValidationError('Report text exceeds the configured snapshot limit.')
    return result


def materialize_images(*, actor, engagement_id, snapshot):
    """Copy immutable, verified PNG pixels outside all database transactions."""
    if not snapshot['include_images'] and not snapshot['logo']:
        targets = []
    else:
        get_engagement(actor, engagement_id, Permission.DOWNLOAD_EVIDENCE)
        targets = ([snapshot['logo']] if snapshot['logo'] else []) + (snapshot['evidence'] if snapshot['include_images'] else [])
    image_count, total = 0, 0
    for item in targets:
        if not item.get('thumbnail_key'):
            continue
        image_count += 1
        if image_count > settings.TRACE_REPORT_MAX_IMAGES or item['thumbnail_size'] > 2 * 1024 * 1024:
            raise ValidationError('Report image count or size limit exceeded.')
        with evidence_storage.open_file(engagement_id, item['thumbnail_key']) as file:
            if not verify_stream(file, size=item['thumbnail_size'], digest=item['thumbnail_sha256']):
                raise ValidationError('Evidence image failed integrity verification.')
            _, pixels = image_thumbnail(file)
        total += len(pixels)
        if total > settings.TRACE_REPORT_MAX_IMAGE_BYTES:
            raise ValidationError('Report images exceed the configured aggregate limit.')
        item['image'] = 'data:image/png;base64,' + base64.b64encode(pixels).decode('ascii')
    # Private storage keys are processing inputs, never report/snapshot outputs.
    for item in snapshot['evidence'] + ([snapshot['logo']] if snapshot['logo'] else []):
        for name in ['thumbnail_key', 'thumbnail_size', 'thumbnail_sha256']:
            item.pop(name, None)
    if len(canonical_json(snapshot)) > settings.TRACE_REPORT_MAX_SNAPSHOT_BYTES:
        raise ValidationError('Report snapshot exceeds the configured text/image limit.')
    return snapshot
