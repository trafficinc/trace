import os
import subprocess
import sys


def test_legacy_engagements_and_audit_survive_upgrade(tmp_path):
    # Rehearse in a separate empty database, never by reversing the operator's DB.
    environment = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.development", "TRACE_STORAGE_ROOT": str(tmp_path), "TRACE_DB_ENGINE": "sqlite"}
    code = '''
import django
django.setup()
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
call_command("migrate", "audit", "0001_initial", interactive=False, verbosity=0)
state = MigrationExecutor(connection).loader.project_state([("audit", "0001_initial")]).apps
LegacyEngagement = state.get_model("engagements", "Engagement")
LegacyEvent = state.get_model("audit", "AuditEvent")
engagement = LegacyEngagement.objects.create(name="Preserved mission")
event = LegacyEvent.objects.create(engagement_id=engagement.pk, action="engagement.created")
call_command("migrate", interactive=False, verbosity=0)
from apps.engagements.models import Engagement
from apps.audit.models import AuditEvent
upgraded = Engagement.objects.get(pk=engagement.pk)
assert upgraded.name == "Preserved mission" and upgraded.status == "planned" and upgraded.version == 1
assert upgraded.created_by_id is None and upgraded.created_at == engagement.created_at
sealed = AuditEvent.objects.get(pk=event.pk)
assert sealed.engagement_ref == engagement.pk
assert sealed.legacy and sealed.before == sealed.after == {}
from apps.audit.integrity import digest
assert digest(sealed) == sealed.record_hash and sealed.chain_sequence == 1
from apps.audit.maintenance import _verify
assert _verify("default")["head_sequence"] == 1
'''
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
