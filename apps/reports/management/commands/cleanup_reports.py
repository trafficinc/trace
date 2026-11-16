from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.audit.services import record_event
from apps.core.concurrency import cas_update
from apps.reports.models import ReportRevision
from apps.reports.services import cleanup_orphans
from apps.reports.storage import StorageError


class Command(BaseCommand):
    help='Remove old unreferenced report files and mark abandoned pending revisions failed; retain report history.'
    def add_arguments(self,parser): parser.add_argument('--older-than-hours',type=int,default=24)
    def handle(self,*args,**options):
        hours=options['older_than_hours']
        if hours<1: raise CommandError('Use a grace period of at least one hour.')
        try: removed,deferred=cleanup_orphans(older_than_seconds=hours*3600)
        except (OSError,StorageError) as exc: raise CommandError('Private report cleanup could not run.') from exc
        # Rendering is bounded to 90 seconds; an hour-old pending job is abandoned.
        with transaction.atomic():
            pending=list(ReportRevision.objects.filter(status='rendering',created_at__lt=timezone.now()-timedelta(hours=hours))[:100])
            for revision in pending:
                before = cas_update(ReportRevision.objects.filter(pk=revision.pk,engagement_id=revision.engagement_id,status='rendering'),version=revision.version,
                    status='failed',failure_code='abandoned',completed_at=timezone.now())
                record_event(action='report.failed',engagement=revision.engagement,subject_id=revision.pk,before=before,metadata={'version':revision.version+1,'status':'failed'})
        self.stdout.write(f'Removed {removed} files; deferred {deferred}; marked {len(pending)} abandoned revisions failed. History retained.')
