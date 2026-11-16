"""Operator verification and bounded retention, with explicit checkpoint continuity."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.models import F, Prefetch
from django.utils import timezone
from apps.engagements.permissions import require_system_admin
from .models import AuditEvent, AuditChainState, EntityRevision
from .integrity import digest, ZERO
from .services import AuditIntegrityError, record_event


@contextmanager
def read_snapshot():
    alias='trace_audit_snapshot'
    if hasattr(connections._connections,alias): raise RuntimeError('Nested audit snapshots are not supported.')
    wrapper=connections['default'].copy(alias=alias)
    wrapper.settings_dict=deepcopy(wrapper.settings_dict)
    if wrapper.vendor == 'sqlite':
        wrapper.settings_dict['OPTIONS']['transaction_mode']='DEFERRED'
    connections[alias]=wrapper
    try:
        with wrapper.cursor() as cursor:
            if wrapper.vendor == 'sqlite': cursor.execute('PRAGMA query_only=ON')
        with transaction.atomic(using=alias):
            if wrapper.vendor == 'postgresql':
                with wrapper.cursor() as cursor: cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            yield alias
    finally:
        wrapper.close()
        del connections[alias]


def _verify(alias):
    state=AuditChainState.objects.using(alias).filter(pk=1).first()
    if state is None:
        if AuditEvent.objects.using(alias).exists(): raise AuditIntegrityError('Audit checkpoint is missing.')
        return {'head_sequence':0,'head_hash':ZERO,'anchor_sequence':0,'anchor_hash':ZERO}
    previous=state.anchor_hash; sequence=state.anchor_sequence
    for event in AuditEvent.objects.using(alias).order_by('chain_sequence').prefetch_related(
        Prefetch('revisions', queryset=EntityRevision.objects.using(alias))
    ).iterator(chunk_size=50):
        if event.chain_sequence!=sequence+1 or event.previous_hash!=previous or digest(event)!=event.record_hash:
            raise AuditIntegrityError('Audit chain verification failed.')
        sequence=event.chain_sequence; previous=event.record_hash
        # Revisions duplicate sealed snapshots, so validate their binding too.
        for revision in event.revisions.all():
            snapshot=event.before if revision.baseline else event.after
            if (revision.snapshot!=snapshot or revision.entity_kind!=event.entity_kind or str(revision.entity_id)!=event.subject_id
                or str(revision.engagement_id)!=str(event.engagement_ref) or revision.entity_version!=snapshot.get('version')
                or revision.created_at!=event.created_at):
                raise AuditIntegrityError('Revision binding verification failed.')
    if sequence!=state.head_sequence or previous!=state.head_hash:
        raise AuditIntegrityError('Audit chain checkpoint verification failed.')
    if state.anchor_sequence==0 and state.anchor_hash!=ZERO: raise AuditIntegrityError('Audit origin is invalid.')
    return {'head_sequence':sequence,'head_hash':previous,'anchor_sequence':state.anchor_sequence,'anchor_hash':state.anchor_hash}


def verify_history(*, actor):
    require_system_admin(actor)
    with read_snapshot() as alias: return _verify(alias)


def cleanup_history(*, actor, apply=False, expected_sequence=None, batch_size=500):
    require_system_admin(actor)
    days=settings.TRACE_AUDIT_RETENTION_DAYS
    if days<=0: raise ValidationError('Audit retention cleanup is disabled.')
    if not 1<=batch_size<=500: raise ValidationError('Cleanup batches must contain 1 to 500 records.')
    cutoff=timezone.now()-timedelta(days=days)
    with read_snapshot() as alias:
        checkpoint=_verify(alias)
        candidates=[]
        # Only a contiguous oldest prefix may be removed, even with clock changes.
        for event in AuditEvent.objects.using(alias).order_by('chain_sequence')[:batch_size]:
            if event.created_at>=cutoff: break
            candidates.append((event.pk,event.chain_sequence,event.record_hash))
    result={**checkpoint,'eligible':len(candidates),'cutoff':cutoff.isoformat(),'applied':False}
    if not apply or not candidates: return result
    if type(expected_sequence) is not int or expected_sequence!=checkpoint['head_sequence']:
        raise ValidationError('Apply requires the head sequence from a reviewed dry run.')
    with transaction.atomic():
        require_system_admin(actor)
        state=AuditChainState.objects.get(pk=1)
        if state.head_sequence!=expected_sequence or state.head_hash!=checkpoint['head_hash'] or state.anchor_sequence!=checkpoint['anchor_sequence']:
            raise ValidationError('Audit history changed. Review a new dry run.')
        _,sequence,anchor=candidates[-1]
        AuditChainState.objects.filter(pk=1,version=state.version).update(anchor_sequence=sequence,anchor_hash=anchor,retention_active=True,version=F('version')+1)
        ids=[pk for pk,_,_ in candidates]
        EntityRevision.objects.filter(event_id__in=ids).delete()
        AuditEvent.objects.filter(pk__in=ids).delete()
        record_event(action=AuditEvent.Action.AUDIT_RETENTION,actor=actor,metadata={'version':sequence,'reason':'retention'})
        AuditChainState.objects.filter(pk=1).update(retention_active=False,version=F('version')+1)
    return {**result,'applied':True,'anchor_sequence':sequence,'anchor_hash':anchor}
