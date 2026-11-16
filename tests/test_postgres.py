import os
import subprocess
import sys
import pytest
from apps.core.transfers import export_database
from apps.findings.services import save_finding

pytestmark=[pytest.mark.django_db(transaction=True),pytest.mark.skipif(not os.environ.get('TRACE_TEST_PG_DSN'),reason='Optional dedicated PostgreSQL test server is not configured.')]


def test_postgresql_migrations_transfer_guards_and_concurrency(access_setup,tmp_path,monkeypatch):
    from apps.audit.models import AuditEvent
    from django.utils import timezone
    from datetime import timedelta
    field=AuditEvent._meta.get_field('created_at')
    monkeypatch.setattr(field,'_get_default',lambda:timezone.now()-timedelta(days=400))
    users,engagement,_=access_setup
    finding=save_finding(actor=users['tester'],engagement_id=engagement.pk,data={'title':'Version 1','severity':'high'})
    for version,title in [(1,'Version 2'),(2,'PostgreSQL version 3')]:
        finding=save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=finding.pk,version=version,data={'title':title,'severity':'high'})
    output=tmp_path/'transfer.json'
    export_database(actor=users['admin'],output=output,maintenance=True)
    result=subprocess.run([sys.executable,'scripts/check_postgres.py',str(output),str(tmp_path/'pg-storage')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'PostgreSQL migration, logical import' in result.stdout
