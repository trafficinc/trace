# Supported replacement: retain applied history and preserve SQLite SQL verbatim.
from importlib import import_module
from django.db import migrations
from apps.core.migration_operations import PortableGuardSQL

Historical = import_module('apps.audit.migrations.0009_seal_history').Migration


class Migration(migrations.Migration):
    replaces = [('audit', '0009_seal_history')]
    dependencies = Historical.dependencies
    operations = [PortableGuardSQL(op.sql, op.reverse_sql, state_operations=op.state_operations, hints=op.hints, elidable=op.elidable)
                  if isinstance(op, migrations.RunSQL) else op for op in Historical.operations]
