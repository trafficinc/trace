import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("engagements", "0001_initial")]
    operations = [migrations.CreateModel(name="AuditEvent", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("action", models.CharField(choices=[("login.success", "Login succeeded"), ("login.failure", "Login failed"), ("logout", "Logout"), ("user.created", "User created"), ("user.updated", "User updated"), ("user.password_changed", "Password changed"), ("engagement.created", "Engagement created"), ("membership.granted", "Membership granted"), ("membership.changed", "Membership changed"), ("membership.revoked", "Membership revoked")], max_length=40)),
        ("subject_id", models.CharField(blank=True, max_length=64)),
        ("subject_hash", models.CharField(blank=True, max_length=64)),
        ("source_hash", models.CharField(blank=True, max_length=64)),
        ("request_id", models.CharField(blank=True, max_length=32)),
        ("metadata", models.JSONField(default=dict)),
        ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
        ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ("engagement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="engagements.engagement")),
    ], options={"ordering": ["-created_at", "-id"]})]
