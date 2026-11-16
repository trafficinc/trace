"""Cooperating process maintenance gate, shared by native/container WSGI/ASGI."""
from contextlib import contextmanager
import fcntl
import os
import stat
from django.conf import settings

_serving_descriptor=None


class MaintenanceError(Exception):
    pass


def _open():
    path=settings.STORAGE_ROOT/'.maintenance.lock'
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    info=os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_nlink!=1:
        os.close(descriptor)
        raise MaintenanceError('Maintenance gate permissions are unsafe.')
    return descriptor


def hold_serving_lock():
    global _serving_descriptor
    if _serving_descriptor is None:
        descriptor=_open()
        try: fcntl.flock(descriptor,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            raise MaintenanceError('Maintenance is active; server startup is blocked.') from None
        _serving_descriptor=descriptor


@contextmanager
def exclusive_maintenance(acknowledged):
    if not acknowledged: raise MaintenanceError('Confirm exclusive maintenance with --maintenance after stopping all workers and operators.')
    if _serving_descriptor is not None: raise MaintenanceError('This process is serving requests.')
    descriptor=_open()
    try:
        try: fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError: raise MaintenanceError('Stop all application workers before maintenance.') from None
        yield
    finally: os.close(descriptor)
