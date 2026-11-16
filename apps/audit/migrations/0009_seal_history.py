"""Seal existing metadata without inventing unavailable historical business values."""
import hashlib
import json
from django.db import migrations

ZERO='0'*64


def seal(apps, schema_editor):
    Event=apps.get_model('audit','AuditEvent')
    State=apps.get_model('audit','AuditChainState')
    previous=ZERO
    sequence=0
    for event in Event.objects.order_by('id').iterator():
        sequence+=1
        event.chain_sequence=sequence
        event.previous_hash=previous
        event.actor_ref=str(event.actor_id) if event.actor_id else ''
        event.legacy=True
        # Keep this historical format stable; runtime verification uses schema 1.
        payload={'schema':1,'sequence':sequence,'previous_hash':previous,
          'action':event.action,'actor_ref':event.actor_ref,'engagement_ref':str(event.engagement_ref) if event.engagement_ref else None,
          'entity_kind':event.entity_kind,'subject_id':event.subject_id,'subject_hash':event.subject_hash,
          'source_hash':event.source_hash,'request_id':event.request_id,'metadata':event.metadata,
          'before':event.before,'after':event.after,'legacy':True,'created_at':event.created_at.isoformat()}
        previous=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
        Event.objects.filter(pk=event.pk).update(chain_sequence=sequence,previous_hash=event.previous_hash,actor_ref=event.actor_ref,legacy=True,record_hash=previous)
    State.objects.create(pk=1,head_sequence=sequence,head_hash=previous)

FIELDS=['action','actor_ref','engagement_ref','entity_kind','subject_id','subject_hash','source_hash','request_id','metadata','before','after','chain_sequence','previous_hash','record_hash','legacy','created_at']
UNCHANGED=' AND '.join(f'NEW."{field}" IS OLD."{field}"' for field in FIELDS)
SQL=[
 f'''CREATE TRIGGER audit_sealed_update BEFORE UPDATE ON audit_auditevent
 WHEN NOT ({UNCHANGED} AND (NEW.actor_id IS OLD.actor_id OR NEW.actor_id IS NULL) AND (NEW.engagement_id IS OLD.engagement_id OR NEW.engagement_id IS NULL))
 BEGIN SELECT RAISE(ABORT, 'Sealed audit records cannot be edited'); END''',
 '''CREATE TRIGGER audit_sealed_insert BEFORE INSERT ON audit_auditevent
 WHEN NEW.chain_sequence IS NULL OR length(NEW.record_hash)!=64 OR NOT EXISTS
 (SELECT 1 FROM audit_auditchainstate WHERE id=1 AND NEW.chain_sequence=head_sequence+1 AND NEW.previous_hash=head_hash)
 BEGIN SELECT RAISE(ABORT, 'Audit records require chain attribution'); END''',
 '''CREATE TRIGGER audit_sealed_delete BEFORE DELETE ON audit_auditevent
 WHEN (SELECT foreign_keys FROM pragma_foreign_keys)=1 AND NOT EXISTS
 (SELECT 1 FROM audit_auditchainstate WHERE id=1 AND retention_active=1 AND OLD.chain_sequence<=anchor_sequence)
 BEGIN SELECT RAISE(ABORT, 'Audit records require authorized retention'); END''',
 '''CREATE TRIGGER audit_revision_update BEFORE UPDATE ON audit_entityrevision
 BEGIN SELECT RAISE(ABORT, 'Revisions cannot be edited'); END''',
 '''CREATE TRIGGER audit_revision_delete BEFORE DELETE ON audit_entityrevision
 WHEN (SELECT foreign_keys FROM pragma_foreign_keys)=1 AND NOT EXISTS
 (SELECT 1 FROM audit_auditchainstate s JOIN audit_auditevent e ON e.id=OLD.event_id
 WHERE s.id=1 AND s.retention_active=1 AND e.chain_sequence<=s.anchor_sequence)
 BEGIN SELECT RAISE(ABORT, 'Revisions require authorized retention'); END''',
 '''CREATE TRIGGER audit_state_delete BEFORE DELETE ON audit_auditchainstate
 WHEN (SELECT foreign_keys FROM pragma_foreign_keys)=1
 BEGIN SELECT RAISE(ABORT, 'Audit checkpoint cannot be deleted'); END''',
]


class Migration(migrations.Migration):
    dependencies=[('audit','0008_auditchainstate_entityrevision_auditevent_actor_ref_and_more'),('evidence','0003_audit_attribution_guards')]
    operations=[migrations.RunPython(seal,migrations.RunPython.noop)]+[
        migrations.RunSQL(sql, f'DROP TRIGGER IF EXISTS {name}') for sql,name in zip(SQL,
        ['audit_sealed_update','audit_sealed_insert','audit_sealed_delete','audit_revision_update','audit_revision_delete','audit_state_delete'])]
