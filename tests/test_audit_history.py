import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.db import connection, connections, transaction, IntegrityError, close_old_connections
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from apps.audit.capture import capture, Snapshot
from apps.audit.models import AuditEvent, AuditChainState, EntityRevision
from apps.audit.services import record_event, AuditIntegrityError
from apps.audit.maintenance import verify_history, cleanup_history
from apps.audit.history import events_for, revisions_for, export_history
from apps.audit.redaction import redact_text
from apps.accounts.models import User
from apps.engagements.services import save_note, delete_note, transition_engagement, grant_membership, change_membership, revoke_membership
from apps.findings.services import save_finding, transition_finding
from apps.testcases.services import create_test_case, update_test_case

pytestmark=pytest.mark.django_db(transaction=True)


def definition(**overrides):
    return {**dict(title='Boundary failure',severity='high',cvss_vector='',description='  Documentation\n    Indented\n',technical_details='',impact='',reproduction_steps='',remediation='',references='',assets=[],test_cases=[]),**overrides}


def case_data(**overrides):
    return {**dict(title='Boundary test',description='',category='Authorization',objective='',methodology='',procedure='  Inspect boundary\n',expected_result='',actual_result='',assigned_tester='',notes='',assets=[]),**overrides}


def finding(users,engagement,**overrides):
    return save_finding(actor=users['tester'],engagement_id=engagement.pk,data=definition(**overrides))


def test_finding_revisions_complete_before_after_and_approval(access_setup):
    users,engagement,_=access_setup
    case=create_test_case(actor=users['tester'],engagement_id=engagement.pk,data=case_data())
    record=finding(users,engagement,test_cases=[case.pk])
    record=save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=record.pk,version=1,data=definition(title='Updated',test_cases=[]))
    event=AuditEvent.objects.get(action='finding.updated')
    assert event.before['title']=='Boundary failure' and event.after['title']=='Updated'
    assert event.before['test_cases']==[str(case.pk)] and event.after['test_cases']==[]
    assert event.before['description']=='  Documentation\n    Indented\n'
    transition_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=record.pk,version=2,target='under_review')
    transition_finding(actor=users['reviewer'],engagement_id=engagement.pk,finding_id=record.pk,version=3,target='confirmed')
    revisions=EntityRevision.objects.filter(entity_kind='finding',entity_id=record.pk)
    assert list(revisions.values_list('entity_version',flat=True))==[4,3,2,1]
    approved=revisions.get(entity_version=4)
    assert approved.event.actor==users['reviewer'] and approved.snapshot['reviewer_id']==users['reviewer'].pk
    assert approved.snapshot['status']=='confirmed'
    assert verify_history(actor=users['admin'])['head_sequence']==AuditEvent.objects.count()


def test_legacy_record_gets_truthful_baseline_and_test_case_revisions(access_setup):
    from apps.findings.models import Finding
    users,engagement,_=access_setup
    record=Finding.objects.create(engagement=engagement,title='Legacy',author=users['tester'],version=7)
    save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=record.pk,version=7,data=definition())
    baseline=EntityRevision.objects.get(entity_kind='finding',entity_version=7)
    assert baseline.baseline and baseline.snapshot['title']=='Legacy'
    assert not EntityRevision.objects.filter(entity_version__lt=7).exists()
    case=create_test_case(actor=users['tester'],engagement_id=engagement.pk,data=case_data())
    update_test_case(actor=users['tester'],engagement_id=engagement.pk,test_case_id=case.pk,version=1,data=case_data(status='in_progress',actual_result='Observed access'))
    event=AuditEvent.objects.get(action='test.updated')
    assert event.before['status']=='not_started' and event.after['status']=='in_progress'
    assert EntityRevision.objects.get(entity_kind='test_case',entity_version=2).snapshot['actual_result']=='Observed access'
    verify_history(actor=users['admin'])


def test_rollback_audit_revision_and_business_are_one_transaction(access_setup,monkeypatch):
    users,engagement,_=access_setup
    record=finding(users,engagement)
    original=EntityRevision.objects.create
    def broken(**kwargs):
        raise RuntimeError('injected revision failure')
    monkeypatch.setattr(EntityRevision.objects,'create',broken)
    head=AuditChainState.objects.get(pk=1).head_hash
    with pytest.raises(RuntimeError):
        save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=record.pk,version=1,data=definition(title='Must rollback'))
    record.refresh_from_db()
    assert record.version==1 and record.title=='Boundary failure'
    assert AuditChainState.objects.get(pk=1).head_hash==head
    assert AuditEvent.objects.filter(action='finding.updated').count()==0
    monkeypatch.setattr(EntityRevision.objects,'create',original)
    count=AuditEvent.objects.count()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            save_note(actor=users['tester'],engagement_id=engagement.pk,body='Rollback note')
            raise RuntimeError('outer rollback')
    assert not engagement.notes.exists() and AuditEvent.objects.count()==count
    verify_history(actor=users['admin'])


@pytest.mark.parametrize('text,secret',[
 ('password: hunter-secret','hunter-secret'),('Authorization: Bearer veryprivate','veryprivate'),
 ('Cookie: sessionid=privatecookie','privatecookie'),('https://name:privatepass@example.test/','privatepass'),
 ('{"api_key":"privatekey","description":"text"}','privatekey'),
 ('-----BEGIN PRIVATE KEY-----\nprivatepem\n-----END PRIVATE KEY-----','privatepem'),
 ('token=privatevalue with spaces','privatevalue'),('ghp_123456789012345678901234567890','ghp_123456789012345678901234567890'),
 ('eyJabc.eyJsecret.signedpayload','eyJabc.eyJsecret.signedpayload'),
 ('pbkdf2_sha256$1000000$salt$privatehash','privatehash')])
def test_credential_redaction(text,secret):
    value=redact_text(text)
    assert secret not in value and '[REDACTED]' in value


def test_redaction_field_allowlist_and_authentication(access_setup,client):
    users,engagement,_=access_setup
    record=finding(users,engagement,technical_details='password: do-not-retain\n  safe details\nCookie: private-session')
    serialized=json.dumps(list(AuditEvent.objects.values()),default=str)+json.dumps(list(EntityRevision.objects.values()),default=str)
    assert 'do-not-retain' not in serialized and 'private-session' not in serialized and 'safe details' in serialized
    snap=capture(record)
    with pytest.raises(ValueError):
        record_event(action='finding.updated',actor=users['tester'],engagement=engagement,subject_id=record.pk,
                     before=Snapshot(snap.kind,snap.subject_id,snap.engagement_ref,{**snap.values,'password':'do-not-retain'}))
    with pytest.raises(ValueError):
        record_event(action='finding.updated',metadata={'body':'unsafe request'})
    client.post(reverse('accounts:login'),{'username':'unrecognized-private-user','password':'never-store-password'})
    auth=AuditEvent.objects.get(action='login.failure')
    assert auth.before==auth.after=={} and auth.entity_kind=='authentication'
    serialized=json.dumps(list(AuditEvent.objects.values()),default=str)
    assert 'never-store-password' not in serialized and 'unrecognized-private-user' not in serialized


def test_membership_lifecycle_and_delete_capture(access_setup):
    users,engagement,_=access_setup
    member=grant_membership(actor=users['lead'],engagement_id=engagement.pk,user_id=users['outsider'].pk,role='viewer')
    change_membership(actor=users['lead'],engagement_id=engagement.pk,membership_id=member.pk,version=1,role='tester')
    event=AuditEvent.objects.get(action='membership.changed')
    assert event.before['role']=='viewer' and event.after['role']=='tester'
    revoke_membership(actor=users['lead'],engagement_id=engagement.pk,membership_id=member.pk,version=2)
    assert AuditEvent.objects.get(action='membership.revoked').after=={}
    note=save_note(actor=users['tester'],engagement_id=engagement.pk,body='Deleted documentation')
    delete_note(actor=users['tester'],engagement_id=engagement.pk,note_id=note.pk,version=1)
    event=AuditEvent.objects.get(action='note.deleted')
    assert event.before['body']=='Deleted documentation' and event.after=={}
    transition_engagement(actor=users['lead'],engagement_id=engagement.pk,target='archived',version=1)
    event=AuditEvent.objects.get(action='engagement.status_changed')
    assert event.before['status']=='planned' and event.after['status']=='archived'
    verify_history(actor=users['admin'])


@pytest.mark.parametrize('role,expected',[('lead',200),('reviewer',200),('admin',200),('tester',403),('viewer',403),('outsider',404)])
def test_audit_http_and_service_permissions(access_setup,client,role,expected):
    users,engagement,_=access_setup
    finding(users,engagement)
    client.force_login(users[role])
    for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
        assert client.get(reverse('audit:list',args=[engagement.pk]),**headers).status_code==expected
        assert client.get(reverse('audit:export',args=[engagement.pk]),**headers).status_code==expected
    if expected==200: assert events_for(actor=users[role],engagement_id=engagement.pk).exists()
    else:
        with pytest.raises((PermissionDenied,Http404)): events_for(actor=users[role],engagement_id=engagement.pk)
        with pytest.raises((PermissionDenied,Http404)): export_history(actor=users[role],engagement_id=engagement.pk)
    assert client.get(reverse('system_audit:list')).status_code==(200 if role=='admin' else 403)


def test_cross_engagement_filters_export_and_escaped_history(access_setup,client):
    users,engagement,foreign=access_setup
    local=finding(users,engagement,title='<script>local title</script>')
    remote=save_finding(actor=users['outsider'],engagement_id=foreign.pk,data=definition(title='Foreign secret title'))
    event=AuditEvent.objects.get(action='finding.created',subject_id=local.pk)
    remote_event=AuditEvent.objects.get(action='finding.created',subject_id=remote.pk)
    client.force_login(users['lead'])
    url=reverse('audit:list',args=[engagement.pk])
    filters={'entity':'finding','subject':str(local.pk),'actor':str(users['tester'].pk),'action':'finding.created','date_from':timezone.now().date().isoformat(),'date_to':timezone.now().date().isoformat()}
    assert client.get(url,filters).status_code==200
    response=client.get(reverse('audit:export',args=[engagement.pk]),filters)
    assert response.status_code==200 and response['Content-Disposition'].startswith('attachment;')
    values=response.json()['events']
    assert len(values)==1 and values[0]['subject_id']==str(local.pk)
    assert b'Foreign secret title' not in response.content and set(response['Cache-Control'].split(', '))=={'private','no-store'}
    assert client.get(reverse('audit:detail',args=[engagement.pk,remote_event.pk])).status_code==404
    response=client.get(reverse('audit:detail',args=[engagement.pk,event.pk]))
    assert b'&lt;script&gt;local title&lt;/script&gt;' in response.content and b'<script>local title' not in response.content
    assert client.get(url,{'date_from':'2026-12-01','date_to':'2026-01-01'}).status_code==400
    assert client.get(url,{'actor':'private-submission'}).status_code==400
    assert client.get(url,{'action':'evidence.uploaded'}).context['page'].paginator.count==0
    for role in ['tester','viewer','reviewer','lead','admin']:
        client.force_login(users[role])
        assert client.get(reverse('audit:revisions',args=[engagement.pk,'finding',local.pk])).status_code==200
        assert client.get(reverse('audit:revisions',args=[engagement.pk,'finding',remote.pk])).status_code==404
        with pytest.raises(Http404): revisions_for(actor=users[role],engagement_id=engagement.pk,kind='finding',entity_id=remote.pk)


def test_sealed_database_guards_and_actor_detachment(access_setup):
    users,engagement,_=access_setup
    record=finding(users,engagement)
    event=AuditEvent.objects.get(action='finding.created')
    revision=EntityRevision.objects.get(entity_id=record.pk)
    for operation in [lambda: AuditEvent.objects.filter(pk=event.pk).update(id=event.pk+10000),lambda: AuditEvent.objects.filter(pk=event.pk).update(metadata={'reason':'tampered'}),lambda: AuditEvent.objects.filter(pk=event.pk).update(actor=users['viewer']),lambda: EntityRevision.objects.filter(pk=revision.pk).update(snapshot={}),lambda: EntityRevision.objects.filter(pk=revision.pk).delete()]:
        with pytest.raises(IntegrityError),transaction.atomic(): operation()
    with pytest.raises(PermissionDenied): event.save()
    with pytest.raises(PermissionDenied): event.delete()
    with pytest.raises(PermissionDenied): revision.delete()
    AuditEvent.objects.filter(pk=event.pk).update(actor=None)
    event.refresh_from_db()
    assert event.actor_ref==str(users['tester'].pk) and event.actor is None
    verify_history(actor=users['admin'])
    # A direct unsealed insert is blocked by SQLite, even bypassing Model.save.
    with pytest.raises(IntegrityError),transaction.atomic():
        AuditEvent.objects.bulk_create([AuditEvent(action='logout')])


def test_privileged_body_tamper_is_detected(access_setup):
    users,engagement,_=access_setup
    finding(users,engagement)
    event=AuditEvent.objects.get(action='finding.created')
    with connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='audit_sealed_update'")
        sql=cursor.fetchone()[0]
        cursor.execute('DROP TRIGGER audit_sealed_update')
    try:
        AuditEvent.objects.filter(pk=event.pk).update(after={'title':'tampered'})
        with pytest.raises(AuditIntegrityError): verify_history(actor=users['admin'])
        with pytest.raises(AuditIntegrityError): save_note(actor=users['tester'],engagement_id=engagement.pk,body='Must rollback')
        assert not engagement.notes.exists()
    finally:
        with connection.cursor() as cursor: cursor.execute(sql)


def test_export_limit_and_retention_admin_only(access_setup,settings):
    users,engagement,_=access_setup
    finding(users,engagement)
    settings.TRACE_AUDIT_EXPORT_LIMIT=0
    with pytest.raises(ValidationError): export_history(actor=users['lead'],engagement_id=engagement.pk)
    for role in ['lead','tester','reviewer','viewer','outsider']:
        with pytest.raises(PermissionDenied): verify_history(actor=users[role])
        with pytest.raises(PermissionDenied): cleanup_history(actor=users[role],apply=True,expected_sequence=1)
    settings.TRACE_AUDIT_RETENTION_DAYS=0
    with pytest.raises(ValidationError): cleanup_history(actor=users['admin'])


def test_retention_preserves_checkpoint_requires_review_and_rolls_back(access_setup,settings,monkeypatch):
    users,engagement,_=access_setup
    settings.TRACE_AUDIT_RETENTION_DAYS=30
    field=AuditEvent._meta.get_field('created_at')
    monkeypatch.setattr(field,'_get_default',lambda:timezone.now()-timedelta(days=60))
    record=finding(users,engagement)
    monkeypatch.setattr(field,'_get_default',timezone.now)
    save_note(actor=users['tester'],engagement_id=engagement.pk,body='Keep recent')
    plan=cleanup_history(actor=users['admin'])
    assert plan['eligible']==1 and not plan['applied'] and AuditEvent.objects.count()==2
    with pytest.raises(ValidationError): cleanup_history(actor=users['admin'],apply=True)
    import apps.audit.maintenance as maintenance
    original=maintenance.record_event
    def broken(**kwargs): raise RuntimeError('retention audit failure')
    monkeypatch.setattr(maintenance,'record_event',broken)
    with pytest.raises(RuntimeError): cleanup_history(actor=users['admin'],apply=True,expected_sequence=plan['head_sequence'])
    assert EntityRevision.objects.filter(entity_id=record.pk).count()==1 and AuditEvent.objects.count()==2
    assert not AuditChainState.objects.get(pk=1).retention_active
    monkeypatch.setattr(maintenance,'record_event',original)
    result=cleanup_history(actor=users['admin'],apply=True,expected_sequence=plan['head_sequence'])
    assert result['applied'] and not EntityRevision.objects.filter(entity_id=record.pk).exists()
    checkpoint=verify_history(actor=users['admin'])
    assert checkpoint['anchor_sequence']==1 and checkpoint['head_sequence']==3
    assert AuditEvent.objects.get(action='audit.retention').actor==users['admin']
    output=io.StringIO()
    call_command('verify_audit',admin='admin',stdout=output)
    assert json.loads(output.getvalue())['anchor_sequence']==1
    with pytest.raises(CommandError): call_command('cleanup_audit',admin='lead',stdout=io.StringIO())


def test_concurrent_audits_have_single_contiguous_chain(access_setup):
    users,engagement,_=access_setup
    actor_id=users['tester'].pk
    barrier=Barrier(2)
    def worker(body):
        close_old_connections()
        try:
            actor=User.objects.get(pk=actor_id)
            barrier.wait(timeout=10)
            return save_note(actor=actor,engagement_id=engagement.pk,body=body).pk
        finally: connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,['First writer','Second writer']))
    assert len(set(results))==2
    assert sorted(AuditEvent.objects.values_list('chain_sequence',flat=True))==[1,2]
    assert verify_history(actor=users['admin'])['head_sequence']==2


def test_audit_size_failure_preserves_business_and_head(access_setup,settings):
    users,engagement,_=access_setup
    record=finding(users,engagement)
    head=AuditChainState.objects.get(pk=1).head_hash
    settings.TRACE_AUDIT_MAX_EVENT_BYTES=1
    with pytest.raises(ValidationError):
        save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=record.pk,version=1,data=definition(title='Rejected size'))
    record.refresh_from_db()
    assert record.version==1 and record.title=='Boundary failure'
    assert AuditChainState.objects.get(pk=1).head_hash==head and AuditEvent.objects.count()==1


@pytest.mark.parametrize('position',[0,1])
def test_missing_event_breaks_continuity_or_head(access_setup,position):
    users,engagement,_=access_setup
    save_note(actor=users['tester'],engagement_id=engagement.pk,body='First')
    save_note(actor=users['tester'],engagement_id=engagement.pk,body='Second')
    events=list(AuditEvent.objects.order_by('chain_sequence'))
    # Model/SQL ordinary deletion is denied. A privileged connection bypass can
    # remove a record, but leaves a detectable gap or unmatched head checkpoint.
    with pytest.raises(IntegrityError),transaction.atomic():
        AuditEvent.objects.filter(pk=events[position].pk).delete()
    with connection.constraint_checks_disabled(),connection.cursor() as cursor:
        cursor.execute('DELETE FROM audit_auditevent WHERE id=%s',[events[position].pk])
    with pytest.raises(AuditIntegrityError): verify_history(actor=users['admin'])


def test_export_byte_limit_and_stale_retention_plan(access_setup,settings,monkeypatch):
    users,engagement,_=access_setup
    field=AuditEvent._meta.get_field('created_at')
    monkeypatch.setattr(field,'_get_default',lambda:timezone.now()-timedelta(days=400))
    finding(users,engagement)
    monkeypatch.setattr(field,'_get_default',timezone.now)
    plan=cleanup_history(actor=users['admin'])
    save_note(actor=users['tester'],engagement_id=engagement.pk,body='Intervening write')
    with pytest.raises(ValidationError): cleanup_history(actor=users['admin'],apply=True,expected_sequence=plan['head_sequence'])
    assert AuditEvent.objects.count()==2
    settings.TRACE_AUDIT_EXPORT_MAX_BYTES=1
    with pytest.raises(ValidationError): export_history(actor=users['lead'],engagement_id=engagement.pk)
    assert not AuditEvent.objects.filter(action='audit.exported').exists()
    verify_history(actor=users['admin'])


def test_staff_model_permissions_do_not_grant_global_history(access_setup,client):
    from django.contrib.auth.models import Permission as ModelPermission
    users,engagement,_=access_setup
    finding(users,engagement)
    User.objects.filter(pk=users['tester'].pk).update(is_staff=True)
    users['tester'].user_permissions.add(ModelPermission.objects.get(codename='view_auditevent'),ModelPermission.objects.get(codename='view_entityrevision'))
    from types import SimpleNamespace
    from django.contrib import admin
    from apps.audit.admin import AuditEventAdmin, EntityRevisionAdmin
    assert not AuditEventAdmin(AuditEvent,admin.site).has_view_permission(SimpleNamespace(user=users['tester']))
    assert not EntityRevisionAdmin(EntityRevision,admin.site).has_view_permission(SimpleNamespace(user=users['tester']))
    client.force_login(users['tester'])
    assert client.get(reverse('admin:audit_auditevent_changelist')).status_code in {302,403}
    assert client.get(reverse('admin:audit_entityrevision_changelist')).status_code in {302,403}
    assert client.get(reverse('system_audit:list')).status_code==403
    client.force_login(users['admin'])
    assert client.get(reverse('admin:audit_auditevent_changelist')).status_code==200
