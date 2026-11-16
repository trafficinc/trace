"""Development-only orchestration; domain services own validation and audit writes."""
from contextlib import contextmanager
from datetime import timedelta
import fcntl
import io
import os
import stat

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from apps.assets import services as asset_services
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.engagements import services as engagement_services
from apps.engagements.models import Engagement, EngagementStatus
from apps.engagements.permissions import require_system_admin
from apps.evidence import services as evidence_services, storage
from apps.findings import services as finding_services
from apps.testcases import services as test_services
from apps.reports import services as report_services, storage as report_storage
from apps.engagements.permissions import Permission, get_writable_engagement
from .demo_data import CLIENT, MARKING, PEOPLE, SCENARIOS


def require_demo_settings():
    # Django's override_settings wrapper leaves SETTINGS_MODULE unset; the
    # environment still identifies the configuration used for disposable tests.
    module = settings.SETTINGS_MODULE or os.environ.get("DJANGO_SETTINGS_MODULE")
    if module not in {"config.settings.development", "config.settings.test"}:
        raise ValidationError("Demo seeding is restricted to the development and disposable test settings.")


def _guard(actor):
    require_demo_settings()
    require_system_admin(actor)
    if connection.in_atomic_block:
        raise ValidationError("Run demo seeding outside a database transaction; private files need independent file operations.")
    if not {"text", "png"}.issubset(settings.TRACE_EVIDENCE_ALLOWED_TYPES):
        raise ValidationError("Demo seeding requires text and PNG evidence types to be enabled.")
    with report_storage.root_directory():
        pass  # Validate private report storage before creating any demo metadata.


@contextmanager
def _seed_lock():
    # A nonblocking local lease prevents two commands from duplicating file uploads.
    # It uses the same checked, descriptor-pinned private root as evidence storage.
    with storage.root_directory() as root:
        descriptor = os.open(".demo-seed.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValidationError("The demo seed lock must be an owner-only regular file.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValidationError("Another demo seed command is running.") from exc
        yield
    finally:
        os.close(descriptor)


@transaction.atomic
def _people(actor):
    require_system_admin(actor)
    User = get_user_model()
    people = {}
    # Check every reserved name before creating anything. Never adopt a real user,
    # reactivate an account, replace a password or change an existing privilege.
    for key, (username, first, last) in PEOPLE.items():
        user = User.objects.filter(username=username).first()
        email = f"{username}@asterion.example.test"
        if user and (user.email != email or not user.is_active or user.is_staff or user.is_superuser):
            raise ValidationError("A reserved demo username is already used by an incompatible account. No accounts were changed.")
        people[key] = user
    for key, (username, first, last) in PEOPLE.items():
        if people[key] is not None:
            continue
        user = User(username=username, first_name=first, last_name=last,
                    email=f"{username}@asterion.example.test", is_active=True, is_staff=False, is_superuser=False)
        user.set_unusable_password()
        user.full_clean()
        user.save()
        record_event(action=AuditEvent.Action.USER_CREATED, actor=actor, subject_id=user.pk)
        people[key] = user
    return people


def _marker(scenario):
    return (f"DEMO EXERCISE {scenario['key'].upper()} — synthetic aerospace red-team training.\n"
            "All organizations, systems, identities and observations in this exercise are fictional.\n"
            "No real contractor information, credentials or classified material is included.")


def _case_data(spec, assets, people):
    return {
        "title": spec["title"], "category": spec["category"],
        "description": "Synthetic training test for a fictional aerospace contractor; no real target activity.",
        "objective": spec["objective"], "methodology": "Authorized offline lab-fixture review and purple-team discussion.",
        "procedure": spec["procedure"], "expected_result": spec["expected"], "actual_result": spec["actual"],
        "notes": "Exercise-only observation. All addresses use reserved documentation ranges or the .test domain.",
        "assigned_tester": people[spec["assigned"]].pk, "assets": [assets[key].pk for key in spec["assets"]],
    }


@transaction.atomic
def _metadata(actor, people, scenario, today):
    """One bounded metadata-only transaction per exercise; no file work or hashing."""
    require_system_admin(actor)
    lead = people[scenario["lead"]]
    candidates = list(Engagement.objects.filter(
        Q(notes__body=_marker(scenario), notes__created_by=lead)
        | Q(memberships__user=lead) | Q(name=scenario["name"])
    ).distinct())
    if candidates:
        if len(candidates) != 1 or not candidates[0].notes.filter(body=_marker(scenario), created_by=lead).exists():
            raise ValidationError("Demo exercise identity is ambiguous or its identifying note was changed. Existing data was preserved.")
        return candidates[0], False

    engagement = engagement_services.create_engagement(actor=actor, name=scenario["name"], lead_id=lead.pk, data={
        "client": CLIENT, "description": scenario["description"], "objectives": scenario["objectives"],
        "scope_summary": scenario["scope"], "start_date": today + timedelta(days=scenario["start_offset"]),
        "end_date": today + timedelta(days=scenario["end_offset"]), "report_classification": MARKING,
    })
    for key, role in (("operator", "tester"), ("analyst", "tester"), ("reviewer", "reviewer"), ("observer", "viewer")):
        engagement_services.grant_membership(actor=actor, engagement_id=engagement.pk, user_id=people[key].pk, role=role)
    engagement = engagement_services.transition_engagement(actor=lead, engagement_id=engagement.pk,
        target=EngagementStatus.ACTIVE, version=engagement.version)
    engagement_services.save_note(actor=lead, engagement_id=engagement.pk, body=_marker(scenario))
    engagement_services.save_note(actor=people["reviewer"], engagement_id=engagement.pk,
        body="Independent review uses synthetic worksheets only. Record uncertainties as drafts; do not claim an untested control failure.")
    for title, offset, completed in scenario["milestones"]:
        milestone = engagement_services.save_milestone(actor=lead, engagement_id=engagement.pk, data={
            "title": title, "description": "Fictional exercise milestone; progress reflects this saved checklist only.",
            "due_date": today + timedelta(days=offset),
        })
        if completed:
            engagement_services.set_milestone_completed(actor=lead, engagement_id=engagement.pk,
                milestone_id=milestone.pk, completed=True, version=milestone.version)

    assets = {}
    for spec in scenario["assets"]:
        assets[spec["key"]] = asset_services.save_asset(actor=people["operator"], engagement_id=engagement.pk,
            data={**{key: value for key, value in spec.items() if key != "key"}, "owner": lead.pk})
    cases = {}
    for spec in scenario["tests"]:
        data = _case_data(spec, assets, people)
        case = test_services.create_test_case(actor=people[spec["assigned"]], engagement_id=engagement.pk, data=data)
        target = spec["status"]
        transitions = ["in_progress", target] if target in {"passed", "failed"} else ([] if target == "not_started" else [target])
        for status in transitions:
            case = test_services.update_test_case(actor=people[spec["assigned"]], engagement_id=engagement.pk,
                test_case_id=case.pk, version=case.version, data={**data, "status": status})
        cases[spec["key"]] = case
        test_services.save_test_note(actor=people["reviewer"], engagement_id=engagement.pk, test_case_id=case.pk,
            body="Reviewer checkpoint: retain the supplied lab worksheet, distinguish observation from assumption, and keep all conclusions within the exercise scope.")
        test_services.save_reference(actor=people[spec["assigned"]], engagement_id=engagement.pk, test_case_id=case.pk,
            data={"label": "Exercise rules of engagement", "citation": f"DEMO-{scenario['key'].upper()}-ROE §4 — synthetic scope and permitted offline reviews", "url": ""})
    for spec in scenario["findings"]:
        finding = finding_services.save_finding(actor=people["operator"], engagement_id=engagement.pk, data={
            "title": spec["title"], "severity": spec["severity"], "description": spec["description"],
            "technical_details": "# Training observation\n" + next(t["actual"] or t["objective"] for t in scenario["tests"] if t["key"] == spec["test"]),
            "impact": spec["impact"], "reproduction_steps": "Review the linked synthetic test case and offline worksheet. No live testing or external connections are required.",
            "remediation": spec["remediation"], "references": f"DEMO-{scenario['key'].upper()} review worksheet (local fictional citation)",
            "assets": [assets[spec["asset"]].pk], "test_cases": [cases[spec["test"]].pk],
        })
        for status in {"draft": (), "under_review": ("under_review",), "confirmed": ("under_review", "confirmed"),
                       "remediated": ("under_review", "confirmed", "remediated")}[spec["status"]]:
            finding = finding_services.transition_finding(actor=people["operator" if status == "under_review" else "reviewer"],
                engagement_id=engagement.pk, finding_id=finding.pk, version=finding.version, target=status)
    return engagement, True


def _illustration(scenario):
    """A visibly synthetic policy diagram, generated entirely outside DB locks."""
    image = Image.new("RGB", (960, 500), "#101722")
    draw = ImageDraw.Draw(image)
    heading = ImageFont.load_default(size=28)
    text = ImageFont.load_default(size=20)
    draw.text((36, 30), "SYNTHETIC TRAINING EVIDENCE", fill="#8ab4ff", font=heading)
    draw.text((36, 78), f"{scenario['key'].upper()} / offline access-policy worksheet", fill="#edf2fa", font=text)
    for y, label, result in ((150, "Approved training access", "ALLOW"), (235, "Cross-workspace access", "DENY"), (320, "Live hardware / production", "OUT OF SCOPE")):
        draw.rectangle((36, y, 924, y + 65), fill="#182230", outline="#334157", width=2)
        draw.text((56, y + 20), label, fill="#edf2fa", font=text)
        draw.text((675, y + 20), result, fill="#8ab4ff", font=text)
    draw.text((36, 430), "Illustrative diagram only. Not a capture of a real system.", fill="#adbed4", font=text)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _artifacts(scenario):
    first = scenario["tests"][0]
    finding = scenario["findings"][0]
    finding_case = next(test["title"] for test in scenario["tests"] if test["key"] == finding["test"])
    prefix = f"demo-{scenario['key']}"
    text = (f"SYNTHETIC TRAINING EVIDENCE — NOT CLASSIFIED\n"
            f"Fictional organization: {CLIENT}\nExercise: {scenario['key'].upper()}\n\n"
            f"Test: {first['title']}\nObserved result: {first['actual']}\n\n"
            "No real systems were contacted. No actual credentials, contractor records or sensitive documents are present.\n").encode()
    artifacts = [
        (f"{prefix}-review-worksheet.txt", text, first["title"], None),
        (f"{prefix}-policy-diagram.png", _illustration(scenario), finding_case, finding["title"]),
        (f"{prefix}-finding-review.txt", ("SYNTHETIC FINDING REVIEW\n\n" + finding["title"] + "\n" + finding["description"] + "\n").encode(),
         next(test["title"] for test in scenario["tests"] if test["key"] == finding["test"]), finding["title"]),
    ]
    return artifacts


def _attach_artifacts(engagement, people, artifacts):
    if engagement.is_read_only:
        return
    for filename, content, case_title, finding_title in artifacts:
        # Filenames and uploader are immutable. Include tombstones so an operator's
        # removal is never undone. Existing metadata, links and files stay untouched.
        existing = list(engagement.evidence.filter(original_filename=filename))
        if existing:
            if len(existing) != 1 or existing[0].uploader_id != people["operator"].pk:
                raise ValidationError("An evidence filename conflicts with the demo dataset. Existing evidence was preserved.")
            continue
        cases = list(engagement.test_cases.filter(title=case_title))
        findings = list(engagement.findings.filter(title=finding_title)) if finding_title else []
        if len(cases) != 1 or finding_title and len(findings) != 1:
            raise ValidationError("A demo evidence link was renamed or is ambiguous. Existing content was preserved.")
        evidence_services.upload_evidence(actor=people["operator"], engagement_id=engagement.pk,
            upload=SimpleUploadedFile(filename, content), data={
                "description": "Synthetic training artifact created locally for this fictional exercise. Contains no real contractor information.",
                "test_cases": [cases[0].pk], "findings": [finding.pk for finding in findings],
            })


def _report_data(scenario):
    return {
        "title": f"[DEMO] {scenario['key'].upper()} — Assessment report",
        "executive_summary": (
            "# Synthetic assessment summary\n"
            f"This fictional {scenario['key'].upper()} exercise documents authorized offline worksheet review. "
            "All observations, organizations and evidence are fabricated training material.\n\n"
            + ("The supplier-access review and independent remediation verification are complete. "
               "The retained findings describe the exercise outcome, not a live security assessment."
               if scenario['completed'] else
               "Assessment work is ongoing. Confirmed findings, observations under review and planning drafts "
               "are explicitly distinguished; unfinished work is not presented as a verified control failure.")
        ),
        "methodology": "1. Confirm the fictional scope and rules of engagement.\n"
            "2. Review supplied offline access-control worksheets.\n"
            "3. Record test results and link synthetic evidence.\n"
            "4. Independently review findings and prioritize remediation.\n\n"
            "No live targets, scanning, exploits or external network requests are involved.",
        "recommendations": "Prioritize independently confirmed observations, assign remediation owners and "
            "record a scoped retest. Review draft and under-review observations before treating them as final conclusions.",
        "header": f"DEMO-{scenario['key'].upper()} / Fictional assessment",
        "footer": "Training copy — no real customer records",
        "marking": MARKING, "include_images": True, "logo": "",
    }


@transaction.atomic
def _prepare_report(engagement, people, scenario):
    """Preserve existing setups; only resume an untouched seed export."""
    lead = people[scenario["lead"]]
    data = _report_data(scenario)
    reports = list(engagement.reports.order_by("id")[:2])
    if reports:
        report = reports[0]
        if (len(reports) == 1 and report.version == 1 and report.created_by_id == lead.pk
                and all(getattr(report, field) == value for field, value in data.items() if field != "logo")
                and report.logo_id is None
                and not report.revisions.filter(status__in=["ready", "rendering"]).exists()):
            return report
        return None
    if engagement.is_read_only:
        return None
    # Recheck permissions/lifecycle under the same short parent transaction used
    # by ordinary report setup. No rendering, image work or hashing happens here.
    get_writable_engagement(lead, engagement.pk, Permission.GENERATE_REPORTS)
    findings = []
    for spec in scenario["findings"]:
        matches = list(engagement.findings.filter(title=spec["title"])[:2])
        if len(matches) != 1:
            raise ValidationError("A demo report finding was renamed or is ambiguous. Existing content was preserved.")
        findings.append(matches[0].pk)
    return report_services.save_report(actor=lead, engagement_id=engagement.pk, data=data, finding_ids=findings)


def seed_demo(*, actor):
    _guard(actor)
    # Draw fixtures before acquiring any database writer lock.
    artifacts = {scenario["key"]: _artifacts(scenario) for scenario in SCENARIOS}
    result = []
    with _seed_lock():
        people = _people(actor)
        for scenario in SCENARIOS:
            engagement, created = _metadata(actor, people, scenario, timezone.localdate())
            _attach_artifacts(engagement, people, artifacts[scenario["key"]])
            report = _prepare_report(engagement, people, scenario)
            if scenario["completed"] and engagement.status == EngagementStatus.ACTIVE and engagement.version == 2:
                # Fixed initial version: never refresh/retry over an operator's edits.
                engagement = engagement_services.transition_engagement(actor=people[scenario["lead"]],
                    engagement_id=engagement.pk, target=EngagementStatus.COMPLETED, version=2)
            if report is not None:
                report_services.generate_report(actor=people[scenario["lead"]], engagement_id=engagement.pk,
                    report_id=report.pk, version=report.version)
            result.append((engagement, created))
    return result
