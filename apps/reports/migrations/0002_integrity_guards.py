from django.db import migrations

SQL = """
CREATE TRIGGER trace_report_finding_insert BEFORE INSERT ON reports_reportfinding WHEN (SELECT engagement_id FROM reports_report WHERE id=NEW.report_id) != (SELECT engagement_id FROM findings_finding WHERE id=NEW.finding_id) BEGIN SELECT RAISE(ABORT,'report finding engagement mismatch'); END;
CREATE TRIGGER trace_report_finding_update BEFORE UPDATE OF report_id,finding_id ON reports_reportfinding WHEN (SELECT engagement_id FROM reports_report WHERE id=NEW.report_id) != (SELECT engagement_id FROM findings_finding WHERE id=NEW.finding_id) BEGIN SELECT RAISE(ABORT,'report finding engagement mismatch'); END;
CREATE TRIGGER trace_report_finding_parent BEFORE UPDATE OF engagement_id ON findings_finding WHEN EXISTS (SELECT 1 FROM reports_reportfinding l JOIN reports_report r ON r.id=l.report_id WHERE l.finding_id=OLD.id AND r.engagement_id!=NEW.engagement_id) BEGIN SELECT RAISE(ABORT,'report linked finding cannot move'); END;
CREATE TRIGGER trace_report_parent BEFORE UPDATE OF engagement_id ON reports_report WHEN OLD.engagement_id IS NOT NEW.engagement_id BEGIN SELECT RAISE(ABORT,'report engagement is immutable'); END;
CREATE TRIGGER trace_report_logo_insert BEFORE INSERT ON reports_report WHEN NEW.logo_id IS NOT NULL AND NEW.engagement_id!=(SELECT engagement_id FROM evidence_evidence WHERE id=NEW.logo_id) BEGIN SELECT RAISE(ABORT,'report logo engagement mismatch'); END;
CREATE TRIGGER trace_report_logo_update BEFORE UPDATE OF logo_id,engagement_id ON reports_report WHEN NEW.logo_id IS NOT NULL AND NEW.engagement_id!=(SELECT engagement_id FROM evidence_evidence WHERE id=NEW.logo_id) BEGIN SELECT RAISE(ABORT,'report logo engagement mismatch'); END;
CREATE TRIGGER trace_report_revision_scope BEFORE INSERT ON reports_reportrevision WHEN NEW.engagement_id!=(SELECT engagement_id FROM reports_report WHERE id=NEW.report_id) BEGIN SELECT RAISE(ABORT,'report revision engagement mismatch'); END;
CREATE TRIGGER trace_report_revision_immutable BEFORE UPDATE ON reports_reportrevision WHEN NEW.engagement_id IS NOT OLD.engagement_id OR NEW.report_id IS NOT OLD.report_id OR NEW.number IS NOT OLD.number OR NEW.report_version IS NOT OLD.report_version OR NEW.created_at IS NOT OLD.created_at OR NEW.renderer_versions IS NOT OLD.renderer_versions OR (NEW.generated_by_id IS NOT OLD.generated_by_id AND NEW.generated_by_id IS NOT NULL) OR OLD.status!='rendering' OR NEW.status NOT IN ('ready','failed') OR NEW.version!=OLD.version+1 OR NEW.completed_at IS NULL BEGIN SELECT RAISE(ABORT,'report revision is immutable after finalization'); END;
CREATE TRIGGER trace_report_artifact_scope BEFORE INSERT ON reports_reportartifact WHEN NEW.engagement_id!=(SELECT engagement_id FROM reports_reportrevision WHERE id=NEW.revision_id) BEGIN SELECT RAISE(ABORT,'report artifact engagement mismatch'); END;
CREATE TRIGGER trace_report_artifact_immutable BEFORE UPDATE ON reports_reportartifact BEGIN SELECT RAISE(ABORT,'report artifact is immutable'); END;
"""

class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]
    operations = [migrations.RunSQL(SQL, """
DROP TRIGGER trace_report_finding_insert;
DROP TRIGGER trace_report_finding_update;
DROP TRIGGER trace_report_finding_parent;
DROP TRIGGER trace_report_parent;
DROP TRIGGER trace_report_logo_insert;
DROP TRIGGER trace_report_logo_update;
DROP TRIGGER trace_report_revision_scope;
DROP TRIGGER trace_report_revision_immutable;
DROP TRIGGER trace_report_artifact_scope;
DROP TRIGGER trace_report_artifact_immutable;
""")]
