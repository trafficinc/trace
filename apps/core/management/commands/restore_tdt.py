from django.core.management.base import BaseCommand, CommandError
from apps.core.backups import restore_backup, validate_backup


class Command(BaseCommand):
    help='Validate a backup; optionally restore to a NEW storage directory under exclusive maintenance.'
    def add_arguments(self,parser):
        parser.add_argument('--source',required=True)
        parser.add_argument('--destination')
        parser.add_argument('--maintenance',action='store_true')
        parser.add_argument('--validate-only',action='store_true')
    def handle(self,*args,**options):
        if not options['validate_only'] and not options['destination']: raise CommandError('Supply --validate-only or a new --destination.')
        try:
            if options['validate_only']: result=validate_backup(options['source'])
            else: result=restore_backup(source=options['source'],destination=options['destination'],maintenance=options['maintenance'])
        except Exception as exc: raise CommandError('Restore validation failed; no existing installation was overwritten.') from exc
        self.stdout.write(f'Backup validated: {len(result["files"])} files. '+('No files restored.' if options['validate_only'] else 'New storage is ready; configure its path, check migrations and start workers.'))
