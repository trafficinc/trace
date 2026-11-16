from django.core.management.base import BaseCommand
from apps.accounts.models import LoginThrottle
from apps.accounts.security import fingerprint, username_fingerprint


class Command(BaseCommand):
    help = "Clear one operator-selected login throttle bucket; requires server shell access."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--username")
        group.add_argument("--source", help="Peer IP as seen by Django; all clients behind a proxy may share it")

    def handle(self, *args, **options):
        key = username_fingerprint(options["username"]) if options["username"] is not None else fingerprint("source", options["source"])
        count, _ = LoginThrottle.objects.filter(pk=key).delete()
        self.stdout.write(f"Cleared {count} throttle bucket(s).")
