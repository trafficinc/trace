"""Exclusive, validated Django logical transfer into an EMPTY PostgreSQL database."""
import json
import os
from pathlib import Path
from itertools import chain
from datetime import datetime
from django.core.serializers.json import DjangoJSONEncoder
from django.apps import apps
from django.core import serializers
from django.core.management import call_command
from django.core.management.color import no_style
from django.db import connection, transaction
from apps.audit.maintenance import _verify
from apps.audit.models import AuditChainState
from apps.engagements.permissions import require_system_admin
from .backups import safe_directory, file_digest, BackupError
from .maintenance import exclusive_maintenance
from .database import mutation_lock

EXCLUDED={'contenttypes.contenttype','auth.permission','sessions.session','admin.logentry'}


class FullPrecisionJSONEncoder(DjangoJSONEncoder):
    def default(self,value):
        # Django's default encoder truncates milliseconds; audit commitments
        # require all six microsecond digits during supported logical transfer.
        if isinstance(value,datetime): return value.isoformat()
        return super().default(value)


def transfer_models():
    return [model for model in apps.get_models() if model._meta.label_lower not in EXCLUDED]


def export_database(*,actor,output,maintenance=False):
    require_system_admin(actor)
    output=Path(output).absolute()
    safe_directory(output.parent)
    if output.exists() or output.is_symlink() or output.with_suffix(output.suffix+'.manifest.json').exists(): raise BackupError('Transfer output already exists.')
    with exclusive_maintenance(maintenance):
        require_system_admin(actor)
        checkpoint=_verify('default')
        models=transfer_models()
        counts={model._meta.label_lower:model.objects.count() for model in models}
        descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(descriptor,'w') as file:
                serializers.serialize('json',chain.from_iterable(model.objects.order_by('pk').iterator() for model in models),
                                      stream=file,cls=FullPrecisionJSONEncoder,use_natural_foreign_keys=True,use_natural_primary_keys=False)
                file.flush(); os.fsync(file.fileno())
            manifest={'schema':1,'file':file_digest(output),'counts':counts,'audit':checkpoint}
            manifest_path=output.with_suffix(output.suffix+'.manifest.json')
            with open(manifest_path,'x') as file:
                os.chmod(manifest_path,0o600); json.dump(manifest,file,sort_keys=True); file.flush(); os.fsync(file.fileno())
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return manifest


def _validate_relationships():
    # Fixed identifiers from reviewed domain models, never submitted SQL.
    joins=[('testcases_testcaseasset','test_case_id','testcases_testcase','asset_id','assets_asset'),
           ('findings_findingasset','finding_id','findings_finding','asset_id','assets_asset'),
           ('findings_findingtestcase','finding_id','findings_finding','test_case_id','testcases_testcase'),
           ('evidence_evidencetestcase','evidence_id','evidence_evidence','test_case_id','testcases_testcase'),
           ('evidence_evidencefinding','evidence_id','evidence_evidence','finding_id','findings_finding'),
           ('reports_reportfinding','report_id','reports_report','finding_id','findings_finding')]
    with connection.cursor() as cursor:
        for table,left,left_table,right,right_table in joins:
            cursor.execute(f'SELECT 1 FROM {table} l JOIN {left_table} a ON a.id=l.{left} JOIN {right_table} b ON b.id=l.{right} WHERE a.engagement_id<>b.engagement_id LIMIT 1')  # nosec B608
            if cursor.fetchone(): raise BackupError('A transferred relationship crosses engagement boundaries.')
        for table,column,parent in [('reports_report','logo_id','evidence_evidence'),('reports_reportrevision','report_id','reports_report'),('reports_reportartifact','revision_id','reports_reportrevision'),('evidence_evidenceallocation','evidence_id','evidence_evidence')]:
            cursor.execute(f'SELECT 1 FROM {table} a JOIN {parent} b ON b.id=a.{column} WHERE a.engagement_id<>b.engagement_id LIMIT 1')  # nosec B608
            if cursor.fetchone(): raise BackupError('A transferred report crosses engagement boundaries.')


def import_postgres(*,source,maintenance=False):
    if connection.vendor!='postgresql': raise BackupError('Logical import is only supported into an empty PostgreSQL database.')
    source=Path(source).absolute(); safe_directory(source.parent)
    manifest=json.loads(source.with_suffix(source.suffix+'.manifest.json').read_text())
    if manifest.get('schema')!=1 or file_digest(source)!=manifest.get('file'): raise BackupError('Logical transfer integrity check failed.')
    models=transfer_models()
    if set(manifest.get('counts',{}))!={model._meta.label_lower for model in models}: raise BackupError('Transfer schema does not match this application release.')
    with exclusive_maintenance(maintenance),transaction.atomic():
        mutation_lock()
        for model in models:
            if model is AuditChainState: continue
            if model.objects.exists(): raise BackupError('Destination database must contain no application, user or group data.')
        if AuditChainState.objects.exclude(head_sequence=0).exists(): raise BackupError('Destination audit state is not empty.')
        # The trusted OS/database owner invokes Django's supported deserializer.
        # User triggers are restored before commit; any failure rolls it all back.
        with connection.cursor() as cursor:
            for model in models:
                cursor.execute(f'ALTER TABLE {connection.ops.quote_name(model._meta.db_table)} DISABLE TRIGGER USER')
            AuditChainState.objects.all().delete()
        call_command('loaddata',str(source),verbosity=0)
        connection.check_constraints()
        _validate_relationships()
        if _verify('default')!=manifest['audit']: raise BackupError('Transferred audit chain does not match its checkpoint.')
        for model in models:
            if model.objects.count()!=manifest['counts'][model._meta.label_lower]: raise BackupError('Transferred row counts do not match.')
        with connection.cursor() as cursor:
            for statement in connection.ops.sequence_reset_sql(no_style(),models): cursor.execute(statement)
            for model in models:
                cursor.execute(f'ALTER TABLE {connection.ops.quote_name(model._meta.db_table)} ENABLE TRIGGER USER')
    return manifest
