from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Event = apps.get_model("audit", "AuditEvent")
    Event.objects.using(schema_editor.connection.alias).filter(
        engagement_id__isnull=False, engagement_ref__isnull=True).update(engagement_ref=F("engagement_id"))


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_auditevent_engagement_ref_alter_auditevent_action_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
