from apps.audit.capture import capture
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.exceptions import EditConflict
from apps.core.concurrency import cas_update, cas_delete
from .models import Engagement, EngagementMembership, EngagementStatus, EngagementNote, EngagementMilestone
from .forms import EngagementForm, NoteForm, MilestoneForm, ENGAGEMENT_FIELDS
from .permissions import Permission, get_engagement, is_system_admin, require_system_admin

Role = EngagementMembership.Role


def validate_role(role):
    if role not in Role.values:
        raise ValidationError("Select a valid engagement role.")


@transaction.atomic
def create_engagement(*, actor, name, lead_id, data=None):
    require_system_admin(actor)
    lead = get_object_or_404(get_user_model().objects.filter(is_active=True), pk=lead_id)
    values = {"name": name, **(data or {})}
    _allowed(values, ENGAGEMENT_FIELDS)
    engagement = _validated(EngagementForm, values)
    engagement.created_by = engagement.updated_by = actor
    engagement.save()
    membership = EngagementMembership.objects.create(engagement=engagement, user=lead, role=Role.LEAD)
    record_event(action=AuditEvent.Action.ENGAGEMENT_CREATED, actor=actor, engagement=engagement, subject_id=engagement.pk)
    record_event(action=AuditEvent.Action.MEMBER_GRANTED, actor=actor, engagement=engagement,
                 subject_id=membership.pk, metadata={"role": Role.LEAD, "target_id": lead.pk})
    return engagement


def _allowed(data, fields):
    if set(data) - set(fields):
        raise ValidationError("Unrecognized fields in this operation.")


def _validated(form_class, data, instance=None):
    form = form_class(data, instance=instance)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    return form.save(commit=False)


def _editable(engagement):
    if engagement.is_read_only:
        raise ValidationError("Completed and archived engagements are read-only. Team access can still be maintained.")


TRANSITIONS = {
    EngagementStatus.PLANNED: {EngagementStatus.ACTIVE, EngagementStatus.ARCHIVED},
    EngagementStatus.ACTIVE: {EngagementStatus.PAUSED, EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED},
    EngagementStatus.PAUSED: {EngagementStatus.ACTIVE, EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED},
    EngagementStatus.COMPLETED: {EngagementStatus.ARCHIVED},
    EngagementStatus.ARCHIVED: set(),
}


@transaction.atomic
def update_engagement(*, actor, engagement_id, data, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.EDIT_ENGAGEMENT, for_update=True)
    _editable(engagement)
    _allowed(data, ENGAGEMENT_FIELDS)
    previous_values = {field: getattr(engagement, field) for field in ENGAGEMENT_FIELDS}
    candidate = _validated(EngagementForm, data, engagement)
    values = {field: getattr(candidate, field) for field in ENGAGEMENT_FIELDS}
    before = cas_update(Engagement.objects.filter(pk=engagement.pk), version=version,
               **values, updated_at=timezone.now(), updated_by=actor)
    record_event(action=AuditEvent.Action.ENGAGEMENT_UPDATED, actor=actor, engagement=engagement,
                 subject_id=engagement.pk, metadata={"version": version + 1,
                     "fields": [field for field in ENGAGEMENT_FIELDS if previous_values[field] != values[field]]}, before=before)
    return Engagement.objects.get(pk=engagement.pk)


@transaction.atomic
def transition_engagement(*, actor, engagement_id, target, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.EDIT_ENGAGEMENT, for_update=True)
    if engagement.version != version:
        raise EditConflict(current=engagement)
    if target not in TRANSITIONS.get(engagement.status, set()):
        raise ValidationError("This status transition is not allowed.")
    now = timezone.now()
    values = {"status": target, "updated_at": now, "updated_by": actor}
    if target == EngagementStatus.COMPLETED:
        values["completed_at"] = now
    if target == EngagementStatus.ARCHIVED:
        values["archived_at"] = now
    before = cas_update(Engagement.objects.filter(pk=engagement.pk), version=version, **values)
    record_event(action=AuditEvent.Action.ENGAGEMENT_STATUS, actor=actor, engagement=engagement,
        subject_id=engagement.pk, metadata={"previous_status": engagement.status, "status": target, "version": version + 1}, before=before)
    return Engagement.objects.get(pk=engagement.pk)


def can_edit_note(actor, note):
    return has_note_authority(actor, note.engagement_id, note.created_by_id)


def has_note_authority(actor, engagement_id, author_id):
    from .permissions import has_permission
    return has_permission(actor, engagement_id, Permission.WRITE_NOTES) and (
        actor.pk == author_id or has_permission(actor, engagement_id, Permission.EDIT_ENGAGEMENT))


def _note_authority(actor, note):
    if not can_edit_note(actor, note):
        raise PermissionDenied("Only the author, a Lead or a System Admin can change this note.")


@transaction.atomic
def save_note(*, actor, engagement_id, body, note_id=None, version=None):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.WRITE_NOTES, for_update=True)
    _editable(engagement)
    note = get_object_or_404(engagement.notes, pk=note_id) if note_id else None
    if note is not None:
        _note_authority(actor, note)
    candidate = _validated(NoteForm, {"body": body}, note)
    if note is None:
        candidate.engagement, candidate.created_by = engagement, actor
        candidate.save()
        action = AuditEvent.Action.NOTE_CREATED
    else:
        before = cas_update(engagement.notes.filter(pk=note.pk), version=version,
                   body=candidate.body, updated_at=timezone.now())
        action = AuditEvent.Action.NOTE_UPDATED
    candidate.refresh_from_db()
    record_event(action=action, actor=actor, engagement=engagement, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate


@transaction.atomic
def delete_note(*, actor, engagement_id, note_id, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.WRITE_NOTES, for_update=True)
    _editable(engagement)
    note = get_object_or_404(engagement.notes, pk=note_id)
    _note_authority(actor, note)
    before = cas_delete(engagement.notes.filter(pk=note.pk), version=version)
    record_event(action=AuditEvent.Action.NOTE_DELETED, actor=actor, engagement=engagement, subject_id=note_id, metadata={"version": version}, before=before)


@transaction.atomic
def save_milestone(*, actor, engagement_id, data, milestone_id=None, version=None):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MILESTONES, for_update=True)
    _editable(engagement)
    fields = ["title", "description", "due_date"]
    _allowed(data, fields)
    milestone = get_object_or_404(engagement.milestones, pk=milestone_id) if milestone_id else None
    candidate = _validated(MilestoneForm, data, milestone)
    if milestone is None:
        candidate.engagement, candidate.created_by = engagement, actor
        candidate.save()
        action = AuditEvent.Action.MILESTONE_CREATED
    else:
        values = {field: getattr(candidate, field) for field in fields}
        before = cas_update(engagement.milestones.filter(pk=milestone.pk), version=version,
                   **values, updated_at=timezone.now())
        action = AuditEvent.Action.MILESTONE_UPDATED
    candidate.refresh_from_db()
    record_event(action=action, actor=actor, engagement=engagement, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate


@transaction.atomic
def set_milestone_completed(*, actor, engagement_id, milestone_id, completed, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MILESTONES, for_update=True)
    _editable(engagement)
    get_object_or_404(engagement.milestones, pk=milestone_id)
    if not isinstance(completed, bool):
        raise ValidationError("Milestone completion must be a boolean.")
    before = cas_update(engagement.milestones.filter(pk=milestone_id), version=version, completed=completed,
               completed_at=timezone.now() if completed else None, updated_at=timezone.now())
    record_event(action=AuditEvent.Action.MILESTONE_UPDATED, actor=actor, engagement=engagement,
                 subject_id=milestone_id, metadata={"fields": ["completed"], "version": version + 1}, before=before)


@transaction.atomic
def delete_milestone(*, actor, engagement_id, milestone_id, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MILESTONES, for_update=True)
    _editable(engagement)
    get_object_or_404(engagement.milestones, pk=milestone_id)
    before = cas_delete(engagement.milestones.filter(pk=milestone_id), version=version)
    record_event(action=AuditEvent.Action.MILESTONE_DELETED, actor=actor, engagement=engagement, subject_id=milestone_id, metadata={"version": version}, before=before)


@transaction.atomic
def purge_engagement(*, actor, engagement_id, version, confirmation, reason):
    """Operator-only permanent purge; never exposed through a web route."""
    require_system_admin(actor)
    engagement = get_engagement(actor, engagement_id, Permission.EDIT_ENGAGEMENT, for_update=True)
    if engagement.version != version:
        raise EditConflict(current=engagement)
    if engagement.status != EngagementStatus.ARCHIVED or str(engagement.pk) != confirmation:
        raise ValidationError("Purge requires an archived engagement and its exact UUID confirmation.")
    if reason not in {"retention", "duplicate", "test-data"}:
        raise ValidationError("Select a permitted purge reason.")
    known = {EngagementMembership, EngagementNote, EngagementMilestone, AuditEvent}
    for relation in Engagement._meta.related_objects:
        if relation.related_model not in known and relation.related_model.objects.filter(**{relation.field.name: engagement}).exists():
            raise ValidationError("This engagement contains records from another module; use a reviewed retention workflow.")
    for records, action in [(engagement.notes.all(), AuditEvent.Action.NOTE_DELETED),
                            (engagement.milestones.all(), AuditEvent.Action.MILESTONE_DELETED),
                            (engagement.memberships.all(), AuditEvent.Action.MEMBER_REVOKED)]:
        for child in records:
            record_event(action=action, actor=actor, engagement_ref=engagement.pk,
                         subject_id=child.pk, before=capture(child), metadata={"reason": reason, "version": child.version})
        records.delete()
    # Preserve immutable UUID references while deliberately detaching the protected FK.
    AuditEvent.objects.filter(engagement=engagement).update(engagement_ref=engagement.pk, engagement=None)
    record_event(action=AuditEvent.Action.ENGAGEMENT_PURGED, actor=actor, subject_id=engagement.pk, engagement_ref=engagement.pk, before=capture(engagement),
                        metadata={"reason": reason, "version": version})
    engagement.delete()


@transaction.atomic
def grant_membership(*, actor, engagement_id, user_id, role):
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MEMBERS, for_update=True)
    validate_role(role)
    user = get_object_or_404(get_user_model().objects.filter(is_active=True), pk=user_id)
    member, created = EngagementMembership.objects.get_or_create(engagement=engagement, user=user, defaults={"role": role})
    if not created:
        raise EditConflict("This user already has a membership. Use the current row to change it.")
    record_event(action=AuditEvent.Action.MEMBER_GRANTED, actor=actor, engagement=engagement,
                 subject_id=member.pk, metadata={"role": role, "target_id": user.pk})
    return member


def _check_membership_change(actor, engagement, member, next_role):
    if actor.pk == member.user_id and not is_system_admin(actor):
        raise PermissionDenied("Ask another Lead or a System Admin to change your access.")
    if member.role == Role.LEAD and next_role != Role.LEAD and not engagement.memberships.filter(
            role=Role.LEAD, user__is_active=True).exclude(pk=member.pk).exists():
        raise ValidationError("Add another active Lead before removing or demoting this Lead.")


@transaction.atomic
def change_membership(*, actor, engagement_id, membership_id, role, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MEMBERS, for_update=True)
    validate_role(role)
    member = get_object_or_404(engagement.memberships, pk=membership_id)
    _check_membership_change(actor, engagement, member, role)
    before = cas_update(engagement.memberships.filter(pk=member.pk), version=version, role=role)
    record_event(action=AuditEvent.Action.MEMBER_CHANGED, actor=actor, engagement=engagement, subject_id=member.pk,
        metadata={"role": role, "previous_role": member.role, "version": version + 1, "target_id": member.user_id}, before=before)


@transaction.atomic
def revoke_membership(*, actor, engagement_id, membership_id, version):
    before = None
    engagement = get_engagement(actor, engagement_id, Permission.MANAGE_MEMBERS, for_update=True)
    member = get_object_or_404(engagement.memberships, pk=membership_id)
    _check_membership_change(actor, engagement, member, None)
    before = cas_delete(engagement.memberships.filter(pk=member.pk), version=version)
    record_event(action=AuditEvent.Action.MEMBER_REVOKED, actor=actor, engagement=engagement,
                 subject_id=member.pk, metadata={"previous_role": member.role, "target_id": member.user_id}, before=before)
