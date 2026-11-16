from django.db import migrations
from apps.core.migration_operations import PortableGuardSQL

SQL = """
CREATE TRIGGER trace_evidence_allocation_insert BEFORE INSERT ON evidence_evidenceallocation
WHEN NEW.evidence_id IS NOT NULL AND NEW.engagement_id != (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id)
BEGIN SELECT RAISE(ABORT, 'evidence allocation engagement mismatch'); END;
CREATE TRIGGER trace_evidence_allocation_update BEFORE UPDATE OF engagement_id, evidence_id ON evidence_evidenceallocation
WHEN NEW.evidence_id IS NOT NULL AND NEW.engagement_id != (SELECT engagement_id FROM evidence_evidence WHERE id=NEW.evidence_id)
BEGIN SELECT RAISE(ABORT, 'evidence allocation engagement mismatch'); END;
"""


class Migration(migrations.Migration):
    dependencies = [('evidence', '0103_evidenceallocation_evidence_allocation_positive_version_and_more')]
    operations = [PortableGuardSQL(SQL, 'DROP TRIGGER trace_evidence_allocation_insert; DROP TRIGGER trace_evidence_allocation_update;')]
