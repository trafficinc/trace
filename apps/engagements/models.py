import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class EngagementStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    ARCHIVED = "archived", "Archived"


class Engagement(models.Model):
    """Versioned mission container and authorization boundary."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    client = models.CharField("Client / organization", max_length=200, blank=True)
    description = models.TextField(blank=True, max_length=20000)
    objectives = models.TextField(blank=True, max_length=20000)
    scope_summary = models.TextField(blank=True, max_length=20000)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=EngagementStatus.choices, default=EngagementStatus.PLANNED, db_index=True)
    report_classification = models.CharField("Report classification / handling marking", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_engagements")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_engagements")
    version = models.PositiveIntegerField(default=1)
    completed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=EngagementStatus.values), name="valid_engagement_status"),
            models.CheckConstraint(condition=models.Q(end_date__isnull=True) | models.Q(start_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")), name="engagement_date_order"),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})

    @property
    def is_read_only(self):
        return self.status in (EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED)

    def __str__(self):
        return self.name


class EngagementMembership(models.Model):
    class Role(models.TextChoices):
        LEAD = "lead", "Lead"
        TESTER = "tester", "Tester"
        REVIEWER = "reviewer", "Reviewer"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="engagement_memberships")
    role = models.CharField(max_length=10, choices=Role.choices)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["engagement", "user"], name="unique_engagement_member"),
            models.CheckConstraint(condition=models.Q(role__in=["lead", "tester", "reviewer", "viewer"]), name="valid_engagement_role"),
        ]
        ordering = ["user__username", "id"]


class EngagementNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.PROTECT, related_name="notes")
    body = models.TextField(max_length=20000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="engagement_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at", "-id"]


class EngagementMilestone(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(Engagement, on_delete=models.PROTECT, related_name="milestones")
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=10000, blank=True)
    due_date = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="engagement_milestones")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["completed", "due_date", "created_at", "id"]
