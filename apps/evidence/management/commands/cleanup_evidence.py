from django.core.management.base import BaseCommand, CommandError
from apps.evidence.services import cleanup_orphans
from apps.evidence.storage import StorageError


class Command(BaseCommand):
    help = 'Remove committed evidence tombstone files and old unreferenced files; never purge metadata.'

    def add_arguments(self, parser):
        parser.add_argument('--older-than-hours', type=int, default=24)

    def handle(self, *args, **options):
        try:
            removed, deferred = cleanup_orphans(older_than_seconds=options['older_than_hours'] * 3600)
        except (OSError, StorageError, ValueError) as exc:
            raise CommandError('Cleanup could not run. Check private storage permissions and the grace period (minimum one hour).') from exc
        self.stdout.write(f'Removed {removed} files; deferred {deferred}. Metadata retained.')
