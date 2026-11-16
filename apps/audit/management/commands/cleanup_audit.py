import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied, ValidationError
from apps.audit.maintenance import cleanup_history
from apps.audit.services import AuditIntegrityError


class Command(BaseCommand):
    help='Review retention cleanup; --apply requires the reviewed head sequence. Default: dry run.'

    def add_arguments(self,parser):
        parser.add_argument('--admin',required=True)
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--expected-sequence',type=int)
        parser.add_argument('--batch-size',type=int,default=500)

    def handle(self,*args,**options):
        try:
            actor=get_user_model().objects.get(username=options['admin'])
            result=cleanup_history(actor=actor,apply=options['apply'],expected_sequence=options['expected_sequence'],batch_size=options['batch_size'])
        except (get_user_model().DoesNotExist,PermissionDenied,ValidationError,AuditIntegrityError) as exc:
            raise CommandError('Audit cleanup failed or access denied; review retention settings and checkpoint.') from exc
        self.stdout.write(json.dumps(result,sort_keys=True))
