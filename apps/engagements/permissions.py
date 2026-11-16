"""Central policy. HTTP scoping and service authorization share these helpers."""
from enum import StrEnum
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.shortcuts import get_object_or_404
from .models import Engagement, EngagementMembership


class Permission(StrEnum):
    VIEW = "view"
    MANAGE_MEMBERS = "manage_members"
    EDIT_ENGAGEMENT = "edit_engagement"
    WRITE_NOTES = "write_notes"
    MANAGE_MILESTONES = "manage_milestones"
    WRITE_TESTS = "write_tests"
    MANAGE_ASSETS = "manage_assets"
    WRITE_TEST_NOTES = "write_test_notes"
    WRITE_FINDINGS = "write_findings"
    REVIEW_FINDINGS = "review_findings"
    ATTACH_EVIDENCE = "attach_evidence"
    DOWNLOAD_EVIDENCE = "download_evidence"
    GENERATE_REPORTS = "generate_reports"
    VIEW_AUDIT = "view_audit"


P = Permission
ROLE_PERMISSIONS = {
    "lead": frozenset(P),
    "tester": frozenset({P.VIEW, P.WRITE_NOTES, P.WRITE_TESTS, P.MANAGE_ASSETS, P.WRITE_TEST_NOTES, P.WRITE_FINDINGS, P.ATTACH_EVIDENCE, P.DOWNLOAD_EVIDENCE, P.GENERATE_REPORTS}),
    "reviewer": frozenset({P.VIEW, P.WRITE_NOTES, P.WRITE_TEST_NOTES, P.REVIEW_FINDINGS, P.DOWNLOAD_EVIDENCE, P.GENERATE_REPORTS, P.VIEW_AUDIT}),
    "viewer": frozenset({P.VIEW, P.DOWNLOAD_EVIDENCE}),
}


def identity(actor):
    if not actor or not actor.is_authenticated or actor.pk is None:
        return None
    return get_user_model().objects.filter(pk=actor.pk, is_active=True).values("id", "is_superuser").first()


def is_system_admin(actor):
    current = identity(actor)
    return bool(current and current["is_superuser"])


def require_system_admin(actor):
    from apps.core.database import mutation_lock
    mutation_lock()
    if not is_system_admin(actor):
        raise PermissionDenied("System Admin access is required.")


def visible_engagements(actor):
    current = identity(actor)
    if current is None:
        return Engagement.objects.none()
    if current["is_superuser"]:
        return Engagement.objects.all()
    return Engagement.objects.filter(memberships__user_id=current["id"])


def has_permission(actor, engagement_id, permission):
    # Unknown capabilities always fail closed, including for administrators.
    try:
        permission = Permission(permission)
    except ValueError:
        return False
    return permission in engagement_permissions(actor, engagement_id)


def engagement_permissions(actor, engagement_id):
    """Resolve all navigation capabilities in two queries, independent of row count."""
    current = identity(actor)
    if current is None:
        return frozenset()
    if current["is_superuser"]:
        return frozenset(P) if Engagement.objects.filter(pk=engagement_id).exists() else frozenset()
    role = EngagementMembership.objects.filter(engagement_id=engagement_id, user_id=current["id"]).values_list("role", flat=True).first()
    return ROLE_PERMISSIONS.get(role, frozenset())


def get_engagement(actor, engagement_id, permission=Permission.VIEW, *, for_update=False):
    if for_update:
        from apps.core.database import mutation_lock
        mutation_lock()
    queryset = visible_engagements(actor)
    if for_update:
        if not connection.in_atomic_block:
            raise RuntimeError("Mutating services must start a short transaction before locking an engagement.")
        # SQLite's IMMEDIATE transaction already reserves the single writer lock.
    if for_update and connection.vendor == 'postgresql':
        queryset = queryset.select_for_update()
    engagement = get_object_or_404(queryset, pk=engagement_id)
    if not has_permission(actor, engagement.pk, permission):
        raise PermissionDenied("Your engagement role does not allow this operation.")
    return engagement


def get_scoped_object(actor, engagement_id, queryset, *, permission=Permission.VIEW, **lookup):
    """For future domain models with an engagement FK, including HTMX/files/reports."""
    engagement = get_engagement(actor, engagement_id, permission)
    return get_object_or_404(queryset.filter(engagement=engagement), **lookup)


def get_writable_engagement(actor, engagement_id, permission):
    """Call inside an atomic service; SQLite IMMEDIATE coordinates writes with closure."""
    engagement = get_engagement(actor, engagement_id, permission, for_update=True)
    if engagement.is_read_only:
        raise ValidationError("Completed and archived engagements are read-only.")
    return engagement
