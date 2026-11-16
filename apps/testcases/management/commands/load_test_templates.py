import json
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.testcases.models import TestCaseTemplate
from apps.testcases.services import save_template


class Command(BaseCommand):
    help = "Publish local JSON procedure templates as an existing System Admin; existing names are skipped."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", type=Path, default=settings.BASE_DIR / "test_templates" / "starter.json")
        parser.add_argument("--admin", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["admin"], is_active=True, is_superuser=True)
        except get_user_model().DoesNotExist as exc:
            raise CommandError("Specify an existing active System Admin.") from exc
        try:
            with options["file"].open("rb") as stream:
                content = stream.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError("File exceeds one MiB")
            rows = json.loads(content)
            if not isinstance(rows, list) or len(rows) > 100 or not all(isinstance(row, dict) for row in rows):
                raise ValueError("Expected at most 100 template objects")
            created = skipped = 0
            with transaction.atomic():
                for row in rows:
                    if TestCaseTemplate.objects.filter(name=row.get("name")).exists():
                        skipped += 1
                    else:
                        save_template(actor=actor, data=row)
                        created += 1
        except (OSError, ValueError, ValidationError, TypeError) as exc:
            raise CommandError("Import refused. Check the local JSON file size, structure and template fields; no partial import was saved.") from exc
        self.stdout.write(f"Published {created} templates; skipped {skipped} existing names.")
