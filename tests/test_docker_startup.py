"""Opt-in real Compose smoke test, with its own disposable named volume/network."""
import os
import secrets
import socket
import subprocess
import urllib.request
import uuid
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('TRACE_RUN_DOCKER_TESTS')!='1',reason='Set TRACE_RUN_DOCKER_TESTS=1 with Docker running to exercise Compose.')


def test_real_compose_native_database_and_image_hygiene(tmp_path):
    project='trace-check-'+uuid.uuid4().hex[:12]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    envfile=tmp_path/'compose.env'
    envfile.write_text('TRACE_SECRET_KEY='+secrets.token_urlsafe(64)+'\nTRACE_ALLOWED_HOSTS=localhost,127.0.0.1\nTRACE_CSRF_TRUSTED_ORIGINS=https://localhost\nTRACE_PUBLISH_PORT='+str(port)+'\n')
    os.chmod(envfile,0o600)
    compose=['docker','compose','-p',project,'--env-file',str(envfile)]
    def run(args,**kwargs):
        result=subprocess.run(args,capture_output=True,text=True,**kwargs)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    try:
        run(compose+['config','--quiet'])
        run(compose+['run','--rm','trace','python','manage.py','migrate','--noinput'])
        run(compose+['run','--rm','trace','python','manage.py','check','--deploy','--fail-level','WARNING'])
        run(compose+['up','-d','--no-build','--wait','--wait-timeout','90'])
        # Linux-only no-replace publication and real resource-limited adapters.
        code = "from pathlib import Path; import tempfile; from apps.core.backups import publish; p=Path(tempfile.mkdtemp()); s=p/'stage'; s.mkdir(); (s/'data').write_text('synthetic'); publish(s,p/'published'); assert (p/'published/data').read_text()=='synthetic'; s.mkdir(); publish(s,p/'second'); s.mkdir();\ntry: publish(s,p/'second')\nexcept FileExistsError: pass\nelse: raise AssertionError('overwrote destination')"
        run(compose+['exec','-T','trace','python','manage.py','shell','-c',code])
        render = "from apps.accounts.models import User; from apps.engagements.models import Engagement; from apps.reports.services import save_report,generate_report; u=User.objects.create_superuser('synthetic-container-render'); e=Engagement.objects.create(name='Synthetic container report'); from apps.testcases.models import TestCase; from apps.evidence.services import upload_evidence; from apps.evidence.quotas import charged_bytes; from django.core.files.uploadedfile import SimpleUploadedFile; c=TestCase.objects.create(engagement=e,title='Synthetic container evidence'); f=upload_evidence(actor=u,engagement_id=e.pk,upload=SimpleUploadedFile('container.txt',b'container evidence'),data={'test_cases':[c.pk]}); assert charged_bytes(e.pk)==f.size and f.storage_allocation.disk_bytes==0; r=save_report(actor=u,engagement_id=e.pk,data={'title':'Synthetic offline render','include_images':False},finding_ids=[]); v=generate_report(actor=u,engagement_id=e.pk,report_id=r.pk,version=1); assert v.status=='ready'; assert set(v.artifacts.values_list('format',flat=True))=={'html','docx','pdf','snapshot'}"
        run(compose+['exec','-T','trace','python','manage.py','shell','-c',render])
        identifier=run(compose+['ps','-q','trace'])
        status=run(['docker','inspect','--format','{{.State.Health.Status}}',identifier])
        assert status=='healthy',run(compose+['logs','--no-log-prefix','trace'])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/',timeout=5) as response:
            assert response.status==200 and response.read()==b'{"status": "ok"}'
        # The disposable image itself contains no operational database or upload.
        code="from pathlib import Path; root=Path('/app'); assert not list(root.rglob('*.sqlite3')); assert not list(root.rglob('*.db')); assert not (root/'.env').exists(); assert not list(Path('/storage').iterdir())"
        run(['docker','run','--rm','--entrypoint','python','trace-local:0.1.0','-c',code])
    finally:
        # Only this test's UUID-named volume/network are removed.
        subprocess.run(compose+['down','--volumes','--timeout','5'],capture_output=True)


def test_compose_https_proxy_with_verified_certificate(tmp_path):
    import ssl
    project='trace-tls-'+uuid.uuid4().hex[:12]
    tls=tmp_path/'tls'; tls.mkdir(mode=0o700)
    generation=subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-subj','/CN=localhost',
        '-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(tls/'trace.key'),'-out',str(tls/'trace.crt'),'-days','1'],capture_output=True)
    assert generation.returncode==0
    os.chmod(tls/'trace.key',0o600)
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); return sock.getsockname()[1]
    backend_port,https_port=free_port(),free_port()
    envfile=tmp_path/'tls.env'
    envfile.write_text('TRACE_SECRET_KEY='+secrets.token_urlsafe(64)+'\nTRACE_ALLOWED_HOSTS=localhost,127.0.0.1\nTRACE_CSRF_TRUSTED_ORIGINS=https://localhost:'+str(https_port)+'\nTRACE_PUBLISH_PORT='+str(backend_port)+'\nTRACE_HTTPS_PUBLISH_PORT='+str(https_port)+'\nTRACE_TLS_DIRECTORY='+str(tls)+'\nTRACE_PROXY_IP=172.30.86.3\n')
    os.chmod(envfile,0o600)
    compose=['docker','compose','-p',project,'--env-file',str(envfile),'--profile','https']
    def run(args):
        result=subprocess.run(args,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        return result.stdout
    try:
        run(compose+['config','--quiet'])
        run(compose+['run','--rm','trace','python','manage.py','migrate','--noinput'])
        run(compose+['up','-d','--no-build','--wait','--wait-timeout','90'])
        context=ssl.create_default_context(cafile=str(tls/'trace.crt'))
        # Verify the isolated test CA, hostname, trusted peer and final app page;
        # no certificate-verification bypass or pretend HTTPS scheme is used.
        with urllib.request.urlopen(f'https://localhost:{https_port}/accounts/login/',context=context,timeout=10) as response:
            assert response.status==200 and b'csrfmiddlewaretoken' in response.read()
            assert 'no-store' in response.headers['Cache-Control']
        with urllib.request.urlopen(f'https://localhost:{https_port}/health/',context=context,timeout=10) as response:
            assert response.read()==b'{"status": "ok"}'
    finally:
        subprocess.run(compose+['down','--volumes','--timeout','5'],capture_output=True)
