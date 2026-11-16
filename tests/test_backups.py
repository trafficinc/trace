import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.db import connection
from apps.core.backups import create_backup, validate_backup, restore_backup, BackupError
from apps.core.maintenance import exclusive_maintenance, MaintenanceError
from apps.evidence.services import upload_evidence
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark=pytest.mark.django_db(transaction=True)


@pytest.fixture
def backup_setup(access_setup,settings,tmp_path):
    users,engagement,foreign=access_setup
    root=tmp_path/'storage'; root.mkdir(mode=0o700)
    settings.STORAGE_ROOT=root
    settings.EVIDENCE_ROOT=root/'evidence'; settings.EVIDENCE_ROOT.mkdir(mode=0o700)
    settings.REPORT_ROOT=root/'reports'; settings.REPORT_ROOT.mkdir(mode=0o700)
    from apps.testcases.models import TestCase
    case=TestCase.objects.create(engagement=engagement,title='Backup case')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('output.txt',b'private evidence\n'),data={'description':'Context','test_cases':[case.pk]})
    return users,engagement,evidence,tmp_path


def backup(data):
    users,_,_,root=data
    target=root/'verified-backup'
    return target,create_backup(actor=users['admin'],output=target,maintenance=True)


def test_consistent_sqlite_and_files_roundtrip(backup_setup):
    users,engagement,evidence,root=backup_setup
    from apps.engagements.services import save_note
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode=WAL')
        assert cursor.fetchone()[0]=='wal'
        cursor.execute('PRAGMA wal_autocheckpoint=0')
    note=save_note(actor=users['tester'],engagement_id=engagement.pk,body='Committed WAL proof')
    assert Path(str(connection.settings_dict['NAME'])+'-wal').exists()
    output,manifest=backup(backup_setup)
    assert manifest['files']['database.sqlite3']['size']>0
    name=f'evidence/{engagement.pk.hex}/{evidence.storage_key}'
    assert (output/name).read_bytes()==b'private evidence\n'
    assert manifest['files'][name]['sha256']==evidence.sha256
    assert validate_backup(output)==manifest
    destination=root/'restored'
    restore_backup(source=output,destination=destination,maintenance=True)
    with sqlite3.connect(destination/'db/tdt.sqlite3') as database:
        assert database.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert database.execute('SELECT body FROM engagements_engagementnote WHERE id=?',(note.pk.hex,)).fetchone()==('Committed WAL proof',)
        assert database.execute('SELECT sha256 FROM evidence_evidence WHERE id=?',(evidence.pk.hex,)).fetchone()==(evidence.sha256,)
    assert (destination/name).read_bytes()==b'private evidence\n'
    assert not (destination/'db/tdt.sqlite3-wal').exists()
    assert (destination/'db/tdt.sqlite3').stat().st_mode&0o777==0o600
    assert destination.stat().st_mode&0o777==0o700


def test_backup_requires_current_admin_and_maintenance(backup_setup):
    users,_,_,root=backup_setup
    for role in ['lead','tester','reviewer','viewer','outsider']:
        with pytest.raises(PermissionDenied): create_backup(actor=users[role],output=root/role,maintenance=True)
    with pytest.raises(MaintenanceError): create_backup(actor=users['admin'],output=root/'missing-confirmation')
    with exclusive_maintenance(True):
        with pytest.raises(MaintenanceError): create_backup(actor=users['admin'],output=root/'locked',maintenance=True)


@pytest.mark.parametrize('mutation',['file','database','missing','extra','traversal','symlink','hardlink'])
def test_restore_rejects_corrupt_and_unsafe_backups(backup_setup,mutation):
    _,_,evidence,root=backup_setup
    output,manifest=backup(backup_setup)
    name=next(name for name in manifest['files'] if name.startswith('evidence/'))
    if mutation=='file': (output/name).write_bytes(b'changed')
    elif mutation=='database':
        with open(output/'database.sqlite3','ab') as file: file.write(b'changed')
    elif mutation=='missing': (output/name).unlink()
    elif mutation=='extra': (output/'unexpected').write_text('unexpected')
    elif mutation=='traversal':
        manifest['files']['../escape']={'size':1,'sha256':'a'*64}
        (output/'manifest.json').write_text(json.dumps(manifest))
    elif mutation=='symlink':
        (output/name).unlink(); (output/name).symlink_to('/etc/passwd')
    elif mutation=='hardlink': os.link(output/name,root/'linked')
    target=root/'must-not-publish'
    with pytest.raises((BackupError,OSError)):
        restore_backup(source=output,destination=target,maintenance=True)
    assert not target.exists()


def test_interrupted_backup_cleanup_and_no_overwrite(backup_setup,monkeypatch):
    users,_,_,root=backup_setup
    import apps.core.backups as service
    original=service.shutil.copyfileobj
    def interrupted(*args,**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr(service.shutil,'copyfileobj',interrupted)
    with pytest.raises(KeyboardInterrupt): create_backup(actor=users['admin'],output=root/'interrupted',maintenance=True)
    assert not (root/'interrupted').exists() and not list(root.glob('.backup-*'))
    monkeypatch.setattr(service.shutil,'copyfileobj',original)
    output,_=backup(backup_setup)
    target=root/'existing'; target.mkdir(mode=0o700); (target/'sentinel').write_text('keep')
    with pytest.raises(BackupError): restore_backup(source=output,destination=target,maintenance=True)
    assert (target/'sentinel').read_text()=='keep'


def test_commands_validate_only_and_report_generic_errors(backup_setup):
    output,_=backup(backup_setup)
    buffer=io.StringIO()
    call_command('restore_tdt',source=str(output),validate_only=True,stdout=buffer)
    assert 'No files restored' in buffer.getvalue()
    with pytest.raises(CommandError): call_command('restore_tdt',source=str(output))
    with pytest.raises(CommandError): call_command('backup_tdt',admin='tester',output=str(output.parent/'denied'),maintenance=True)


def test_backup_includes_thumbnails_and_report_artifacts(backup_setup):
    import io
    from PIL import Image
    from apps.reports.models import Report, ReportRevision, ReportArtifact
    from apps.reports import storage
    users,engagement,evidence,root=backup_setup
    image=io.BytesIO(); Image.new('RGB',(16,16),'red').save(image,format='PNG')
    screenshot=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('screen.png',image.getvalue()),data={'description':'Screenshot','test_cases':[evidence.test_cases.first().pk]})
    report=Report.objects.create(engagement=engagement,title='Backup report')
    revision=ReportRevision.objects.create(report=report,engagement=engagement,number=1,report_version=1,generated_by=users['tester'])
    key,file=storage.create_file(engagement.pk)
    with file:
        file.write(b'private report artifact'); storage.sync_file(file,engagement.pk)
    ReportArtifact.objects.create(revision=revision,engagement=engagement,format='docx',storage_key=key,size=23,sha256=hashlib.sha256(b'private report artifact').hexdigest())
    output,manifest=backup(backup_setup)
    assert f'evidence/{engagement.pk.hex}/{screenshot.thumbnail_key}' in manifest['files']
    assert f'reports/{engagement.pk.hex}/{key}' in manifest['files']
    assert validate_backup(output)==manifest


def test_recovery_preserves_evidence_images_and_all_report_artifacts(backup_setup):
    users,engagement,evidence,root=backup_setup
    from PIL import Image
    from apps.findings.services import save_finding
    from apps.reports import services as reports, storage as report_storage
    from apps.reports.models import ReportArtifact
    image=io.BytesIO(); Image.new('RGB',(32,24),'blue').save(image,format='PNG')
    case=evidence.test_cases.get()
    finding=save_finding(actor=users['tester'],engagement_id=engagement.pk,
        data={'title':'Synthetic recovery finding','severity':'low','test_cases':[case.pk]})
    screenshot=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('synthetic-recovery.png',image.getvalue()),
        data={'description':'Synthetic recovery image','test_cases':[case.pk],'findings':[finding.pk]})
    report=reports.save_report(actor=users['tester'],engagement_id=engagement.pk,
        data={'title':'Synthetic recovery report','include_images':True},finding_ids=[finding.pk])
    revision=reports.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=report.pk,version=1)
    artifacts={}
    for artifact in revision.artifacts.all():
        with report_storage.open_file(engagement.pk,artifact.storage_key) as file: artifacts[artifact.storage_key]=file.read()
    assert set(revision.artifacts.values_list('format',flat=True))=={'html','docx','pdf','snapshot'}
    output,manifest=backup(backup_setup)
    target=root/'recovered-with-reports'
    restore_backup(source=output,destination=target,maintenance=True)
    assert validate_backup(output)==manifest
    for name,metadata in manifest['files'].items():
        recovered=target/('db/tdt.sqlite3' if name=='database.sqlite3' else name)
        assert recovered.stat().st_size==metadata['size']
        assert hashlib.sha256(recovered.read_bytes()).hexdigest()==metadata['sha256']
    for key,payload in artifacts.items(): assert (target/'reports'/engagement.pk.hex/key).read_bytes()==payload
    assert (target/'evidence'/engagement.pk.hex/screenshot.thumbnail_key).is_file()
    with sqlite3.connect(target/'db/tdt.sqlite3') as database:
        assert database.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert not database.execute('PRAGMA foreign_key_check').fetchall()
        assert database.execute('SELECT status FROM reports_reportrevision WHERE id=?',(revision.pk.hex,)).fetchone()==('ready',)
        assert database.execute('SELECT finding_id FROM reports_reportfinding WHERE report_id=?',(report.pk.hex,)).fetchone()==(finding.pk.hex,)
        assert database.execute('SELECT COUNT(*) FROM reports_reportartifact').fetchone()==(4,)
    assert ReportArtifact.objects.count()==4
