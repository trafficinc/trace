from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from django.db import close_old_connections
from django.test import RequestFactory
from apps.accounts.models import User
from apps.accounts.throttling import reserve_attempt
from apps.audit.models import AuditEvent
from apps.core.exceptions import EditConflict
from apps.engagements.services import change_membership
from apps.engagements.services import update_engagement


@pytest.mark.django_db(transaction=True)
def test_two_role_writers_have_one_version_winner(access_setup):
    users, first, _ = access_setup
    member = first.memberships.get(user=users["tester"])
    barrier = Barrier(2)
    def write(role):
        close_old_connections()
        try:
            actor = User.objects.get(pk=users["lead"].pk)
            barrier.wait(timeout=10)
            try:
                change_membership(actor=actor, engagement_id=first.pk, membership_id=member.pk, role=role, version=1)
            except EditConflict:
                return "conflict"
            return "saved"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["viewer", "reviewer"]))
    assert sorted(results) == ["conflict", "saved"]
    member.refresh_from_db()
    assert member.version == 2
    assert AuditEvent.objects.filter(action="membership.changed").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_login_reservations_cannot_exceed_limit(settings):
    settings.TRACE_LOGIN_ACCOUNT_LIMIT = 1
    barrier = Barrier(2)
    def reserve(_):
        close_old_connections()
        try:
            request = RequestFactory().post("/accounts/login/", REMOTE_ADDR="127.0.0.1")
            barrier.wait(timeout=10)
            reservations, retry = reserve_attempt("same-account", request)
            return "limited" if retry else "reserved"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, range(2)))
    assert sorted(results) == ["limited", "reserved"]


@pytest.mark.django_db(transaction=True)
def test_two_engagement_editors_cannot_overwrite_each_other(access_setup):
    users, first, _ = access_setup
    barrier = Barrier(2)
    def write(name):
        close_old_connections()
        try:
            actor = User.objects.get(pk=users["lead"].pk)
            barrier.wait(timeout=10)
            try:
                update_engagement(actor=actor, engagement_id=first.pk, data={"name": name}, version=1)
            except EditConflict:
                return "conflict"
            return "saved"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["First writer", "Second writer"]))
    assert sorted(results) == ["conflict", "saved"]
    first.refresh_from_db()
    assert first.version == 2
    assert AuditEvent.objects.filter(action="engagement.updated").count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_test_case_editors_have_one_winner(access_setup):
    from apps.testcases.services import create_test_case, update_test_case
    users, first, _ = access_setup
    case = create_test_case(actor=users["tester"], engagement_id=first.pk, data={"title": "Original", "category": "Auth"})
    barrier = Barrier(2)
    def write(title):
        close_old_connections()
        try:
            actor = User.objects.get(pk=users["tester"].pk)
            barrier.wait(timeout=10)
            try:
                update_test_case(actor=actor, engagement_id=first.pk, test_case_id=case.pk,
                    data={"title": title, "category": "Auth", "status": "in_progress"}, version=1)
            except EditConflict:
                return "conflict"
            return "saved"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["Writer A", "Writer B"]))
    assert sorted(results) == ["conflict", "saved"]
    case.refresh_from_db()
    assert case.version == 2 and case.status == "in_progress"
    assert AuditEvent.objects.filter(action="test.updated").count() == 1
