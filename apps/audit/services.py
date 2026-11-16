import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from apps.core.logging import request_id
from .models import AuditEvent, AuditChainState, EntityRevision
from .capture import Snapshot, SCHEMAS, RELATIONS, current_snapshot, kind_for_action
from .redaction import redact_value
from .integrity import canonical, digest

ALLOWED_METADATA={'role','previous_role','version','active','target_id','reason','status','previous_status','fields','result'}
READ_ACTIONS={'evidence.downloaded','evidence.verified','report.downloaded'}


class AuditIntegrityError(Exception):
    pass


def _metadata(metadata):
    if set(metadata)-ALLOWED_METADATA: raise ValueError('Audit metadata contains unapproved fields.')
    result=redact_value(metadata)
    if len(canonical(result))>8192: raise ValueError('Audit metadata is too large.')
    for key in ['role','previous_role']:
        if key in result and result[key] not in {'lead','tester','reviewer','viewer'}: raise ValueError('Invalid audit role.')
    if 'version' in result and (type(result['version']) is not int or result['version']<0): raise ValueError('Invalid audit version.')
    if 'active' in result and type(result['active']) is not bool: raise ValueError('Invalid audit active flag.')
    for key in ['status','previous_status','result','reason']:
        if key in result and (not isinstance(result[key],str) or not re.fullmatch(r'[a-z_\-]{1,40}',result[key])): raise ValueError('Invalid audit metadata value.')
    if 'fields' in result:
        allowed={field for _,fields in SCHEMAS.values() for field in fields}|{'completed'}
        if not isinstance(result['fields'],list) or set(result['fields'])-allowed: raise ValueError('Invalid audited field names.')
    if 'target_id' in result and not re.fullmatch(r'[0-9a-f\-]{1,64}',str(result['target_id'])): raise ValueError('Invalid audit target.')
    return result


@transaction.atomic
def record_event(*, action, actor=None, engagement=None, subject_id='', metadata=None,
                 subject_hash='', source_hash='', before=None, after=None, engagement_ref=None, entity_kind=None):
    from apps.core.database import mutation_lock
    mutation_lock()
    if action not in AuditEvent.Action.values: raise ValueError('Unknown audit action.')
    for value in [before,after]:
        if value is not None and not isinstance(value,Snapshot): raise ValueError('Business history requires an allowlisted snapshot.')
    for snapshot in [before, after]:
        if snapshot:
            if snapshot.kind not in SCHEMAS: raise ValueError('Unknown snapshot kind.')
            allowed=set(SCHEMAS[snapshot.kind][1])|set(RELATIONS.get(snapshot.kind,[]))
            if snapshot.kind=='report': allowed.add('findings')
            if set(snapshot.values)!=allowed or redact_value(snapshot.values)!=snapshot.values:
                raise ValueError('History values must match the redacted business schema.')
    reference=engagement.pk if engagement else engagement_ref
    kind=entity_kind or (before.kind if before else kind_for_action(action))
    if kind not in set(SCHEMAS)|{'authentication','system'}: raise ValueError('Unknown audit entity kind.')
    if before and (before.kind!=kind or before.subject_id!=str(subject_id) or before.engagement_ref!=(str(reference) if reference else None)):
        raise ValueError('Audit before-state is outside the event scope.')
    if action not in READ_ACTIONS and kind in SCHEMAS and after is None and not action.endswith(('.deleted','.revoked','.purged')):
        after=current_snapshot(kind,str(subject_id),reference)
    if after and (after.kind!=kind or after.subject_id!=str(subject_id) or after.engagement_ref!=(str(reference) if reference else None)):
        raise ValueError('Audit after-state is outside the event scope.')
    state=AuditChainState.objects.filter(pk=1).first()
    if state is None:
        if AuditEvent.objects.exists(): raise AuditIntegrityError('Audit chain state is missing.')
        state=AuditChainState.objects.create(pk=1)
    if state.head_sequence>state.anchor_sequence:
        tail=AuditEvent.objects.filter(chain_sequence=state.head_sequence).first()
        if tail is None or tail.record_hash!=state.head_hash or digest(tail)!=tail.record_hash:
            raise AuditIntegrityError('Audit chain tail verification failed.')
    elif state.head_sequence!=state.anchor_sequence or state.head_hash!=state.anchor_hash:
        raise AuditIntegrityError('Audit chain anchor is inconsistent.')
    event=AuditEvent(action=action,actor=actor,actor_ref=str(actor.pk) if actor and actor.pk else '',engagement=engagement,
        engagement_ref=reference,entity_kind=kind,subject_id=str(subject_id),metadata=_metadata(metadata or {}),
        before=before.values if before else {},after=after.values if after else {},
        subject_hash=subject_hash,source_hash=source_hash,request_id=request_id.get() or '',
        chain_sequence=state.head_sequence+1,previous_hash=state.head_hash)
    if len(canonical(event.before))+len(canonical(event.after))>settings.TRACE_AUDIT_MAX_EVENT_BYTES:
        raise ValidationError('Audited business values exceed the configured history limit. Shorten the documentation or ask an administrator to review the limit.')
    event.record_hash=digest(event)
    event.save(force_insert=True)
    if AuditChainState.objects.filter(pk=1,version=state.version).update(head_sequence=event.chain_sequence,head_hash=event.record_hash,version=F('version')+1)!=1:
        raise AuditIntegrityError('Audit chain state changed.')
    if kind in {'finding','test_case'} and reference and action not in READ_ACTIONS:
        for snapshot,baseline in [(before,True),(after,False)]:
            if snapshot and snapshot.values.get('version'):
                exists=EntityRevision.objects.filter(entity_kind=kind,entity_id=subject_id,entity_version=snapshot.values['version']).exists()
                if not exists:
                    EntityRevision.objects.create(event=event,engagement_id=reference,entity_kind=kind,entity_id=subject_id,
                        entity_version=snapshot.values['version'],snapshot=snapshot.values,baseline=baseline,created_at=event.created_at)
    return event
