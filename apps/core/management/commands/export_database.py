from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.core.transfers import export_database


class Command(BaseCommand):
    help='Export an exclusive Django logical transfer and integrity manifest. Contains sensitive database data.'
    def add_arguments(self,parser):
        parser.add_argument('--output',required=True)
        parser.add_argument('--admin',required=True)
        parser.add_argument('--maintenance',action='store_true')
    def handle(self,*args,**options):
        try:
            result=export_database(actor=get_user_model().objects.get(username=options['admin']),output=options['output'],maintenance=options['maintenance'])
        except Exception as exc: raise CommandError('Database export failed; check permissions, maintenance state and destination.') from exc
        self.stdout.write(f'Logical export verified: {sum(result["counts"].values())} records. Protect the file and manifest together.')
