"""Real file-backed quota races, interrupted streaming and permission boundaries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import os
import subprocess
import sys
from threading import Barrier
from unittest.mock import patch
import pytest
from PIL import Image
from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict
from apps.engagements.models import Engagement
from apps.evidence import quotas, services, storage
from apps.evidence.models import Evidence, EvidenceAllocation, EvidenceQuota
from apps.testcases.models import TestCase as Case

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def quota_work(access_setup, settings, tmp_path):
    users, engagement, foreign = access_setup
    root = tmp_path/'private'; root.mkdir(mode=0o700)
    settings.STORAGE_ROOT = root
    settings.EVIDENCE_ROOT = root/'evidence'; settings.EVIDENCE_ROOT.mkdir(mode=0o700)
    settings.DATABASE_ROOT = root/'db'; settings.DATABASE_ROOT.mkdir(mode=0o700)
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES = 1024**2
    settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES = 2*1024**2
    first = Case.objects.create(engagement=engagement, title='Synthetic quota case')
    second = Case.objects.create(engagement=foreign, title='Foreign quota case')
    return users, engagement, foreign, first, second


def upload(work, content=b'a'*70, *, foreign=False):
    users, engagement, other, case, foreign_case = work
    return services.upload_evidence(actor=users['outsider' if foreign else 'tester'],
        engagement_id=(other if foreign else engagement).pk,
        upload=SimpleUploadedFile('synthetic.txt', content), data={'description':'Synthetic quota test','test_cases':[(foreign_case if foreign else case).pk]})


def test_exact_quota_boundary_and_untrusted_declared_size(quota_work, settings):
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES = 70
    record = upload(quota_work)
    assert quotas.charged_bytes(record.engagement_id) == 70
    with pytest.raises(quotas.CapacityError): upload(quota_work, b'b')
    assert Evidence.objects.count() == 1 and quotas.charged_bytes() == 70
    assert EvidenceAllocation.objects.filter(disk_bytes__gt=0).count() == 0
    class Dishonest:
        name='synthetic.log'
        size=0
        def chunks(self, **kwargs): yield b'a'*71
    services.remove_evidence(actor=quota_work[0]['tester'],engagement_id=record.engagement_id,evidence_id=record.pk,version=1)
    with pytest.raises(quotas.CapacityError):
        services.upload_evidence(actor=quota_work[0]['tester'],engagement_id=record.engagement_id,upload=Dishonest(),data={'test_cases':[quota_work[3].pk]})
    assert quotas.charged_bytes() == 0


def test_thumbnail_is_included_and_rolls_back_at_boundary(quota_work, settings):
    output=io.BytesIO(); Image.new('RGB',(32,24),'red').save(output,format='PNG'); data=output.getvalue()
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES=len(data)
    with pytest.raises(quotas.CapacityError):
        services.upload_evidence(actor=quota_work[0]['tester'],engagement_id=quota_work[1].pk,
            upload=SimpleUploadedFile('synthetic.png',data),data={'test_cases':[quota_work[3].pk]})
    assert not Evidence.objects.exists() and quotas.charged_bytes()==0
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES=1024**2
    record=services.upload_evidence(actor=quota_work[0]['tester'],engagement_id=quota_work[1].pk,
        upload=SimpleUploadedFile('synthetic.png',data),data={'test_cases':[quota_work[3].pk]})
    assert record.thumbnail_size and quotas.charged_bytes()==record.size+record.thumbnail_size


@pytest.mark.parametrize('_attempt', range(3))
@pytest.mark.parametrize('foreign,total,expected',[(False,200,1),(True,200,2),(True,100,1)])
def test_actual_simultaneous_upload_connections_share_budgets(quota_work, settings, foreign, total, expected, _attempt):
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES=100
    settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES=total
    assert connection.vendor=='sqlite' and str(connection.settings_dict['NAME'])!=':memory:'
    barrier=Barrier(2)
    def worker(other):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            try: return ('saved',str(upload(quota_work,foreign=other).pk))
            except quotas.CapacityError: return ('quota',None)
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,False),pool.submit(worker,foreign)]
        results=[future.result(timeout=15) for future in futures]
    assert sum(result[0]=='saved' for result in results)==expected
    assert Evidence.objects.count()==expected and quotas.charged_bytes()==70*expected
    assert not EvidenceAllocation.objects.filter(disk_bytes__gt=0).exists()


@pytest.mark.parametrize('status,error',[(507,'low'),(503,'unknown')])
def test_disk_capacity_refuses_before_writes_and_preserves_http_draft(quota_work,client,status,error):
    users,engagement,_,case,_=quota_work
    client.force_login(users['tester'])
    probe=patch('apps.evidence.quotas.disk_probes',side_effect=OSError) if error=='unknown' else patch('apps.evidence.quotas.disk_probes',return_value=[{'free':1,'reserve':2,'inodes_available':10}])
    with probe:
        response=client.post(reverse('evidence:upload',args=[engagement.pk]),{
            'file':SimpleUploadedFile('synthetic.txt',b'private'), 'description':'  UNSAVED\n  draft', 'test_cases':[case.pk]},HTTP_HX_REQUEST='true')
    assert response.status_code==status and 'no-store' in response['Cache-Control']
    assert response.context['form'].data['description']=='  UNSAVED\n  draft'
    assert response.context['form'].data.getlist('test_cases')==[str(case.pk)]
    assert not Evidence.objects.exists() and quotas.charged_bytes()==0
    assert not EvidenceAllocation.objects.exists()
    assert not list(django_settings.EVIDENCE_ROOT.glob('*/*'))


def test_quota_rejection_preserves_fields_after_file_part(quota_work, settings, client):
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES=0
    users,engagement,_,case,_=quota_work;client.force_login(users['tester'])
    response=client.post(reverse('evidence:upload',args=[engagement.pk]),{'file':SimpleUploadedFile('synthetic.txt',b'a'),
        'description':'PRESERVE AFTER FILE', 'test_cases':[case.pk]})
    assert response.status_code==413 and b'PRESERVE AFTER FILE' in response.content
    assert response.context['form'].data.getlist('test_cases')==[str(case.pk)]
    assert not Evidence.objects.exists() and quotas.charged_bytes()==0


def test_lowered_quota_is_rechecked_before_publication(quota_work):
    users,engagement,_,case,_=quota_work
    class Changing:
        name='synthetic.log'
        def chunks(self,**kwargs):
            yield b'a'*70
            quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=60,version=0)
    with pytest.raises(quotas.CapacityError):
        services.upload_evidence(actor=users['tester'],engagement_id=engagement.pk,upload=Changing(),data={'test_cases':[case.pk]})
    assert not Evidence.objects.exists() and quotas.charged_bytes()==0


def test_failed_deletion_remains_charged_until_cleanup(quota_work):
    record=upload(quota_work)
    with patch('apps.evidence.services.storage.remove_file',side_effect=OSError):
        services.remove_evidence(actor=quota_work[0]['tester'],engagement_id=record.engagement_id,evidence_id=record.pk,version=1)
    assert quotas.charged_bytes()==70
    removed,deferred=services.cleanup_orphans(older_than_seconds=3600)
    assert removed==1 and deferred==0 and quotas.charged_bytes()==0


def test_interrupted_upload_releases_reservation(quota_work):
    class Interrupted:
        name='synthetic.log'
        def chunks(self,**kwargs):
            yield b'pending bytes'
            raise OSError
    with pytest.raises(OSError):services.upload_evidence(actor=quota_work[0]['tester'],engagement_id=quota_work[1].pk,
        upload=Interrupted(),data={'test_cases':[quota_work[3].pk]})
    assert quotas.charged_bytes()==0 and not EvidenceAllocation.objects.filter(disk_bytes__gt=0).exists()


def test_reconciliation_dry_run_then_abandoned_lease_cleanup(quota_work):
    users,engagement,*_=quota_work
    reservation=quotas.begin(actor=users['tester'],engagement_id=engagement.pk)
    key,file=storage.create_file(engagement.pk);reservation.attach('staging_key',key);reservation.reserve(70);file.write(b'a'*70);file.close()
    EvidenceAllocation.objects.filter(pk=reservation.id).update(updated_at=timezone.now()-timedelta(days=2))
    os.utime(django_settings.EVIDENCE_ROOT/engagement.pk.hex/key,(time_stamp:=timezone.now().timestamp()-2*86400,time_stamp))
    assert services.cleanup_orphans(older_than_seconds=3600)==(0,1)
    active=quotas.reconcile(actor=users['admin'],apply=True,maintenance=True,older_than_seconds=3600)
    assert active['active']==1 and quotas.charged_bytes()==70
    reservation.lease.__exit__(None,None,None);reservation.closed=True  # Simulate process death, preserving on-disk bytes.
    before=EvidenceAllocation.objects.get(pk=reservation.id)
    dry=quotas.reconcile(actor=users['admin'],older_than_seconds=3600)
    assert dry['released']==1 and EvidenceAllocation.objects.get(pk=reservation.id).version==before.version
    assert (django_settings.EVIDENCE_ROOT/engagement.pk.hex/key).exists()
    result=quotas.reconcile(actor=users['admin'],apply=True,maintenance=True,older_than_seconds=3600)
    assert result['released']==1 and quotas.charged_bytes()==0
    assert not (django_settings.EVIDENCE_ROOT/engagement.pk.hex/key).exists()
    assert AuditEvent.objects.filter(action='evidence_storage.reconciled',actor=users['admin']).exists()


def test_existing_evidence_is_charged_without_migration_file_io(quota_work):
    record=upload(quota_work);EvidenceAllocation.objects.filter(evidence=record).delete()
    assert quotas.charged_bytes()==70
    before=AuditEvent.objects.count()
    result=quotas.reconcile(actor=quota_work[0]['admin'])
    assert result['legacy']==1 and not EvidenceAllocation.objects.exists() and AuditEvent.objects.count()==before
    quotas.reconcile(actor=quota_work[0]['admin'],apply=True,maintenance=True)
    assert quotas.charged_bytes()==70 and EvidenceAllocation.objects.get().evidence_id==record.pk


@pytest.mark.parametrize('role',['lead','tester','reviewer','viewer','outsider'])
def test_admin_storage_and_policy_permissions_http_htmx_and_service(quota_work,client,role):
    users,engagement,foreign,*_=quota_work
    client.force_login(users[role])
    for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
        assert client.get(reverse('core:storage_status'),**headers).status_code==403
        assert client.get(reverse('evidence:quota',args=[engagement.pk]),**headers).status_code==403
    with pytest.raises(PermissionDenied):quotas.set_quota(actor=users[role],engagement_id=engagement.pk,limit_bytes=100,version=0)
    with pytest.raises(PermissionDenied):quotas.system_status(actor=users[role])
    with pytest.raises(PermissionDenied):quotas.reconcile(actor=users[role])
    if role in {'tester','reviewer','viewer'}:
        from django.http import Http404
        with pytest.raises(Http404):quotas.usage(actor=users[role],engagement_id=foreign.pk)


def test_policy_cas_conflicts_and_audit_rollback(quota_work,client):
    users,engagement,*_=quota_work;client.force_login(users['admin'])
    record=quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=100,version=0)
    assert record.version==1
    quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=200,version=1)
    with pytest.raises(EditConflict):quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=300,version=1)
    response=client.post(reverse('evidence:quota',args=[engagement.pk]),{'limit_bytes':300,'version':1})
    assert response.status_code==409 and b'300' in response.content and b'200 bytes' in response.content
    assert response.context['form'].data['limit_bytes']=='300'
    event=AuditEvent.objects.filter(action='evidence_quota.changed').order_by('-chain_sequence').first()
    assert event.before['limit_bytes']==100 and event.after['limit_bytes']==200
    with patch('apps.audit.services.record_event',side_effect=RuntimeError):
        with pytest.raises(RuntimeError):quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=400,version=2)
    assert EvidenceQuota.objects.get(pk=record.pk).limit_bytes==200
    Engagement.objects.filter(pk=engagement.pk).update(status='completed')
    quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=None,version=2)
    assert quotas.limit_for(engagement.pk)==django_settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES


def test_scoped_ui_and_admin_only_disk_warnings(quota_work,client):
    users,engagement,*_=quota_work
    with patch('apps.evidence.quotas.disk_probes',return_value=[{'free':1,'total':100,'reserve':2,'inodes_available':10,'percent_free':1,'warning':True,'label':'Private evidence'}]):
        client.force_login(users['admin'])
        assert b'Storage capacity needs attention' in client.get(reverse('core:storage_status')).content
        assert b'Review storage' in client.get(reverse('core:dashboard')).content
        client.force_login(users['tester'])
        assert b'Review storage' not in client.get(reverse('core:dashboard')).content
        response=client.get(reverse('evidence:list',args=[engagement.pk]))
        assert b'Engagement evidence usage' in response.content and b'Manage evidence quota' not in response.content
        assert b'Upload buffering' not in response.content


def test_reconcile_command_requires_explicit_maintenance_and_current_admin(quota_work):
    users,*_=quota_work
    with pytest.raises(CommandError):call_command('reconcile_evidence_storage',admin=users['tester'].username)
    with pytest.raises(CommandError):call_command('reconcile_evidence_storage',admin=users['admin'].username,apply=True)
    output=io.StringIO();call_command('reconcile_evidence_storage',admin=users['admin'].username,stdout=output)
    assert output.getvalue().startswith('Dry run:')


def test_capacity_lock_rejects_symlink_and_no_file_io_in_writer_transaction(quota_work,tmp_path):
    target=tmp_path/'unchanged';target.write_text('synthetic')
    (django_settings.EVIDENCE_ROOT/'.quota-capacity.lock').symlink_to(target)
    with pytest.raises(OSError):upload(quota_work)
    assert target.read_text()=='synthetic'
    with transaction.atomic():
        with pytest.raises(RuntimeError):quotas.begin(actor=quota_work[0]['tester'],engagement_id=quota_work[1].pk)


def test_invalid_storage_settings_fail_framework_checks(settings):
    from apps.core.checks import storage_configuration
    settings.TRACE_STORAGE_WARNING_PERCENT=100
    settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES=-1
    assert {error.id for error in storage_configuration(None)}=={'evidence.E005','evidence.E006'}


def test_allocation_database_guards_reject_foreign_evidence(quota_work):
    record=upload(quota_work)
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceAllocation.objects.filter(evidence=record).update(engagement=quota_work[2])
    EvidenceAllocation.objects.filter(evidence=record).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceAllocation.objects.bulk_create([EvidenceAllocation(engagement=quota_work[2],evidence=record)])


def test_stale_initial_policy_form_is_a_conflict(quota_work,client):
    users,engagement,*_=quota_work
    client.force_login(users['admin'])
    url=reverse('evidence:quota',args=[engagement.pk])
    assert client.get(url).context['form'].initial['version']==0
    quotas.set_quota(actor=users['admin'],engagement_id=engagement.pk,limit_bytes=0,version=0)
    response=client.post(url,{'limit_bytes':100,'version':0})
    assert response.status_code==409 and response.context['form'].data['limit_bytes']=='100'
    assert EvidenceQuota.objects.get(engagement=engagement).limit_bytes==0


def test_a_separate_process_cannot_spend_an_active_reservation(quota_work,settings):
    users,engagement,_,case,_=quota_work
    settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES=100
    settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES=200
    database=str(connection.settings_dict['NAME'])
    assert 'trace-tests-' in database
    reservation=quotas.begin(actor=users['tester'],engagement_id=engagement.pk)
    reservation.reserve(70)
    code=f"import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.development'; import config.settings.development as configuration; configuration.DATABASES['default']['NAME']={database!r}; import django; django.setup(); from django.contrib.auth import get_user_model; from django.core.files.uploadedfile import SimpleUploadedFile; from apps.evidence.services import upload_evidence; from apps.evidence.quotas import CapacityError; actor=get_user_model().objects.get(pk={users['tester'].pk});\ntry: upload_evidence(actor=actor,engagement_id={str(engagement.pk)!r},upload=SimpleUploadedFile('child.txt',b'a'*70),data={{'test_cases':[{str(case.pk)!r}]}})\nexcept CapacityError: print('quota')\nelse: raise AssertionError('Process overspent reservation')"
    try:
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,timeout=10,
            env={**os.environ,'TRACE_DB_ENGINE':'sqlite','TRACE_STORAGE_ROOT':str(settings.STORAGE_ROOT),
                 'TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES':'100','TRACE_EVIDENCE_TOTAL_QUOTA_BYTES':'200'})
        assert result.returncode==0 and result.stdout.strip().splitlines()[-1]==b'quota'
        assert quotas.charged_bytes()==70
    finally: reservation.close()
    assert quotas.charged_bytes()==0


def test_per_file_rejection_preserves_later_form_fields(quota_work,settings,client):
    settings.TRACE_EVIDENCE_MAX_BYTES=5
    users,engagement,_,case,_=quota_work
    client.force_login(users['tester'])
    response=client.post(reverse('evidence:upload',args=[engagement.pk]),{'file':SimpleUploadedFile('too-big.txt',b'123456'),
        'description':'PRESERVE SIZE FAILURE','test_cases':[case.pk]})
    assert response.status_code==413 and b'PRESERVE SIZE FAILURE' in response.content
    assert response.context['form'].data.getlist('test_cases')==[str(case.pk)]
    assert not Evidence.objects.exists() and not EvidenceAllocation.objects.exists()
