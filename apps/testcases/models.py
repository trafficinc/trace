import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models


class TestCaseStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class TestCaseTemplate(models.Model):
    """A local shared blueprint; never includes engagement results or assignments."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=20000, blank=True)
    category = models.CharField(max_length=100)
    objective = models.TextField(max_length=20000, blank=True)
    methodology = models.TextField(max_length=20000, blank=True)
    procedure = models.TextField(max_length=40000, blank=True)
    expected_result = models.TextField(max_length=20000, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_test_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class TestCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey("engagements.Engagement", on_delete=models.PROTECT, related_name="test_cases")
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=20000, blank=True)
    category = models.CharField(max_length=100)
    objective = models.TextField(max_length=20000, blank=True)
    methodology = models.TextField(max_length=20000, blank=True)
    procedure = models.TextField(max_length=40000, blank=True)
    expected_result = models.TextField(max_length=20000, blank=True)
    actual_result = models.TextField(max_length=20000, blank=True)
    status = models.CharField(max_length=14, choices=TestCaseStatus.choices, default=TestCaseStatus.NOT_STARTED)
    assigned_tester = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_test_cases")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    assets = models.ManyToManyField("assets.Asset", through="TestCaseAsset", related_name="test_cases", blank=True)
    notes = models.TextField(max_length=20000, blank=True)
    source_template = models.ForeignKey(TestCaseTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="test_cases")
    source_template_version = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_test_cases")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["title", "id"]
        indexes = [models.Index(fields=["engagement", field]) for field in ("status", "assigned_tester", "category", "title", "updated_at")]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=TestCaseStatus.values), name="valid_test_case_status"),
            models.CheckConstraint(condition=~models.Q(status__in=["passed", "failed"]) | ~models.Q(actual_result=""), name="test_outcome_has_result"),
            models.CheckConstraint(condition=models.Q(completed_at__isnull=True) | models.Q(started_at__isnull=True) | models.Q(completed_at__gte=models.F("started_at")), name="test_timestamp_order"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}
        if self.assigned_tester_id and self.engagement_id and not self.engagement.memberships.filter(
                user_id=self.assigned_tester_id, user__is_active=True, role__in=["lead", "tester"]).exists():
            errors["assigned_tester"] = "Assign an active Lead or Tester from this engagement."
        if self.status in (TestCaseStatus.PASSED, TestCaseStatus.FAILED) and not self.actual_result.strip():
            errors["actual_result"] = "Record an actual result before marking a test passed or failed."
        if self.completed_at and self.started_at and self.completed_at < self.started_at:
            errors["completed_at"] = "Completion cannot precede the start."
        if errors:
            raise ValidationError(errors)


class TestCaseAsset(models.Model):
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name="asset_links")
    asset = models.ForeignKey("assets.Asset", on_delete=models.PROTECT, related_name="test_links")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["test_case", "asset"], name="unique_test_asset")]

    def clean(self):
        super().clean()
        if self.test_case_id and self.asset_id and self.test_case.engagement_id != self.asset.engagement_id:
            raise ValidationError("Related assets must belong to the test case's engagement.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TestCaseNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name="note_entries")
    body = models.TextField(max_length=20000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="test_case_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at", "-id"]


class TestCaseReference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name="references")
    label = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, blank=True, validators=[URLValidator(schemes=["http", "https"])])
    citation = models.TextField(max_length=4000, blank=True, help_text="Document, section, ticket ID or other local citation.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="test_case_references")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["label", "id"]

    def clean(self):
        super().clean()
        if not (self.url or self.citation.strip()):
            raise ValidationError({"citation": "Provide an HTTP/HTTPS URL or a local citation."})
