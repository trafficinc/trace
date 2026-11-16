"""Local byte reservations: short CAS transactions, leased uploads and fail-closed capacity."""
from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path
import tempfile
import time
import uuid
from typing import Any
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from apps.core.concurrency import cas_update, cas_delete
from apps.core.exceptions import EditConflict
from apps.engagements.permissions import get_engagement, get_writable_engagement, require_system_admin, Permission
from .models import Evidence, EvidenceAllocation, EvidenceQuota
from . import storage

logger = logging.getLogger('trace.evidence')


class CapacityError(ValidationError):
    def __init__(self, message, status=413):
        self.status = status
        logger.warning('evidence_capacity_blocked', extra={'status_code': status})
        super().__init__(message)


def _outside():
    if connection.in_atomic_block:
        raise RuntimeError('Storage leases and filesystem probes run outside database transactions.')


@contextmanager
def _lock(name, *, wait=True):
    _outside()
    with storage.root_directory() as root:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            descriptor = os.open(name, flags, dir_fd=root)
        except FileNotFoundError:
            try:
                descriptor = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
            except FileExistsError:
                # Another process published the persistent coordination file.
                descriptor = os.open(name, flags, dir_fd=root)
    try:
        storage._private(os.fstat(descriptor))
        deadline = time.monotonic() + (5 if wait else 0)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait or time.monotonic() >= deadline:
                    raise CapacityError('Storage capacity is busy. Try again shortly.', 503) from None
                time.sleep(.02)  # Only retry idempotent lease acquisition, never content writes.
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def capacity_lock():
    with _lock('.quota-capacity.lock'):
        yield


def disk_probes(*, include_archives=False):
    """Available blocks for this service user, grouped by actual filesystem device."""
    locations = [('Private evidence', settings.EVIDENCE_ROOT, settings.TRACE_STORAGE_MIN_FREE_BYTES),
                 ('Database', settings.DATABASE_ROOT, settings.TRACE_STORAGE_MIN_FREE_BYTES),
                 ('Upload buffering', Path(tempfile.gettempdir()), settings.TRACE_UPLOAD_TEMP_MIN_FREE_BYTES)]
    if include_archives:
        locations += [('Reports', settings.REPORT_ROOT, settings.TRACE_STORAGE_MIN_FREE_BYTES),
                      ('Backups', settings.BACKUP_ROOT, settings.TRACE_STORAGE_MIN_FREE_BYTES)]
    devices: dict[int, dict[str, Any]] = {}
    for label, path, reserve in locations:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info, stats = os.fstat(descriptor), os.fstatvfs(descriptor)
        finally:
            os.close(descriptor)
        current = devices.setdefault(info.st_dev, {'labels': [], 'free': stats.f_bavail * stats.f_frsize,
            'total': stats.f_blocks * stats.f_frsize, 'reserve': reserve, 'inodes_available': stats.f_favail})
        current['labels'].append(label)
        current['reserve'] = max(current['reserve'], reserve)
    for row in devices.values():
        row['percent_free'] = round(100 * row['free'] / row['total'], 1) if row['total'] else 0
        row['warning'] = row['free'] <= row['reserve'] or row['percent_free'] <= settings.TRACE_STORAGE_WARNING_PERCENT
        row['label'] = ' / '.join(row.pop('labels'))
    return list(devices.values())


def _budget():
    try:
        probes = disk_probes()
    except OSError:
        raise CapacityError('Storage capacity cannot be checked. Try again or contact a System Admin.', 503) from None
    if not probes or any(row['inodes_available'] == 0 for row in probes):
        raise CapacityError('Storage capacity is insufficient. Contact a System Admin.', 507)
    return min(row['free'] - row['reserve'] for row in probes)


def _sum(queryset, expression):
    return queryset.aggregate(value=Sum(expression))['value'] or 0


def charged_bytes(engagement_id=None):
    allocations = EvidenceAllocation.objects.all()
    # Existing installations and supported data imports are charged immediately,
    # without filesystem work in a schema migration. Reconciliation adopts them.
    legacy = Evidence.objects.filter(storage_allocation__isnull=True)
    if engagement_id is not None:
        allocations = allocations.filter(engagement_id=engagement_id)
        legacy = legacy.filter(engagement_id=engagement_id)
    return _sum(allocations, F('original_bytes') + F('thumbnail_bytes')) + _sum(legacy, F('size') + F('thumbnail_size'))


def limit_for(engagement_id):
    override = EvidenceQuota.objects.filter(engagement_id=engagement_id).values_list('limit_bytes', flat=True).first()
    return settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES if override is None else override


def _check(allocation, original, thumbnail, disk, budget):
    delta = original + thumbnail - allocation.original_bytes - allocation.thumbnail_bytes
    if charged_bytes(allocation.engagement_id) + delta > limit_for(allocation.engagement_id):
        raise CapacityError('This engagement’s evidence quota is exhausted. Remove unneeded evidence or contact a System Admin.')
    if charged_bytes() + delta > settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES:
        raise CapacityError('The server’s evidence quota is exhausted. Contact a System Admin.')
    total_disk = _sum(EvidenceAllocation.objects.all(), 'disk_bytes') - allocation.disk_bytes + disk
    if total_disk > budget:
        raise CapacityError('Not enough free storage to upload safely. Contact a System Admin.', 507)


class Reservation:
    def __init__(self, identifier, engagement_id, actor, lease):
        self.id, self.engagement_id, self.actor, self.lease = identifier, engagement_id, actor, lease
        self.closed = False
        self.original_reserved = self.thumbnail_reserved = 0

    def row(self):
        return EvidenceAllocation.objects.get(pk=self.id, engagement_id=self.engagement_id, actor_id=self.actor.pk)

    def attach(self, field, key):
        if field not in {'original_key', 'thumbnail_key', 'staging_key'}:
            raise ValueError('Invalid allocation key field.')
        storage._key(key)
        with capacity_lock(), transaction.atomic():
            row = self.row()
            if row.evidence_id:
                raise ValidationError('Upload allocation is already committed.')
            cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=self.engagement_id),
                       version=row.version, **{field: key}, updated_at=timezone.now())

    def reserve(self, original, thumbnail=0):
        if original < 0 or original > settings.TRACE_EVIDENCE_MAX_BYTES or not 0 <= thumbnail <= 2 * 1024**2:
            raise CapacityError('Evidence exceeds the configured upload limit.')
        if original <= self.original_reserved and thumbnail <= self.thumbnail_reserved:
            return
        with capacity_lock():
            budget = _budget()  # Filesystem metadata probe outside the writer transaction.
            with transaction.atomic():
                get_writable_engagement(self.actor, self.engagement_id, Permission.ATTACH_EVIDENCE)
                row = self.row()
                if row.evidence_id:
                    raise ValidationError('Upload allocation is already committed.')
                original = max(original, row.original_bytes)
                thumbnail = max(thumbnail, row.thumbnail_bytes)
                # Conservative peak covers HTTP body buffering, private staging,
                # final copy and the bounded thumbnail. Never trust Content-Length.
                disk = 3 * original + 2 * 1024**2
                _check(row, original, thumbnail, disk, budget)
                cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=self.engagement_id), version=row.version,
                           original_bytes=original, thumbnail_bytes=thumbnail, disk_bytes=disk, updated_at=timezone.now())
                self.original_reserved, self.thumbnail_reserved = original, thumbnail

    @contextmanager
    def publication(self):
        with capacity_lock():
            budget = _budget()
            with transaction.atomic():
                row = self.row()
                _check(row, row.original_bytes, row.thumbnail_bytes, row.disk_bytes, budget)
                yield

    def commit(self, evidence):
        if not connection.in_atomic_block or evidence.engagement_id != self.engagement_id:
            raise ValueError('Evidence publication requires its authorized engagement transaction.')
        row = self.row()
        if row.evidence_id or row.original_bytes != evidence.size or row.thumbnail_bytes != evidence.thumbnail_size:
            raise ValidationError('Upload reservation does not match the stored evidence.')
        cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=self.engagement_id), version=row.version,
                   evidence=evidence, updated_at=timezone.now())

    def close(self):
        if self.closed:
            return
        try:
            with capacity_lock():
                row = self.row()
                # Committed originals are never unlinked here, including ambiguous
                # commit outcomes. Pending files belong only to this leased writer.
                fields = ['staging_key'] if row.evidence_id else ['original_key', 'thumbnail_key', 'staging_key']
                removed = {}
                for field in fields:
                    key = getattr(row, field)
                    if not key:
                        continue
                    try:
                        storage.remove_file(self.engagement_id, key)
                    except FileNotFoundError:
                        pass
                    except (OSError, storage.StorageError):
                        logger.warning('evidence_cleanup_deferred')
                        continue
                    removed[field] = ''
                original = row.original_bytes if row.evidence_id or row.original_key and 'original_key' not in removed or row.staging_key and 'staging_key' not in removed else 0
                thumbnail = row.thumbnail_bytes if row.evidence_id or row.thumbnail_key and 'thumbnail_key' not in removed else 0
                with transaction.atomic():
                    cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=self.engagement_id), version=row.version,
                               original_bytes=original, thumbnail_bytes=thumbnail, disk_bytes=0, updated_at=timezone.now(), **removed)
                    if row.evidence_id is None and not original and not thumbnail and all(not getattr(row, field) or field in removed for field in fields):
                        cas_delete(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=self.engagement_id), version=row.version + 1)
        except Exception:
            # Retain the conservative charge on uncertain cleanup/database errors.
            logger.warning('evidence_cleanup_deferred')
        finally:
            self.closed = True
            self.lease.__exit__(None, None, None)
            _drop_lease(self.id)


def begin(*, actor, engagement_id):
    _outside()
    engagement = get_engagement(actor, engagement_id, Permission.ATTACH_EVIDENCE)
    if engagement.is_read_only:
        raise ValidationError('Completed and archived engagements are read-only.')
    identifier = uuid.uuid4()
    lease = _lock('.quota-upload-' + identifier.hex)
    lease.__enter__()
    try:
        with capacity_lock():
            budget = _budget()
            with transaction.atomic():
                get_writable_engagement(actor, engagement_id, Permission.ATTACH_EVIDENCE)
                if charged_bytes(engagement.pk) >= limit_for(engagement.pk):
                    raise CapacityError('This engagement’s evidence quota is exhausted. Remove unneeded evidence or contact a System Admin.')
                if charged_bytes() >= settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES:
                    raise CapacityError('The server’s evidence quota is exhausted. Contact a System Admin.')
                if _sum(EvidenceAllocation.objects.all(), 'disk_bytes') + 2 * 1024**2 > budget:
                    raise CapacityError('Not enough free storage to upload safely. Contact a System Admin.', 507)
                EvidenceAllocation.objects.create(pk=identifier, engagement_id=engagement.pk, actor=actor, disk_bytes=2*1024**2)
        return Reservation(identifier, engagement.pk, actor, lease)
    except BaseException:
        lease.__exit__(None, None, None)
        _drop_lease(identifier)
        raise


def _drop_lease(identifier):
    try:
        with storage.root_directory() as root:
            os.unlink(".quota-upload-" + identifier.hex, dir_fd=root)
    except FileNotFoundError:
        pass
    except (OSError, storage.StorageError):
        logger.warning("evidence_cleanup_deferred")


def record_removed(engagement_id, key):
    """Called only after successful unlink/missing-file confirmation, outside DB locks."""
    with capacity_lock(), transaction.atomic():
        row = EvidenceAllocation.objects.filter(engagement_id=engagement_id).filter(Q(original_key=key) | Q(thumbnail_key=key) | Q(staging_key=key)).first()
        if row is None:
            legacy = Evidence.objects.filter(engagement_id=engagement_id, storage_allocation__isnull=True).filter(Q(storage_key=key) | Q(thumbnail_key=key)).first()
            if legacy is None:
                return
            row = EvidenceAllocation.objects.create(engagement_id=engagement_id, evidence=legacy, actor_id=legacy.uploader_id,
                original_key=legacy.storage_key, thumbnail_key=legacy.thumbnail_key,
                original_bytes=legacy.size, thumbnail_bytes=legacy.thumbnail_size)
        values: dict[str, Any] = {}
        if key == row.original_key:
            values.update(original_key='', original_bytes=0)
        if key == row.thumbnail_key:
            values.update(thumbnail_key='', thumbnail_bytes=0)
        if key == row.staging_key:
            values['staging_key'] = ''
        cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=engagement_id), version=row.version,
                   updated_at=timezone.now(), **values)


def usage(*, actor, engagement_id):
    get_engagement(actor, engagement_id, Permission.DOWNLOAD_EVIDENCE)
    used, limit = charged_bytes(engagement_id), limit_for(engagement_id)
    return {'used': used, 'limit': limit, 'remaining': max(0, limit-used), 'over_limit': used >= limit,
            'percent': min(100, round(100*used/limit)) if limit else 100}


def system_status(*, actor):
    require_system_admin(actor)
    try:
        disks = disk_probes(include_archives=True)
    except OSError:
        disks = []
    used = charged_bytes()
    return {'used': used, 'limit': settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES, 'disks': disks,
            'warning': not disks or any(row['warning'] for row in disks) or used >= settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES,
            'reserved_disk': _sum(EvidenceAllocation.objects.all(), 'disk_bytes')}


def set_quota(*, actor, engagement_id, limit_bytes, version):
    require_system_admin(actor)
    if limit_bytes is not None and (type(limit_bytes) is not int or not 0 <= limit_bytes <= 1024**5):
        raise ValidationError('Quota must be between zero and 1 PiB, or blank to use the default.')
    if type(version) is not int or version < 0:
        raise ValidationError('A valid quota policy version is required.')
    from apps.audit.services import record_event
    with capacity_lock(), transaction.atomic():
        require_system_admin(actor)
        engagement = get_engagement(actor, engagement_id, for_update=True)
        current = EvidenceQuota.objects.filter(engagement=engagement).first()
        before = None
        if current is None:
            if version != 0:
                raise EditConflict(current=engagement)
            current = EvidenceQuota.objects.create(engagement=engagement, limit_bytes=limit_bytes, updated_by=actor)
        else:
            if version == 0:
                raise EditConflict(current=current)
            before = cas_update(EvidenceQuota.objects.filter(pk=current.pk, engagement=engagement), version=version,
                                limit_bytes=limit_bytes, updated_by=actor, updated_at=timezone.now())
            current.refresh_from_db()
        record_event(action='evidence_quota.changed', actor=actor, engagement=engagement, subject_id=current.pk,
                     metadata={'version': current.version}, before=before)
        return current


@contextmanager
def _inactive_lease(identifier):
    """Inspect existing lease without creating coordination files during dry runs."""
    with storage.root_directory() as root:
        try:
            descriptor = os.open('.quota-upload-' + identifier.hex, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        except FileNotFoundError:
            yield True
            return
    try:
        storage._private(os.fstat(descriptor))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(descriptor)


def reconcile(*, actor, apply=False, maintenance=False, older_than_seconds=86400):
    """Adopt legacy charges and release only missing/deleted/stale unleased files."""
    _outside()
    require_system_admin(actor)
    if type(older_than_seconds) is not int or older_than_seconds < 3600:
        raise ValidationError('Use an orphan grace period of at least one hour.')
    from contextlib import nullcontext
    from apps.core.maintenance import exclusive_maintenance
    from apps.audit.services import record_event
    from .services import cleanup_orphans
    cutoff = timezone.now() - timezone.timedelta(seconds=older_than_seconds)
    result = {'legacy': 0, 'released': 0, 'deferred': 0, 'missing_live_files': 0, 'active': 0, 'orphan_files_removed': 0, 'orphan_files_eligible': 0}
    with exclusive_maintenance(maintenance) if apply else nullcontext():
        # Metadata adoption never reads files under the database writer lock.
        for evidence in Evidence.objects.filter(storage_allocation__isnull=True).iterator(chunk_size=100):
            result['legacy'] += 1
            if apply:
                with capacity_lock(), transaction.atomic():
                    require_system_admin(actor)
                    if not EvidenceAllocation.objects.filter(evidence=evidence).exists():
                        row = EvidenceAllocation.objects.create(engagement_id=evidence.engagement_id, evidence=evidence,
                            actor_id=evidence.uploader_id, original_key=evidence.storage_key, thumbnail_key=evidence.thumbnail_key,
                            original_bytes=evidence.size, thumbnail_bytes=evidence.thumbnail_size)
                        record_event(action='evidence_storage.reconciled', actor=actor, engagement=evidence.engagement,
                                     subject_id=row.pk, metadata={'result': 'adopted', 'version': row.version})
        def legacy_candidates():
            if not apply:
                for evidence in Evidence.objects.filter(storage_allocation__isnull=True).iterator(chunk_size=100):
                    yield EvidenceAllocation(pk=uuid.uuid5(uuid.NAMESPACE_OID, 'evidence-quota-' + str(evidence.pk)),
                        engagement_id=evidence.engagement_id, evidence=evidence, actor_id=evidence.uploader_id,
                        original_key=evidence.storage_key, thumbnail_key=evidence.thumbnail_key,
                        original_bytes=evidence.size, thumbnail_bytes=evidence.thumbnail_size,
                        created_at=evidence.created_at, updated_at=evidence.updated_at)
        from itertools import chain
        candidates = chain(legacy_candidates(), EvidenceAllocation.objects.select_related('evidence', 'engagement').iterator(chunk_size=100))
        for row in candidates:
            with _inactive_lease(row.pk) as inactive:
                if not inactive:
                    result['active'] += 1
                    continue
                evidence = row.evidence
                if evidence is None and row.updated_at > cutoff:
                    continue
                values: dict[str, Any] = {}
                for field in ['original_key', 'thumbnail_key', 'staging_key']:
                    key = getattr(row, field)
                    if not key:
                        continue
                    retained = evidence is not None and evidence.deleted_at is None and field != 'staging_key'
                    try:
                        with storage.open_file(row.engagement_id, key, exclusive=True):
                            pass
                    except FileNotFoundError:
                        exists = False
                    except (OSError, storage.StorageError):
                        result['deferred'] += 1
                        continue
                    else:
                        exists = True
                    if retained:
                        if not exists:
                            result['missing_live_files'] += 1
                        continue
                    if exists and not apply:
                        result['released'] += 1
                        continue
                    if exists:
                        try:
                            storage.remove_file(row.engagement_id, key)
                        except FileNotFoundError:
                            pass
                        except (OSError, storage.StorageError):
                            result['deferred'] += 1
                            continue
                    values[field] = ''
                    if field == 'original_key':
                        values['original_bytes'] = 0
                    elif field == 'thumbnail_key':
                        values['thumbnail_bytes'] = 0
                    result['released'] += 1
                if evidence is None and not (values.get('original_key', row.original_key) or values.get('staging_key', row.staging_key)):
                    values['original_bytes'] = 0
                if not values.get('thumbnail_key', row.thumbnail_key):
                    values['thumbnail_bytes'] = 0
                if row.disk_bytes:
                    values['disk_bytes'] = 0
                values = {key: value for key, value in values.items() if getattr(row, key) != value}
                disposable = evidence is None and not values.get('original_bytes', row.original_bytes) and not values.get('thumbnail_bytes', row.thumbnail_bytes) and not any(values.get(field, getattr(row, field)) for field in ['original_key', 'thumbnail_key', 'staging_key'])
                if apply and (values or disposable):
                    with capacity_lock(), transaction.atomic():
                        require_system_admin(actor)
                        cas_update(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=row.engagement_id), version=row.version,
                                   updated_at=timezone.now(), **values)
                        if disposable:
                            cas_delete(EvidenceAllocation.objects.filter(pk=row.pk, engagement_id=row.engagement_id), version=row.version + 1)
                        record_event(action='evidence_storage.reconciled', actor=actor, engagement=row.engagement,
                                     subject_id=row.pk, metadata={'result': 'released', 'version': row.version + 1})
                if apply:
                    _drop_lease(row.pk)
        if apply:
            require_system_admin(actor)
            record_event(action='evidence_storage.reconciled', actor=actor, metadata={'result': 'started', 'reason': 'orphan_cleanup'})
            removed, deferred = cleanup_orphans(older_than_seconds=older_than_seconds)
            result['orphan_files_removed'] = removed
            result['deferred'] += deferred
            record_event(action='evidence_storage.reconciled', actor=actor, metadata={'result': 'completed', 'reason': 'orphan_cleanup'})
        else:
            result['orphan_files_eligible'], _ = cleanup_orphans(older_than_seconds=older_than_seconds, dry_run=True)
    return result


@contextmanager
def cleanup_lease(engagement_id, key):
    from contextlib import ExitStack
    with ExitStack() as leases:
        rows = EvidenceAllocation.objects.filter(engagement_id=engagement_id).filter(
            Q(original_key=key) | Q(thumbnail_key=key) | Q(staging_key=key)).values_list('pk', flat=True)
        inactive = all(leases.enter_context(_inactive_lease(identifier)) for identifier in rows)
        yield inactive
