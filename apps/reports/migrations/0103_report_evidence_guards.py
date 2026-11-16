from django.db import migrations
from apps.core.migration_operations import PortableGuardSQL


SQL = """
CREATE TRIGGER trace_report_evidence_insert BEFORE INSERT ON reports_reportevidence WHEN (SELECT engagement_id FROM reports_report WHERE id=NEW.report_id) != (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) BEGIN SELECT RAISE(ABORT,'report evidence engagement mismatch'); END;
CREATE TRIGGER trace_report_evidence_update BEFORE UPDATE OF report_id,evidence_id ON reports_reportevidence WHEN (SELECT engagement_id FROM reports_report WHERE id=NEW.report_id) != (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id) BEGIN SELECT RAISE(ABORT,'report evidence engagement mismatch'); END;
"""


class Migration(migrations.Migration):
    dependencies = [('reports', '0102_report_evidence_selection')]
    operations = [PortableGuardSQL(SQL, """
DROP TRIGGER trace_report_evidence_insert;
DROP TRIGGER trace_report_evidence_update;
""")]
