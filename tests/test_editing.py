from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
import sqlite3
from unittest.mock import patch
import uuid
import pytest
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, OperationalError, transaction
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.concurrency import cas_update
from apps.core.exceptions import EditConflict
from apps.core.models import EditorPresence
from apps.core.presence import heartbeat, editors
from apps.engagements.models import EngagementMembership, EngagementStatus
from apps.findings.services import save_finding

pytestmark = pytest.mark.django_db(transaction=True)


def data(title='Original', **extra):
    return {'title': title, 'severity': 'high', 'description': '  Indented\n    detail', **extra}


@pytest.fixture
def editing_setup(access_setup):
    users, engagement, foreign = access_setup
    bob = User.objects.create_user('tester-b')
    EngagementMembership.objects.create(engagement=engagement, user=bob, role='tester')
    users['tester-b'] = bob
    finding = save_finding(actor=users['tester'], engagement_id=engagement.pk, data=data())
    for version in (1, 2):
        finding = save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=finding.pk, version=version, data=data('Version three'))
    assert finding.version == 3
    assert Path(connection.settings_dict['NAME']).is_file()
    return users, engagement, foreign, finding


def edit_url(engagement, finding):
    return reverse('findings:edit', args=[engagement.pk, finding.pk])


def presence_url(engagement, finding):
    return reverse('core:engagement_editor_presence', args=[engagement.pk, 'finding', finding.pk])


def token(response):
    return response.context['merge_token']


def test_acceptance_two_http_editors_load_three_one_gets_four_other_conflicts(editing_setup):
    users, engagement, _, finding = editing_setup
    first, second = Client(), Client()
    first.force_login(users['tester'])
    second.force_login(users['tester-b'])
    barrier, saved = Barrier(2), Event()
    def edit(client, title, winner):
        close_old_connections()
        try:
            response = client.get(edit_url(engagement, finding))
            assert response.context['form'].initial['version'] == 3
            identity = id(connection.connection)
            barrier.wait(timeout=10)
            if not winner:
                assert saved.wait(10)
            response = client.post(edit_url(engagement, finding), data(title, version=3), HTTP_HX_REQUEST='true')
            if winner:
                saved.set()
            return response.status_code, response.content, identity
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(edit, first, 'Tester A saved', True)
        b = pool.submit(edit, second, 'Tester B unsaved', False)
        left, right = a.result(timeout=20), b.result(timeout=20)
    assert left[0] == 204 and right[0] == 409 and left[2] != right[2]
    assert b'Tester A saved' in right[1] and b'Tester B unsaved' in right[1]
    assert b'Current saved values' in right[1] and b'Your submitted values' in right[1]
    finding.refresh_from_db()
    assert finding.version == 4 and finding.title == 'Tester A saved'
    assert AuditEvent.objects.filter(action='finding.updated', subject_id=finding.pk).count() == 3


def test_two_testers_edit_different_records_simultaneously(editing_setup):
    users, engagement, _, first = editing_setup
    second = save_finding(actor=users['tester-b'], engagement_id=engagement.pk, data=data('Other'))
    barrier = Barrier(2)
    def edit(actor_id, record_id, version):
        close_old_connections()
        try:
            actor = User.objects.get(pk=actor_id)
            barrier.wait(timeout=10)
            return save_finding(actor=actor, engagement_id=engagement.pk, finding_id=record_id,
                                version=version, data=data('Saved ' + str(record_id))).version
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(edit, users['tester'].pk, first.pk, 3)
        right = pool.submit(edit, users['tester-b'].pk, second.pk, 1)
        assert left.result(timeout=20) == 4
        assert right.result(timeout=20) == 2
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.title.startswith('Saved ') and second.title.startswith('Saved ')


def conflict(editing_setup, client):
    users, engagement, _, finding = editing_setup
    save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=finding.pk, version=3, data=data('Current saved'))
    client.force_login(users['tester-b'])
    return client.post(edit_url(engagement, finding), data('Preserved draft', version=3))


def test_explicit_manual_merge_is_two_step_and_never_automatically_saves(editing_setup, client):
    users, engagement, _, finding = editing_setup
    response = conflict(editing_setup, client)
    assert response.status_code == 409
    reviewed = token(response)
    prepared = client.post(edit_url(engagement, finding), data('Manually combined values', version=3, _prepare_merge=reviewed))
    assert prepared.status_code == 200 and prepared.context['merge_ready']
    assert prepared.context['form']['version'].value() == '4'
    finding.refresh_from_db()
    assert finding.title == 'Current saved' and finding.version == 4
    saved = client.post(edit_url(engagement, finding), data('Manually combined values', version=4))
    assert saved.status_code == 302
    finding.refresh_from_db()
    assert finding.title == 'Manually combined values' and finding.version == 5


def test_prepare_even_with_current_version_never_executes_write(editing_setup, client):
    users, engagement, _, finding = editing_setup
    response = conflict(editing_setup, client)
    with patch('apps.findings.views.services.save_finding', wraps=save_finding) as save:
        prepared = client.post(edit_url(engagement, finding), data('Review only', version=4, _prepare_merge=token(response)))
        assert prepared.status_code == 200 and not save.called
    finding.refresh_from_db()
    assert finding.version == 4 and finding.title == 'Current saved'


def test_second_change_during_review_requires_new_comparison(editing_setup, client):
    users, engagement, _, finding = editing_setup
    response = conflict(editing_setup, client)
    old_token = token(response)
    save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=finding.pk, version=4, data=data('Newer again'))
    response = client.post(edit_url(engagement, finding), data('Preserved draft', version=3, _prepare_merge=old_token))
    assert response.status_code == 409 and not response.context['merge_ready']
    assert response.context['form']['version'].value() == '3'
    assert b'Newer again' in response.content and b'Preserved draft' in response.content


def test_merge_token_bound_to_actor_path_and_snapshot(editing_setup, client):
    users, engagement, _, finding = editing_setup
    response = conflict(editing_setup, client)
    reviewed = token(response)
    client.force_login(users['tester'])
    response = client.post(edit_url(engagement, finding), data('Do not save', version=3, _prepare_merge=reviewed))
    assert response.status_code == 409 and not response.context['merge_ready']
    response = client.post(edit_url(engagement, finding), data('Do not save', version=3, _prepare_merge='tampered'))
    assert response.status_code == 409
    finding.refresh_from_db()
    assert finding.version == 4


def test_invalid_stale_draft_and_html_remain_safe(editing_setup, client):
    users, engagement, _, finding = editing_setup
    conflict(editing_setup, client)
    response = client.post(edit_url(engagement, finding), data('', version=3, description='<img src=x onerror=alert(1)>'))
    assert response.status_code == 409
    assert b'&lt;img' in response.content and b'<img src=x' not in response.content
    assert response.context['form']['description'].value() == '<img src=x onerror=alert(1)>'


def test_cas_missing_foreign_and_stale_distinguished_only_in_scope(editing_setup):
    users, engagement, foreign, finding = editing_setup
    with transaction.atomic(), pytest.raises(EditConflict) as error:
        cas_update(engagement.findings.filter(pk=finding.pk), version=1, title='Lost')
    assert error.value.current.pk == finding.pk
    with transaction.atomic(), pytest.raises(Http404):
        cas_update(foreign.findings.filter(pk=finding.pk), version=3, title='Foreign')
    with transaction.atomic(), pytest.raises(Http404):
        cas_update(engagement.findings.filter(pk=uuid.uuid4()), version=3, title='Missing')
    with pytest.raises(RuntimeError):
        cas_update(engagement.findings.filter(pk=finding.pk), version=3, title='No transaction')


@pytest.mark.parametrize('role, expected', [('lead',200), ('tester',200), ('tester-b',200), ('admin',200), ('reviewer',403), ('viewer',403), ('outsider',404)])
def test_presence_http_roles_and_read_only_content_versions(editing_setup, client, role, expected):
    users, engagement, _, finding = editing_setup
    client.force_login(users[role])
    response = client.post(presence_url(engagement, finding), {}, HTTP_HX_REQUEST='true')
    assert response.status_code == expected
    finding.refresh_from_db()
    assert finding.version == 3
    if expected == 200:
        assert EditorPresence.objects.filter(actor=users[role]).count() == 1


def test_presence_scope_expiry_revocation_and_no_lock(editing_setup):
    users, engagement, foreign, finding = editing_setup
    arguments = dict(kind='finding', object_id=finding.pk, engagement_id=engagement.pk)
    heartbeat(actor=users['tester'], **arguments)
    assert editors(actor=users['tester-b'], **arguments) == ['tester']
    saved = save_finding(actor=users['tester-b'], engagement_id=engagement.pk, finding_id=finding.pk, version=3, data=data('Presence does not lock'))
    assert saved.version == 4
    with pytest.raises(Http404):
        editors(actor=users['outsider'], **{**arguments, 'engagement_id': foreign.pk})
    EngagementMembership.objects.filter(engagement=engagement, user=users['tester']).update(role='viewer')
    assert editors(actor=users['tester-b'], **arguments) == []
    with pytest.raises(PermissionDenied):
        heartbeat(actor=users['tester'], **arguments)
    EngagementMembership.objects.filter(engagement=engagement, user=users['tester']).update(role='tester')
    EditorPresence.objects.update(seen_at=timezone.now()-timedelta(seconds=61))
    assert editors(actor=users['tester-b'], **arguments) == []
    heartbeat(actor=users['tester-b'], **arguments)
    assert not EditorPresence.objects.filter(actor=users['tester']).exists()
    heartbeat(actor=users['tester-b'], leave=True, **arguments)
    assert not EditorPresence.objects.exists()


def test_status_poll_and_dashboard_are_scoped_fragments_not_edit_forms(editing_setup, client):
    users, engagement, foreign, finding = editing_setup
    client.force_login(users['tester'])
    page = client.get(edit_url(engagement, finding))
    assert b'every 20s' in page.content and b'Share editor presence' in page.content
    assert not EditorPresence.objects.exists()  # Optional means no heartbeat on open.
    url = reverse('core:engagement_editor_status', args=[engagement.pk, 'finding', finding.pk])
    save_finding(actor=users['tester-b'], engagement_id=engagement.pk, finding_id=finding.pk, version=3, data=data('Saved4'))
    response = client.get(url, {'version': 3}, HTTP_HX_REQUEST='true')
    assert response.status_code == 200 and b'Saved version 4' in response.content
    assert b'draft loaded version 3' in response.content and b'<input' not in response.content and b'<textarea' not in response.content
    assert 'HX-Request' in response['Vary'] and response['Cache-Control'] == 'no-store, private'
    response = client.get(reverse('core:dashboard'), HTTP_HX_REQUEST='true')
    assert response.status_code == 200 and b'every 30s' in response.content and b'Second engagement' not in response.content
    client.force_login(users['outsider'])
    assert client.get(url, {'version': 3}).status_code == 404


def test_presence_disabled_and_csrf_protected(editing_setup, client, settings):
    users, engagement, _, finding = editing_setup
    secure = Client(enforce_csrf_checks=True)
    secure.force_login(users['tester'])
    assert secure.post(presence_url(engagement, finding)).status_code == 403
    settings.TRACE_EDITOR_PRESENCE_ENABLED = False
    client.force_login(users['tester'])
    assert client.post(presence_url(engagement, finding)).status_code == 404
    assert b'Share editor presence' not in client.get(edit_url(engagement, finding)).content


def test_expired_poll_cannot_redirect_away_from_unsaved_draft(editing_setup, client):
    _, engagement, _, finding = editing_setup
    url = reverse('core:engagement_editor_status', args=[engagement.pk, 'finding', finding.pk])
    response = client.get(url, {'version': 3}, HTTP_HX_REQUEST='true')
    assert response.status_code == 401 and 'HX-Redirect' not in response
    assert b'draft remains here' in response.content


def test_presence_retries_only_identified_transient_errors(editing_setup):
    users, engagement, _, finding = editing_setup
    native = sqlite3.OperationalError()
    native.sqlite_errorcode = sqlite3.SQLITE_BUSY
    busy = OperationalError()
    busy.__cause__ = native
    from apps.core.editing import resolve_editor
    with patch('apps.core.presence.resolve_editor', side_effect=[busy, resolve_editor(actor=users['tester'], kind='finding', object_id=finding.pk, engagement_id=engagement.pk)]), patch('apps.core.presence.time.sleep') as sleep:
        heartbeat(actor=users['tester'], kind='finding', object_id=finding.pk, engagement_id=engagement.pk)
        assert sleep.call_count == 1
    with patch('apps.core.presence.resolve_editor', side_effect=OperationalError), patch('apps.core.presence.time.sleep') as sleep:
        with pytest.raises(OperationalError):
            heartbeat(actor=users['tester'], kind='finding', object_id=finding.pk, engagement_id=engagement.pk)
        assert not sleep.called


def test_profile_and_membership_conflicts_compare_safe_fields(editing_setup, client):
    users, engagement, _, _ = editing_setup
    client.force_login(users['lead'])
    users['lead'].first_name = 'Saved first name'
    users['lead'].version = 2
    users['lead'].save()
    response = client.post(reverse('accounts:profile'), {'first_name':'Unsaved name', 'last_name':'', 'email':'', 'version':1})
    assert response.status_code == 409 and b'Saved first name' in response.content and b'Unsaved name' in response.content
    prepared = client.post(reverse('accounts:profile'), {'first_name':'Unsaved name', 'last_name':'', 'email':'', 'version':1, '_prepare_merge':token(response)}, HTTP_HX_REQUEST='true')
    assert prepared.status_code == 200
    result = client.post(reverse('accounts:profile'), {'first_name':'Unsaved name', 'last_name':'', 'email':'', 'version':2, '_merge_form':1}, HTTP_HX_REQUEST='true')
    assert result.status_code == 204 and result['HX-Redirect'] == reverse('accounts:profile')
    member = engagement.memberships.get(user=users['tester'])
    engagement.memberships.filter(pk=member.pk).update(version=2, role='viewer')
    response = client.post(reverse('engagements:member_change', args=[engagement.pk, member.pk]), {'version':1, 'role':'reviewer'})
    assert response.status_code == 409 and b'Viewer' in response.content and b'reviewer' in response.content


def test_closed_and_foreign_snapshots_do_not_allow_merge_or_data_disclosure(editing_setup, client):
    users, engagement, foreign, finding = editing_setup
    response = conflict(editing_setup, client)
    reviewed = token(response)
    engagement.status = EngagementStatus.COMPLETED
    engagement.save()
    response = client.post(edit_url(engagement, finding), data('Keep me', version=3, _prepare_merge=reviewed))
    assert response.status_code == 409 and not response.context['can_merge'] and b'Keep me' in response.content
    client.force_login(users['outsider'])
    response = client.post(reverse('findings:edit', args=[foreign.pk, finding.pk]), data('Foreign', version=1))
    assert response.status_code == 404 and b'Current saved' not in response.content


def test_cas_executes_scoped_database_version_increment(editing_setup):
    users, engagement, _, finding = editing_setup
    updates = []
    def capture(execute, sql, params, many, context):
        if sql.startswith('UPDATE "findings_finding"'):
            updates.append(sql)
        return execute(sql, params, many, context)
    with connection.execute_wrapper(capture):
        save_finding(actor=users['tester'], engagement_id=engagement.pk, finding_id=finding.pk, version=3, data=data('Atomic'))
    assert len(updates) == 1
    update, where = updates[0].split(' WHERE ')
    assert '"version" = ("findings_finding"."version" + ' in update
    assert all(name in where for name in ['"engagement_id"', '"id"', '"version"'])


def test_all_editable_domain_records_and_forms_have_positive_versions():
    from django.apps import apps
    from django.db import models
    from django import forms
    from apps.accounts.forms import ProfileForm, UserStatusForm
    from apps.engagements.forms import EditEngagementForm, EditNoteForm, EditMilestoneForm, ChangeMembershipForm
    from apps.assets.forms import EditAssetForm
    from apps.testcases.forms import EditTestCaseForm, EditTemplateForm as EditTestTemplateForm, EditTestNoteForm, EditReferenceForm
    from apps.findings.forms import EditFindingForm, EditTemplateForm as EditFindingTemplateForm, TransitionForm
    from apps.evidence.forms import EditEvidenceForm
    from apps.reports.forms import EditReportForm, EditTemplateForm as EditReportTemplateForm
    for label in ['accounts.User', 'engagements.Engagement', 'engagements.EngagementMembership', 'engagements.EngagementNote',
                  'engagements.EngagementMilestone', 'assets.Asset', 'testcases.TestCase', 'testcases.TestCaseTemplate',
                  'testcases.TestCaseNote', 'testcases.TestCaseReference', 'findings.Finding', 'findings.FindingTemplate', 'evidence.Evidence', 'reports.Report', 'reports.ReportTemplate']:
        field = apps.get_model(label)._meta.get_field('version')
        assert isinstance(field, models.IntegerField) and field.default == 1
    for cls in [ProfileForm, UserStatusForm, EditEngagementForm, EditNoteForm, EditMilestoneForm, ChangeMembershipForm,
                EditAssetForm, EditTestCaseForm, EditTestTemplateForm, EditTestNoteForm, EditReferenceForm,
                EditFindingForm, EditFindingTemplateForm, TransitionForm, EditEvidenceForm, EditReportForm, EditReportTemplateForm]:
        field = cls.base_fields['version']
        assert isinstance(field.widget, forms.HiddenInput) and field.min_value == 1


def test_concurrent_presence_upserts_are_idempotent(editing_setup):
    users, engagement, _, finding = editing_setup
    barrier = Barrier(2)
    def write(_):
        close_old_connections()
        try:
            actor = User.objects.get(pk=users['tester'].pk)
            barrier.wait(timeout=10)
            heartbeat(actor=actor, kind='finding', object_id=finding.pk, engagement_id=engagement.pk)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, [1, 2]))
    assert EditorPresence.objects.count() == 1
    finding.refresh_from_db()
    assert finding.version == 3


def test_password_conflict_never_echoes_authentication_material(editing_setup, client):
    users, _, _, _ = editing_setup
    actor = users['tester']
    old_password, new_password = 'Lakes-Old-Passphrase-821!', 'New-River-Passphrase-934!'
    actor.set_password(old_password)
    actor.save()
    client.force_login(actor)
    User.objects.filter(pk=actor.pk).update(version=2)
    response = client.post(reverse('accounts:password_change'), {'old_password': old_password,
        'new_password1': new_password, 'new_password2': new_password, 'version': 1})
    assert response.status_code == 409
    assert old_password.encode() not in response.content and new_password.encode() not in response.content
    assert actor.password.encode() not in response.content
    assert not response.context['can_merge']
    response = client.post(reverse('accounts:password_change'), {'old_password': 'incorrect',
        'new_password1': new_password, 'new_password2': new_password, 'version': 1})
    assert response.status_code == 409
    assert 'old_password' in response.context['form'].fields
    assert 'is_active' not in response.context['form'].fields
    assert old_password.encode() not in response.content and new_password.encode() not in response.content


def test_expired_htmx_save_cannot_redirect_and_discard_draft(editing_setup, client):
    _, engagement, _, finding = editing_setup
    response = client.post(edit_url(engagement, finding), data('Draft stays in browser', version=3), HTTP_HX_REQUEST='true')
    assert response.status_code == 401 and 'HX-Redirect' not in response


def test_stale_inline_milestone_action_preserves_comparison_and_merge(editing_setup, client):
    from apps.engagements.services import save_milestone, set_milestone_completed
    users, engagement, _, _ = editing_setup
    milestone = save_milestone(actor=users['lead'], engagement_id=engagement.pk, data={'title':'Task'})
    set_milestone_completed(actor=users['lead'], engagement_id=engagement.pk, milestone_id=milestone.pk, completed=True, version=1)
    client.force_login(users['lead'])
    url = reverse('engagements:milestone_complete', args=[engagement.pk, milestone.pk])
    response = client.post(url, {'version':1}, HTTP_HX_REQUEST='true')
    assert response.status_code == 409 and b'Current saved values' in response.content
    response = client.post(url, {'version':1, '_prepare_merge':token(response)}, HTTP_HX_REQUEST='true')
    assert response.status_code == 200 and response.context['merge_ready']
    response = client.post(url, {'version':2, '_merge_form':1}, HTTP_HX_REQUEST='true')
    assert response.status_code == 200 and response['HX-Retarget'] == '#milestones'
    milestone.refresh_from_db()
    assert not milestone.completed and milestone.version == 3


def test_shared_template_presence_is_admin_only(editing_setup, client):
    from apps.findings.services import save_template
    users, _, _, _ = editing_setup
    template = save_template(actor=users['admin'], data={**data(), 'is_active':True})
    url = reverse('core:editor_presence', args=['finding-template', template.pk])
    client.force_login(users['tester'])
    assert client.get(url).status_code == 403
    client.force_login(users['admin'])
    assert client.post(url).status_code == 200
