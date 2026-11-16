from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.http import Http404
from apps.core.exceptions import EditConflict
from apps.engagements.services import purge_engagement


class Command(BaseCommand):
    help = "Permanently purge an archived engagement and its notes, milestones and memberships. Back up first."

    def add_arguments(self, parser):
        parser.add_argument("engagement_id")
        parser.add_argument("--admin", required=True)
        parser.add_argument("--version", required=True, type=int)
        parser.add_argument("--confirm", required=True, help="Repeat the exact engagement UUID")
        parser.add_argument("--reason", required=True, choices=["retention", "duplicate", "test-data"])

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["admin"], is_superuser=True, is_active=True)
        except get_user_model().DoesNotExist as exc:
            raise CommandError("An existing active System Admin is required.") from exc
        try:
            purge_engagement(actor=actor, engagement_id=options["engagement_id"], version=options["version"],
                             confirmation=options["confirm"], reason=options["reason"])
        except (ValidationError, Http404, EditConflict) as exc:
            raise CommandError("Purge refused: validate the UUID, archived state, version, confirmation and related records.") from exc
        self.stdout.write("Archived engagement purged. Audit records retained.")
