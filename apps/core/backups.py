"""Private directory backups: SQLite backup API + referenced, verified file bytes.

Restore never extracts an archive or overwrites a running installation. It
validates the database, chain, manifest and every file before publishing a new
storage directory. Operators switch to that directory during maintenance.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import ctypes
import sys
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import uuid
from urllib.parse import quote
from django.conf import settings
from django.db import connections
from django.utils import timezone
from apps.engagements.permissions import require_system_admin
from apps.audit.maintenance import _verify
from apps.evidence import storage as evidence_storage
from apps.reports import storage as report_storage
from .maintenance import exclusive_maintenance


class BackupError(Exception):
    pass


def safe_directory(path):
    path=Path(os.path.abspath(path))
    for part in [*reversed(path.parents),path]:
        if part.is_symlink(): raise BackupError('Symlink backup paths are not allowed.')
    if not path.is_dir(): raise BackupError('Backup directory is missing.')
    info=path.stat()
    if info.st_uid!=os.geteuid() or info.st_mode&0o077: raise BackupError('Backup directory must be owner-only.')
    return path


def _destination(path):
    if '\x00' in os.fspath(path):
        raise BackupError('Invalid destination path.')
    path=Path(os.path.abspath(path))
    safe_directory(path.parent)
    if path.exists() or path.is_symlink(): raise BackupError('Destination must not exist; restore never overwrites data.')
    for public in [settings.STATIC_ROOT,*settings.STATICFILES_DIRS]:
        public=Path(public[1] if isinstance(public,(tuple,list)) else public).resolve()
        if path==public or public in path.parents or path in public.parents: raise BackupError('Backup destination overlaps static storage.')
    return path


def private_parents(path, root):
    current=root
    for part in path.relative_to(root).parts:
        current=current/part
        current.mkdir(mode=0o700,exist_ok=True)


def sync_directories(root):
    for path, _, _ in os.walk(root,topdown=False):
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)


def publish(stage,destination):
    sync_directories(stage)
    if stage.parent != destination.parent:
        raise BackupError('Publication requires a staging directory beside its destination.')
    descriptor=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        library=ctypes.CDLL(None,use_errno=True)
        if sys.platform.startswith('linux'):
            rename=getattr(library,'renameat2',None)
            flags=1  # Linux RENAME_NOREPLACE.
        elif sys.platform=='darwin':
            rename=getattr(library,'renameatx_np',None)
            flags=4  # Darwin RENAME_EXCL (sys/stdio.h).
        else:
            rename=None
        if rename is None:
            raise BackupError('Atomic non-overwriting publication is unavailable on this platform.')
        rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        rename.restype=ctypes.c_int
        if rename(descriptor,os.fsencode(stage.name),descriptor,os.fsencode(destination.name),flags):
            raise OSError(ctypes.get_errno(),'Atomic non-overwriting publication failed.')
    finally:
        os.close(descriptor)
    descriptor=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def file_digest(path):
    digest=hashlib.sha256(); size=0
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as file:
        info=os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode&0o077 or info.st_mode&0o111:
            raise BackupError('Backup contains unsafe files.')
        for chunk in iter(lambda:file.read(1024*1024),b''): size+=len(chunk); digest.update(chunk)
    return {'size':size,'sha256':digest.hexdigest()}


def _database(path):
    database=sqlite3.connect(f'file:{quote(str(path))}?mode=ro',uri=True)
    try:
        if database.execute('PRAGMA quick_check').fetchall()!=[('ok',)] or database.execute('PRAGMA foreign_key_check').fetchone():
            raise BackupError('SQLite consistency validation failed.')
        return database
    except BaseException:
        database.close(); raise


@contextmanager
def snapshot_alias(path):
    alias='trace_backup_validation'
    wrapper=connections['default'].copy(alias=alias)
    wrapper.settings_dict=deepcopy(wrapper.settings_dict)
    wrapper.settings_dict.update(ENGINE='django.db.backends.sqlite3',NAME=str(path),OPTIONS={'timeout':10,'transaction_mode':'DEFERRED'})
    if wrapper.vendor!='sqlite':
        from django.db.backends.sqlite3.base import DatabaseWrapper
        wrapper=DatabaseWrapper(wrapper.settings_dict,alias=alias)
    connections[alias]=wrapper
    try:
        with wrapper.cursor() as cursor: cursor.execute('PRAGMA query_only=ON')
        yield alias
    finally:
        wrapper.close(); del connections[alias]


def references(database):
    refs={}
    for engagement,key,size,digest,thumbnail,thumb_size,thumb_hash in database.execute('SELECT engagement_id,storage_key,size,sha256,thumbnail_key,thumbnail_size,thumbnail_sha256 FROM evidence_evidence WHERE deleted_at IS NULL'):
        refs[f'evidence/{engagement}/{key}']={'size':size,'sha256':digest}
        if thumbnail: refs[f'evidence/{engagement}/{thumbnail}']={'size':thumb_size,'sha256':thumb_hash}
    for engagement,key,size,digest in database.execute('SELECT engagement_id,storage_key,size,sha256 FROM reports_reportartifact'):
        refs[f'reports/{engagement}/{key}']={'size':size,'sha256':digest}
    for name,meta in refs.items():
        if not re.fullmatch(r'(evidence|reports)/[0-9a-f]{32}/[0-9a-f]{32}',name) or not re.fullmatch('[0-9a-f]{64}',meta['sha256']) or meta['size']<=0:
            raise BackupError('Database file references are invalid.')
    return refs


def create_backup(*,actor,output,maintenance=False):
    require_system_admin(actor)
    if connections['default'].vendor!='sqlite': raise BackupError('Use PostgreSQL logical backups with a matching private-file snapshot.')
    if connections['default'].in_atomic_block: raise BackupError('Backup must run outside a transaction.')
    output=_destination(output)
    stage=output.parent/('.backup-'+uuid.uuid4().hex)
    with exclusive_maintenance(maintenance):
        require_system_admin(actor)
        stage.mkdir(mode=0o700)
        try:
            source=sqlite3.connect(f'file:{quote(str(connections["default"].settings_dict["NAME"]))}?mode=ro',uri=True)
            snapshot=stage/'database.sqlite3'
            descriptor=os.open(snapshot,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(descriptor)
            destination=sqlite3.connect(snapshot)
            try:
                source.backup(destination)
                destination.execute('PRAGMA journal_mode=DELETE')
            finally: destination.close(); source.close()
            database=_database(snapshot)
            try:
                refs=references(database)
                migrations=[list(row) for row in database.execute('SELECT app,name FROM django_migrations ORDER BY app,name')]
            finally: database.close()
            for name,expected in refs.items():
                module,engagement,key=name.split('/')
                storage=evidence_storage if module=='evidence' else report_storage
                target=stage/name; private_parents(target.parent,stage)
                with storage.open_file(uuid.UUID(hex=engagement),key) as source_file:
                    with open(target,'xb') as destination_file:
                        os.chmod(target,0o600); shutil.copyfileobj(source_file,destination_file,1024*1024)
                        destination_file.flush(); os.fsync(destination_file.fileno())
                if file_digest(target)!=expected: raise BackupError('A referenced private file failed integrity verification.')
            with snapshot_alias(snapshot) as alias: checkpoint=_verify(alias)
            files={'database.sqlite3':file_digest(snapshot),**refs}
            manifest={'schema':1,'created_at':timezone.now().isoformat(),'operator_ref':str(actor.pk),'files':files,'audit':checkpoint,'migrations':migrations}
            manifest_path=stage/'manifest.json'
            manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n'); os.chmod(manifest_path,0o600)
            with open(manifest_path,'rb') as file: os.fsync(file.fileno())
            validate_backup(stage)
            publish(stage,output)
            return manifest
        except BaseException:
            shutil.rmtree(stage,ignore_errors=True); raise


def validate_backup(directory):
    directory=safe_directory(directory)
    manifest_path=directory/'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size>64*1024*1024: raise BackupError('Backup manifest is unsafe or oversized.')
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('schema')!=1 or not isinstance(manifest.get('files'),dict) or 'database.sqlite3' not in manifest['files']:
        raise BackupError('Unsupported backup manifest.')
    expected=set(manifest['files'])|{'manifest.json'}; actual=set()
    for root,dirs,files in os.walk(directory,followlinks=False):
        for child in dirs:
            safe_directory(Path(root)/child)
        for child in files: actual.add((Path(root)/child).relative_to(directory).as_posix())
    if expected!=actual: raise BackupError('Backup has missing or unexpected files.')
    for name,metadata in manifest['files'].items():
        if name!='database.sqlite3' and not re.fullmatch(r'(evidence|reports)/[0-9a-f]{32}/[0-9a-f]{32}',name):
            raise BackupError('Backup contains an invalid relative path.')
        if file_digest(directory/name)!=metadata: raise BackupError('Backup file hash or size mismatch.')
    database=_database(directory/'database.sqlite3')
    try:
        if {name:meta for name,meta in manifest['files'].items() if name!='database.sqlite3'}!=references(database):
            raise BackupError('Manifest does not match the database file references.')
        if [list(row) for row in database.execute('SELECT app,name FROM django_migrations ORDER BY app,name')]!=manifest['migrations']:
            raise BackupError('Migration manifest mismatch.')
    finally: database.close()
    with snapshot_alias(directory/'database.sqlite3') as alias:
        if _verify(alias)!=manifest['audit']: raise BackupError('Audit checkpoint mismatch.')
    return manifest


def restore_backup(*,source,destination,maintenance=False):
    destination=_destination(destination)
    # Restoring a lost instance cannot depend on credentials in the damaged DB.
    # This is an OS-operator command, never a web endpoint.
    with exclusive_maintenance(maintenance):
        manifest=validate_backup(source)
        source=Path(source)
        stage=destination.parent/('.restore-'+uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            for name in manifest['files']:
                target=stage/('db/tdt.sqlite3' if name=='database.sqlite3' else name)
                private_parents(target.parent,stage)
                with open(source/name,'rb') as original, open(target,'xb') as restored:
                    os.chmod(target,0o600); shutil.copyfileobj(original,restored,1024*1024)
                    restored.flush(); os.fsync(restored.fileno())
                if file_digest(target)!=manifest['files'][name]: raise BackupError('Restored bytes failed verification.')
            for directory in ['evidence','reports','backups']: (stage/directory).mkdir(mode=0o700,exist_ok=True)
            publish(stage,destination)
        except BaseException:
            shutil.rmtree(stage,ignore_errors=True); raise
    return manifest
