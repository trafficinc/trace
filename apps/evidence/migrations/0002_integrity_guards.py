from django.db import migrations

SQL = """
CREATE TRIGGER trace_evidence_test_insert BEFORE INSERT ON evidence_evidencetestcase
WHEN (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) != (SELECT engagement_id FROM testcases_testcase WHERE id=NEW.test_case_id)
BEGIN SELECT RAISE(ABORT, 'evidence relationship engagement mismatch'); END;
CREATE TRIGGER trace_evidence_test_update BEFORE UPDATE OF evidence_id, test_case_id ON evidence_evidencetestcase
WHEN (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) != (SELECT engagement_id FROM testcases_testcase WHERE id=NEW.test_case_id)
BEGIN SELECT RAISE(ABORT, 'evidence relationship engagement mismatch'); END;
CREATE TRIGGER trace_evidence_test_parent BEFORE UPDATE OF engagement_id ON testcases_testcase
WHEN EXISTS (SELECT 1 FROM evidence_evidencetestcase l JOIN evidence_evidence e ON e.id=l.evidence_id WHERE l.test_case_id=OLD.id AND e.engagement_id != NEW.engagement_id)
BEGIN SELECT RAISE(ABORT, 'evidence linked record cannot change engagement'); END;
CREATE TRIGGER trace_evidence_finding_insert BEFORE INSERT ON evidence_evidencefinding
WHEN (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) != (SELECT engagement_id FROM findings_finding WHERE id=NEW.finding_id)
BEGIN SELECT RAISE(ABORT, 'evidence relationship engagement mismatch'); END;
CREATE TRIGGER trace_evidence_finding_update BEFORE UPDATE OF evidence_id, finding_id ON evidence_evidencefinding
WHEN (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) != (SELECT engagement_id FROM findings_finding WHERE id=NEW.finding_id)
BEGIN SELECT RAISE(ABORT, 'evidence relationship engagement mismatch'); END;
CREATE TRIGGER trace_evidence_finding_parent BEFORE UPDATE OF engagement_id ON findings_finding
WHEN EXISTS (SELECT 1 FROM evidence_evidencefinding l JOIN evidence_evidence e ON e.id=l.evidence_id WHERE l.finding_id=OLD.id AND e.engagement_id != NEW.engagement_id)
BEGIN SELECT RAISE(ABORT, 'evidence linked record cannot change engagement'); END;
CREATE TRIGGER trace_evidence_provenance BEFORE UPDATE ON evidence_evidence
WHEN NEW.engagement_id IS NOT OLD.engagement_id OR NEW.original_filename IS NOT OLD.original_filename OR NEW.storage_key IS NOT OLD.storage_key OR NEW.kind IS NOT OLD.kind OR NEW.content_type IS NOT OLD.content_type OR NEW.size IS NOT OLD.size OR NEW.sha256 IS NOT OLD.sha256 OR NEW.thumbnail_key IS NOT OLD.thumbnail_key OR NEW.thumbnail_size IS NOT OLD.thumbnail_size OR NEW.thumbnail_sha256 IS NOT OLD.thumbnail_sha256 OR NEW.created_at IS NOT OLD.created_at OR (NEW.uploader_id IS NOT OLD.uploader_id AND NEW.uploader_id IS NOT NULL) OR (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NOT OLD.deleted_at)
BEGIN SELECT RAISE(ABORT, 'evidence provenance is immutable'); END;
CREATE TRIGGER trace_evidence_audit_update BEFORE UPDATE ON audit_auditevent
WHEN (OLD.action LIKE 'evidence.%' OR NEW.action LIKE 'evidence.%') AND (NEW.action IS NOT OLD.action OR NEW.engagement_ref IS NOT OLD.engagement_ref OR NEW.subject_id IS NOT OLD.subject_id OR NEW.metadata IS NOT OLD.metadata OR NEW.created_at IS NOT OLD.created_at OR NEW.request_id IS NOT OLD.request_id OR NEW.subject_hash IS NOT OLD.subject_hash OR NEW.source_hash IS NOT OLD.source_hash)
BEGIN SELECT RAISE(ABORT, 'evidence audit metadata is immutable'); END;

"""

class Migration(migrations.Migration):
    dependencies = [("evidence", "0001_initial"), ("audit", "0006_alter_auditevent_action")]
    operations = [migrations.RunSQL(SQL, """
DROP TRIGGER trace_evidence_test_insert;
DROP TRIGGER trace_evidence_test_update;
DROP TRIGGER trace_evidence_test_parent;
DROP TRIGGER trace_evidence_finding_insert;
DROP TRIGGER trace_evidence_finding_update;
DROP TRIGGER trace_evidence_finding_parent;
DROP TRIGGER trace_evidence_provenance;
DROP TRIGGER trace_evidence_audit_update;
""")]
