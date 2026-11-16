#!/usr/bin/env python3
"""Prepare exact binary wheels on a CONNECTED matching OS/Python/architecture."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess  # nosec B404
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory',required=True)
parser.add_argument('--postgres',action='store_true')
parser.add_argument('--test',action='store_true')
parser.add_argument('--quality',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
output=Path(args.directory).absolute()
if output.exists(): parser.error('Use a new wheel directory.')
output.mkdir(mode=0o700)
requirements=['-r',str(root/'requirements'/('quality.txt' if args.quality else 'test.txt' if args.test else 'runtime.txt'))]
if args.postgres: requirements+=['-r',str(root/'requirements/postgres.txt')]
subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:','--dest',str(output),*requirements],check=True)  # nosec B603
files={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(output.glob('*.whl'))}
(output/'SHA256SUMS.json').write_text(json.dumps(files,indent=2,sort_keys=True)+'\n')
print(f'Prepared {len(files)} wheels. Transfer them with the matching lock files and a separately trusted manifest.')
