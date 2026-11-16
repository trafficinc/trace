from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.concurrency import cas_update
from apps.engagements.permissions import Permission, get_writable_engagement
from .forms import AssetForm, ASSET_FIELDS


@transaction.atomic
def save_asset(*, actor, engagement_id, data, asset_id=None, version=None):
    before = None
    engagement = get_writable_engagement(actor, engagement_id, Permission.MANAGE_ASSETS)
    if set(data) - set(ASSET_FIELDS):
        raise ValidationError("Unrecognized asset fields.")
    asset = get_object_or_404(engagement.assets, pk=asset_id) if asset_id else None
    form = AssetForm(data, instance=asset, engagement=engagement)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    candidate = form.save(commit=False)
    if asset is None:
        candidate.created_by = actor
        candidate.save()
        action = AuditEvent.Action.ASSET_CREATED
    else:
        values = {field: getattr(candidate, field) for field in ASSET_FIELDS}
        before = cas_update(engagement.assets.filter(pk=asset_id), version=version, **values, updated_at=timezone.now())
        action = AuditEvent.Action.ASSET_UPDATED
    candidate.refresh_from_db()
    record_event(action=action, actor=actor, engagement=engagement, subject_id=candidate.pk, metadata={"version": candidate.version}, before=before)
    return candidate
