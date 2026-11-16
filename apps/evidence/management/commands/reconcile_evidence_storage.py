import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.evidence.quotas import reconcile


class Command(BaseCommand):
    help = 'Inspect quota charges by default; --apply --maintenance reconciles safe cleanup under exclusive maintenance.'

    def add_arguments(self, parser):
        parser.add_argument('--admin', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--maintenance', action='store_true')
        parser.add_argument('--older-than-hours', type=int, default=24)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options['admin'])
            result = reconcile(actor=actor, apply=options['apply'], maintenance=options['maintenance'],
                               older_than_seconds=options['older_than_hours'] * 3600)
        except Exception as error:
            raise CommandError('Storage reconciliation refused. Check System Admin authorization, exclusive maintenance, private storage and grace period.') from error
        self.stdout.write(('Applied: ' if options['apply'] else 'Dry run: ') + json.dumps(result, sort_keys=True))
