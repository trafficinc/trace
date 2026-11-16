#!/usr/bin/env python3
"""Validate a transferred wheelhouse without importing or executing its wheels."""
import hashlib
import json
from pathlib import Path
import sys

root=Path(sys.argv[1])
expected=json.loads((root/'SHA256SUMS.json').read_text())
if not expected or set(expected)!={file.name for file in root.iterdir() if file.name!='SHA256SUMS.json'}: raise SystemExit('Wheel inventory mismatch.')
for name,digest in expected.items():
    if Path(name).name!=name or not name.endswith('.whl'): raise SystemExit('Unsafe wheel path.')
    file=root/name
    if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest: raise SystemExit('Wheel integrity mismatch.')
print('Offline wheel inventory and hashes verified.')
