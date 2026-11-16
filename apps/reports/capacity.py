"""Bound concurrent exports across local WSGI workers without holding DB locks."""
from contextlib import contextmanager
import fcntl
import os
from django.conf import settings
from django.core.exceptions import ValidationError
from . import storage


@contextmanager
def render_slot():
    descriptor = None
    with storage.root_directory() as root:
        for number in range(settings.TRACE_REPORT_CONCURRENT_EXPORTS):
            candidate = os.open(f'.render-slot-{number}', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root)
            try:
                storage._private(os.fstat(candidate))
                fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(candidate)
                continue
            except BaseException:
                os.close(candidate)
                raise
            descriptor = candidate
            break
    if descriptor is None:
        raise ValidationError('Report generation is at capacity. Try again after another export finishes.')
    try:
        yield
    finally:
        os.close(descriptor)
