import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import pytest

RUN=os.environ.get('TRACE_RUN_STARTUP_TESTS')=='1'


def test_bind_defaults_fail_closed():
    for args in [['--host','0.0.0.0'],['--host','0.0.0.0','--allow-lan','--development']]:
        result=subprocess.run([sys.executable,'scripts/serve.py',*args],capture_output=True)
        assert result.returncode!=0 and b'Non-loopback binding requires' in result.stderr


@pytest.mark.skipif(not RUN,reason='Set TRACE_RUN_STARTUP_TESTS=1 to bind temporary loopback servers.')
@pytest.mark.parametrize('trusted',['0','1'])
def test_actual_native_production_startup_and_proxy_headers(tmp_path,trusted):
    root=tmp_path/'native'; root.mkdir(mode=0o700)
    env={**os.environ,'DJANGO_SETTINGS_MODULE':'config.settings.production',
         'TRACE_STORAGE_ROOT':str(root),'TRACE_DB_ENGINE':'sqlite',
         'TRACE_SECRET_KEY':secrets.token_urlsafe(64),'TRACE_ALLOWED_HOSTS':'localhost,127.0.0.1',
         'TRACE_CSRF_TRUSTED_ORIGINS':'https://localhost','TRACE_TRUST_PROXY':trusted,'TRACE_PROXY_IP':'127.0.0.1'}
    for command in [['migrate','--noinput'],['check','--deploy','--fail-level','WARNING']]:
        result=subprocess.run([sys.executable,'manage.py',*command],env=env,capture_output=True)
        assert result.returncode==0,result.stderr.decode()
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1',0)); port=temporary.getsockname()[1]
    log=open(tmp_path/'server.log','w+b')
    server=subprocess.Popen([sys.executable,'scripts/serve.py','--port',str(port)],env=env,stdout=log,stderr=log)
    try:
        url=f'http://127.0.0.1:{port}'
        for attempt in range(100):
            try:
                with urllib.request.urlopen(url+'/health/',timeout=1) as response: assert response.read()==b'{"status": "ok"}'
                break
            except (OSError,urllib.error.URLError):
                if server.poll() is not None: raise AssertionError('Native server exited before readiness.')
                time.sleep(.1)
        else: raise AssertionError('Native readiness timed out.')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        opener=urllib.request.build_opener(NoRedirect)
        request=urllib.request.Request(url+'/accounts/login/',headers={'X-Forwarded-Proto':'https'})
        if trusted=='1':
            with opener.open(request,timeout=5) as response:
                assert response.status==200 and 'no-store' in response.headers['Cache-Control']
        else:
            with pytest.raises(urllib.error.HTTPError) as error: opener.open(request,timeout=5)
            assert error.value.code==301 and error.value.headers['Location'].startswith('https://')
        # Running WSGI process holds the shared maintenance gate.
        check='import django; django.setup(); from apps.core.maintenance import exclusive_maintenance;\nwith exclusive_maintenance(True): pass'
        result=subprocess.run([sys.executable,'-c',check],env=env,capture_output=True)
        assert result.returncode!=0 and b'Stop all application workers' in result.stderr
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait()
        log.close()


@pytest.mark.skipif(not RUN,reason='Set TRACE_RUN_STARTUP_TESTS=1 to bind a temporary loopback server.')
def test_native_development_serves_bundled_static_assets(tmp_path):
    root=tmp_path/'development'; root.mkdir(mode=0o700)
    env={**os.environ,'TRACE_STORAGE_ROOT':str(root),'TRACE_DB_ENGINE':'sqlite',
         'DJANGO_SETTINGS_MODULE':'config.settings.development','TRACE_ALLOWED_HOSTS':'localhost,127.0.0.1'}
    migration=subprocess.run([sys.executable,'manage.py','migrate','--noinput'],env=env,capture_output=True)
    assert migration.returncode==0
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1',0)); port=temporary.getsockname()[1]
    server=subprocess.Popen([sys.executable,'scripts/serve.py','--development','--port',str(port)],env=env,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                with urllib.request.urlopen(base+'/health/',timeout=1) as response: assert response.status==200
                break
            except OSError:
                if server.poll() is not None: raise AssertionError('Development server exited before readiness.')
                time.sleep(.1)
        else: raise AssertionError('Development readiness timed out.')
        for path,content in [('css/app.css',b'.trace-shell'),('js/app.js',b'data-sidebar-toggle')]:
            with urllib.request.urlopen(base+'/static/'+path,timeout=5) as response:
                assert response.status==200 and content in response.read()
        with pytest.raises(urllib.error.HTTPError) as error: urllib.request.urlopen(base+'/media/db/tdt.sqlite3',timeout=5)
        assert error.value.code==404
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait()
