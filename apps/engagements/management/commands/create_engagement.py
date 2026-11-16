from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from apps.engagements.services import create_engagement


class Command(BaseCommand):
    help = "Create a minimal engagement access container with an existing active Lead."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--admin", required=True, help="Existing System Admin username for audit attribution")
        parser.add_argument("--lead", required=True, help="Existing active Lead username")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            admin = User.objects.get(username=options["admin"], is_active=True, is_superuser=True)
            lead = User.objects.get(username=options["lead"], is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("Specify an existing active System Admin and active Lead.") from exc
        try:
            engagement = create_engagement(actor=admin, name=options["name"], lead_id=lead.pk)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(str(engagement.pk))
