from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.views.decorators.debug import sensitive_variables
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.exceptions import EditConflict
from apps.core.concurrency import cas_update
from apps.engagements.permissions import identity, require_system_admin
from .forms import CreateUserForm

User = get_user_model()


@sensitive_variables("data", "form", "user")
def create_account(*, actor, data):
    require_system_admin(actor)
    form = CreateUserForm(data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    user = form.save(commit=False)  # Django hashes and validates passwords; outside the write transaction.
    user.is_staff = user.is_superuser = False
    user.is_active = True
    with transaction.atomic():
        from apps.core.database import mutation_lock
        mutation_lock()
        require_system_admin(actor)
        user.save()
        record_event(action=AuditEvent.Action.USER_CREATED, actor=actor, subject_id=user.pk)
    return user


@transaction.atomic
def update_profile(*, actor, data, version):
    from apps.core.database import mutation_lock
    mutation_lock()
    before = None
    if identity(actor) is None:
        raise PermissionDenied
    # The service also validates its allowlisted fields for non-HTTP callers.
    candidate = User.objects.get(pk=actor.pk)
    for field in ("first_name", "last_name", "email"):
        setattr(candidate, field, data[field])
    candidate.full_clean(exclude=["password"])
    changes = {field: getattr(candidate, field) for field in ("first_name", "last_name", "email")}
    before = cas_update(User.objects.filter(pk=actor.pk, is_active=True), version=version, **changes)
    record_event(action=AuditEvent.Action.USER_UPDATED, actor=actor, subject_id=actor.pk, metadata={"version": version + 1}, before=before)


@transaction.atomic
def set_account_active(*, actor, user_id, active, version):
    from apps.core.database import mutation_lock
    mutation_lock()
    before = None
    require_system_admin(actor)
    if not isinstance(active, bool):
        raise ValidationError("Account status must be a boolean.")
    # The IMMEDIATE transaction reserves SQLite's writer before these reads.
    administrators = list(User.objects.filter(is_superuser=True).order_by("pk"))
    require_system_admin(actor)
    user = get_object_or_404(User.objects.all(), pk=user_id)
    if user.is_superuser and not active and not any(item.is_active and item.pk != user.pk for item in administrators):
        raise ValidationError("The last active System Admin cannot be disabled.")
    before = cas_update(User.objects.filter(pk=user.pk), version=version,
               is_active=active, session_version=F("session_version") + 1)
    record_event(action=AuditEvent.Action.USER_UPDATED, actor=actor, subject_id=user.pk,
                 metadata={"active": bool(active), "version": version + 1}, before=before)


@sensitive_variables("old_password", "new_password", "old_hash", "current")
def change_password(*, actor, old_password, new_password, version):
    from apps.core.database import mutation_lock
    mutation_lock()
    before = None
    if identity(actor) is None:
        raise PermissionDenied
    current = User.objects.get(pk=actor.pk)
    if not current.check_password(old_password):
        raise ValidationError("The current password is incorrect.")
    validate_password(new_password, current)
    old_hash = current.password
    current.set_password(new_password)  # Slow hashing stays outside the write transaction.
    with transaction.atomic():
        from apps.core.database import mutation_lock
        mutation_lock()
        if User.objects.filter(pk=actor.pk, is_active=True, version=version).exclude(password=old_hash).exists():
            raise EditConflict(current=User.objects.get(pk=actor.pk))
        before = cas_update(User.objects.filter(pk=actor.pk, is_active=True), version=version, password=current.password)
        record_event(action=AuditEvent.Action.PASSWORD_CHANGED, actor=actor, subject_id=actor.pk, before=before)
    return User.objects.get(pk=actor.pk)
