import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

SECTIONS = ['executive_summary', 'scope', 'objectives', 'methodology', 'test_summary', 'severity_summary', 'findings', 'evidence', 'recommendations']


def validate_sections(value):
    if not isinstance(value, list) or len(value) != len(SECTIONS) or not all(isinstance(v, str) for v in value) or set(value) != set(SECTIONS):
        raise ValidationError('Include every supported section exactly once, in the desired order.')


def default_sections():
    return list(SECTIONS)


class ReportTemplate(models.Model):
    class Palette(models.TextChoices):
        BLUE = 'blue', 'Flight blue'
        GRAPHITE = 'graphite', 'Graphite'
        AUBERGINE = 'aubergine', 'Aubergine'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    palette = models.CharField(max_length=12, choices=Palette.choices, default=Palette.BLUE)
    sections = models.JSONField(default=default_sections, validators=[validate_sections])
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='reports')
    title = models.CharField(max_length=200)
    executive_summary = models.TextField(max_length=20000, blank=True)
    methodology = models.TextField(max_length=20000, blank=True)
    recommendations = models.TextField(max_length=20000, blank=True)
    header = models.CharField(max_length=200, blank=True)
    footer = models.CharField(max_length=200, blank=True)
    marking = models.CharField('Handling / classification marking', max_length=200, blank=True)
    include_images = models.BooleanField(default=True)
    logo = models.ForeignKey('evidence.Evidence', null=True, blank=True, on_delete=models.PROTECT, related_name='report_logos')
    source_template = models.ForeignKey(ReportTemplate, null=True, blank=True, on_delete=models.PROTECT)
    source_template_version = models.PositiveIntegerField(null=True, blank=True)
    template_snapshot = models.JSONField(default=dict, editable=False)
    findings = models.ManyToManyField('findings.Finding', through='ReportFinding', blank=True)
    additional_evidence = models.ManyToManyField('evidence.Evidence', through='ReportEvidence', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-updated_at', 'id']
        indexes = [models.Index(fields=['engagement', 'updated_at'])]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.logo_id and (self.logo.engagement_id != self.engagement_id or self.logo.deleted_at or self.logo.kind not in {'png', 'jpeg'}):
            raise ValidationError({'logo': 'Select an active image from this engagement.'})


class ReportFinding(models.Model):
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name='finding_links')
    finding = models.ForeignKey('findings.Finding', on_delete=models.PROTECT)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['report', 'finding'], name='unique_report_finding'),
                       models.UniqueConstraint(fields=['report', 'position'], name='unique_report_position')]

    def clean(self):
        super().clean()
        if self.report_id and self.finding_id and self.report.engagement_id != self.finding.engagement_id:
            raise ValidationError('Report findings must belong to the same engagement.')


class ReportEvidence(models.Model):
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name='evidence_links')
    evidence = models.ForeignKey('evidence.Evidence', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['report', 'evidence'], name='unique_report_evidence')]

    def clean(self):
        super().clean()
        if self.report_id and self.evidence_id and self.report.engagement_id != self.evidence.engagement_id:
            raise ValidationError('Report evidence must belong to the same engagement.')


class ReportRevision(models.Model):
    class Status(models.TextChoices):
        RENDERING = 'rendering', 'Rendering'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='report_revisions')
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name='revisions')
    number = models.PositiveIntegerField()
    report_version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RENDERING)
    failure_code = models.CharField(max_length=24, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    renderer_versions = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['report', 'number'], name='unique_report_revision'),
                       models.CheckConstraint(condition=models.Q(status__in=['rendering', 'ready', 'failed']), name='valid_report_revision_status')]


class ReportArtifact(models.Model):
    revision = models.ForeignKey(ReportRevision, on_delete=models.PROTECT, related_name='artifacts')
    engagement = models.ForeignKey('engagements.Engagement', on_delete=models.PROTECT, related_name='report_artifacts')
    format = models.CharField(max_length=8, choices=[(v, v.upper()) for v in ['html', 'docx', 'pdf', 'snapshot']])
    storage_key = models.CharField(max_length=32, unique=True)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['revision', 'format'], name='unique_revision_artifact')]
