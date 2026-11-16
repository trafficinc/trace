from concurrent.futures import ThreadPoolExecutor
import io
from threading import Event
from unittest.mock import patch
import zipfile
import pytest
from PIL import Image
from docx import Document
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction, IntegrityError, close_old_connections
from django.http import Http404
from django.urls import reverse
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict
from apps.engagements.models import Engagement, EngagementStatus, EngagementMembership
from apps.engagements.services import purge_engagement
from apps.findings.services import save_finding
from apps.findings.models import Finding
from apps.testcases.models import TestCase as CaseRecord
from apps.evidence.services import upload_evidence
from apps.reports.models import Report, ReportRevision, ReportArtifact, ReportTemplate, ReportFinding, SECTIONS
from apps.reports import services, storage
from apps.reports.snapshots import collect_snapshot, materialize_images, canonical_json
from apps.reports.rendering import html_report, docx_report, pdf_report, RenderError
from apps.reports.pdf_worker import offline_fetcher

pytestmark=pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup(access_setup,settings,tmp_path):
    users,engagement,foreign=access_setup
    settings.EVIDENCE_ROOT=tmp_path/'evidence'; settings.EVIDENCE_ROOT.mkdir(mode=0o700)
    settings.REPORT_ROOT=tmp_path/'reports'; settings.REPORT_ROOT.mkdir(mode=0o700)
    engagement.client='Sample client'; engagement.scope_summary='Internal application\n  Restricted scope'
    engagement.objectives='Evaluate access control'; engagement.report_classification='SUPPLIED HANDLING'; engagement.save()
    case=CaseRecord.objects.create(engagement=engagement,title='Authorization test',category='Access',methodology='Manual role comparison',status='passed',actual_result='Expected restrictions held')
    first=save_finding(actor=users['tester'],engagement_id=engagement.pk,data={'title':'First finding','severity':'high','description':'**Rich detail**\n\n```\n  preserve indentation\n```','impact':'Client impact','reproduction_steps':'1. First\n2. Second','remediation':'Apply authorization checks','references':'[Reference](https://example.com/reference)','test_cases':[case.pk]})
    second=save_finding(actor=users['tester'],engagement_id=engagement.pk,data={'title':'Second finding','severity':'critical','description':'Second description','remediation':'Patch system'})
    outsider=Finding.objects.create(engagement=foreign,title='FOREIGN SECRET',severity='low')
    return users,engagement,foreign,first,second,case,outsider


def definition(**kwargs):
    return {'title':'Client assessment','executive_summary':'Executive assessment','methodology':'Manual assessment','recommendations':'Prioritize repairs',
            'header':'Client header','footer':'Client footer','marking':'SUPPLIED MARKING','include_images':False,'logo':'',**kwargs}


def report(setup,**kwargs):
    users,engagement,_,first,second,*_=setup
    return services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(),finding_ids=[second.pk,first.pk],**kwargs)


def snapshot(setup,record):
    users,engagement,*_=setup
    revision=services._reserve(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=record.version)
    return materialize_images(actor=users['tester'],engagement_id=engagement.pk,snapshot=collect_snapshot(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,revision=revision))


def test_snapshot_selection_order_counts_and_sections(setup):
    users,engagement,_,first,second,*_=setup
    record=report(setup)
    data=snapshot(setup,record)
    assert [f['id'] for f in data['findings']]==[str(second.pk),str(first.pk)]
    assert data['severity_summary'][0]['count']==1 and data['severity_summary'][1]['count']==1
    assert data['test_counts']=={'Passed':1}
    assert data['report']['marking']=='SUPPLIED MARKING'
    assert data['report']['template']['sections']==SECTIONS
    audit=AuditEvent.objects.get(action='report.saved',subject_id=record.pk)
    assert audit.before=={} and audit.after['findings']==[str(second.pk),str(first.pk)]
    started=AuditEvent.objects.get(action='report.started',engagement=engagement)
    assert started.after['status']=='rendering' and started.after['report_version']==1
    assert b'FOREIGN SECRET' not in canonical_json(data)
    assert data['engagement']['scope']=='Internal application\n  Restricted scope'
    assert data['findings'][1]['description'].startswith('**Rich detail**')
    save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=first.pk,version=1,data={'title':'Later title','severity':'low'})
    assert data['findings'][1]['title']=='First finding' and data['findings'][1]['version']==1


def test_snapshot_read_connection_is_not_a_writer_and_remains_consistent(setup):
    users,engagement,_,first,*_=setup
    record=report(setup)
    revision=services._reserve(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    with connection.cursor() as cursor: cursor.execute('PRAGMA journal_mode=WAL')
    reached,changed=Event(),Event()
    original=__import__('apps.reports.snapshots',fromlist=['_bounded'])._bounded
    def pause(queryset,*args):
        if args[-1]=='findings':
            reached.set(); assert changed.wait(10)
        return original(queryset,*args)
    def writer():
        close_old_connections()
        try:
            assert reached.wait(10)
            with transaction.atomic():
                Engagement.objects.filter(pk=engagement.pk).update(client='NEW CLIENT')
                Finding.objects.filter(pk=first.pk).update(title='NEW FINDING')
            changed.set()
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as pool, patch('apps.reports.snapshots._bounded',side_effect=pause):
        future=pool.submit(writer)
        data=collect_snapshot(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,revision=revision)
        future.result(timeout=10)
    assert data['engagement']['client']=='Sample client'
    assert data['findings'][1]['title']=='First finding'
    assert Finding.objects.get(pk=first.pk).title=='NEW FINDING'


def test_html_docx_and_real_pdf_render_offline_and_repeatably(setup):
    data=snapshot(setup,report(setup))
    with patch('socket.create_connection',side_effect=AssertionError('Network disabled')):
        html=html_report(data)
        docx=docx_report(data)
        pdf=pdf_report(html)
    assert pdf.startswith(b'%PDF-') and len(pdf)>2000
    assert html==html_report(data) and docx==docx_report(data)
    assert '<strong>Rich detail</strong>' in html and '  preserve indentation' in html
    assert '<h2>Severity summary</h2>' in html and '<h2>Executive summary</h2>' in html
    assert '&quot;DejaVu' not in html
    word=Document(io.BytesIO(docx))
    text='\n'.join(p.text for p in word.paragraphs)
    assert 'Client assessment' in text and 'First finding' in text and '  preserve indentation' in text
    assert 'https://example.com/reference' in text
    assert 'SUPPLIED MARKING' in word.sections[0].header.paragraphs[0].text
    assert 'Client footer' in word.sections[0].footer.paragraphs[0].text
    with zipfile.ZipFile(io.BytesIO(docx)) as package:
        assert all(i.date_time==(1980,1,1,0,0,0) for i in package.infolist())


@pytest.mark.parametrize('value',['https://example.com/image.png','http://127.0.0.1/','file:///etc/passwd','data:image/svg+xml;base64,PHN2Zz4=','ftp://example.com/'])
def test_pdf_fetcher_denies_external_or_active_resources(value):
    with pytest.raises(ValueError): offline_fetcher(value)


def test_templates_are_data_not_executable_code_and_copy_is_versioned(setup):
    users,engagement,_,first,*_=setup
    template=services.save_template(actor=users['admin'],data={'name':'Reusable','palette':'aubergine','sections':list(reversed(SECTIONS)),'is_active':True})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(header='{{ secret }} {% include "/etc/passwd" %} <script>alert(1)</script>'),finding_ids=[first.pk],template_id=template.pk,template_version=1)
    services.save_template(actor=users['admin'],template_id=template.pk,version=1,data={'name':'Changed','palette':'blue','sections':SECTIONS,'is_active':False})
    record.refresh_from_db()
    assert record.template_snapshot['palette']=='aubergine' and record.source_template_version==1
    data=snapshot(setup,record); html=html_report(data)
    assert '{{ secret }}' in html and '{% include' in html and '&lt;script&gt;' in html
    assert '<script>' not in html and data['report']['template']['sections']==list(reversed(SECTIONS))
    assert html.index('<h2>Recommendations</h2>')<html.index('<h2>Scope</h2>')
    with pytest.raises(ValidationError): services.save_template(actor=users['admin'],data={'name':'Invalid','palette':'blue','sections':['scope'],'is_active':True})
    with pytest.raises(PermissionDenied): services.save_template(actor=users['tester'],data={'name':'Unauthorized'})


def test_template_stale_copy_and_unknown_code_fields_rejected(setup):
    users,engagement,_,first,*_=setup
    template=services.save_template(actor=users['admin'],data={'name':'Reusable','palette':'blue','sections':SECTIONS,'is_active':True})
    with pytest.raises(EditConflict): services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(),finding_ids=[first.pk],template_id=template.pk,template_version=99)
    with pytest.raises(ValidationError): services.save_template(actor=users['admin'],data={'name':'Executable','html':'{{ settings.SECRET_KEY }}'})


def test_revision_files_immutable_and_old_exports_survive_source_edits(setup,settings):
    users,engagement,_,first,*_=setup
    record=report(setup)
    revision=services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    assert revision.status=='ready' and revision.version==2 and revision.artifacts.count()==4
    artifact,file=services.open_artifact(actor=users['reviewer'],engagement_id=engagement.pk,revision_id=revision.pk,format='html')
    old=file.read(); file.close()
    path=settings.REPORT_ROOT/engagement.pk.hex/artifact.storage_key
    assert path.stat().st_mode & 0o777==0o600
    save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=first.pk,version=1,data={'title':'Later title','severity':'low'})
    _,file=services.open_artifact(actor=users['reviewer'],engagement_id=engagement.pk,revision_id=revision.pk,format='html')
    assert file.read()==old; file.close()
    assert b'First finding' in old and b'Later title' not in old
    with pytest.raises(IntegrityError),transaction.atomic(): ReportArtifact.objects.filter(pk=artifact.pk).update(sha256='a'*64)
    with pytest.raises(IntegrityError),transaction.atomic(): ReportRevision.objects.filter(pk=revision.pk).update(report_version=2)
    assert AuditEvent.objects.filter(action='report.ready',subject_id=revision.pk).exists()


@pytest.mark.parametrize('role', ['lead','tester','reviewer','admin'])
def test_generation_roles_and_http_downloads(setup,client,role):
    users,engagement,*_=setup
    record=report(setup)
    revision=services.generate_report(actor=users[role],engagement_id=engagement.pk,report_id=record.pk,version=1)
    client.force_login(users[role])
    for format in ['docx','html','pdf']:
        response=client.get(reverse('reports:download',args=[engagement.pk,revision.pk,format]))
        assert response.status_code==200 and response['Content-Disposition'].startswith('attachment;')
        assert b''.join(response.streaming_content); response.close()
    response=client.get(reverse('reports:preview',args=[engagement.pk,revision.pk]))
    assert response.status_code==200 and response['Content-Disposition'].startswith('inline;')
    assert 'sandbox' in response['Content-Security-Policy'] and "default-src 'none'" in response['Content-Security-Policy']
    assert 'unsafe-inline' in response['Content-Security-Policy'] and 'script-src' not in response['Content-Security-Policy']
    assert response['Cache-Control']=='no-store, private'
    response.close()


@pytest.mark.parametrize('role', ['viewer','outsider'])
def test_denied_generation_and_foreign_http_ids(setup,client,role):
    users,engagement,foreign,*_=setup
    record=report(setup)
    with pytest.raises((PermissionDenied,Http404)): services.generate_report(actor=users[role],engagement_id=engagement.pk,report_id=record.pk,version=1)
    client.force_login(users[role])
    for hx in [{},{'HTTP_HX_REQUEST':'true'}]:
        assert client.post(reverse('reports:detail',args=[engagement.pk,record.pk]),{'version':1},**hx).status_code==(403 if role=='viewer' else 404)
    client.force_login(users['outsider'])
    assert client.get(reverse('reports:detail',args=[foreign.pk,record.pk])).status_code==404
    assert ReportRevision.objects.count()==0


def test_foreign_selection_and_database_relationship_guards(setup):
    users,engagement,foreign,first,_,_,outsider=setup
    with pytest.raises(ValidationError): services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(),finding_ids=[outsider.pk])
    record=report(setup)
    link=ReportFinding(report=record,finding=outsider,position=99)
    with pytest.raises(ValidationError): link.clean()
    with pytest.raises(IntegrityError),transaction.atomic(): ReportFinding.objects.bulk_create([link])
    with pytest.raises(IntegrityError),transaction.atomic(): Finding.objects.filter(pk=first.pk).update(engagement=foreign)
    with pytest.raises(IntegrityError),transaction.atomic(): Report.objects.filter(pk=record.pk).update(engagement=foreign)


def test_safe_images_and_logo_persist_in_snapshot(setup):
    users,engagement,_,first,_,case,*_=setup
    output=io.BytesIO(); Image.new('RGB',(128,96),'red').save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,upload=SimpleUploadedFile('image.png',output.getvalue()),data={'description':'Screenshot','test_cases':[case.pk],'findings':[first.pk]})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(include_images=True,logo=evidence.pk),finding_ids=[first.pk])
    data=snapshot(setup,record)
    assert data['logo']['image'].startswith('data:image/png;base64,') and data['evidence'][0]['image']
    assert b'thumbnail_key' not in canonical_json(data)
    assert '<img' in html_report(data)
    assert Document(io.BytesIO(docx_report(data))).inline_shapes
    assert pdf_report(html_report(data)).startswith(b'%PDF-')


def test_image_integrity_and_export_limits_fail_closed(setup,settings):
    users,engagement,_,first,_,case,*_=setup
    output=io.BytesIO(); Image.new('RGB',(32,32)).save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,upload=SimpleUploadedFile('image.png',output.getvalue()),data={'test_cases':[case.pk]})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(include_images=True,logo=evidence.pk),finding_ids=[first.pk])
    (settings.EVIDENCE_ROOT/engagement.pk.hex/evidence.thumbnail_key).write_bytes(b'corrupt')
    with pytest.raises(ValidationError): snapshot(setup,record)
    settings.TRACE_REPORT_MAX_FINDINGS=0
    with pytest.raises(ValidationError): snapshot(setup,record)


def test_direct_evidence_selection_embeds_images_without_findings(setup):
    users,engagement,_,_,_,case,*_=setup
    output=io.BytesIO(); Image.new('RGB',(128,96),'red').save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('standalone.png',output.getvalue()),data={'test_cases':[case.pk]})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,
        data=definition(include_images=True),finding_ids=[],evidence_ids=[evidence.pk])
    data=snapshot(setup,record)
    assert len(data['evidence'])==1 and data['evidence'][0]['image']
    assert len(Document(io.BytesIO(docx_report(data))).inline_shapes)==1
    assert html_report(data).count('data:image/png;base64,')==1
    assert not evidence.findings.exists()
    assert AuditEvent.objects.get(action='report.saved',subject_id=record.pk).after['additional_evidence']==[str(evidence.pk)]


def test_direct_evidence_selection_is_versioned_and_scoped(setup,client):
    from apps.reports.models import ReportEvidence
    users,engagement,foreign,first,*_=setup
    output=io.BytesIO(); Image.new('RGB',(32,32)).save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('selected.png',output.getvalue()),data={'findings':[first.pk]})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,
        data=definition(include_images=True),finding_ids=[first.pk],evidence_ids=[evidence.pk])
    assert len(snapshot(setup,record)['evidence'])==1  # Direct + automatic references deduplicate.
    client.force_login(users['tester'])
    response=client.get(reverse('reports:edit',args=[engagement.pk,record.pk]))
    assert response.context['form']['additional_evidence'].value()==[evidence.pk]
    saved=services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,
        version=1,data=definition(),finding_ids=[],evidence_ids=[])
    with pytest.raises(EditConflict):
        services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,
            version=1,data=definition(),finding_ids=[],evidence_ids=[evidence.pk])
    assert not saved.additional_evidence.exists()
    foreign_report=Report.objects.create(engagement=foreign,title='Foreign')
    with pytest.raises(ValidationError):
        services.save_report(actor=users['admin'],engagement_id=foreign.pk,data=definition(),finding_ids=[],evidence_ids=[evidence.pk])
    with pytest.raises(IntegrityError),transaction.atomic():
        ReportEvidence.objects.bulk_create([ReportEvidence(report=foreign_report,evidence=evidence)])
    with pytest.raises(PermissionDenied):
        services.save_report(actor=users['viewer'],engagement_id=engagement.pk,data=definition(),finding_ids=[],evidence_ids=[evidence.pk])


def test_direct_evidence_images_can_be_disabled(setup):
    users,engagement,_,first,*_=setup
    output=io.BytesIO(); Image.new('RGB',(32,32)).save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('reference.png',output.getvalue()),data={'findings':[first.pk]})
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,
        data=definition(include_images=False),finding_ids=[],evidence_ids=[evidence.pk])
    data=snapshot(setup,record)
    assert len(data['evidence'])==1 and 'image' not in data['evidence'][0]
    assert not Document(io.BytesIO(docx_report(data))).inline_shapes


def test_direct_evidence_http_save_and_conflict_preserve_selection(setup,client):
    users,engagement,_,first,*_=setup
    output=io.BytesIO(); Image.new('RGB',(32,32)).save(output,format='PNG')
    evidence=upload_evidence(actor=users['tester'],engagement_id=engagement.pk,
        upload=SimpleUploadedFile('http-image.png',output.getvalue()),data={'findings':[first.pk]})
    client.force_login(users['tester'])
    payload={**definition(include_images=True),'additional_evidence':[str(evidence.pk)],
        'findings-TOTAL_FORMS':'0','findings-INITIAL_FORMS':'0',
        'findings-MIN_NUM_FORMS':'0','findings-MAX_NUM_FORMS':'500'}
    assert client.post(reverse('reports:create',args=[engagement.pk]),payload).status_code==302
    record=Report.objects.get()
    assert list(record.additional_evidence.all())==[evidence]
    services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,
        version=1,data=definition(),finding_ids=[],evidence_ids=[])
    response=client.post(reverse('reports:edit',args=[engagement.pk,record.pk]),
        {**payload,'version':1},HTTP_HX_REQUEST='true')
    assert response.status_code==409
    assert response.context['form']['additional_evidence'].value()==[str(evidence.pk)]
    assert b'http-image.png' in response.content
    assert not record.additional_evidence.exists()


def test_rendering_holds_no_write_transaction_and_failures_preserve_history(setup,settings):
    users,engagement,*_=setup
    record=report(setup)
    def fail(snapshot):
        assert not connection.in_atomic_block
        raise RenderError('sensitive diagnostic must not be stored')
    with patch('apps.reports.services.render_all',side_effect=fail):
        with pytest.raises(RenderError): services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    revision=record.revisions.get()
    assert revision.status=='failed' and revision.failure_code=='generation_failed'
    assert not revision.artifacts.exists() and list(settings.REPORT_ROOT.glob('*/*'))==[]
    assert AuditEvent.objects.filter(action='report.failed').exists()


def test_revocation_during_render_cannot_publish(setup,settings):
    users,engagement,*_=setup
    record=report(setup)
    def revoked(snapshot):
        assert not connection.in_atomic_block
        EngagementMembership.objects.filter(engagement=engagement,user=users['tester']).update(role='viewer')
        return {'html':b'private','docx':b'private','pdf':b'private'}
    with patch('apps.reports.services.render_all',side_effect=revoked):
        with pytest.raises(PermissionDenied): services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    assert record.revisions.get().status=='failed' and not ReportArtifact.objects.exists()
    assert list(settings.REPORT_ROOT.glob('*/*'))==[]


def test_closed_setup_is_frozen_but_derived_exports_and_purge_protection_remain(setup):
    users,engagement,*_=setup
    record=report(setup)
    engagement.status=EngagementStatus.ARCHIVED; engagement.save()
    with pytest.raises(ValidationError): services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1,data=definition(),finding_ids=[])
    revision=services.generate_report(actor=users['reviewer'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    assert revision.status=='ready'
    with pytest.raises(ValidationError): purge_engagement(actor=users['admin'],engagement_id=engagement.pk,version=engagement.version,confirmation=str(engagement.pk),reason='test-data')


def test_report_and_template_pages_work_with_versioned_forms(setup,client):
    users,engagement,_,first,second,*_=setup
    client.force_login(users['tester'])
    response=client.get(reverse('reports:create',args=[engagement.pk]))
    assert response.status_code==200
    assert b'for="id_findings-0-include"' in response.content
    assert b'for="id_findings-0-position"' in response.content
    payload={**definition(),'findings-TOTAL_FORMS':'2','findings-INITIAL_FORMS':'2','findings-MIN_NUM_FORMS':'0','findings-MAX_NUM_FORMS':'500',
             'findings-0-finding':str(first.pk),'findings-0-include':'on','findings-0-position':2,'findings-1-finding':str(second.pk),'findings-1-include':'on','findings-1-position':1}
    response=client.post(reverse('reports:create',args=[engagement.pk]),payload)
    assert response.status_code==302
    record=Report.objects.get()
    assert [link.finding_id for link in record.finding_links.all()]==[second.pk,first.pk]
    assert client.get(reverse('reports:list',args=[engagement.pk])).status_code==200
    assert client.get(reverse('reports:detail',args=[engagement.pk,record.pk])).status_code==200
    assert client.get(reverse('reports:edit',args=[engagement.pk,record.pk])).status_code==200
    response=client.post(reverse('reports:edit',args=[engagement.pk,record.pk]),{**payload,'title':'Unsaved report','version':99},HTTP_HX_REQUEST='true')
    assert response.status_code==409 and b'Unsaved report' in response.content and b'findings-0-include' in response.content
    client.force_login(users['admin'])
    assert client.get(reverse('report_templates:create')).status_code==200
    assert client.post(reverse('report_templates:create'),{'name':'Shared','palette':'blue','sections':'\n'.join(SECTIONS),'is_active':'on'}).status_code==302
    template=ReportTemplate.objects.get()
    assert client.get(reverse('report_templates:edit',args=[template.pk])).status_code==200
    assert client.get(reverse('report_templates:list')).status_code==200


def test_report_storage_traversal_and_symlinks_rejected(setup,settings,tmp_path):
    _,engagement,*_=setup
    with pytest.raises(storage.StorageError): storage.open_file(engagement.pk,'../../secret')
    outside=tmp_path/'outside'; outside.mkdir(mode=0o700)
    (settings.REPORT_ROOT/engagement.pk.hex).symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError): storage.create_file(engagement.pk)
    assert not list(outside.iterdir())


def test_new_revisions_reflect_new_data_without_replacing_previous_outputs(setup):
    users,engagement,_,first,second,*_=setup
    record=report(setup)
    with patch('apps.reports.services.render_all',side_effect=lambda snapshot:{'html':html_report(snapshot).encode(),'docx':b'word fixture','pdf':b'pdf fixture'}):
        one=services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
        save_finding(actor=users['tester'],engagement_id=engagement.pk,finding_id=first.pk,version=1,data={'title':'Updated for revision two','severity':'low'})
        two=services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    assert (one.number,two.number)==(1,2)
    _,left=services.open_artifact(actor=users['lead'],engagement_id=engagement.pk,revision_id=one.pk,format='html')
    _,right=services.open_artifact(actor=users['lead'],engagement_id=engagement.pk,revision_id=two.pk,format='html')
    assert b'Updated for revision two' not in left.read() and b'Updated for revision two' in right.read()
    left.close();right.close()
    assert record.revisions.count()==2


def test_excluded_findings_not_exported_and_empty_selection_has_zero_counts(setup):
    users,engagement,_,first,second,*_=setup
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(),finding_ids=[first.pk])
    data=snapshot(setup,record)
    assert 'Second finding' not in html_report(data)
    assert data['severity_summary'][0]['count']==0
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1,data=definition(executive_summary=''),finding_ids=[])
    data=snapshot(setup,record)
    assert all(row['count']==0 for row in data['severity_summary'])
    assert '0 selected findings' in data['report']['executive_summary']
    assert data['tests'][0]['status']=='Passed'


def test_stale_config_cannot_replace_finding_selection(setup):
    users,engagement,_,first,second,*_=setup
    record=report(setup)
    record=services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1,data=definition(title='Current'),finding_ids=[first.pk])
    with pytest.raises(EditConflict): services.save_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1,data=definition(title='Stale'),finding_ids=[second.pk])
    record.refresh_from_db()
    assert record.title=='Current' and record.version==2 and list(record.findings.all())==[first]


def test_final_database_failure_rolls_back_artifacts_and_cleans_files(setup,settings):
    users,engagement,*_=setup
    record=report(setup)
    with patch('apps.reports.services.render_all',return_value={'html':b'html','docx':b'word','pdf':b'pdf'}),patch('apps.reports.services.ReportArtifact.objects.bulk_create',side_effect=IntegrityError):
        with pytest.raises(IntegrityError): services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    assert record.revisions.get().status=='failed' and not ReportArtifact.objects.exists()
    assert list(settings.REPORT_ROOT.glob('*/*'))==[]
    assert not AuditEvent.objects.filter(action='report.ready').exists()


def test_foreign_revision_downloads_and_hash_corruption_fail_closed(setup,settings,client):
    users,engagement,foreign,*_=setup
    record=report(setup)
    with patch('apps.reports.services.render_all',return_value={'html':b'html','docx':b'word','pdf':b'pdf'}):
        revision=services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    client.force_login(users['outsider'])
    for hx in [{},{'HTTP_HX_REQUEST':'true'}]:
        response=client.get(reverse('reports:download',args=[foreign.pk,revision.pk,'pdf']),**hx)
        assert response.status_code==404
    client.force_login(users['viewer'])
    assert client.get(reverse('reports:download',args=[engagement.pk,revision.pk,'pdf'])).status_code==403
    artifact=revision.artifacts.get(format='pdf')
    (settings.REPORT_ROOT/engagement.pk.hex/artifact.storage_key).write_bytes(b'corrupted')
    client.force_login(users['tester'])
    assert client.get(reverse('reports:download',args=[engagement.pk,revision.pk,'pdf'])).status_code==409
    assert client.get(reverse('reports:download',args=[engagement.pk,revision.pk,'snapshot'])).status_code==404


def test_orphan_cleanup_respects_leases_and_committed_references(setup,settings):
    import os
    users,engagement,*_=setup
    record=report(setup)
    with patch('apps.reports.services.render_all',return_value={'html':b'html','docx':b'word','pdf':b'pdf'}):
        revision=services.generate_report(actor=users['tester'],engagement_id=engagement.pk,report_id=record.pk,version=1)
    artifact=revision.artifacts.get(format='pdf')
    os.utime(settings.REPORT_ROOT/engagement.pk.hex/artifact.storage_key,(0,0))
    key,file=storage.create_file(engagement.pk);file.write(b'interrupted');file.flush();os.utime(file.fileno(),(0,0))
    assert services.cleanup_orphans()[0]==0
    file.close()
    output=io.StringIO();call_command('cleanup_reports',stdout=output)
    assert 'Removed 1 files' in output.getvalue()
    assert (settings.REPORT_ROOT/engagement.pk.hex/artifact.storage_key).exists()
    assert not (settings.REPORT_ROOT/engagement.pk.hex/key).exists()


def test_revision_numbers_are_serialized_across_connections(setup):
    from threading import Barrier
    users,engagement,*_=setup
    record=report(setup);barrier=Barrier(2)
    def reserve(_):
        close_old_connections()
        try:
            actor=User.objects.get(pk=users['tester'].pk)
            barrier.wait(timeout=10)
            return services._reserve(actor=actor,engagement_id=engagement.pk,report_id=record.pk,version=1).number
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(reserve,[1,2]))==[1,2]


def test_foreign_logo_and_revision_scope_guards(setup):
    users,engagement,foreign,*_=setup
    from apps.evidence.models import Evidence
    fake=Evidence.objects.create(engagement=foreign,original_filename='logo.png',storage_key='a'*32,kind='png',content_type='image/png',size=1,sha256='b'*64,uploader=users['outsider'])
    with pytest.raises(ValidationError): services.save_report(actor=users['tester'],engagement_id=engagement.pk,data=definition(logo=fake.pk),finding_ids=[])
    record=report(setup)
    with pytest.raises(IntegrityError),transaction.atomic(): Report.objects.filter(pk=record.pk).update(logo=fake)
    with pytest.raises(IntegrityError),transaction.atomic(): ReportRevision.objects.create(engagement=foreign,report=record,number=1,report_version=1)
