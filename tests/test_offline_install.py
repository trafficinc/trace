import hashlib
import json
from pathlib import Path
import subprocess
import sys


def test_wheel_inventory_validation_rejects_tampering_and_paths(tmp_path):
    path=tmp_path/'fixture.whl'; path.write_bytes(b'not executed fixture')
    manifest={'fixture.whl':hashlib.sha256(path.read_bytes()).hexdigest()}
    (tmp_path/'SHA256SUMS.json').write_text(json.dumps(manifest))
    command=[sys.executable,'scripts/verify_wheels.py',str(tmp_path)]
    assert subprocess.run(command,capture_output=True).returncode==0
    path.write_bytes(b'changed')
    assert subprocess.run(command,capture_output=True).returncode!=0
    (tmp_path/'SHA256SUMS.json').write_text(json.dumps({'../outside.whl':'a'*64}))
    assert subprocess.run(command,capture_output=True).returncode!=0


def test_runtime_locks_and_image_copy_are_explicit():
    root=Path(__file__).resolve().parents[1]
    for file in ['runtime.txt','test.txt','postgres.txt']:
        for line in (root/'requirements'/file).read_text().splitlines():
            if line and not line.startswith(('#','-r')): assert '==' in line and not any(sign in line for sign in ['>=','<=','~=', '*'])
    docker=(root/'Dockerfile').read_text()
    assert 'COPY . .' not in docker and 'USER trace' in docker
    assert 'COPY static' in docker and 'COPY apps' in docker
