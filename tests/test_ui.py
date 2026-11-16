"""Navigation, authorization boundaries and server-rendered accessibility contracts."""
from html.parser import HTMLParser
from uuid import uuid4
import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from apps.accounts.models import User
from apps.assets.models import Asset
from apps.audit.services import record_event
from apps.core.dashboards import workspace_summary, engagement_summary
from apps.core.search import search_records
from apps.engagements.models import Engagement, EngagementMembership, EngagementMilestone
from apps.findings.models import Finding
from apps.findings.services import save_finding
from apps.testcases.models import TestCase as Case
from apps.evidence.models import Evidence
from apps.reports.models import Report

pytestmark=pytest.mark.django_db


class Markup(HTMLParser):
    def __init__(self,html):
        super().__init__(); self.elements=[]; self.feed(html)
    def handle_starttag(self,tag,attrs): self.elements.append((tag,dict(attrs)))
    def attrs(self,tag): return [attrs for name,attrs in self.elements if name==tag]


@pytest.fixture
def work(access_setup):
    users,first,foreign=access_setup
    local=Case.objects.create(engagement=first,title='Boundary active case',status='in_progress',assigned_tester=users['tester'])
    Case.objects.create(engagement=first,title='Boundary passed case',status='passed',actual_result='Denied')
    Case.objects.create(engagement=foreign,title='FOREIGN SECRET TEST',status='in_progress')
    finding=save_finding(actor=users['tester'],engagement_id=first.pk,data={'title':'Boundary open finding','severity':'critical','technical_details':'PRIVATE AUDIT BODY'})
    Finding.objects.create(engagement=first,title='Boundary remediated finding',status='remediated',author=users['tester'])
    Finding.objects.create(engagement=foreign,title='FOREIGN SECRET FINDING',author=users['outsider'])
    Asset.objects.create(engagement=first,name='Boundary local asset',asset_type='host')
    Asset.objects.create(engagement=foreign,name='FOREIGN SECRET ASSET',asset_type='host')
    evidence=Evidence.objects.create(engagement=first,original_filename='Boundary-log.txt',storage_key=uuid4().hex,kind='text',content_type='text/plain',size=10,sha256='a'*64,uploader=users['tester'])
    Evidence.objects.create(engagement=foreign,original_filename='FOREIGN SECRET FILE.txt',storage_key=uuid4().hex,kind='text',content_type='text/plain',size=10,sha256='b'*64,uploader=users['outsider'])
    EngagementMilestone.objects.create(engagement=first,title='Complete task',completed=True)
    EngagementMilestone.objects.create(engagement=first,title='Open task')
    record_event(action='login.success',actor=users['admin'])
    return users,first,foreign,local,finding,evidence


@pytest.mark.parametrize('role',['lead','tester','reviewer','viewer','admin'])
def test_dashboard_roles_scoping_counts_and_partial(work,client,role):
    users,first,foreign,*_=work
    client.force_login(users[role])
    for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
        response=client.get(reverse('core:dashboard'),**headers)
        assert response.status_code==200 and response['Cache-Control']=='no-store, private'
        assert 'HX-Request' in response['Vary']
        assert b'Boundary active case' in response.content and b'Boundary open finding' in response.content
        assert b'PRIVATE AUDIT BODY' not in response.content and b'Login succeeded' not in response.content
        assert (b'FOREIGN SECRET TEST' in response.content)==(role in {'lead','admin'})
        # Lead also has Viewer access on the second engagement; scope is access,
        # not the role held on the first engagement.
        assert response.context['summary']['tests']==(2 if role in {'lead','admin'} else 1)
        assert (b'<!doctype html>' not in response.content)==bool(headers)
        assert b'<textarea' not in response.content
    if role=='tester': assert b'Assigned to you' in response.content


def test_unauthorized_disabled_and_revoked_dashboards(work,client):
    users,first,foreign,*_=work
    assert client.get(reverse('core:dashboard')).status_code==302
    assert client.get(reverse('core:search')).status_code==302
    client.force_login(users['viewer'])
    url=reverse('engagements:detail',args=[foreign.pk])
    for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
        response=client.get(url,{'panel':'overview_status'},**headers)
        assert response.status_code==404 and b'FOREIGN SECRET' not in response.content
    EngagementMembership.objects.filter(engagement=first,user=users['viewer']).delete()
    response=client.get(reverse('core:dashboard'),HTTP_HX_REQUEST='true')
    assert response.status_code==200 and b'Boundary' not in response.content
    assert response.context['summary']['engagements']==0
    User.objects.filter(pk=users['viewer'].pk).update(is_active=False)
    response=client.get(reverse('core:search'),{'q':'Boundary'},HTTP_HX_REQUEST='true')
    assert response.status_code==204 and 'HX-Redirect' in response and b'Boundary' not in response.content


def test_engagement_progress_is_real_and_severity_excludes_closed_findings(work,client):
    users,first,foreign,*_=work
    summary=engagement_summary(actor=users['viewer'],engagement_id=first.pk)
    assert summary['test_progress']=={'total':2,'finished':1,'passed':1,'failed':0,'blocked':0,'percent':50}
    assert [item['count'] for item in summary['severity_summary']]==[1,0,0,0,0]
    assert summary['member_activity'][0]['actor__username']=='tester'
    client.force_login(users['viewer'])
    url=reverse('engagements:detail',args=[first.pk])
    page=client.get(url)
    assert b'1 of 2 cases finished' in page.content and b'1 / 2 complete' in page.content
    response=client.get(url,{'panel':'overview_status'},HTTP_HX_REQUEST='true')
    assert response.status_code==200 and b'id="engagement-status"' in response.content
    assert b'<!doctype html>' not in response.content and b'<form' not in response.content
    assert b'FOREIGN SECRET' not in response.content and b'PRIVATE AUDIT BODY' not in response.content
    assert 'HX-Request' in response['Vary']
    filtered=client.get(reverse('findings:list',args=[first.pk]),{'severity':'critical','open':'1'})
    assert filtered.context['page'].paginator.count==1


@pytest.mark.parametrize('kind',['engagement','asset','test_case','finding','evidence'])
@pytest.mark.parametrize('htmx',[False,True])
def test_search_domain_boundaries_and_partial_contract(work,client,kind,htmx):
    users,first,foreign,*_=work
    client.force_login(users['tester'])
    headers={'HTTP_HX_REQUEST':'true'} if htmx else {}
    response=client.get(reverse('core:search'),{'q':'Boundary' if kind!='engagement' else 'engagement','kind':kind},**headers)
    assert response.status_code==200
    assert response.context['results'].paginator.count>=1
    assert b'FOREIGN SECRET' not in response.content and b'Second engagement' not in response.content
    assert (b'<!doctype html>' not in response.content)==htmx
    assert 'HX-Request' in response['Vary'] and response['Cache-Control']=='no-store, private'
    empty=client.get(reverse('core:search'),{'q':'FOREIGN SECRET','kind':kind},**headers)
    assert empty.context['results'].paginator.count==0
    unauthorized=client.get(reverse('core:search'),{'q':'','kind':kind,'engagement':foreign.pk},**headers)
    assert unauthorized.status_code==404
    from django.http import Http404
    with pytest.raises(Http404):
        search_records(actor=users['tester'],data={'q':'Boundary','kind':kind,'engagement':str(foreign.pk)})


def test_search_validation_literal_matching_and_deleted_evidence(work,client):
    users,first,_,_,_,evidence=work
    client.force_login(users['tester'])
    url=reverse('core:search')
    for data in [{'q':'x'*201},{'q':'Boundary','kind':'account'},{'q':'Boundary','engagement':'../secret'}]:
        assert client.get(url,data).status_code==400
    assert client.get(url).context['results'].paginator.count==0
    assert client.get(url,{'q':'%','kind':'finding'}).context['results'].paginator.count==0
    Evidence.objects.filter(pk=evidence.pk).update(deleted_at=__import__('django.utils.timezone',fromlist=['now']).now())
    assert client.get(url,{'q':'Boundary','kind':'evidence'}).context['results'].paginator.count==0
    response=client.get(url,{'q':'<script>alert(1)</script>'})
    assert b'<script>alert(1)</script>' not in response.content
    assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in response.content


def test_search_pagination_keeps_filters_and_query_count_is_bounded(work,client):
    users,first,*_=work
    Case.objects.bulk_create([Case(engagement=first,title=f'Paged test {i}') for i in range(43)])
    client.force_login(users['tester'])
    with CaptureQueriesContext(connection) as queries:
        response=client.get(reverse('core:search'),{'q':'Paged test','kind':'test_case','engagement':first.pk,'page':'2'})
    assert response.status_code==200 and len(response.context['search_rows'])==20
    assert response.context['results'].paginator.count==43
    assert 'kind=test_case' in response.context['search_params'] and str(first.pk) in response.context['search_params']
    assert len(queries)<=18
    assert b'aria-label="Table pages"' in response.content


def test_dashboard_query_budget_does_not_scale_with_rendered_rows(work,client):
    users,first,*_=work
    client.force_login(users['tester'])
    # Warm vendor checks and template caches outside the measured region.
    client.get(reverse('core:dashboard'))
    with CaptureQueriesContext(connection) as small: client.get(reverse('core:dashboard'))
    Case.objects.bulk_create([Case(engagement=first,title=f'Priority {i}',assigned_tester=users['tester']) for i in range(30)])
    Finding.objects.bulk_create([Finding(engagement=first,title=f'Finding {i}',author=users['tester']) for i in range(30)])
    with CaptureQueriesContext(connection) as large:
        response=client.get(reverse('core:dashboard'))
    assert len(large)==len(small) and len(large)<=18
    assert len(response.context['active_tests'])==10 and len(response.context['open_findings'])==10
    activity_queries=[item['sql'] for item in large if 'audit_auditevent' in item['sql']]
    assert activity_queries and all('"before"' not in query and '"after"' not in query and '"metadata"' not in query for query in activity_queries)


def test_navigation_breadcrumbs_accessibility_and_long_text(work,client):
    users,first,_,case,finding,evidence=work
    client.force_login(users['viewer'])
    response=client.get(reverse('findings:detail',args=[first.pk,finding.pk]))
    markup=Markup(response.content.decode())
    assert any(a.get('aria-label')=='Breadcrumb' for a in markup.attrs('nav'))
    assert any(a.get('aria-current')=='page' for a in markup.attrs('li'))
    assert b'href="/search/"' in response.content and b'First engagement' in response.content
    assert reverse('reports:list',args=[first.pk]).encode() not in response.content
    assert ('href="'+reverse('audit:list',args=[first.pk])+'"').encode() not in response.content
    client.force_login(users['lead'])
    response=client.get(reverse('engagements:detail',args=[first.pk]))
    assert reverse('reports:list',args=[first.pk]).encode() in response.content
    assert ('href="'+reverse('audit:list',args=[first.pk])+'"').encode() in response.content
    page=client.get(reverse('core:dashboard'))
    markup=Markup(page.content.decode())
    ids=[a['id'] for _,a in markup.elements if a.get('id')]
    assert len(ids)==len(set(ids))
    assert any(a.get('href')=='#main-content' for a in markup.attrs('a'))
    assert all(a.get('scope') in {'row','col'} for a in markup.attrs('th'))
    assert any(a.get('aria-label')=='Toggle navigation' for a in markup.attrs('button'))
    css=(settings.BASE_DIR/'static/css/app.css').read_text()
    assert 'overflow-wrap:anywhere' in css and 'prefers-reduced-motion' in css and ':focus-visible' in css
    Evidence.objects.create(engagement=first, original_filename='<script>'+('long-'*30)+'.txt', storage_key=uuid4().hex, kind='text',content_type='text/plain',size=1,sha256='c'*64,uploader=users['tester'])
    response=client.get(reverse('evidence:list',args=[first.pk]))
    assert b'&lt;script&gt;long-' in response.content and b'<script>long-' not in response.content


def test_form_labels_aria_errors_and_success_notifications(work,client):
    users,first,*_=work
    client.force_login(users['tester'])
    response=client.post(reverse('assets:create',args=[first.pk]),{'name':'','asset_type':'host'})
    assert response.status_code in {200,400}
    markup=Markup(response.content.decode())
    labels={a.get('for') for a in markup.attrs('label')}
    assert 'id_name' in labels
    field=next(a for a in markup.attrs('input') if a.get('name')=='name')
    assert field.get('aria-invalid')=='true' and 'form-control' in field.get('class','')
    assert 'id_name_error' in field.get('aria-describedby','')
    assert b'Check the form' in response.content and b'role="alert"' in response.content
    response=client.post(reverse('assets:create',args=[first.pk]),{'name':'Saved UI asset','asset_type':'host','hostname':'ui-test.internal','scope_status':'in_scope'},follow=True)
    assert response.status_code==200 and b'Changes saved.' in response.content and b'alert-success' in response.content


def test_permission_errors_are_generic_vary_aware_and_private(work,client,settings):
    users,first,foreign,*_=work
    settings.DEBUG=False
    client.force_login(users['viewer'])
    for headers in [{},{'HTTP_HX_REQUEST':'true'}]:
        response=client.get(reverse('assets:create',args=[first.pk]),**headers)
        assert response.status_code==403 and b'Access unavailable' in response.content
        assert 'HX-Request' in response['Vary'] and response['Cache-Control']=='no-store, private'
        assert (b'<!doctype html>' not in response.content)==bool(headers)
        response=client.get(reverse('engagements:detail',args=[foreign.pk]),**headers)
        assert response.status_code==404 and b'Page unavailable' in response.content
        assert b'Second engagement' not in response.content


def test_report_and_evidence_filters_paginate_and_remain_scoped(work,client):
    users,first,foreign,*_=work
    Report.objects.bulk_create([Report(engagement=first,title=f'Quarterly report {i}') for i in range(23)])
    Report.objects.create(engagement=foreign,title='FOREIGN SECRET REPORT')
    client.force_login(users['tester'])
    url=reverse('reports:list',args=[first.pk])
    response=client.get(url,{'q':'Quarterly','sort':'title','page':2},HTTP_HX_REQUEST='true')
    assert response.status_code==200 and len(response.context['page'])==3
    assert b'<!doctype html>' not in response.content and b'FOREIGN SECRET' not in response.content
    assert 'q=Quarterly' in response.context['pagination_query']
    response=client.get(reverse('evidence:list',args=[first.pk]),{'q':'Boundary','kind':'png'},HTTP_HX_REQUEST='true')
    assert response.status_code==200 and response.context['page'].paginator.count==0
    assert b'FOREIGN SECRET' not in response.content


def test_local_assets_fonts_csp_and_theme_preferences(work,client):
    users,*_=work
    client.force_login(users['tester'])
    response=client.get(reverse('core:dashboard'))
    markup=Markup(response.content.decode())
    for tag in ['script','link']:
        for attrs in markup.attrs(tag):
            url=attrs.get('src') or attrs.get('href') or ''
            assert not url.startswith(('http:','https:','//'))
    root=settings.BASE_DIR
    assert (root/'static/vendor/inter-latin.woff2').read_bytes().startswith(b'wOF2')
    assert 'SIL OPEN FONT LICENSE' in (root/'static/vendor/inter.LICENSE').read_text().upper()
    assert 'font-src \'self\'' in response['Content-Security-Policy']
    assert 'trace.display' in (root/'static/js/theme.js').read_text()
    profile=client.get(reverse('accounts:profile'))
    assert b'data-theme-mode' in profile.content and b'data-theme-palette' in profile.content


def test_direct_dashboard_services_do_not_read_foreign_scope(work):
    from django.http import Http404
    users,first,foreign,*_=work
    summary=workspace_summary(actor=users['tester'])
    assert summary['summary']['engagements']==1
    assert all(case.engagement_id==first.pk for case in summary['active_tests'])
    with pytest.raises(Http404): engagement_summary(actor=users['tester'],engagement_id=foreign.pk)


def test_workspace_engagement_pagination_preserves_user_scope(work,client):
    users,first,*_=work
    for i in range(12):
        engagement=Engagement.objects.create(name=f'Assigned {i}')
        EngagementMembership.objects.create(user=users['tester'],engagement=engagement,role='tester')
    client.force_login(users['tester'])
    response=client.get(reverse('core:dashboard'),{'page':2},HTTP_HX_REQUEST='true')
    assert response.context['engagement_page'].paginator.count==13
    assert len(response.context['engagement_page'])==3
    assert b'hx-get="/?page=2"' in response.content and b'Second engagement' not in response.content
