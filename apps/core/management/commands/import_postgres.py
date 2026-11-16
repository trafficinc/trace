from django.core.management.base import BaseCommand, CommandError
from apps.core.transfers import import_postgres


class Command(BaseCommand):
    help='OS-operator import into an EMPTY PostgreSQL database during exclusive maintenance.'
    def add_arguments(self,parser):
        parser.add_argument('--source',required=True)
        parser.add_argument('--maintenance',action='store_true')
    def handle(self,*args,**options):
        try: import_postgres(source=options['source'],maintenance=options['maintenance'])
        except Exception as exc: raise CommandError('PostgreSQL import failed and rolled back. Verify the empty destination, matching release and trusted transfer manifest.') from exc
        self.stdout.write('Logical import verified. Retain the original database until file integrity, access checks and report generation pass.')
