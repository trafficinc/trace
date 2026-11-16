from django.db import migrations

OLD_SQL = """
CREATE TRIGGER trace_evidence_audit_update BEFORE UPDATE ON audit_auditevent
WHEN (OLD.action LIKE 'evidence.%' OR NEW.action LIKE 'evidence.%') AND (NEW.action IS NOT OLD.action OR NEW.engagement_ref IS NOT OLD.engagement_ref OR NEW.subject_id IS NOT OLD.subject_id OR NEW.metadata IS NOT OLD.metadata OR NEW.created_at IS NOT OLD.created_at OR NEW.request_id IS NOT OLD.request_id OR NEW.subject_hash IS NOT OLD.subject_hash OR NEW.source_hash IS NOT OLD.source_hash)
BEGIN SELECT RAISE(ABORT, 'evidence audit metadata is immutable'); END;
"""
NEW_SQL = """
CREATE TRIGGER trace_evidence_audit_update BEFORE UPDATE ON audit_auditevent
WHEN (OLD.action LIKE 'evidence.%' OR NEW.action LIKE 'evidence.%') AND (NEW.action IS NOT OLD.action OR NEW.engagement_ref IS NOT OLD.engagement_ref OR NEW.subject_id IS NOT OLD.subject_id OR NEW.metadata IS NOT OLD.metadata OR NEW.created_at IS NOT OLD.created_at OR NEW.request_id IS NOT OLD.request_id OR NEW.subject_hash IS NOT OLD.subject_hash OR NEW.source_hash IS NOT OLD.source_hash OR (NEW.actor_id IS NOT OLD.actor_id AND NEW.actor_id IS NOT NULL) OR (NEW.engagement_id IS NOT OLD.engagement_id AND NEW.engagement_id IS NOT NULL))
BEGIN SELECT RAISE(ABORT, 'evidence audit metadata is immutable'); END;
"""

class Migration(migrations.Migration):
    dependencies = [("evidence", "0002_integrity_guards")]
    operations = [migrations.RunSQL("DROP TRIGGER trace_evidence_audit_update;\n" + NEW_SQL,
                                    "DROP TRIGGER trace_evidence_audit_update;\n" + OLD_SQL)]
