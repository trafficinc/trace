from datetime import timedelta
import sqlite3
import time
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, transaction
from django.http import Http404
from django.utils import timezone
from .editing import resolve_editor
from .models import EditorPresence

TTL_SECONDS = 60


def _busy(error):
    code = getattr(error.__cause__, 'sqlite_errorcode', None)
    return code is not None and code & 0xff in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def heartbeat(*, actor, kind, object_id, engagement_id=None, leave=False):
    if not settings.TRACE_EDITOR_PRESENCE_ENABLED:
        raise Http404
    for attempt in range(3):
        try:
            with transaction.atomic():
                record, engagement = resolve_editor(actor=actor, kind=kind, object_id=object_id,
                                                     engagement_id=engagement_id, writable=True)
                key = dict(actor=actor, kind=kind, object_id=str(record.pk),
                           engagement_ref=engagement.pk if engagement else None)
                if leave:
                    EditorPresence.objects.filter(**key).delete()
                else:
                    now = timezone.now()
                    if not EditorPresence.objects.filter(**key).update(seen_at=now):
                        EditorPresence.objects.create(**key, seen_at=now)
                # Bounded TTL housekeeping keeps abandoned sessions out of queries.
                expired = list(EditorPresence.objects.filter(seen_at__lt=timezone.now()-timedelta(seconds=TTL_SECONDS)).values_list('pk', flat=True)[:100])
                EditorPresence.objects.filter(pk__in=expired).delete()
            return record, engagement
        except OperationalError as exc:
            # A heartbeat is idempotent. Content mutations are never replayed.
            if not _busy(exc) or attempt == 2:
                raise
            time.sleep(0.02 * (attempt + 1))


def editors(*, actor, kind, object_id, engagement_id=None):
    if not settings.TRACE_EDITOR_PRESENCE_ENABLED:
        raise Http404
    record, engagement = resolve_editor(actor=actor, kind=kind, object_id=object_id, engagement_id=engagement_id)
    rows = EditorPresence.objects.filter(kind=kind, object_id=str(record.pk), engagement_ref=engagement.pk if engagement else None,
        seen_at__gte=timezone.now()-timedelta(seconds=TTL_SECONDS), actor__is_active=True).exclude(actor=actor).select_related('actor').order_by('actor__username')[:25]
    result = []
    for row in rows:
        try:
            # Revocation/deactivation and per-author restrictions apply immediately,
            # even if an old heartbeat has not reached its TTL yet.
            resolve_editor(actor=row.actor, kind=kind, object_id=record.pk, engagement_id=engagement_id, writable=True)
        except (PermissionDenied, Http404):
            continue
        result.append(row.actor.get_username())
    return result
