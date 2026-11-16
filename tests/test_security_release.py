"""Adversarial release regressions; exclusively synthetic records and temporary files."""
from html.parser import HTMLParser
import io
import json
import os
import secrets
import signal
import subprocess
import sys
import zipfile
import pytest
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from apps.accounts.services import set_account_active
from apps.assets.models import Asset
from apps.audit.models import AuditEvent
from apps.audit.redaction import redact_text
from apps.core import backups
from apps.evidence.services import upload_evidence
from apps.findings.formatting import render_narrative
from apps.findings.services import save_finding
from apps.reports import services as reports, storage
from apps.reports.capacity import render_slot
from apps.reports.models import ReportRevision, ReportArtifact
from apps.reports.rendering import RenderError
from apps.testcases.models import TestCase as Case

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def secure_work(access_setup, settings, tmp_path):
    users, engagement, foreign = access_setup
    root = tmp_path / 'storage'
    root.mkdir(mode=0o700)
    settings.STORAGE_ROOT = root
    settings.EVIDENCE_ROOT = root / 'evidence'
    settings.REPORT_ROOT = root / 'reports'
    settings.EVIDENCE_ROOT.mkdir(mode=0o700)
    settings.REPORT_ROOT.mkdir(mode=0o700)
    settings.TRACE_REPORT_CONCURRENT_EXPORTS = 1
    case = Case.objects.create(engagement=engagement, title='Synthetic security test')
    foreign_case = Case.objects.create(engagement=foreign, title='FOREIGN_RECORD_CANARY')
    asset = Asset.objects.create(engagement=foreign, name='FOREIGN_RECORD_CANARY')
    finding = save_finding(actor=users['tester'], engagement_id=engagement.pk,
                           data={'title':'Synthetic finding','severity':'low','description':'<script>alert(1)</script>'})
    other_finding = save_finding(actor=users['outsider'],engagement_id=foreign.pk,data={'title':'FOREIGN_RECORD_CANARY','severity':'low'})
    evidence = upload_evidence(actor=users['outsider'],engagement_id=foreign.pk,
        upload=SimpleUploadedFile('foreign.txt',b'SYNTHETIC_FILE_CANARY'),data={'description':'Synthetic','test_cases':[foreign_case.pk]})
    report = reports.save_report(actor=users['tester'],engagement_id=engagement.pk,
        data={'title':'Synthetic report','include_images':False},finding_ids=[finding.pk])
    foreign_report = reports.save_report(actor=users['outsider'],engagement_id=foreign.pk,
        data={'title':'FOREIGN_RECORD_CANARY','include_images':False},finding_ids=[other_finding.pk])
    return users,engagement,foreign,case,finding,report,[("assets",asset.pk),("testcases",foreign_case.pk),("findings",other_finding.pk),("evidence",evidence.pk),("reports",foreign_report.pk)]


@pytest.mark.parametrize('role',['lead','tester','reviewer','viewer','admin'])
def test_foreign_objects_never_resolve_under_another_parent(secure_work,client,role):
    users,engagement,_,_,_,_,objects=secure_work
    client.force_login(users[role])
    for namespace,pk in objects:
        for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
            response=client.get(reverse(namespace+':detail',args=[engagement.pk,pk]),**headers)
            assert response.status_code in {403,404}
            assert b'FOREIGN_RECORD_CANARY' not in response.content and b'SYNTHETIC_FILE_CANARY' not in response.content
            assert response['Cache-Control']=='no-store, private'


def test_real_csrf_checks_cover_forms_logout_and_presence(secure_work):
    users,engagement,_,_,finding,_,_=secure_work
    client=Client(enforce_csrf_checks=True)
    client.force_login(users['tester'])
    count=AuditEvent.objects.count()
    targets=[reverse('accounts:profile'),reverse('accounts:logout'),reverse('findings:edit',args=[engagement.pk,finding.pk]),
        reverse('evidence:upload',args=[engagement.pk]),reverse('reports:create',args=[engagement.pk]),
        reverse('core:engagement_editor_presence',args=[engagement.pk,'finding',finding.pk])]
    for url in targets:
        response=client.post(url,{'version':1,'title':'UNSAVED_CSRF_CANARY'})
        assert response.status_code==403 and response['Cache-Control']=='no-store, private'
    assert AuditEvent.objects.count()==count
    client.get(reverse('accounts:login'))
    token=client.cookies[settings.CSRF_COOKIE_NAME].value
    data={'first_name':'Synthetic tester','last_name':'','email':'','version':1}
    assert client.post(reverse('accounts:profile'),data,HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://foreign.invalid').status_code==403
    assert client.post(reverse('accounts:profile'),data,HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='http://testserver').status_code==302
    assert client.get(reverse('accounts:logout')).status_code==405


def test_login_rotation_open_redirect_and_disabled_session(secure_work):
    users,_,_,_,_,_,_=secure_work
    actor=users['tester']; password=secrets.token_urlsafe(32)
    actor.set_password(password); actor.save(update_fields=['password'])
    client=Client()
    session=client.session; session['synthetic_prelogin']=True; session.save()
    previous=session.session_key
    response=client.post(reverse('accounts:login'),{'username':actor.username,'password':password,'next':'https://foreign.invalid/'})
    assert response.status_code==302 and response['Location']=='/'
    assert client.session.session_key!=previous
    set_account_active(actor=users['admin'],user_id=actor.pk,active=False,version=1)
    set_account_active(actor=users['admin'],user_id=actor.pk,active=True,version=2)
    assert client.get(reverse('core:dashboard')).status_code==302
    assert password not in json.dumps(list(AuditEvent.objects.values()),default=str)


class NarrativeMarkup(HTMLParser):
    def __init__(self,html):
        super().__init__(); self.elements=[]; self.feed(html)
    def handle_starttag(self,tag,attrs): self.elements.append((tag,dict(attrs)))


@pytest.mark.parametrize('payload',[
    '<img src=x onerror=alert(1)>','<svg onload=alert(1)>','[x](javascript:alert(1))',
    '[x](data:text/html;base64,PHNjcmlwdD4=)','[x](https://example.test/" onclick="alert(1))',
    '[**label**](https://example.test/`code`)','![image](https://foreign.invalid/pixel)',
    '{{ SECRET_KEY }} {% include "private" %}','[x](https://[invalid/)',
    '**<script>alert(1)</script>**\n```\n<img onerror=1>\n```',
])
def test_narratives_only_emit_allowlisted_tags_and_attributes(payload):
    rendered=str(render_narrative(payload))
    parsed=NarrativeMarkup(rendered)
    allowed={'p','br','strong','em','code','pre','ul','ol','li','h3','h4','h5','h6','a'}
    for tag,attrs in parsed.elements:
        assert tag in allowed
        if tag=='a':
            assert set(attrs)=={'href','rel'} and attrs['href'].startswith(('https://','http://'))
        else: assert not attrs
    assert '<script' not in rendered and '<img' not in rendered and '<svg' not in rendered


def test_hostile_plain_text_is_processed_within_a_fixed_budget():
    code="from apps.findings.formatting import render_narrative; from apps.audit.redaction import redact_text; render_narrative('['*40000); [redact_text('a-a'*14000) for _ in range(7)]; print('bounded')"
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,timeout=5)
    assert result.returncode==0 and result.stdout.strip()==b'bounded'
    assert 'private-secret' not in redact_text('jdbc:postgresql://user:private-secret@host/db')


def test_report_workers_have_limits_no_credentials_and_safe_outputs(secure_work,monkeypatch):
    users,engagement,_,_,_,report,_=secure_work
    import apps.reports.rendering as rendering
    original=rendering.subprocess.Popen
    calls=[]
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','ENVIRONMENT_SECRET_CANARY')
    def checked(command,**kwargs):
        assert kwargs['start_new_session'] and len(kwargs['pass_fds'])==3
        assert 'AWS_SECRET_ACCESS_KEY' not in kwargs['env'] and 'TRACE_SECRET_KEY' not in kwargs['env'] and 'TRACE_DB_PASSWORD' not in kwargs['env']
        calls.append(command)
        return original(command,**kwargs)
    monkeypatch.setattr(rendering.subprocess,'Popen',checked)
    revision=reports.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=report.pk,version=1)
    assert revision.status=='ready' and len(calls)==1
    for artifact in revision.artifacts.all():
        with storage.open_file(engagement.pk,artifact.storage_key) as file: payload=file.read()
        assert b'ENVIRONMENT_SECRET_CANARY' not in payload
        if artifact.format=='html': assert b'<script>alert(1)</script>' not in payload
        elif artifact.format=='docx':
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                assert not any('vbaproject' in name.lower() for name in archive.namelist())
    assert not any(path.name.startswith('.render-') and path.is_dir() for path in settings.REPORT_ROOT.iterdir())


def test_report_timeout_is_generic_and_releases_capacity(secure_work,monkeypatch):
    users,engagement,_,_,_,report,_=secure_work
    import apps.reports.rendering as rendering
    class Hung:
        pid=123456789
        count=0
        def wait(self,timeout=None):
            self.count+=1
            if self.count==1: raise subprocess.TimeoutExpired('fixed worker',timeout)
            return -signal.SIGKILL
    killed=[]
    monkeypatch.setattr(rendering.subprocess,'Popen',lambda *args,**kwargs:Hung())
    monkeypatch.setattr(rendering.os,'killpg',lambda pid,sig:killed.append((pid,sig)))
    with pytest.raises(RenderError,match='time limit'):
        reports.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=report.pk,version=1)
    assert killed==[(Hung.pid,signal.SIGKILL)]
    assert ReportRevision.objects.get(report=report).status=='failed' and not ReportArtifact.objects.exists()
    with render_slot(): pass


def test_report_capacity_is_shared_by_processes_and_authorized_first(secure_work):
    users,engagement,_,_,_,report,_=secure_work
    code=f"from pathlib import Path; from django.conf import settings; settings.configure(REPORT_ROOT=Path({str(settings.REPORT_ROOT)!r}), EVIDENCE_ROOT=Path({str(settings.EVIDENCE_ROOT)!r}), STATIC_ROOT=Path({str(settings.STATIC_ROOT)!r}), STATICFILES_DIRS=[], TRACE_REPORT_CONCURRENT_EXPORTS=1); from apps.reports.capacity import render_slot; from django.core.exceptions import ValidationError;\ntry:\n with render_slot(): print('unexpected capacity')\nexcept ValidationError: print('busy')"
    with render_slot():
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,timeout=5)
        assert result.returncode==0 and result.stdout.strip()==b'busy'
        with pytest.raises(PermissionDenied): reports.generate_report(actor=users['viewer'],engagement_id=engagement.pk,report_id=report.pk,version=1)
        with pytest.raises(ValidationError,match='capacity'): reports.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=report.pk,version=1)
    assert not ReportRevision.objects.exists()


def test_backup_publication_does_not_replace_a_raced_destination(secure_work,tmp_path,monkeypatch):
    users,*_=secure_work
    original=backups.publish
    inodes=[]
    def raced(stage,destination):
        destination.mkdir(mode=0o700)
        inodes.append(destination.stat().st_ino)
        original(stage,destination)
    monkeypatch.setattr(backups,'publish',raced)
    destination=tmp_path/'raced-backup'
    with pytest.raises(FileExistsError): backups.create_backup(actor=users['admin'],output=destination,maintenance=True)
    assert destination.is_dir() and destination.stat().st_ino==inodes[0] and not list(destination.iterdir())
    assert not list(tmp_path.glob('.backup-*'))


def test_test_settings_cannot_inherit_an_operator_database(tmp_path):
    env={**os.environ,'DJANGO_SETTINGS_MODULE':'config.settings.test','TRACE_DB_ENGINE':'postgresql','TRACE_DB_HOST':'192.0.2.1','TRACE_DB_NAME':'DO_NOT_CONNECT','TRACE_DB_USER':'DO_NOT_CONNECT','TRACE_STORAGE_ROOT':str(tmp_path/'operator')}
    code="from config.settings import test as s; assert s.DATABASES['default']['ENGINE']=='django.db.backends.sqlite3'; assert s.STORAGE_ROOT.name.startswith('trace-tests-'); print('disposable')"
    result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=5)
    assert result.returncode==0 and result.stdout.strip()==b'disposable'


def test_outer_middleware_marks_early_responses_private():
    from django.http import HttpResponse
    from django.test import RequestFactory
    from apps.core.middleware import RequestLogMiddleware
    for status in [301, 400, 403, 500]:
        response = RequestLogMiddleware(lambda request: HttpResponse(status=status))(RequestFactory().get('/accounts/login/'))
        assert response['Cache-Control'] == 'no-store, private'
        assert len(response['X-Request-ID']) == 32


def test_pytest_rejects_operator_settings_before_collection(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'pytest', '--ds=config.settings.development', '--collect-only', '-q', 'tests/test_security_release.py'],
        env={**os.environ, 'TRACE_STORAGE_ROOT':str(tmp_path/'unused-operator')}, capture_output=True, timeout=15)
    assert result.returncode == 4 and b'production/development databases are forbidden' in result.stderr
    assert not list(tmp_path.rglob('*.sqlite3'))
