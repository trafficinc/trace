import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="Engagement", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("name", models.CharField(max_length=200)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"ordering": ["name", "id"]}),
        migrations.CreateModel(name="EngagementMembership", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("role", models.CharField(choices=[("lead", "Lead"), ("tester", "Tester"), ("reviewer", "Reviewer"), ("viewer", "Viewer")], max_length=10)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("engagement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="engagements.engagement")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="engagement_memberships", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["user__username", "id"], "constraints": [
            models.UniqueConstraint(fields=("engagement", "user"), name="unique_engagement_member"),
            models.CheckConstraint(condition=models.Q(role__in=["lead", "tester", "reviewer", "viewer"]), name="valid_engagement_role"),
        ]}),
    ]
