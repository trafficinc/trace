"""Database-backed limits shared by all workers and all authentication entry points."""
import math
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import LoginThrottle
from .security import source_fingerprint, username_fingerprint


def reserve_attempt(username, request):
    now = timezone.now()
    window = timedelta(seconds=settings.TRACE_LOGIN_WINDOW_SECONDS)
    source_key = source_fingerprint(request)
    # Bound bucket growth once a source is blocked. Transaction checks below remain authoritative.
    source = LoginThrottle.objects.filter(pk=source_key).first()
    if source and source.window_started + window > now and source.attempts >= settings.TRACE_LOGIN_SOURCE_LIMIT:
        return [], max(1, math.ceil((source.window_started + window - now).total_seconds()))
    limits = {username_fingerprint(username): settings.TRACE_LOGIN_ACCOUNT_LIMIT,
              source_key: settings.TRACE_LOGIN_SOURCE_LIMIT}
    reservations = []
    retry_after = 0
    with transaction.atomic():
        from apps.core.database import mutation_lock
        mutation_lock()
        rows = []
        for key in sorted(limits):
            LoginThrottle.objects.get_or_create(key=key, defaults={"window_started": now})
            # IMMEDIATE reserves SQLite's writer; row locks are not supported.
            row = LoginThrottle.objects.get(pk=key)
            if row.window_started + window <= now:
                row.window_started, row.attempts = now, 0
                row.save(update_fields=["window_started", "attempts"])
            rows.append(row)
            if row.attempts >= limits[key]:
                retry_after = max(retry_after, math.ceil((row.window_started + window - now).total_seconds()))
        if not retry_after:
            for row in rows:
                LoginThrottle.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
                reservations.append((row.pk, row.window_started))
    return reservations, retry_after


def release_success(reservations):
    with transaction.atomic():
        from apps.core.database import mutation_lock
        mutation_lock()
        for key, window_started in sorted(reservations):
            LoginThrottle.objects.filter(pk=key, window_started=window_started, attempts__gt=0).update(attempts=F("attempts") - 1)


def record_unhandled_failure(request):
    """Include malformed forms and valid nonstaff credentials rejected by admin."""
    if getattr(request, "trace_login_audited", False):
        return
    from django.contrib.auth.signals import user_login_failed
    username = request.POST.get("username", "")
    _, retry_after = reserve_attempt(username, request)
    if retry_after:
        request.trace_login_retry_after = retry_after
    user_login_failed.send(sender=__name__, credentials={"username": username}, request=request)
