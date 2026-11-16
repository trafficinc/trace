import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Evidence(models.Model):
    """Immutable file provenance with versioned description, links and removal tombstone."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='evidence')
    original_filename = models.CharField(max_length=200)
    storage_key = models.CharField(max_length=32, unique=True, editable=False)
    kind = models.CharField(max_length=12, editable=False)
    content_type = models.CharField(max_length=80, editable=False)
    size = models.PositiveBigIntegerField(editable=False)
    sha256 = models.CharField(max_length=64, editable=False)
    thumbnail_key = models.CharField(max_length=32, blank=True, editable=False)
    thumbnail_size = models.PositiveIntegerField(default=0, editable=False)
    thumbnail_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    description = models.TextField(max_length=20000, blank=True)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='uploaded_evidence')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='removed_evidence')
    test_cases = models.ManyToManyField('testcases.TestCase', through='EvidenceTestCase', related_name='evidence', blank=True)
    findings = models.ManyToManyField('findings.Finding', through='EvidenceFinding', related_name='evidence', blank=True)

    class Meta:
        ordering = ['-created_at', 'id']
        indexes = [models.Index(fields=['engagement', 'deleted_at', 'created_at'])]
        constraints = [models.CheckConstraint(condition=models.Q(size__gt=0), name='evidence_nonempty'),
                       models.CheckConstraint(condition=models.Q(version__gte=1), name='evidence_positive_version'),
                       models.CheckConstraint(condition=models.Q(kind__in=['png', 'jpeg', 'pdf', 'text', 'pcap', 'zip']), name='evidence_known_kind')]

    def __str__(self):
        return self.original_filename


class EvidenceTestCase(models.Model):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name='test_case_links')
    test_case = models.ForeignKey('testcases.TestCase', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['evidence', 'test_case'], name='unique_evidence_test')]

    def clean(self):
        super().clean()
        if self.evidence_id and self.test_case_id and self.evidence.engagement_id != self.test_case.engagement_id:
            raise ValidationError('Test case must belong to the evidence engagement.')


class EvidenceFinding(models.Model):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name='finding_links')
    finding = models.ForeignKey('findings.Finding', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['evidence', 'finding'], name='unique_evidence_finding')]

    def clean(self):
        super().clean()
        if self.evidence_id and self.finding_id and self.evidence.engagement_id != self.finding.engagement_id:
            raise ValidationError('Finding must belong to the evidence engagement.')


class EvidenceQuota(models.Model):
    """Versioned administrative policy, independent of engagement content lifecycle."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.OneToOneField('engagements.Engagement', on_delete=models.PROTECT, related_name='evidence_quota')
    limit_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(version__gte=1), name='evidence_quota_positive_version')]


class EvidenceAllocation(models.Model):
    """Pending/retained byte charges. Leases, never timestamps alone, protect writers."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='evidence_allocations')
    evidence = models.OneToOneField(Evidence, null=True, blank=True, on_delete=models.PROTECT, related_name='storage_allocation')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    original_key = models.CharField(max_length=32, blank=True)
    thumbnail_key = models.CharField(max_length=32, blank=True)
    staging_key = models.CharField(max_length=32, blank=True)
    original_bytes = models.PositiveBigIntegerField(default=0)
    thumbnail_bytes = models.PositiveBigIntegerField(default=0)
    disk_bytes = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['engagement', 'evidence']), models.Index(fields=['updated_at'])]
        constraints = [models.CheckConstraint(condition=models.Q(version__gte=1), name='evidence_allocation_positive_version')]

    def clean(self):
        super().clean()
        if self.evidence_id and self.evidence.engagement_id != self.engagement_id:
            raise ValidationError('Evidence allocation must belong to the same engagement.')
