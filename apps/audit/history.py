"""Read/export policy lives here so direct callers get the same permission checks."""
import json
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from apps.engagements.permissions import Permission, get_engagement, require_system_admin
from .models import AuditEvent, EntityRevision
from .capture import SCHEMAS
from .redaction import redact_value
from .services import record_event
from .integrity import payload
from .forms import HistoryFilter


def events_for(*,actor,engagement_id=None):
    if engagement_id is None:
        require_system_admin(actor)
        return AuditEvent.objects.all()
    engagement=get_engagement(actor,engagement_id,Permission.VIEW_AUDIT)
    return AuditEvent.objects.filter(engagement_ref=engagement.pk)


def filter_events(queryset,data):
    form=HistoryFilter(data)
    if not form.is_valid(): raise ValidationError(form.errors.as_data())
    for key,field in [('entity','entity_kind'),('subject','subject_id'),('actor','actor_ref'),('action','action'),('date_from','created_at__date__gte'),('date_to','created_at__date__lte')]:
        value=form.cleaned_data.get(key)
        if value: queryset=queryset.filter(**{field:value})
    return queryset


def revisions_for(*,actor,engagement_id,kind,entity_id):
    from django.apps import apps
    from django.http import Http404
    if kind not in {'finding','test_case'}: raise Http404
    engagement=get_engagement(actor,engagement_id,Permission.VIEW)
    entity=get_object_or_404(apps.get_model(SCHEMAS[kind][0]).objects.filter(engagement=engagement),pk=entity_id)
    return entity,EntityRevision.objects.filter(engagement=engagement,entity_kind=kind,entity_id=entity.pk).select_related('event','event__actor')


def public_event(event):
    value=payload(event)
    # Legacy events are never silently rewritten; redact only the presentation.
    for key in ['metadata','before','after']: value[key]=redact_value(value[key])
    return {**value,'record_hash':event.record_hash}


def export_history(*,actor,engagement_id=None,filters=None):
    queryset=filter_events(events_for(actor=actor,engagement_id=engagement_id),filters or {}).order_by('chain_sequence')
    encoded: list[bytes] = []
    size=0
    for event in queryset[:settings.TRACE_AUDIT_EXPORT_LIMIT+1].iterator(chunk_size=50):
        if len(encoded)>=settings.TRACE_AUDIT_EXPORT_LIMIT:
            raise ValidationError('Too many audit events. Narrow the filters before exporting.')
        item=json.dumps(public_event(event),ensure_ascii=True,sort_keys=True).encode()
        size+=len(item)
        if size>settings.TRACE_AUDIT_EXPORT_MAX_BYTES:
            raise ValidationError('Audit export exceeds the byte limit. Narrow the filters.')
        encoded.append(item)
    result=b'{"schema":1,"notice":"Filtered, redacted history; verify the complete database chain with verify_audit.","events":['+b','.join(encoded)+b']}'
    with transaction.atomic():
        events_for(actor=actor,engagement_id=engagement_id)  # Recheck current membership, including on closed engagements.
        engagement=get_engagement(actor,engagement_id,Permission.VIEW_AUDIT,for_update=True) if engagement_id else None
        record_event(action=AuditEvent.Action.AUDIT_EXPORTED,actor=actor,engagement=engagement,metadata={'result':'exported'})
    return result
