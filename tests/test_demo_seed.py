import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.urls import reverse

from apps.assets.forms import ASSET_FIELDS
from apps.assets.models import Asset
from apps.assets.services import save_asset
from apps.audit.models import AuditEvent
from apps.core.demo_data import MARKING, PEOPLE, SCENARIOS
from apps.core.demo_seed import _seed_lock, seed_demo
from apps.engagements.forms import ENGAGEMENT_FIELDS
from apps.engagements.models import Engagement
from apps.engagements.services import update_engagement
from apps.evidence import services as evidence_services
from apps.evidence.models import Evidence
from apps.findings.models import Finding
from apps.reports.models import Report, ReportRevision, ReportArtifact
from apps.reports import services as report_services, storage as report_storage
from apps.reports.rendering import RenderError
import json
from apps.testcases.models import TestCase as CaseRecord

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def demo(settings, tmp_path):
    settings.EVIDENCE_ROOT = tmp_path / "evidence"
    settings.REPORT_ROOT = tmp_path / "reports"
    admin = get_user_model().objects.create_superuser("demo-operator-admin")
    return admin, settings.EVIDENCE_ROOT


def run(admin):
    output = io.StringIO()
    call_command("seed_demo", admin=admin.username, stdout=output)
    return output.getvalue()


def snapshot():
    return {
        "users": list(get_user_model().objects.order_by("pk").values_list("pk", "version", "is_active", "is_staff", "is_superuser")),
        "engagements": list(Engagement.objects.order_by("pk").values_list("pk", "version", "name", "status")),
        "assets": list(Asset.objects.order_by("pk").values_list("pk", "version", "description")),
        "tests": list(CaseRecord.objects.order_by("pk").values_list("pk", "version", "status", "actual_result")),
        "findings": list(Finding.objects.order_by("pk").values_list("pk", "version", "status")),
        "evidence": list(Evidence.objects.order_by("pk").values_list("pk", "version", "deleted_at")),
        "reports": list(Report.objects.order_by("pk").values_list("pk", "version", "title")),
        "revisions": list(ReportRevision.objects.order_by("pk").values_list("pk", "status")),
        "artifacts": list(ReportArtifact.objects.order_by("pk").values_list("pk", "sha256")),
        "audit": AuditEvent.objects.count(),
    }


def test_full_demo_uses_real_services_and_scoped_relationships(demo, client):
    admin, root = demo
    original_upload = evidence_services.upload_evidence

    def upload(**kwargs):
        assert not connection.in_atomic_block
        return original_upload(**kwargs)

    with patch("apps.core.demo_seed.evidence_services.upload_evidence", side_effect=upload):
        output = run(admin)
    assert output.count("Created:") == 2
    assert Engagement.objects.count() == 2
    assert Asset.objects.count() == 10
    assert CaseRecord.objects.count() == 11
    assert Finding.objects.count() == 4
    assert Evidence.objects.count() == 6
    assert Report.objects.count() == 2 and ReportRevision.objects.filter(status="ready").count() == 2
    assert ReportArtifact.objects.count() == 8
    for report in Report.objects.select_related("engagement"):
        assert report.marking == MARKING and report.findings.count() == report.engagement.findings.count()
        revision = report.revisions.get()
        assert set(revision.artifacts.values_list("format", flat=True)) == {"html", "docx", "pdf", "snapshot"}
        artifact = revision.artifacts.get(format="snapshot")
        with report_storage.open_file(report.engagement_id, artifact.storage_key) as file:
            data = json.load(file)
        assert data["engagement"]["id"] == str(report.engagement_id)
        assert data["engagement"]["status"] == report.engagement.get_status_display()
        assert {row["id"] for row in data["findings"]} == {str(pk) for pk in report.findings.values_list("pk", flat=True)}
        assert data["report"]["marking"] == MARKING
        assert any(row.get("image", "").startswith("data:image/png;base64,") for row in data["evidence"])
    assert set(Engagement.objects.values_list("status", flat=True)) == {"active", "completed"}
    assert set(CaseRecord.objects.values_list("status", flat=True)) == {"not_started", "in_progress", "blocked", "passed", "failed", "not_applicable"}
    for user in get_user_model().objects.exclude(pk=admin.pk):
        assert not user.has_usable_password()
        assert user.is_active and not user.is_staff and not user.is_superuser
    for engagement in Engagement.objects.all():
        assert engagement.report_classification == MARKING
        assert engagement.created_by_id == admin.pk
        assert set(engagement.memberships.values_list("role", flat=True)) == {"lead", "tester", "reviewer", "viewer"}
        if engagement.is_read_only:
            assert engagement.completed_at
            assert not engagement.milestones.filter(completed=False).exists()
        else:
            assert engagement.milestones.filter(completed=True).count() == 2
            assert engagement.milestones.filter(completed=False).count() == 2
    for case in CaseRecord.objects.all():
        assert all(asset.engagement_id == case.engagement_id for asset in case.assets.all())
        assert case.references.exists() and case.note_entries.exists()
        assert case.assigned_tester.engagement_memberships.filter(engagement_id=case.engagement_id, role__in=["lead", "tester"]).exists()
        if case.status in {"passed", "failed"}:
            assert case.actual_result and case.started_at and case.completed_at
    for finding in Finding.objects.exclude(status__in=["draft", "under_review"]):
        assert finding.reviewer_id != finding.author_id and finding.reviewed_at
    for evidence in Evidence.objects.all():
        assert evidence.test_cases.exists()
        assert all(case.engagement_id == evidence.engagement_id for case in evidence.test_cases.all())
        assert all(finding.engagement_id == evidence.engagement_id for finding in evidence.findings.all())
        _, file = evidence_services.open_download(actor=admin, engagement_id=evidence.engagement_id, evidence_id=evidence.pk)
        with file:
            assert file.read()
        if evidence.kind == "png":
            assert evidence.thumbnail_key and evidence.thumbnail_size
    assert Evidence.objects.filter(kind="png").count() == 2
    assert AuditEvent.objects.filter(action="evidence.uploaded").count() == 6
    assert AuditEvent.objects.filter(action="user.created").count() == len(PEOPLE)
    client.force_login(admin)
    for engagement in Engagement.objects.all():
        assert client.get(reverse("evidence:list", args=[engagement.pk])).status_code == 200


def test_rerun_preserves_operator_edits_and_removed_evidence(demo):
    admin, root = demo
    run(admin)
    engagement = Engagement.objects.get(status="active")
    data = {field: getattr(engagement, field) for field in ENGAGEMENT_FIELDS}
    data["name"] = "Operator renamed the demo exercise"
    engagement = update_engagement(actor=admin, engagement_id=engagement.pk, version=engagement.version, data=data)
    asset = engagement.assets.first()
    data = {field: getattr(asset, field) for field in ASSET_FIELDS}
    data.update(owner=asset.owner_id, description="Operator revision must survive reruns.")
    save_asset(actor=admin, engagement_id=engagement.pk, asset_id=asset.pk, version=asset.version, data=data)
    evidence = engagement.evidence.first()
    evidence_services.remove_evidence(actor=admin, engagement_id=engagement.pk, evidence_id=evidence.pk, version=evidence.version)
    before = snapshot()
    files = sorted(str(path) for path in root.rglob("*") if path.is_file())
    assert run(admin).count("Preserved:") == 2
    assert snapshot() == before
    assert sorted(str(path) for path in root.rglob("*") if path.is_file()) == files


def test_partial_evidence_failure_can_resume_without_duplicate_metadata(demo):
    admin, _ = demo
    with patch("apps.core.demo_seed.evidence_services.upload_evidence", side_effect=OSError):
        with pytest.raises(CommandError):
            run(admin)
    assert Engagement.objects.count() == 1
    assert CaseRecord.objects.count() == 8
    first_id = Engagement.objects.get().pk
    run(admin)
    assert Engagement.objects.filter(pk=first_id).exists()
    assert Engagement.objects.count() == 2 and CaseRecord.objects.count() == 11
    assert Evidence.objects.count() == 6


def test_metadata_failure_rolls_back_exercise_without_file_work(demo):
    admin, _ = demo
    with patch("apps.core.demo_seed.test_services.save_reference", side_effect=ValidationError("fixture rejected")):
        with pytest.raises(CommandError):
            run(admin)
    assert not Engagement.objects.exists()
    assert not Asset.objects.exists() and not CaseRecord.objects.exists()
    assert not Evidence.objects.exists()
    assert get_user_model().objects.count() == len(PEOPLE) + 1
    run(admin)
    assert Engagement.objects.count() == 2


@pytest.mark.parametrize("role", ["lead", "tester", "reviewer", "viewer"])
def test_seeded_roles_have_expected_http_and_service_access(demo, client, role):
    admin, _ = demo
    run(admin)
    engagement = Engagement.objects.get(status="active")
    foreign = Engagement.objects.get(status="completed")
    member = engagement.memberships.filter(role=role).select_related("user").first().user
    client.force_login(member)
    assert client.get(reverse("evidence:list", args=[engagement.pk])).status_code == 200
    assert client.get(reverse("evidence:upload", args=[engagement.pk])).status_code == (200 if role in {"lead", "tester"} else 403)
    evidence = foreign.evidence.first()
    assert client.get(reverse("evidence:detail", args=[engagement.pk, evidence.pk])).status_code == 404
    if role in {"reviewer", "viewer"}:
        with pytest.raises(PermissionDenied):
            evidence_services.upload_evidence(actor=member, engagement_id=engagement.pk, upload=None, data={})
    with pytest.raises(PermissionDenied):
        seed_demo(actor=member)


def test_production_and_custom_settings_are_rejected_before_mutation(demo, settings):
    admin, root = demo
    for module in ("config.settings.production", "custom.settings"):
        settings.DEBUG = True
        settings.SETTINGS_MODULE = module
        with pytest.raises(CommandError):
            run(admin)
        with pytest.raises(ValidationError):
            seed_demo(actor=admin)
    assert not root.exists()
    assert not Engagement.objects.exists() and get_user_model().objects.count() == 1


def test_reserved_username_collision_fails_without_changing_existing_accounts(demo):
    admin, _ = demo
    User = get_user_model()
    collision = User.objects.create_user(PEOPLE["observer"][0], email="existing@example.test")
    with pytest.raises(CommandError):
        run(admin)
    collision.refresh_from_db()
    assert collision.email == "existing@example.test" and not collision.is_superuser
    assert User.objects.count() == 2 and not Engagement.objects.exists()


def test_existing_non_admin_and_missing_admin_are_rejected(demo):
    admin, root = demo
    user = get_user_model().objects.create_user("ordinary-operator")
    for username in (user.username, "does-not-exist"):
        with pytest.raises(CommandError):
            call_command("seed_demo", admin=username, stdout=io.StringIO())
    assert not root.exists() and not Engagement.objects.exists()


def test_seed_lock_is_nonblocking_and_no_duplicate_records_are_created(demo):
    admin, _ = demo
    with _seed_lock():
        with pytest.raises(CommandError, match="Another demo seed command"):
            run(admin)
    assert not Engagement.objects.exists()
    run(admin)
    assert Engagement.objects.count() == 2


def test_completed_seed_does_not_overwrite_a_newer_engagement_version(demo):
    admin, _ = demo
    original_upload = evidence_services.upload_evidence
    edited = False

    def upload(**kwargs):
        nonlocal edited
        evidence = original_upload(**kwargs)
        engagement = evidence.engagement
        if "TALON" in engagement.name and not edited:
            data = {field: getattr(engagement, field) for field in ENGAGEMENT_FIELDS}
            data["description"] = "Operator changed this record while the seed was attaching evidence."
            update_engagement(actor=admin, engagement_id=engagement.pk, version=engagement.version, data=data)
            edited = True
        return evidence

    with patch("apps.core.demo_seed.evidence_services.upload_evidence", side_effect=upload):
        with pytest.raises(CommandError):
            run(admin)
    engagement = Engagement.objects.get(name=SCENARIOS[1]["name"])
    assert engagement.status == "active" and engagement.version == 3
    assert engagement.description.startswith("Operator changed")
    run(admin)
    engagement.refresh_from_db()
    assert engagement.status == "active" and engagement.version == 3


def test_demo_reports_render_outside_transactions_and_retry_failed_exports(demo):
    admin, _ = demo
    original = report_services.generate_report
    def generate(**kwargs):
        assert not connection.in_atomic_block
        return original(**kwargs)
    with patch("apps.core.demo_seed.report_services.render_all", side_effect=RenderError("synthetic failure")):
        with pytest.raises(CommandError): run(admin)
    assert Report.objects.count() == 1 and ReportRevision.objects.get().status == "failed"
    with patch("apps.core.demo_seed.report_services.generate_report", side_effect=generate):
        run(admin)
    assert Report.objects.count() == 2 and ReportRevision.objects.filter(status="ready").count() == 2
    before = snapshot()
    run(admin)
    assert snapshot() == before


def test_demo_preserves_edited_report_and_does_not_reopen_closed_engagement(demo):
    admin, _ = demo
    run(admin)
    report = Report.objects.get(engagement__status="active")
    data = {field: getattr(report, field) for field in ["title", "executive_summary", "methodology", "recommendations", "header", "footer", "marking", "include_images"]}
    data.update(title="Operator's report setup", logo="")
    report_services.save_report(actor=admin,engagement_id=report.engagement_id,report_id=report.pk,version=report.version,
        data=data,finding_ids=list(report.findings.values_list("pk",flat=True)))
    before = snapshot()
    run(admin)
    assert snapshot() == before


def test_interrupted_seed_export_resumes_without_replacing_setup(demo):
    admin, _ = demo
    with patch("apps.core.demo_seed.report_services.generate_report", side_effect=OSError):
        with pytest.raises(CommandError): run(admin)
    report = Report.objects.get()
    assert not report.revisions.exists()
    run(admin)
    report.refresh_from_db()
    assert report.version == 1 and report.revisions.get().status == "ready"


def test_existing_closed_demo_without_reports_is_not_reopened(demo):
    admin, _ = demo
    from apps.core.demo_seed import _prepare_report
    def prepare(engagement, people, scenario):
        return None if scenario["completed"] else _prepare_report(engagement, people, scenario)
    with patch("apps.core.demo_seed._prepare_report", side_effect=prepare): run(admin)
    closed = Engagement.objects.get(status="completed")
    assert not closed.reports.exists()
    before = snapshot()
    run(admin)
    assert snapshot() == before


def test_unsafe_report_storage_is_rejected_before_demo_mutations(demo, settings):
    admin, _ = demo
    settings.REPORT_ROOT.mkdir(mode=0o755)
    settings.REPORT_ROOT.chmod(0o755)
    with pytest.raises(CommandError, match="database/storage readiness"):
        run(admin)
    assert not Engagement.objects.exists() and get_user_model().objects.count() == 1
