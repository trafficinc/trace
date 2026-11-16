"""Fixed, credential-free, resource-limited HTML/DOCX/PDF adapter process."""
import json
import logging
import os
from pathlib import Path
import resource
import sys

logging.disable(logging.CRITICAL)


def main():
    output, base, snapshot_limit, artifact_limit, seconds, libraries = sys.argv[1:]
    snapshot_limit, artifact_limit, seconds = int(snapshot_limit), int(artifact_limit), int(seconds)
    resource.setrlimit(resource.RLIMIT_CPU, (min(seconds, 60), min(seconds, 60)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (artifact_limit, artifact_limit))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    except (ValueError, OSError):
        if sys.platform != 'darwin':
            raise
    from django.conf import settings
    settings.configure(BASE_DIR=Path(base), USE_I18N=False, USE_TZ=True,
        TRACE_REPORT_MAX_ARTIFACT_BYTES=artifact_limit, TRACE_REPORT_RENDER_TIMEOUT=seconds,
        TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES=libraries)
    raw = sys.stdin.buffer.read(snapshot_limit + 1)
    if len(raw) > snapshot_limit:
        raise ValueError('Snapshot limit exceeded.')
    snapshot = json.loads(raw)
    from .rendering import html_report, docx_report
    from .pdf_worker import render_pdf
    html = html_report(snapshot).encode()
    descriptors = json.loads(output)
    if len(descriptors) != 3 or any(type(fd) is not int for fd in descriptors):
        raise ValueError('Invalid output descriptors.')
    for descriptor, render in zip(descriptors, [lambda: html, lambda: docx_report(snapshot), lambda: render_pdf(html)]):
        data = render()
        if not data or len(data) > artifact_limit:
            raise ValueError('Output limit exceeded.')
        with os.fdopen(os.dup(descriptor), 'wb') as file:
            file.write(data)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(1)
