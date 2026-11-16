from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
import stat
import struct
from unittest.mock import patch
import zipfile
import pytest
from PIL import Image, PngImagePlugin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction, close_old_connections, connection
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict
from apps.engagements.models import EngagementStatus, EngagementMembership
from apps.engagements.services import purge_engagement
from apps.findings.models import Finding
from apps.testcases.models import TestCase as CaseRecord
from apps.evidence import services, storage
from apps.evidence.models import Evidence, EvidenceTestCase, EvidenceFinding
from apps.evidence.uploads import BoundedUploadHandler

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup(access_setup, settings, tmp_path):
    root = tmp_path / 'private-evidence'
    root.mkdir(mode=0o700)
    settings.EVIDENCE_ROOT = root
    users, engagement, foreign = access_setup
    case = CaseRecord.objects.create(engagement=engagement, title='Local test')
    finding = Finding.objects.create(engagement=engagement, title='Local finding', author=users['tester'])
    return users, engagement, foreign, case, finding, root


def upload(setup, *, content=b'private log\n  indented\n', name='output.txt', role='tester', **kwargs):
    users, engagement, _, case, _, _ = setup
    return services.upload_evidence(actor=users[role], engagement_id=engagement.pk,
        upload=SimpleUploadedFile(name, content, content_type='text/html'), data={'description': '  Original\nDescription', 'test_cases': [case.pk]}, **kwargs)


def path_for(setup, evidence, key=None):
    return setup[-1] / evidence.engagement_id.hex / (key or evidence.storage_key)


def png(size=(64, 48)):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Secret', 'customer metadata')
    Image.new('RGB', size, 'red').save(output, format='PNG', pnginfo=metadata)
    return output.getvalue()


def test_upload_provenance_and_private_permissions(setup):
    users, engagement, _, case, _, root = setup
    e = upload(setup, name='../../../../client-output.txt')
    path = path_for(setup, e)
    assert e.original_filename == 'client-output.txt'
    assert len(e.storage_key) == 32 and e.storage_key != e.id.hex
    assert path.read_bytes() == b'private log\n  indented\n'
    assert e.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert e.content_type == 'text/plain' and e.kind == 'text' and e.uploader == users['tester']
    assert e.description == '  Original\nDescription' and list(e.test_cases.all()) == [case]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    audit = AuditEvent.objects.get(action='evidence.uploaded')
    assert audit.engagement == engagement and audit.subject_id == str(e.pk) and audit.metadata == {'version': 1}
    assert e.sha256 not in str(audit.metadata) and e.original_filename not in str(audit.metadata)
    assert audit.before == {} and audit.after['original_filename'] == 'client-output.txt'
    assert audit.after['test_cases'] == [str(case.pk)] and audit.after['uploader_id'] == users['tester'].pk
    assert 'storage_key' not in audit.after and 'sha256' not in audit.after
    assert 'private log' not in str(audit.after)
    with pytest.raises(IntegrityError), transaction.atomic():
        Evidence.objects.filter(pk=e.pk).update(sha256='a'*64)
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditEvent.objects.filter(pk=audit.pk).update(metadata={'version': 99})
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditEvent.objects.filter(pk=audit.pk).update(actor=users['lead'])


@pytest.mark.parametrize('role', ['lead', 'tester', 'admin'])
def test_write_roles(setup, role):
    assert upload(setup, role=role).uploader == setup[0][role]


@pytest.mark.parametrize('role', ['reviewer', 'viewer', 'outsider'])
def test_denied_upload_roles_services_and_http(setup, client, role):
    users, engagement, *_ = setup
    with pytest.raises((PermissionDenied, Http404)):
        upload(setup, role=role)
    client.force_login(users[role])
    response = client.post(reverse('evidence:upload', args=[engagement.pk]), {'file': SimpleUploadedFile('secret.txt', b'secret')}, HTTP_HX_REQUEST='true')
    assert response.status_code == (404 if role == 'outsider' else 403)
    assert not Evidence.objects.exists()


@pytest.mark.parametrize('role', ['lead', 'tester', 'reviewer', 'viewer', 'admin'])
def test_authenticated_download_headers_and_roles(setup, client, role):
    users, engagement, *_ = setup
    e = upload(setup)
    client.force_login(users[role])
    response = client.get(reverse('evidence:download', args=[engagement.pk, e.pk]))
    assert response.status_code == 200
    assert response['Content-Type'] == 'application/octet-stream'
    assert response['Content-Disposition'].startswith('attachment;')
    assert 'output.txt' not in response['Content-Disposition']
    assert response['X-Content-Type-Options'] == 'nosniff'
    assert "default-src 'none'" in response['Content-Security-Policy'] and 'sandbox' in response['Content-Security-Policy']
    assert response['Cache-Control'] == 'no-store, private'
    assert b''.join(response.streaming_content) == b'private log\n  indented\n'
    response.close()
    assert AuditEvent.objects.filter(action='evidence.downloaded', actor=users[role]).exists()


def test_foreign_and_anonymous_access(setup, client):
    users, engagement, foreign, *_ = setup
    e = upload(setup)
    for role, eid in [('outsider', engagement.pk), ('outsider', foreign.pk), ('lead', foreign.pk)]:
        client.force_login(users[role])
        for name in ['detail', 'download', 'thumbnail', 'edit', 'remove']:
            for headers in ({}, {'HTTP_HX_REQUEST': 'true'}):
                response = client.get(reverse('evidence:'+name, args=[eid, e.pk]), **headers)
                assert response.status_code in {403, 404}
        with pytest.raises((PermissionDenied, Http404)):
            services.open_download(actor=users[role], engagement_id=eid, evidence_id=e.pk)
        with pytest.raises((PermissionDenied, Http404)):
            services.verify_evidence(actor=users[role], engagement_id=eid, evidence_id=e.pk)
        with pytest.raises((PermissionDenied, Http404)):
            services.remove_evidence(actor=users[role], engagement_id=eid, evidence_id=e.pk, version=1)
    client.logout()
    assert client.get(reverse('evidence:download', args=[engagement.pk, e.pk])).status_code == 302
    assert client.get('/media/' + e.storage_key).status_code == 404
    assert client.get('/static/' + e.storage_key).status_code == 404
    assert path_for(setup, e).exists()


def test_scoped_relationships_in_forms_services_and_sqlite(setup, client):
    users, engagement, foreign, case, finding, _ = setup
    foreign_case = CaseRecord.objects.create(engagement=foreign, title='Foreign')
    foreign_finding = Finding.objects.create(engagement=foreign, title='Foreign')
    for field, value in [('test_cases', foreign_case), ('findings', foreign_finding)]:
        with pytest.raises(ValidationError):
            services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=SimpleUploadedFile('test', b'log'), data={field: [value.pk]})
    with pytest.raises(ValidationError):
        services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=SimpleUploadedFile('test', b'log'), data={})
    e = upload(setup)
    for model, field, value in [(EvidenceTestCase, 'test_case', foreign_case), (EvidenceFinding, 'finding', foreign_finding)]:
        link = model(evidence=e, **{field: value})
        with pytest.raises(ValidationError):
            link.clean()
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.bulk_create([link])
    EvidenceFinding.objects.create(evidence=e, finding=finding)
    for model, pk in [(CaseRecord, case.pk), (Finding, finding.pk), (Evidence, e.pk)]:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=pk).update(engagement=foreign)
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceTestCase.objects.filter(evidence=e).update(test_case=foreign_case)
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceFinding.objects.filter(evidence=e).update(finding=foreign_finding)
    client.force_login(users['tester'])
    response = client.post(reverse('evidence:upload', args=[engagement.pk]), {'file': SimpleUploadedFile('test', b'log'), 'test_cases': [foreign_case.pk]})
    assert response.status_code == 200 and response.context['form'].errors
    assert Evidence.objects.count() == 1


def test_upload_limits_and_lied_size(setup, settings, client):
    users, engagement, _, case, *_ = setup
    settings.TRACE_EVIDENCE_MAX_BYTES = 10
    incoming = SimpleUploadedFile('log', b'x' * 11)
    incoming.size = 1
    with pytest.raises(ValidationError):
        services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=incoming, data={'test_cases': [case.pk]})
    assert not Evidence.objects.exists() and list(setup[-1].glob('*/*')) == []
    client.force_login(users['tester'])
    response = client.post(reverse('evidence:upload', args=[engagement.pk]), {'file': SimpleUploadedFile('log', b'x' * 11), 'test_cases': [case.pk]})
    assert response.status_code == 413
    assert list(setup[-1].glob('*/*')) == []
    assert upload(setup, content=b'1234567890').size == 10


@pytest.mark.parametrize('content', [b'', b'\x00\xff binary', b'%PDF-1.7\nbroken', b'\x89PNG\r\n\x1a\nbroken', b'<html><script>alert(1)</script>', b'#!/bin/sh\necho hello', b'<svg onload="alert(1)">'])
def test_invalid_types_and_empty_files_leave_no_orphans(setup, content):
    with pytest.raises(ValidationError):
        upload(setup, content=content, name='pretend.png')
    assert not Evidence.objects.exists() and list(setup[-1].glob('*/*')) == []


def test_type_is_content_not_extension_or_browser_mime(setup, settings):
    assert upload(setup, name='fake.png').kind == 'text'
    assert upload(setup, content=b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n', name='log.txt').kind == 'pdf'
    packet = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    assert upload(setup, content=packet, name='log.txt').kind == 'pcap'
    settings.TRACE_EVIDENCE_ALLOWED_TYPES = ['pdf']
    with pytest.raises(ValidationError):
        upload(setup)


def test_image_thumbnail_strips_metadata_and_verifies(setup, client):
    users, engagement, *_ = setup
    e = upload(setup, content=png(), name='output.log')
    assert e.kind == 'png' and e.thumbnail_key and e.thumbnail_sha256
    with Image.open(path_for(setup, e, e.thumbnail_key)) as preview:
        assert preview.format == 'PNG' and not preview.info and max(preview.size) <= 512
    assert services.verify_evidence(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk) == 'verified'
    client.force_login(users['viewer'])
    response = client.get(reverse('evidence:thumbnail', args=[engagement.pk, e.pk]))
    assert response.status_code == 200 and response['Content-Type'] == 'image/png'
    assert response['Content-Disposition'].startswith('inline;')
    assert hashlib.sha256(b''.join(response.streaming_content)).hexdigest() == e.thumbnail_sha256
    response.close()


def test_image_resource_limits_and_parser_timeout(setup, settings):
    settings.TRACE_EVIDENCE_IMAGE_PIXELS = 20
    with pytest.raises(ValidationError):
        upload(setup, content=png())
    settings.TRACE_EVIDENCE_IMAGE_PIXELS = 12_000_000
    import subprocess
    with patch('apps.evidence.validation.subprocess.run', side_effect=subprocess.TimeoutExpired('parser', 10)):
        with pytest.raises(ValidationError):
            upload(setup, content=png())
    assert not Evidence.objects.exists() and list(setup[-1].glob('*/*')) == []


def test_zip_optional_and_traversal_members_rejected(setup, settings):
    def archive(name):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as target:
            target.writestr(name, b'binary\x00')
        return output.getvalue()
    with pytest.raises(ValidationError):
        upload(setup, content=archive('safe.bin'))
    settings.TRACE_EVIDENCE_ALLOWED_TYPES = ['zip']
    assert upload(setup, content=archive('safe.bin')).kind == 'zip'
    with pytest.raises(ValidationError):
        upload(setup, content=archive('../../escape'))


def test_corruption_is_not_downloaded(setup, client):
    users, engagement, *_ = setup
    e = upload(setup)
    path_for(setup, e).write_bytes(b'changed')
    assert services.verify_evidence(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk) == 'mismatch'
    with pytest.raises(storage.StorageError):
        services.open_download(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk)
    client.force_login(users['viewer'])
    assert client.get(reverse('evidence:download', args=[engagement.pk, e.pk])).status_code == 409
    assert AuditEvent.objects.get(action='evidence.verified').metadata['result'] == 'mismatch'
    path_for(setup, e).unlink()
    assert services.verify_evidence(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk) == 'unavailable'


def test_path_keys_symlinks_hardlinks_and_permissions(setup, tmp_path):
    users, engagement, *_ = setup
    e = upload(setup)
    for key in ['../escape', '/etc/passwd', e.storage_key + '/..', 'a'*31, 'a'*32 + '\x00']:
        with pytest.raises(storage.StorageError):
            storage.open_file(engagement.pk, key)
    target = tmp_path / 'outside'
    target.write_bytes(b'outside secret')
    target.chmod(0o600)
    path = path_for(setup, e)
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(OSError):
        storage.open_file(engagement.pk, e.storage_key)
    with pytest.raises(OSError):
        storage.remove_file(engagement.pk, e.storage_key)
    assert target.read_bytes() == b'outside secret'
    path.unlink()
    os.link(target, path)
    with pytest.raises(storage.StorageError):
        storage.open_file(engagement.pk, e.storage_key)
    path.unlink()
    path.write_bytes(b'private log\n  indented\n')
    path.chmod(0o644)
    with pytest.raises(storage.StorageError):
        storage.open_file(engagement.pk, e.storage_key)
    path.chmod(0o600)
    path.parent.chmod(0o755)
    with pytest.raises(storage.StorageError):
        storage.open_file(engagement.pk, e.storage_key)


def test_directory_symlink_and_static_overlap_fail_closed(setup, settings, tmp_path):
    users, engagement, *_ = setup
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    (setup[-1] / engagement.pk.hex).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        upload(setup)
    assert list(outside.iterdir()) == []
    settings.EVIDENCE_ROOT = tmp_path / 'root-link'
    settings.EVIDENCE_ROOT.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        storage.create_file(engagement.pk)
    settings.EVIDENCE_ROOT = settings.STATIC_ROOT / 'private'
    with pytest.raises(storage.StorageError):
        storage.create_file(engagement.pk)


def test_interrupted_upload_and_db_failure_cleanup(setup):
    users, engagement, _, case, *_ = setup
    class Interrupted:
        name = 'interrupted.log'
        def chunks(self, **kwargs):
            yield b'first chunk'
            raise OSError('interrupted transport')
    with pytest.raises(OSError):
        services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=Interrupted(), data={'test_cases': [case.pk]})
    assert list(setup[-1].glob('*/*')) == []
    with patch('apps.evidence.services.record_event', side_effect=IntegrityError):
        with pytest.raises(IntegrityError):
            upload(setup)
    assert list(setup[-1].glob('*/*')) == [] and not Evidence.objects.exists()


def test_parser_interrupted_upload_cleanup(setup):
    users, engagement, *_ = setup
    request = RequestFactory().post('/test')
    request.user = users['tester']
    request.resolver_match = type('Match', (), {'namespace': 'evidence', 'kwargs': {'engagement_id': engagement.pk}})()
    handler = BoundedUploadHandler(request)
    handler.new_file('file', 'log.txt', 'text/plain', None)
    handler.receive_data_chunk(b'partial', 0)
    assert len(list(setup[-1].glob('*/*'))) == 1
    handler.upload_interrupted()
    assert list(setup[-1].glob('*/*')) == []


def test_versioned_edit_delete_and_rollback(setup):
    users, engagement, _, case, finding, _ = setup
    e = upload(setup)
    data = {'description': '  draft\nunchanged', 'test_cases': [case.pk], 'findings': [finding.pk]}
    with pytest.raises(EditConflict):
        services.update_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, data=data, version=99)
    e = services.update_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, data=data, version=1)
    assert e.version == 2 and e.description == data['description'] and e.findings.get() == finding
    with pytest.raises(EditConflict):
        services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    with pytest.raises(RuntimeError), transaction.atomic():
        services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=2)
        assert path_for(setup, e).exists()
        raise RuntimeError('abort transaction')
    e.refresh_from_db()
    assert e.deleted_at is None and path_for(setup, e).exists()
    services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=2)
    e.refresh_from_db()
    assert e.version == 3 and e.deleted_at and e.deleted_by == users['tester']
    assert not path_for(setup, e).exists() and Evidence.objects.filter(pk=e.pk).exists()
    assert AuditEvent.objects.filter(action='evidence.removed').count() == 1
    with pytest.raises(Http404):
        services.open_download(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk)


def test_delete_cleanup_deferred_until_download_lease_released(setup):
    users, engagement, *_ = setup
    e = upload(setup)
    _, file = services.open_download(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk)
    services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    assert path_for(setup, e).exists()
    file.close()
    assert services.cleanup_orphans() == (1, 0)
    assert not path_for(setup, e).exists()


def test_orphan_cleanup_respects_live_leases_and_active_references(setup):
    users, engagement, *_ = setup
    e = upload(setup)
    key, file = storage.create_file(engagement.pk)
    file.write(b'interrupted upload')
    file.flush()
    os.utime(file.fileno(), (0, 0))
    assert services.cleanup_orphans()[0] == 0
    assert path_for(setup, e, key).exists()
    file.close()
    assert services.cleanup_orphans() == (1, 0)
    assert path_for(setup, e).exists() and not path_for(setup, e, key).exists()


def test_permission_and_engagement_rechecked_after_streaming(setup):
    users, engagement, _, case, *_ = setup
    class Revoked:
        name = 'log.txt'
        def chunks(self, **kwargs):
            yield b'log'
            EngagementMembership.objects.filter(engagement=engagement, user=users['tester']).update(role='viewer')
    with pytest.raises(PermissionDenied):
        services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=Revoked(), data={'test_cases': [case.pk]})
    assert not Evidence.objects.exists() and list(setup[-1].glob('*/*')) == []


@pytest.mark.parametrize('state', [EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED])
def test_read_only_engagements_and_purge_blocked(setup, state):
    users, engagement, _, case, *_ = setup
    e = upload(setup)
    engagement.status = state
    engagement.save()
    with pytest.raises(ValidationError):
        upload(setup)
    with pytest.raises(ValidationError):
        services.update_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1, data={'test_cases': [case.pk]})
    with pytest.raises(ValidationError):
        services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    assert services.verify_evidence(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk) == 'verified'
    if state == EngagementStatus.ARCHIVED:
        with pytest.raises(ValidationError):
            purge_engagement(actor=users['admin'], engagement_id=engagement.pk, version=engagement.version, confirmation=str(engagement.pk), reason='test-data')


def test_manage_restrictions_and_disabled_users(setup):
    users, engagement, _, case, *_ = setup
    e = upload(setup, role='lead')
    for role in ['tester', 'reviewer', 'viewer', 'outsider']:
        with pytest.raises((PermissionDenied, Http404)):
            services.remove_evidence(actor=users[role], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    users['lead'].is_active = False
    users['lead'].save()
    with pytest.raises(Http404):
        services.open_download(actor=users['lead'], engagement_id=engagement.pk, evidence_id=e.pk)


def test_http_pages_metadata_edits_and_removal(setup, client):
    users, engagement, _, case, finding, _ = setup
    client.force_login(users['tester'])
    response = client.post(reverse('evidence:upload', args=[engagement.pk]), {'file': SimpleUploadedFile('log', b'private log'), 'test_cases': [case.pk], 'findings': [finding.pk], 'description': '  preserved\nlines'})
    assert response.status_code == 302
    e = Evidence.objects.get()
    assert len(list(setup[-1].glob('*/*'))) == 1  # Request-spool file was cleaned.
    for name in ['list', 'upload', 'detail', 'edit', 'remove']:
        args = [engagement.pk] if name in {'list', 'upload'} else [engagement.pk, e.pk]
        assert client.get(reverse('evidence:'+name, args=args)).status_code == 200
    assert client.post(reverse('evidence:detail', args=[engagement.pk, e.pk])).status_code == 302
    assert client.get(reverse('testcases:detail', args=[engagement.pk, case.pk])).status_code == 200
    assert client.get(reverse('findings:detail', args=[engagement.pk, finding.pk])).status_code == 200
    response = client.post(reverse('evidence:edit', args=[engagement.pk, e.pk]), {'description': 'Unsaved draft', 'test_cases': [case.pk], 'version': 99}, HTTP_HX_REQUEST='true')
    assert response.status_code == 409 and b'Unsaved draft' in response.content
    assert client.post(reverse('evidence:remove', args=[engagement.pk, e.pk]), {'version': 1}).status_code == 302
    assert client.get(reverse('evidence:detail', args=[engagement.pk, e.pk])).status_code == 404


def test_file_operations_never_hold_database_transaction(setup):
    users, engagement, *_ = setup
    with transaction.atomic(), pytest.raises(RuntimeError):
        upload(setup)
    original = services.copy_upload
    def checked(*args, **kwargs):
        assert not connection.in_atomic_block
        return original(*args, **kwargs)
    with patch('apps.evidence.services.copy_upload', side_effect=checked):
        upload(setup)


@pytest.mark.parametrize('role', ['lead', 'tester', 'admin', 'reviewer', 'viewer', 'outsider'])
def test_http_removal_roles_and_htmx(setup, client, role):
    users, engagement, *_ = setup
    e = upload(setup)
    client.force_login(users[role])
    response = client.post(reverse('evidence:remove', args=[engagement.pk, e.pk]), {'version': 1}, HTTP_HX_REQUEST='true')
    assert response.status_code == {'lead': 204, 'tester': 204, 'admin': 204, 'reviewer': 403, 'viewer': 403, 'outsider': 404}[role]
    e.refresh_from_db()
    assert bool(e.deleted_at) == (role in {'lead', 'tester', 'admin'})


def test_thumbnail_corruption_is_not_served_and_removed_files_are_cleaned(setup, client):
    users, engagement, *_ = setup
    e = upload(setup, content=png())
    path_for(setup, e, e.thumbnail_key).write_bytes(b'<html>not an image')
    assert services.verify_evidence(actor=users['viewer'], engagement_id=engagement.pk, evidence_id=e.pk) == 'mismatch'
    client.force_login(users['viewer'])
    assert client.get(reverse('evidence:thumbnail', args=[engagement.pk, e.pk])).status_code == 409
    services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    assert list(setup[-1].glob('*/*')) == []


def test_jpeg_and_animation_policy(setup):
    output = io.BytesIO()
    Image.new('RGB', (1024, 800), 'blue').save(output, format='JPEG')
    e = upload(setup, content=output.getvalue(), name='screenshot.txt')
    assert e.kind == 'jpeg'
    with Image.open(path_for(setup, e, e.thumbnail_key)) as thumb:
        assert max(thumb.size) == 512
    output = io.BytesIO()
    Image.new('RGB', (16, 16), 'red').save(output, format='PNG', save_all=True, append_images=[Image.new('RGB', (16, 16), 'blue')], duration=100, loop=0)
    with pytest.raises(ValidationError):
        upload(setup, content=output.getvalue())
    assert Evidence.objects.count() == 1


def test_deferred_cleanup_logs_only_known_event_and_command_retries(setup, caplog):
    from django.core.management import call_command
    users, engagement, *_ = setup
    e = upload(setup)
    with patch('apps.evidence.services.storage.remove_file', side_effect=OSError('secret/raw/path')):
        services.remove_evidence(actor=users['tester'], engagement_id=engagement.pk, evidence_id=e.pk, version=1)
    assert path_for(setup, e).exists()
    assert all('secret/raw/path' not in record.getMessage() for record in caplog.records)
    output = io.StringIO()
    call_command('cleanup_evidence', stdout=output)
    assert 'Removed 1 files' in output.getvalue() and not path_for(setup, e).exists()
    assert Evidence.objects.filter(pk=e.pk).exists()


def test_concurrent_evidence_metadata_edits_have_one_winner(setup):
    from threading import Barrier
    users, engagement, _, case, *_ = setup
    e = upload(setup)
    barrier = Barrier(2)
    def write(description):
        close_old_connections()
        try:
            actor = User.objects.get(pk=users['tester'].pk)
            barrier.wait(timeout=10)
            try:
                services.update_evidence(actor=actor, engagement_id=engagement.pk, evidence_id=e.pk,
                                         version=1, data={'description': description, 'test_cases': [case.pk]})
            except EditConflict:
                return 'conflict'
            return 'saved'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ['one', 'two'])) == ['conflict', 'saved']
    assert AuditEvent.objects.filter(action='evidence.updated').count() == 1
    e.refresh_from_db()
    assert e.version == 2


def test_engagement_closure_during_upload_leaves_no_files(setup):
    users, engagement, _, case, *_ = setup
    class Closing:
        name = 'log.txt'
        def chunks(self, **kwargs):
            yield b'log bytes'
            engagement.status = EngagementStatus.COMPLETED
            engagement.save()
    with pytest.raises(ValidationError):
        services.upload_evidence(actor=users['tester'], engagement_id=engagement.pk, upload=Closing(), data={'test_cases': [case.pk]})
    assert list(setup[-1].glob('*/*')) == [] and not Evidence.objects.exists()


def test_active_names_rejected_even_with_text_content(setup):
    for name in ['script.js', 'page.html', 'image.svg', 'payload.exe']:
        with pytest.raises(ValidationError):
            upload(setup, name=name)
    assert list(setup[-1].glob('*/*')) == []


def test_static_symlink_alias_rejected(setup, settings, tmp_path):
    public_alias = tmp_path / 'public-alias'
    public_alias.symlink_to(setup[-1], target_is_directory=True)
    settings.STATICFILES_DIRS = [public_alias]
    with pytest.raises(storage.StorageError):
        storage.root_path()
