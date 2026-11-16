from django.db import migrations

REVISION_INSERT='''
CREATE TRIGGER audit_revision_insert BEFORE INSERT ON audit_entityrevision
WHEN NOT EXISTS (
 SELECT 1 FROM audit_auditevent e
 WHERE e.id=NEW.event_id AND e.entity_kind=NEW.entity_kind
 AND replace(e.subject_id,'-','')=NEW.entity_id AND e.engagement_ref=NEW.engagement_id
 AND NEW.created_at=e.created_at
 AND NEW.snapshot=CASE WHEN NEW.baseline=1 THEN e.before ELSE e.after END
 AND json_extract(NEW.snapshot,'$.version')=NEW.entity_version
)
BEGIN SELECT RAISE(ABORT, 'Revision must match its sealed event'); END
'''


class Migration(migrations.Migration):
    dependencies=[('audit','0009_seal_history')]
    operations=[
        migrations.RunSQL('''CREATE TRIGGER audit_identity_update BEFORE UPDATE OF id ON audit_auditevent
            WHEN NEW.id IS NOT OLD.id
            BEGIN SELECT RAISE(ABORT, 'Audit identity cannot be edited'); END''','DROP TRIGGER audit_identity_update'),
        migrations.RunSQL(REVISION_INSERT,'DROP TRIGGER audit_revision_insert'),
    ]
