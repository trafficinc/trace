# Supported replacement: retain applied history and preserve SQLite SQL verbatim.
from importlib import import_module
from django.db import migrations
from apps.core.migration_operations import PortableGuardSQL

Historical = import_module('apps.findings.migrations.0002_relationship_guards').Migration


class Migration(migrations.Migration):
    replaces = [('findings', '0002_relationship_guards')]
    dependencies = Historical.dependencies
    operations = [PortableGuardSQL(op.sql, op.reverse_sql, state_operations=op.state_operations, hints=op.hints, elidable=op.elidable)
                  if isinstance(op, migrations.RunSQL) else op for op in Historical.operations]
