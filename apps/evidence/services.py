import hashlib
import logging
import os
import time
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.services import record_event
from apps.core.concurrency import cas_update
from apps.engagements.permissions import Permission as P, get_engagement, get_writable_engagement, has_permission
from .forms import EvidenceForm, FIELDS
from .models import Evidence, EvidenceTestCase, EvidenceFinding
from . import storage, quotas
from .validation import copy_upload, classify, safe_filename, TYPES, verify_stream

logger = logging.getLogger('trace.evidence')


def _outside_transaction():
    if connection.in_atomic_block:
        raise RuntimeError('Evidence file operations must run outside database transactions.')


def _form(data, *, engagement, instance=None):
    if set(data) - set(FIELDS):
        raise ValidationError('Unrecognized evidence fields.')
    form = EvidenceForm(data, engagement=engagement, instance=instance)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    return form


def can_manage(actor, evidence):
    return has_permission(actor, evidence.engagement_id, P.ATTACH_EVIDENCE) and (
        evidence.uploader_id == actor.pk or has_permission(actor, evidence.engagement_id, P.EDIT_ENGAGEMENT))


def _authority(actor, evidence):
    if not can_manage(actor, evidence):
        raise PermissionDenied('Only the uploader, a Lead or a System Admin can manage this evidence.')


def _links(evidence, values):
    evidence.test_case_links.all().delete()
    evidence.finding_links.all().delete()
    EvidenceTestCase.objects.bulk_create([EvidenceTestCase(evidence=evidence, test_case=case) for case in values['test_cases']])
    EvidenceFinding.objects.bulk_create([EvidenceFinding(evidence=evidence, finding=finding) for finding in values['findings']])


def _event(action, actor, evidence, before=None, **metadata):
    record_event(action=action, actor=actor, engagement=evidence.engagement, subject_id=evidence.pk,
                 metadata={'version': evidence.version, **metadata}, before=before)


def _cleanup(engagement_id, keys):
    for key in keys:
        if key:
            try:
                try:
                    storage.remove_file(engagement_id, key)
                except FileNotFoundError:
                    pass
                quotas.record_removed(engagement_id, key)
            except (OSError, storage.StorageError):
                # Tombstones and the operator sweep make cleanup retryable after failure.
                logger.warning('evidence_cleanup_deferred')


def upload_evidence(*, actor, engagement_id, upload, data):
    _outside_transaction()
    engagement = get_engagement(actor, engagement_id, P.ATTACH_EVIDENCE)
    if engagement.is_read_only:
        raise ValidationError('Completed and archived engagements are read-only.')
    _form(data, engagement=engagement)
    staged = getattr(upload, "reservation", None)
    if staged is not None and (not isinstance(staged, quotas.Reservation) or staged.actor.pk != actor.pk or staged.engagement_id != engagement.pk or staged.closed):
        raise ValidationError("Upload allocation is outside this engagement.")
    reservation = staged or quotas.begin(actor=actor, engagement_id=engagement.pk)
    keys, handles, committed = [], [], False
    try:
        key, file = storage.create_file(engagement.pk)
        keys.append(key)
        handles.append(file)
        reservation.attach("original_key", key)
        size, digest = copy_upload(upload, file, before_write=reservation.reserve)
        kind, thumbnail = classify(file, size)
        storage.sync_file(file, engagement.pk)
        thumbnail_key, thumbnail_size, thumbnail_digest = '', 0, ''
        if thumbnail is not None:
            reservation.reserve(size, len(thumbnail))
            thumbnail_key, preview = storage.create_file(engagement.pk)
            keys.append(thumbnail_key)
            handles.append(preview)
            reservation.attach("thumbnail_key", thumbnail_key)
            preview.write(thumbnail)
            storage.sync_file(preview, engagement.pk)
            thumbnail_size, thumbnail_digest = len(thumbnail), hashlib.sha256(thumbnail).hexdigest()
        # All file work is complete; reserve SQLite's writer lock only for metadata.
        with reservation.publication():
            engagement = get_writable_engagement(actor, engagement_id, P.ATTACH_EVIDENCE)
            form = _form(data, engagement=engagement)
            evidence = form.save(commit=False)
            evidence.uploader = actor
            evidence.original_filename = safe_filename(upload.name)
            evidence.storage_key, evidence.kind = key, kind
            evidence.content_type = TYPES[kind][0]
            evidence.size, evidence.sha256 = size, digest
            evidence.thumbnail_key, evidence.thumbnail_size, evidence.thumbnail_sha256 = thumbnail_key, thumbnail_size, thumbnail_digest
            evidence.save()
            _links(evidence, form.cleaned_data)
            reservation.commit(evidence)
            _event('evidence.uploaded', actor, evidence)
        committed = True
        return evidence
    finally:
        # Keep exclusive file leases until the database transaction has committed.
        for handle in handles:
            try:
                handle.close()
            except OSError:
                logger.warning('evidence_cleanup_deferred')
        if not committed and keys:
            # A commit error/interrupt can have an uncertain outcome. Never unlink
            # a file referenced by a committed row; leave uncertain files to the sweep.
            try:
                referenced = Evidence.objects.filter(storage_key=keys[0]).exists()
            except DatabaseError:
                logger.warning('evidence_cleanup_deferred')
            else:
                if not referenced:
                    _cleanup(engagement_id, keys)
        if staged is None:
            reservation.close()


@transaction.atomic
def update_evidence(*, actor, engagement_id, evidence_id, data, version):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, P.ATTACH_EVIDENCE)
    evidence = get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True), pk=evidence_id)
    _authority(actor, evidence)
    form = _form(data, engagement=engagement, instance=evidence)
    before = cas_update(engagement.evidence.filter(pk=evidence.pk, deleted_at__isnull=True), version=version,
               description=form.cleaned_data['description'], updated_at=timezone.now())
    _links(evidence, form.cleaned_data)
    evidence.refresh_from_db()
    _event('evidence.updated', actor, evidence, before=before)
    return evidence


@transaction.atomic
def remove_evidence(*, actor, engagement_id, evidence_id, version):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, P.ATTACH_EVIDENCE)
    evidence = get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True), pk=evidence_id)
    _authority(actor, evidence)
    now = timezone.now()
    before = cas_update(engagement.evidence.filter(pk=evidence.pk, deleted_at__isnull=True), version=version,
               deleted_at=now, deleted_by=actor, updated_at=now)
    evidence.refresh_from_db()
    _event('evidence.removed', actor, evidence, before=before)
    # No file deletion happens while a transaction can still roll back.
    transaction.on_commit(lambda: _cleanup(engagement.pk, [evidence.storage_key, evidence.thumbnail_key]))
    return evidence


def _scoped(actor, engagement_id, evidence_id):
    engagement = get_engagement(actor, engagement_id, P.DOWNLOAD_EVIDENCE)
    return get_object_or_404(engagement.evidence.filter(deleted_at__isnull=True), pk=evidence_id)


def open_download(*, actor, engagement_id, evidence_id, thumbnail=False):
    _outside_transaction()
    evidence = _scoped(actor, engagement_id, evidence_id)
    if thumbnail and not evidence.thumbnail_key:
        raise Http404
    key = evidence.thumbnail_key if thumbnail else evidence.storage_key
    size = evidence.thumbnail_size if thumbnail else evidence.size
    digest = evidence.thumbnail_sha256 if thumbnail else evidence.sha256
    file = None
    try:
        file = storage.open_file(engagement_id, key)
        if not verify_stream(file, size=size, digest=digest):
            raise storage.StorageError('Evidence integrity check failed.')
        with transaction.atomic():
            evidence = _scoped(actor, engagement_id, evidence_id)
            _event('evidence.downloaded', actor, evidence)
        return evidence, file
    except BaseException:
        if file:
            file.close()
        raise


def verify_evidence(*, actor, engagement_id, evidence_id):
    _outside_transaction()
    evidence = _scoped(actor, engagement_id, evidence_id)
    result = 'verified'
    for key, size, digest in [(evidence.storage_key, evidence.size, evidence.sha256),
                              (evidence.thumbnail_key, evidence.thumbnail_size, evidence.thumbnail_sha256)]:
        if not key:
            continue
        try:
            with storage.open_file(engagement_id, key) as file:
                if not verify_stream(file, size=size, digest=digest):
                    result = 'mismatch'
        except (OSError, storage.StorageError):
            result = 'unavailable'
    with transaction.atomic():
        evidence = _scoped(actor, engagement_id, evidence_id)
        _event('evidence.verified', actor, evidence, result=result)
    return result


def cleanup_orphans(*, older_than_seconds=86400, dry_run=False):
    """Operator sweep: leases protect active uploads; tombstones allow deferred deletion."""
    _outside_transaction()
    if older_than_seconds < 3600:
        raise ValueError('Orphan grace period must be at least one hour.')
    removed, deferred = 0, 0
    cutoff = time.time() - older_than_seconds
    with storage.root_directory() as root:
        for directory_name in os.listdir(root):
            if not isinstance(directory_name, str) or len(directory_name) != 32:
                continue
            try:
                engagement_id = uuid.UUID(hex=directory_name)
                if engagement_id.hex != directory_name:
                    continue
                with storage.engagement_directory(engagement_id) as directory:
                    keys = os.listdir(directory)
                for key in keys:
                    try:
                        with storage.open_file(engagement_id, key, exclusive=True) as file:
                            # File lock spans the reference check and unlink. Live uploads
                            # hold their own lease until commit; names are never reused.
                            records = Evidence.objects.filter(engagement_id=engagement_id).filter(Q(storage_key=key) | Q(thumbnail_key=key))
                            if records.filter(deleted_at__isnull=True).exists():
                                continue
                            if not records.exists() and os.fstat(file.fileno()).st_mtime > cutoff:
                                continue
                            with quotas.cleanup_lease(engagement_id, key) as inactive:
                                if not inactive:
                                    deferred += 1
                                    continue
                                if dry_run:
                                    removed += 1
                                    continue
                                with storage.engagement_directory(engagement_id) as pinned:
                                    info = os.stat(key, dir_fd=pinned, follow_symlinks=False)
                                    if (info.st_dev, info.st_ino) != (os.fstat(file.fileno()).st_dev, os.fstat(file.fileno()).st_ino):
                                        raise storage.StorageError('Orphan changed during cleanup.')
                                    os.unlink(key, dir_fd=pinned)
                                    os.fsync(pinned)
                                removed += 1
                                quotas.record_removed(engagement_id, key)
                    except (OSError, storage.StorageError):
                        deferred += 1
            except (ValueError, OSError, storage.StorageError):
                deferred += 1
    return removed, deferred
