import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.urls import reverse
from apps.core.exceptions import EditConflict
from apps.audit.models import AuditEvent
from apps.assets.models import Asset
from apps.testcases.models import TestCase as CaseRecord
from apps.engagements.models import EngagementStatus
from apps.findings.models import Finding, FindingTemplate, FindingAsset, FindingTestCase, validate_cvss
from apps.findings.services import save_finding, transition_finding, save_template, copy_template
from apps.findings.formatting import render_narrative


def definition(**overrides):
    return dict(title='Unsafe access', severity='high', cvss_vector='', description='**Impact**\n\n```\n  preserved\n```', technical_details='', impact='', reproduction_steps='', remediation='', references='', **overrides)


def create(users, engagement):
    return save_finding(actor=users['tester'], engagement_id=engagement.pk, data=definition())


@pytest.mark.parametrize('vector', ['CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H', 'CVSS:3.0/A:N/I:L/C:L/S:C/UI:R/PR:L/AC:H/AV:P', ''])
def test_valid_vectors(vector):
    validate_cvss(vector)


@pytest.mark.parametrize('vector', ['CVSS:3.1/AV:N', 'CVSS:4.0/AV:N', 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:', 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/I:H', 'CVSS:3.1/AV:NN/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'])
def test_invalid_vectors(vector):
    with pytest.raises(ValidationError):
        validate_cvss(vector)


def test_formatting():
    html = str(render_narrative('# Title\n\n**bold** *em*\n\n```\n  <payload>\n```\n[web](https://example.com)\n[x](javascript:alert(1))\n<script>alert(1)</script>\n<img src=x onerror=alert(1)>'))
    assert '<strong>bold</strong>' in html and '<h3>Title</h3>' in html
    assert '  &lt;payload&gt;' in html and '<pre><code>' in html
    assert 'href="https://example.com"' in html
    assert '<script' not in html and '<img' not in html and 'href="javascript:' not in html


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['lead', 'tester', 'admin'])
def test_writers(access_setup, role):
    users, engagement, _ = access_setup
    finding = save_finding(actor=users[role], engagement_id=engagement.pk, data=definition())
    assert finding.author == users[role] and finding.version == 1 and finding.cvss_score is None
    assert AuditEvent.objects.filter(action='finding.created', subject_id=finding.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['reviewer', 'viewer', 'outsider'])
def test_denied_writers(access_setup, client, role):
    users, engagement, _ = access_setup
    with pytest.raises((PermissionDenied, Http404)):
        save_finding(actor=users[role], engagement_id=engagement.pk, data=definition())
    client.force_login(users[role])
    for headers in ({}, {'HTTP_HX_REQUEST': 'true'}):
        assert client.post(reverse('findings:create', args=[engagement.pk]), definition(), **headers).status_code in {403, 404}


@pytest.mark.django_db
def test_review_lifecycle_and_conflicts(access_setup):
    users, engagement, _ = access_setup
    f = create(users, engagement)
    with pytest.raises(ValidationError):
        transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='confirmed', version=1)
    f = transition_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, target='under_review', version=1)
    with pytest.raises(PermissionDenied):
        transition_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, target='confirmed', version=2)
    with pytest.raises(ValidationError):
        save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=2, data=definition())
    f = transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='draft', version=2)
    with pytest.raises(EditConflict):
        save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=1, data=definition())
    f = save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=f.version, data=definition())
    assert f.reviewer is None
    f = transition_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, target='under_review', version=f.version)
    f = transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='confirmed', version=f.version)
    assert f.reviewer == users['reviewer'] and f.reviewed_at
    f = transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='remediated', version=f.version)
    assert f.status == 'remediated'
    with pytest.raises(ValidationError):
        transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='accepted_risk', version=f.version)


@pytest.mark.django_db
def test_independent_approval(access_setup):
    users, engagement, _ = access_setup
    f = save_finding(actor=users['lead'], engagement_id=engagement.pk, data=definition())
    f = transition_finding(actor=users['lead'], engagement_id=engagement.pk, finding_id=f.pk, target='under_review', version=f.version)
    with pytest.raises(PermissionDenied):
        transition_finding(actor=users['lead'], engagement_id=engagement.pk, finding_id=f.pk, target='confirmed', version=f.version)
    f = transition_finding(actor=users['admin'], engagement_id=engagement.pk, finding_id=f.pk, target='confirmed', version=f.version)
    f = transition_finding(actor=users['reviewer'], engagement_id=engagement.pk, finding_id=f.pk, target='accepted_risk', version=f.version)
    assert f.status == 'accepted_risk'


@pytest.mark.django_db
def test_template_snapshot(access_setup):
    users, engagement, other = access_setup
    for role in ['lead', 'tester', 'reviewer', 'viewer', 'outsider']:
        with pytest.raises(PermissionDenied):
            save_template(actor=users[role], data={**definition(), 'is_active': True})
    template = save_template(actor=users['admin'], data={**definition(), 'is_active': True})
    with pytest.raises(ValidationError):
        save_template(actor=users['admin'], data={**definition(), 'engagement': engagement.pk})
    with pytest.raises(EditConflict):
        copy_template(actor=users['tester'], engagement_id=engagement.pk, template_id=template.pk, version=2)
    f = copy_template(actor=users['tester'], engagement_id=engagement.pk, template_id=template.pk, version=1)
    g = copy_template(actor=users['outsider'], engagement_id=other.pk, template_id=template.pk, version=1)
    assert f.pk != g.pk and f.engagement != g.engagement
    assert not f.assets.exists() and not f.test_cases.exists() and f.reviewer is None and f.status == 'draft'
    save_template(actor=users['admin'], template_id=template.pk, version=1, data={**definition(), 'title': 'Changed', 'is_active': False})
    f.refresh_from_db()
    assert f.title == 'Unsafe access' and f.source_template_version == 1
    with pytest.raises(Http404):
        copy_template(actor=users['tester'], engagement_id=engagement.pk, template_id=template.pk, version=2)


@pytest.mark.django_db
def test_scoped_relationships_and_db_guards(access_setup):
    users, engagement, other = access_setup
    f = create(users, engagement)
    asset = Asset.objects.create(engagement=other, name='Foreign', asset_type='other')
    case = CaseRecord.objects.create(engagement=other, title='Foreign')
    for field, record in [('assets', asset), ('test_cases', case)]:
        with pytest.raises(ValidationError):
            save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=1, data={**definition(), field: [record.pk]})
    for model, kwargs in [(FindingAsset, {'asset': asset}), (FindingTestCase, {'test_case': case})]:
        link = model(finding=f, **kwargs)
        with pytest.raises(ValidationError):
            link.clean()
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.bulk_create([link])
    asset.engagement = engagement
    asset.save()
    case.engagement = engagement
    case.save()
    FindingAsset.objects.create(finding=f, asset=asset)
    FindingTestCase.objects.create(finding=f, test_case=case)
    for model, pk in [(Asset, asset.pk), (CaseRecord, case.pk), (Finding, f.pk)]:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=pk).update(engagement=other)


@pytest.mark.django_db
@pytest.mark.parametrize('state', [EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED])
def test_closed_and_foreign(access_setup, client, state):
    users, engagement, other = access_setup
    f = create(users, engagement)
    client.force_login(users['outsider'])
    for headers in ({}, {'HTTP_HX_REQUEST': 'true'}):
        assert client.get(reverse('findings:detail', args=[engagement.pk, f.pk]), **headers).status_code == 404
        assert client.get(reverse('findings:detail', args=[other.pk, f.pk]), **headers).status_code == 404
    with pytest.raises(Http404):
        save_finding(actor=users['outsider'], engagement_id=other.pk, finding_id=f.pk, version=1, data=definition())
    engagement.status = state
    engagement.save()
    with pytest.raises(ValidationError):
        save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=1, data=definition())
    with pytest.raises(ValidationError):
        transition_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, version=1, target='under_review')


@pytest.mark.django_db
def test_http_pages_filters_and_preserved_draft(access_setup, client):
    users, engagement, _ = access_setup
    f = create(users, engagement)
    client.force_login(users['tester'])
    for url in [reverse('findings:list', args=[engagement.pk]), reverse('findings:detail', args=[engagement.pk, f.pk]), reverse('findings:edit', args=[engagement.pk, f.pk]), reverse('finding_templates:list')]:
        assert client.get(url).status_code == 200
    response = client.get(reverse('findings:list', args=[engagement.pk]), {'severity': 'low', 'sort': 'severity'})
    assert not response.context['page'].object_list.exists()
    assert client.get(reverse('findings:list', args=[engagement.pk]), {'q': 'Unsafe', 'status': 'draft'}).context['page'].paginator.count == 1
    response = client.post(reverse('findings:edit', args=[engagement.pk, f.pk]), {**definition(), 'version': 9, 'title': 'Unsaved draft'}, HTTP_HX_REQUEST='true')
    assert response.status_code == 409 and b'Unsaved draft' in response.content
    client.force_login(users['reviewer'])
    response = client.post(reverse('findings:detail', args=[engagement.pk, f.pk]), {'target': 'confirmed', 'version': 1})
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['lead', 'tester', 'reviewer', 'viewer', 'admin', 'outsider'])
def test_http_review_roles(access_setup, client, role):
    users, engagement, _ = access_setup
    f = create(users, engagement)
    f = transition_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=f.pk, target='under_review', version=1)
    client.force_login(users[role])
    response = client.post(reverse('findings:detail', args=[engagement.pk, f.pk]), {'target': 'confirmed', 'version': f.version}, HTTP_HX_REQUEST='true')
    assert response.status_code == {'lead': 204, 'reviewer': 204, 'admin': 204, 'tester': 403, 'viewer': 403, 'outsider': 404}[role]
    f.refresh_from_db()
    assert f.status == ('confirmed' if role in {'lead', 'reviewer', 'admin'} else 'under_review')


@pytest.mark.django_db
def test_template_http_and_form_post_relationships(access_setup, client):
    users, engagement, other = access_setup
    client.force_login(users['admin'])
    assert client.post(reverse('finding_templates:create'), {**definition(), 'is_active': 'on'}).status_code == 302
    template = FindingTemplate.objects.get()
    for name in ['detail', 'edit']:
        assert client.get(reverse('finding_templates:' + name, args=[template.pk])).status_code == 200
    client.force_login(users['tester'])
    detail = client.get(reverse('finding_templates:detail', args=[template.pk]))
    assert detail.status_code == 200 and b'Second engagement' not in detail.content
    assert client.get(reverse('finding_templates:edit', args=[template.pk])).status_code == 403
    url = reverse('findings:copy', args=[engagement.pk, template.pk])
    assert client.get(url).status_code == 200
    assert not Finding.objects.exists()
    assert client.post(url, {'version': 1}).status_code == 302
    f = Finding.objects.get()
    asset = Asset.objects.create(engagement=engagement, name='App', asset_type='other')
    case = CaseRecord.objects.create(engagement=engagement, title='Local test')
    assert client.post(reverse('findings:edit', args=[engagement.pk, f.pk]), {**definition(), 'version': 1, 'assets': [asset.pk], 'test_cases': [case.pk]}).status_code == 302
    assert list(f.assets.all()) == [asset] and list(f.test_cases.all()) == [case]
    assert client.post(reverse('findings:copy', args=[other.pk, template.pk]), {'version': 1}).status_code == 404


@pytest.mark.django_db
def test_finding_blocks_operator_purge(access_setup):
    from apps.engagements.services import purge_engagement
    users, engagement, _ = access_setup
    create(users, engagement)
    engagement.status = EngagementStatus.ARCHIVED
    engagement.save()
    with pytest.raises(ValidationError):
        purge_engagement(actor=users['admin'], engagement_id=engagement.pk, version=1, confirmation=str(engagement.pk), reason='test-data')
    assert engagement.findings.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_finding_edits(access_setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection
    from django.contrib.auth import get_user_model
    assert str(connection.settings_dict['NAME']) != ':memory:'
    users, engagement, _ = access_setup
    f = create(users, engagement)
    barrier = Barrier(2)
    def write(title):
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=users['tester'].pk)
            barrier.wait(timeout=10)
            try:
                save_finding(actor=actor, engagement_id=engagement.pk, finding_id=f.pk, version=1, data={**definition(), 'title': title})
            except EditConflict:
                return 'conflict'
            return 'saved'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ['First', 'Second'])) == ['conflict', 'saved']
    f.refresh_from_db()
    assert f.version == 2
    assert AuditEvent.objects.filter(action='finding.updated').count() == 1
