"""Disposable PostgreSQL integration scenario, invoked by test_postgres.py.

Uses a dedicated local test server; creates/drops only a UUID-named database.
Never pass production server credentials to this test helper.
"""
import os
from pathlib import Path
import sys
import uuid
import psycopg
from psycopg import sql

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
source,storage=sys.argv[1:]
name='trace_test_'+uuid.uuid4().hex
admin=psycopg.connect(os.environ['TRACE_TEST_PG_DSN'],autocommit=True)
admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
try:
    info=admin.info
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings.development',TRACE_DB_ENGINE='postgresql',TRACE_DB_NAME=name,
        TRACE_DB_USER=info.user,TRACE_DB_PASSWORD=info.password or '',TRACE_DB_HOST=info.host,TRACE_DB_PORT=str(info.port),TRACE_STORAGE_ROOT=storage)
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate',interactive=False,verbosity=0)
    from apps.core.transfers import import_postgres
    # Recomputed file digests must not hide a corrupt committed audit body.
    import json
    from apps.core.backups import file_digest
    from apps.audit.services import AuditIntegrityError
    bad=Path(source).with_name('invalid-transfer.json')
    fixture=json.loads(Path(source).read_text())
    next(row for row in fixture if row['model']=='audit.auditevent')['fields']['record_hash']='a'*64
    bad.write_text(json.dumps(fixture)); os.chmod(bad,0o600)
    manifest=json.loads(Path(source+'.manifest.json').read_text())
    manifest['file']=file_digest(bad)
    bad_manifest=Path(str(bad)+'.manifest.json'); bad_manifest.write_text(json.dumps(manifest)); os.chmod(bad_manifest,0o600)
    try: import_postgres(source=bad,maintenance=True)
    except AuditIntegrityError: pass
    else: raise AssertionError('Corrupt transfer was accepted.')
    from apps.accounts.models import User
    from apps.audit.models import AuditEvent
    assert not User.objects.exists() and not AuditEvent.objects.exists()
    import_postgres(source=source,maintenance=True)
    from apps.accounts.models import User
    from apps.findings.models import Finding
    from apps.findings.services import save_finding
    from apps.core.exceptions import EditConflict
    from apps.audit.maintenance import verify_history
    from apps.testcases.models import TestCase, TestCaseAsset
    from apps.assets.models import Asset
    from apps.engagements.models import Engagement
    from apps.audit.models import AuditEvent
    from django.db import transaction,connections,close_old_connections,IntegrityError
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    actor=User.objects.get(username='tester'); admin_user=User.objects.get(username='admin')
    finding=Finding.objects.get(title='PostgreSQL version 3')
    barrier=Barrier(2)
    def worker(index):
        close_old_connections()
        try:
            user=User.objects.get(pk=actor.pk); barrier.wait(timeout=10)
            try:
                saved=save_finding(actor=user,engagement_id=finding.engagement_id,finding_id=finding.pk,version=3,data={'title':f'Winner {index}','severity':'high'})
                return saved.version
            except EditConflict: return 'conflict'
        finally: connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(worker,[1,2]))
    assert sorted(map(str,outcomes))==['4','conflict']
    assert Finding.objects.get(pk=finding.pk).version==4
    # Cross-engagement SQL guards remain active after logical import.
    foreign=Engagement.objects.exclude(pk=finding.engagement_id).first()
    case=TestCase.objects.create(engagement_id=finding.engagement_id,title='PG relationship')
    asset=Asset.objects.create(engagement=foreign,name='Foreign asset')
    try:
        with transaction.atomic(): TestCaseAsset.objects.bulk_create([TestCaseAsset(test_case=case,asset=asset)])
    except IntegrityError: pass
    else: raise AssertionError('PostgreSQL relationship guard did not reject a foreign asset.')
    event=AuditEvent.objects.order_by('-id').first()
    try:
        with transaction.atomic(): AuditEvent.objects.filter(pk=event.pk).update(metadata={})
    except IntegrityError: pass
    else: raise AssertionError('PostgreSQL audit guard failed.')
    from apps.reports.snapshots import read_snapshot
    with read_snapshot() as alias:
        assert Finding.objects.using(alias).get(pk=finding.pk).version==4
    verify_history(actor=admin_user)
    from apps.audit.maintenance import cleanup_history
    plan=cleanup_history(actor=admin_user)
    assert plan['eligible']==3
    cleanup_history(actor=admin_user,apply=True,expected_sequence=plan['head_sequence'])
    verify_history(actor=admin_user)
    from apps.accounts.throttling import reserve_attempt
    with ThreadPoolExecutor(max_workers=6) as pool:
        attempts=list(pool.map(lambda i:reserve_attempt('pg-throttle',None),range(6)))
    assert sum(not retry for _,retry in attempts)==5
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.evidence.services import upload_evidence
    evidence=upload_evidence(actor=actor,engagement_id=finding.engagement_id,upload=SimpleUploadedFile('pg-output.txt',b'PG evidence'),data={'description':'Test','test_cases':[case.pk]})
    from apps.evidence.quotas import set_quota, charged_bytes, CapacityError
    from apps.evidence.models import EvidenceAllocation
    assert charged_bytes(finding.engagement_id)==evidence.size
    try:
        with transaction.atomic(): EvidenceAllocation.objects.filter(evidence=evidence).update(engagement=foreign)
    except IntegrityError: pass
    else: raise AssertionError('PostgreSQL allocation engagement guard failed.')
    quota=set_quota(actor=admin_user,engagement_id=finding.engagement_id,limit_bytes=0,version=0)
    try: upload_evidence(actor=actor,engagement_id=finding.engagement_id,upload=SimpleUploadedFile('blocked.txt',b'quota'),data={'test_cases':[case.pk]})
    except CapacityError: pass
    else: raise AssertionError('PostgreSQL quota enforcement failed.')
    set_quota(actor=admin_user,engagement_id=finding.engagement_id,limit_bytes=None,version=quota.version)
    from apps.reports.services import save_report,generate_report
    report=save_report(actor=actor,engagement_id=finding.engagement_id,data={'title':'PostgreSQL report','include_images':False},finding_ids=[finding.pk])
    revision=generate_report(actor=actor,engagement_id=finding.engagement_id,report_id=report.pk,version=1)
    assert revision.status=='ready' and revision.artifacts.count()==4
    verify_history(actor=admin_user)
    # Counters/sequence reset allow a new auth user after imported integer IDs.
    User.objects.create_user('after-import')
    print('PostgreSQL migration, logical import, CAS concurrency, guards, read snapshots and audit verification passed.')
finally:
    try:
        from django.db import connections
        connections.close_all()
    except ImportError: pass
    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    admin.close()
