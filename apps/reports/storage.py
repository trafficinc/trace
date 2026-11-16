"""POSIX local storage. Pin directory descriptors; never resolve user-supplied paths."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat
import uuid
from django.conf import settings


class StorageError(Exception):
    """A private file is unavailable or the storage boundary is unsafe."""


def _private(info, *, directory=False):
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise StorageError('Private storage permissions are unsafe.')
    if not directory and info.st_mode & 0o111:
        raise StorageError('Executable private files are not supported.')
    if not directory and info.st_nlink != 1:
        raise StorageError('Linked private files are not supported.')


def _key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
        raise StorageError('Invalid private storage key.')
    return key


def root_path():
    root = Path(os.path.abspath(settings.REPORT_ROOT))
    public = [Path(settings.STATIC_ROOT), *[Path(item[1] if isinstance(item, (list, tuple)) else item) for item in settings.STATICFILES_DIRS]]
    for path in public:
        path = path.resolve()
        resolved = root.resolve()
        if resolved == path or resolved in path.parents or path in resolved.parents:
            raise StorageError('Report storage overlaps public static storage.')
    evidence = Path(settings.EVIDENCE_ROOT).resolve()
    if root.resolve() == evidence or root.resolve() in evidence.parents or evidence in root.resolve().parents:
        raise StorageError('Report and evidence storage must be separate.')
    return root


@contextmanager
def root_directory():
    root = root_path()
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(root.parts[1:]):
            if index == len(root.parts) - 2:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _private(os.fstat(descriptor), directory=True)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def engagement_directory(engagement_id, *, create=False):
    name = uuid.UUID(str(engagement_id)).hex
    with root_directory() as root:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=root)
                os.fsync(root)
            except FileExistsError:
                pass
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            _private(os.fstat(descriptor), directory=True)
            yield descriptor
        finally:
            os.close(descriptor)


def create_file(engagement_id):
    key = uuid.uuid4().hex
    with engagement_directory(engagement_id, create=True) as directory:
        descriptor = os.open(key, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            file = os.fdopen(descriptor, 'w+b')
        except BaseException:
            os.close(descriptor)
            os.unlink(key, dir_fd=directory)
            raise
    return key, file


def open_file(engagement_id, key, *, exclusive=False):
    _key(key)
    with engagement_directory(engagement_id) as directory:
        descriptor = os.open(_key(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _private(os.fstat(descriptor))
        fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise


def remove_file(engagement_id, key):
    """Unlink only a regular, exclusively locked file in the pinned engagement dir."""
    try:
        with open_file(engagement_id, key, exclusive=True) as file:
            with engagement_directory(engagement_id) as directory:
                info = os.stat(_key(key), dir_fd=directory, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != (os.fstat(file.fileno()).st_dev, os.fstat(file.fileno()).st_ino):
                    raise StorageError('Private file changed during cleanup.')
                os.unlink(key, dir_fd=directory)
                os.fsync(directory)
    except FileNotFoundError:
        pass


def sync_file(file, engagement_id):
    file.flush()
    os.fsync(file.fileno())
    with engagement_directory(engagement_id) as directory:
        os.fsync(directory)
