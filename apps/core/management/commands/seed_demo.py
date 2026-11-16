from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.core.demo_seed import require_demo_settings, seed_demo
from apps.core.exceptions import EditConflict
from apps.reports.rendering import RenderError
from apps.reports.storage import StorageError as ReportStorageError
from apps.evidence.storage import StorageError


class Command(BaseCommand):
    help = "Seed fictional aerospace red-team exercises in development only; never resets existing data."
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Existing active System Admin username for audit attribution")

    def handle(self, *args, **options):
        try:
            require_demo_settings()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        try:
            actor = get_user_model().objects.get(username=options["admin"], is_active=True, is_superuser=True)
        except get_user_model().DoesNotExist as exc:
            raise CommandError("Specify an existing active System Admin with --admin. No credentials are created.") from exc
        try:
            result = seed_demo(actor=actor)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        except (PermissionDenied, EditConflict, DatabaseError, OSError, StorageError, ReportStorageError, RenderError) as exc:
            raise CommandError("Demo seeding stopped. Check database/storage readiness and account permissions; existing content was preserved. Re-run after resolving the issue; records are not reset.") from exc
        for engagement, created in result:
            label = "Created" if created else "Preserved"
            self.stdout.write(f"{label}: {engagement.name} [{engagement.status}] /engagements/{engagement.pk}/")
        self.stdout.write(self.style.SUCCESS("Demo exercises ready. Sign in with your existing account; demo role accounts have no generated sign-in credentials."))
