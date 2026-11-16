from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from .security import source_fingerprint, username_fingerprint


@receiver(user_logged_in)
def login_succeeded(sender, request, user, **kwargs):
    record_event(action=AuditEvent.Action.LOGIN_SUCCESS, actor=user,
        subject_hash=username_fingerprint(user.get_username()), source_hash=source_fingerprint(request))


@receiver(user_login_failed)
def login_failed(sender, credentials, request=None, **kwargs):
    username = credentials.get("username", "")
    if not isinstance(username, str):
        username = ""
    record_event(action=AuditEvent.Action.LOGIN_FAILURE,
        subject_hash=username_fingerprint(username), source_hash=source_fingerprint(request),
        metadata={"reason": "throttled" if getattr(request, "trace_login_retry_after", 0) else "invalid_credentials"})
    if request is not None:
        request.trace_login_audited = True


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    if user is not None and user.is_authenticated:
        record_event(action=AuditEvent.Action.LOGOUT, actor=user, source_hash=source_fingerprint(request))
