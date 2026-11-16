import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied, ValidationError
from apps.audit.maintenance import verify_history
from apps.audit.services import AuditIntegrityError


class Command(BaseCommand):
    help='Verify audit continuity and revision bindings; print a checkpoint for independent safekeeping.'

    def add_arguments(self,parser):
        parser.add_argument('--admin',required=True,help='Active System Admin username.')

    def handle(self,*args,**options):
        try:
            actor=get_user_model().objects.get(username=options['admin'])
            result=verify_history(actor=actor)
        except (get_user_model().DoesNotExist,PermissionDenied,ValidationError,AuditIntegrityError) as exc:
            raise CommandError('Audit verification failed or access denied.') from exc
        self.stdout.write(json.dumps(result,sort_keys=True))
