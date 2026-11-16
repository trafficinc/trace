import codecs
import hashlib
import json
import os
import re
import struct
import subprocess  # nosec B404
import sys
import zipfile
from pathlib import PurePosixPath
from django.conf import settings
from django.core.exceptions import ValidationError

TYPES = {'png': ('image/png', 'png'), 'jpeg': ('image/jpeg', 'jpg'), 'pdf': ('application/pdf', 'pdf'),
         'text': ('text/plain', 'txt'), 'pcap': ('application/vnd.tcpdump.pcap', 'pcap'), 'zip': ('application/zip', 'zip')}


def safe_filename(value):
    value = str(value or '').replace('\\', '/').rsplit('/', 1)[-1]
    value = ''.join(c for c in value if c.isprintable() and c not in '\r\n\x00')[:200]
    return value or 'evidence'


def copy_upload(upload, destination, *, before_write=None):
    # An additional denylist avoids offering recognizably active original names.
    # Content classification below remains mandatory for every allowed filename.
    extension = safe_filename(upload.name).rsplit('.', 1)[-1].lower()
    if extension in {'html', 'htm', 'xhtml', 'svg', 'js', 'mjs', 'cjs', 'css', 'sh', 'bash', 'zsh', 'bat', 'cmd', 'ps1', 'py', 'php', 'exe', 'dll', 'so', 'dylib', 'wasm'}:
        raise ValidationError('Active script, webpage and executable filenames are not accepted.')
    digest, size = hashlib.sha256(), 0
    for chunk in upload.chunks(chunk_size=64 * 1024):
        size += len(chunk)
        if size > settings.TRACE_EVIDENCE_MAX_BYTES:
            raise ValidationError('Evidence exceeds the configured upload limit.')
        if before_write is not None:
            before_write(size)
        destination.write(chunk)
        digest.update(chunk)
    if not size:
        raise ValidationError('Empty evidence files are not accepted.')
    destination.flush()
    destination.seek(0)
    return size, digest.hexdigest()


def image_thumbnail(file):
    command = [sys.executable, '-m', 'apps.evidence.image_worker', str(settings.TRACE_EVIDENCE_IMAGE_PIXELS),
               str(settings.TRACE_EVIDENCE_IMAGE_SIDE), str(settings.TRACE_EVIDENCE_IMAGE_MEMORY), '5']
    file.seek(0)
    try:
        result = subprocess.run(command, stdin=file, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,  # nosec B603
                                timeout=10, check=True, cwd=settings.BASE_DIR,
                                env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'})
        header, thumbnail = result.stdout.split(b'\n', 1)
        kind = json.loads(header)['kind']
        if kind not in {'png', 'jpeg'} or not thumbnail.startswith(b'\x89PNG\r\n\x1a\n') or len(thumbnail) > 2 * 1024 * 1024:
            raise ValueError
        return kind, thumbnail
    except (subprocess.SubprocessError, ValueError, KeyError, OSError) as exc:
        raise ValidationError('Screenshot is invalid or exceeds image processing limits.') from exc


def validate_pcap(file):
    header = file.read(24)
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(header[:4])
    if len(header) != 24 or endian is None:
        raise ValidationError('Invalid packet capture header.')
    major, minor, _, _, snaplen, _ = struct.unpack(endian + 'HHIIII', header[4:])
    if (major, minor) != (2, 4) or not 0 < snaplen <= settings.TRACE_EVIDENCE_MAX_BYTES:
        raise ValidationError('Unsupported packet capture format.')
    while packet := file.read(16):
        if len(packet) != 16:
            raise ValidationError('Truncated packet capture.')
        _, _, captured, original = struct.unpack(endian + 'IIII', packet)
        if captured > snaplen or captured > original or len(file.read(captured)) != captured:
            raise ValidationError('Invalid packet capture record.')


def classify(file, size):
    """Identify content, never filename/MIME. Documents/artifacts remain untrusted."""
    file.seek(0)
    header = file.read(512)
    file.seek(0)
    thumbnail = None
    if header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff'):
        expected = 'png' if header.startswith(b'\x89PNG') else 'jpeg'
        if expected not in settings.TRACE_EVIDENCE_ALLOWED_TYPES:
            raise ValidationError('This evidence type is disabled.')
        kind, thumbnail = image_thumbnail(file)
    elif re.match(rb'%PDF-1\.[0-9][\r\n ]', header) or header.startswith(b'%PDF-2.0'):
        file.seek(max(0, size - 1024))
        if b'%%EOF' not in file.read(1024):
            raise ValidationError('Incomplete PDF document.')
        kind = 'pdf'
    elif header[:4] in {b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4', b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d'}:
        validate_pcap(file)
        kind = 'pcap'
    elif header.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        # Inspect the directory only. Never extract or decompress uploaded artifacts.
        if 'zip' not in settings.TRACE_EVIDENCE_ALLOWED_TYPES:
            raise ValidationError('ZIP artifacts are disabled.')
        try:
            # Bound central-directory parsing before ZipFile allocates entry objects.
            file.seek(max(0, size - 65557))
            tail = file.read(65557)
            marker = tail.rfind(b'PK\x05\x06')
            if marker < 0 or len(tail) - marker < 22:
                raise ValueError
            _, disk, directory_disk, disk_entries, total_entries, directory_size, _, comment_size = struct.unpack('<4s4H2IH', tail[marker:marker+22])
            if disk or directory_disk or disk_entries != total_entries or total_entries > 1000 or directory_size > 2 * 1024 * 1024 or len(tail) - marker != 22 + comment_size:
                raise ValueError
            with zipfile.ZipFile(file) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or sum(i.file_size for i in entries) > 200 * 1024 * 1024:
                    raise ValueError
                for entry in entries:
                    path = PurePosixPath(entry.filename.replace('\\', '/'))
                    if path.is_absolute() or '..' in path.parts or re.match(r'^[A-Za-z]:', str(path)) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            raise ValidationError('Invalid or oversized ZIP directory.') from exc
        kind = 'zip'
    else:
        # Strict UTF-8, no binary controls. Text may contain hostile output and is
        # always downloaded as octet-stream with a server-selected .txt filename.
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        try:
            while chunk := file.read(64 * 1024):
                text = decoder.decode(chunk)
                if any(ord(c) < 32 and c not in '\n\r\t\f' for c in text):
                    raise ValueError
            decoder.decode(b'', final=True)
        except (UnicodeError, ValueError) as exc:
            raise ValidationError('Unrecognized evidence content. Choose a supported file type.') from exc
        if re.match(rb'\s*(?:<!doctype\s+html|<html\b|<script\b|<svg\b|<\?xml|#!)', header, re.I):
            raise ValidationError('Active HTML, SVG and executable script files are not accepted.')
        kind = 'text'
    if kind not in settings.TRACE_EVIDENCE_ALLOWED_TYPES:
        raise ValidationError('This evidence type is disabled.')
    file.seek(0)
    return kind, thumbnail


def verify_stream(file, *, size, digest):
    actual, total = hashlib.sha256(), 0
    file.seek(0)
    while chunk := file.read(64 * 1024):
        total += len(chunk)
        if total > size:
            return False
        actual.update(chunk)
    file.seek(0)
    return total == size and actual.hexdigest() == digest
