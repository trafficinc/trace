import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Severity(models.TextChoices):
    CRITICAL = 'critical', 'Critical'
    HIGH = 'high', 'High'
    MEDIUM = 'medium', 'Medium'
    LOW = 'low', 'Low'
    INFORMATIONAL = 'informational', 'Informational'


class FindingStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    UNDER_REVIEW = 'under_review', 'Under review'
    CONFIRMED = 'confirmed', 'Confirmed'
    REMEDIATED = 'remediated', 'Remediated'
    ACCEPTED_RISK = 'accepted_risk', 'Accepted risk'


def validate_cvss(value):
    """Validate complete CVSS 3.0/3.1 base vectors without claiming calculated scores."""
    if not value:
        return
    parts = value.split('/')
    metrics = dict(AV='NALP', AC='LH', PR='NLH', UI='NR', S='UC', C='HLN', I='HLN', A='HLN')
    if parts[0] not in {'CVSS:3.0', 'CVSS:3.1'} or len(parts) != 9:
        raise ValidationError('Enter a complete CVSS:3.0 or CVSS:3.1 base vector (eight metrics).')
    seen = set()
    for part in parts[1:]:
        pair = part.split(':')
        if len(pair) != 2 or pair[0] not in metrics or pair[0] in seen or pair[1] not in set(metrics[pair[0]]):
            raise ValidationError('Invalid or duplicate CVSS base metric.')
        seen.add(pair[0])


class Definition(models.Model):
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    cvss_vector = models.CharField(max_length=255, blank=True, validators=[validate_cvss])
    cvss_score = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True, editable=False)
    description = models.TextField(max_length=40000, blank=True)
    technical_details = models.TextField(max_length=40000, blank=True)
    impact = models.TextField(max_length=40000, blank=True)
    reproduction_steps = models.TextField(max_length=40000, blank=True)
    remediation = models.TextField('Remediation recommendations', max_length=40000, blank=True)
    references = models.TextField(max_length=20000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.cvss_score is not None:
            raise ValidationError({'cvss_score': 'Scores are unavailable without a maintained CVSS calculator.'})

    def __str__(self):
        return self.title


class FindingTemplate(Definition):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['title', 'id']


class Finding(Definition):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='findings')
    status = models.CharField(max_length=16, choices=FindingStatus.choices, default=FindingStatus.DRAFT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='authored_findings')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_findings')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_template = models.ForeignKey(FindingTemplate, null=True, blank=True, on_delete=models.PROTECT)
    source_template_version = models.PositiveIntegerField(null=True, blank=True)
    assets = models.ManyToManyField('assets.Asset', through='FindingAsset', related_name='findings', blank=True)
    test_cases = models.ManyToManyField('testcases.TestCase', through='FindingTestCase', related_name='findings', blank=True)

    class Meta:
        ordering = ['-updated_at', 'id']
        indexes = [models.Index(fields=['engagement', field]) for field in ('severity', 'status', 'title', 'updated_at')]
        constraints = [models.CheckConstraint(condition=models.Q(status__in=FindingStatus.values), name='valid_finding_status'), models.CheckConstraint(condition=models.Q(severity__in=Severity.values), name='valid_finding_severity')]


class FindingAsset(models.Model):
    finding = models.ForeignKey(Finding, on_delete=models.PROTECT, related_name='asset_links')
    asset = models.ForeignKey('assets.Asset', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['finding', 'asset'], name='unique_finding_asset')]

    def clean(self):
        if self.finding_id and self.asset_id and self.finding.engagement_id != self.asset.engagement_id:
            raise ValidationError('Asset must belong to the finding engagement.')


class FindingTestCase(models.Model):
    finding = models.ForeignKey(Finding, on_delete=models.PROTECT, related_name='test_case_links')
    test_case = models.ForeignKey('testcases.TestCase', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['finding', 'test_case'], name='unique_finding_test')]

    def clean(self):
        if self.finding_id and self.test_case_id and self.finding.engagement_id != self.test_case.engagement_id:
            raise ValidationError('Test case must belong to the finding engagement.')
