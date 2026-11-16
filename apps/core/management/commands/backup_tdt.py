from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.core.backups import create_backup


class Command(BaseCommand):
    help='Create a verified private SQLite/evidence/report backup during exclusive maintenance.'
    def add_arguments(self,parser):
        parser.add_argument('--output',required=True)
        parser.add_argument('--admin',required=True)
        parser.add_argument('--maintenance',action='store_true')
    def handle(self,*args,**options):
        try:
            actor=get_user_model().objects.get(username=options['admin'])
            result=create_backup(actor=actor,output=options['output'],maintenance=options['maintenance'])
        except Exception as exc: raise CommandError('Backup failed. Check administrator access, maintenance exclusivity, paths and file integrity.') from exc
        self.stdout.write(f'Backup verified: {len(result["files"])} files; audit sequence {result["audit"]["head_sequence"]}. Protect the manifest and backup together.')
