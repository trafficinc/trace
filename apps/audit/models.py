from django.conf import settings
from django.db import models
from django.core.exceptions import PermissionDenied
from django.utils import timezone


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        AUDIT_EXPORTED = "audit.exported", "Audit exported"
        AUDIT_RETENTION = "audit.retention", "Audit retention cleanup"
        HISTORY_BASELINE = "history.baseline", "Revision baseline captured"
        LOGIN_SUCCESS = "login.success", "Login succeeded"
        LOGIN_FAILURE = "login.failure", "Login failed"
        LOGOUT = "logout", "Logout"
        USER_CREATED = "user.created", "User created"
        USER_UPDATED = "user.updated", "User updated"
        PASSWORD_CHANGED = "user.password_changed", "Password changed"
        ENGAGEMENT_CREATED = "engagement.created", "Engagement created"
        ENGAGEMENT_UPDATED = "engagement.updated", "Engagement updated"
        ENGAGEMENT_STATUS = "engagement.status_changed", "Engagement status changed"
        ENGAGEMENT_PURGED = "engagement.purged", "Engagement purged"
        NOTE_CREATED = "note.created", "Engagement note created"
        NOTE_UPDATED = "note.updated", "Engagement note updated"
        NOTE_DELETED = "note.deleted", "Engagement note deleted"
        MILESTONE_CREATED = "milestone.created", "Milestone created"
        MILESTONE_UPDATED = "milestone.updated", "Milestone updated"
        MILESTONE_DELETED = "milestone.deleted", "Milestone deleted"
        MEMBER_GRANTED = "membership.granted", "Membership granted"
        MEMBER_CHANGED = "membership.changed", "Membership changed"
        MEMBER_REVOKED = "membership.revoked", "Membership revoked"
        ASSET_CREATED = "asset.created", "Asset created"
        ASSET_UPDATED = "asset.updated", "Asset updated"
        FINDING_CREATED = "finding.created", "Finding created"
        FINDING_UPDATED = "finding.updated", "Finding updated"
        FINDING_STATUS = "finding.status_changed", "Finding status changed"
        FINDING_TEMPLATE_SAVED = "finding_template.saved", "Finding template saved"
        REPORT_SAVED = "report.saved", "Report setup saved"
        REPORT_STARTED = "report.started", "Report generation started"
        REPORT_READY = "report.ready", "Report revision ready"
        REPORT_FAILED = "report.failed", "Report generation failed"
        REPORT_DOWNLOADED = "report.downloaded", "Report artifact downloaded"
        REPORT_TEMPLATE_SAVED = "report_template.saved", "Report template saved"
        EVIDENCE_QUOTA_CHANGED = "evidence_quota.changed", "Evidence quota changed"
        EVIDENCE_RECONCILED = "evidence_storage.reconciled", "Evidence storage reconciled"
        EVIDENCE_UPLOADED = "evidence.uploaded", "Evidence uploaded"
        EVIDENCE_UPDATED = "evidence.updated", "Evidence metadata updated"
        EVIDENCE_REMOVED = "evidence.removed", "Evidence removed"
        EVIDENCE_DOWNLOADED = "evidence.downloaded", "Evidence downloaded"
        EVIDENCE_VERIFIED = "evidence.verified", "Evidence integrity checked"
        TEST_CREATED = "test.created", "Test case created"
        TEST_UPDATED = "test.updated", "Test case updated"
        TEST_TEMPLATE_CREATED = "test_template.created", "Test template created"
        TEST_TEMPLATE_UPDATED = "test_template.updated", "Test template updated"
        TEST_NOTE_SAVED = "test_note.saved", "Test case note saved"
        TEST_REFERENCE_SAVED = "test_reference.saved", "Test case reference saved"
        TEST_CHILD_DELETED = "test_child.deleted", "Test case supporting record deleted"

    action = models.CharField(max_length=40, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    engagement = models.ForeignKey("engagements.Engagement", null=True, blank=True, on_delete=models.PROTECT)
    engagement_ref = models.UUIDField(null=True, blank=True, db_index=True)
    subject_id = models.CharField(max_length=64, blank=True)
    subject_hash = models.CharField(max_length=64, blank=True)
    source_hash = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict)
    entity_kind = models.CharField(max_length=32, blank=True, db_index=True)
    actor_ref = models.CharField(max_length=64, blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    chain_sequence = models.PositiveBigIntegerField(null=True, unique=True, editable=False)
    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    record_hash = models.CharField(max_length=64, blank=True, editable=False)
    legacy = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionDenied('Audit records cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Use the authorized audit retention workflow.')

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=['engagement_ref','entity_kind','subject_id','created_at']),
                   models.Index(fields=['engagement_ref','actor_ref','created_at'])]


class AuditChainState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    head_sequence = models.PositiveBigIntegerField(default=0)
    head_hash = models.CharField(max_length=64, default='0'*64)
    anchor_sequence = models.PositiveBigIntegerField(default=0)
    anchor_hash = models.CharField(max_length=64, default='0'*64)
    retention_active = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)


class EntityRevision(models.Model):
    event = models.ForeignKey(AuditEvent, on_delete=models.PROTECT, related_name='revisions')
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='entity_revisions')
    entity_kind = models.CharField(max_length=16, choices=[('finding','Finding'),('test_case','Test case')])
    entity_id = models.UUIDField()
    entity_version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    baseline = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-entity_version','-id']
        constraints = [models.UniqueConstraint(fields=['entity_kind','entity_id','entity_version'],name='unique_entity_revision')]
        indexes = [models.Index(fields=['engagement','entity_kind','entity_id','entity_version'])]

    def save(self, *args, **kwargs):
        if not self._state.adding: raise PermissionDenied('Revision history cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Use the authorized audit retention workflow.')
