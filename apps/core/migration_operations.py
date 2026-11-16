"""Portable replacements for historical SQLite guard SQL, without rewriting it.

Replacement migrations preserve the exact historical SQLite operations. On a
fresh PostgreSQL installation their fixed trigger predicates are compiled into
PL/pgSQL row guards. No runtime or user supplied SQL enters this compiler.
"""
import importlib
import re
from django.db import migrations

GUARD_MODULES=(
 'testcases.0002_asset_engagement_guards', 'findings.0002_relationship_guards',
 'evidence.0002_integrity_guards', 'evidence.0003_audit_attribution_guards',
 'reports.0002_integrity_guards', 'reports.0003_attribution_retention',
 'evidence.0104_allocation_engagement_guards',
 'reports.0103_report_evidence_guards',
 'audit.0009_seal_history', 'audit.0010_history_identity_guards',
)
PATTERN=re.compile(r'CREATE TRIGGER (\w+) (BEFORE .+?) ON (\w+)\s*(?:WHEN (.*?))?\s*BEGIN SELECT RAISE\(ABORT,\s*\'([^\']+)\'\); END\s*;?', re.S)


def _tables():
    result={}
    for module in GUARD_MODULES:
        cls=importlib.import_module('apps.'+module.split('.')[0]+'.migrations.'+module.split('.')[1]).Migration
        for operation in cls.operations:
            if isinstance(operation,migrations.RunSQL):
                for match in PATTERN.finditer(operation.sql): result[match[1]]=match[3]
    return result


def postgres_statements(sql):
    tables=_tables()
    statements=[]
    remaining=sql.strip()
    while remaining:
        remaining=remaining.lstrip(' \r\n\t;')
        if not remaining: break
        drop=re.match(r'DROP TRIGGER (?:IF EXISTS )?(\w+)\s*;?',remaining)
        if drop:
            name=drop[1]; table=tables[name]
            statements.extend([f'DROP TRIGGER IF EXISTS {name} ON {table}',f'DROP FUNCTION IF EXISTS {name}_guard()'])
            remaining=remaining[drop.end():]; continue
        match=PATTERN.match(remaining)
        if not match: raise ValueError('Unrecognized historical guard SQL.')
        name,timing,table,predicate,message=match.groups()
        predicate=predicate or 'TRUE'
        predicate=predicate.replace('retention_active=1','retention_active=TRUE').replace('NEW.baseline=1','NEW.baseline=TRUE')
        predicate=predicate.replace('(SELECT foreign_keys FROM pragma_foreign_keys)','1')
        predicate=re.sub(r'\bIS NOT (?!NULL\b)', 'IS DISTINCT FROM ', predicate)
        predicate=re.sub(r'\bIS (?!NULL\b|NOT\b|DISTINCT\b)', 'IS NOT DISTINCT FROM ', predicate)
        predicate=predicate.replace("json_extract(NEW.snapshot,'$.version')", "(NEW.snapshot->>'version')::integer")
        predicate=predicate.replace("replace(e.subject_id,'-','')=NEW.entity_id", "replace(e.subject_id,'-','')=replace(NEW.entity_id::text,'-','')")
        returned='OLD' if 'DELETE' in timing else 'NEW'
        statements.append(f"CREATE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(763834901); IF ({predicate}) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{message}'; END IF; RETURN {returned}; END; $$")
        statements.append(f'CREATE TRIGGER {name} {timing} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()')
        remaining=remaining[match.end():]
    return statements


class PortableGuardSQL(migrations.RunSQL):
    def _run_sql(self,schema_editor,sqls):
        if schema_editor.connection.vendor=='postgresql':
            for statement in postgres_statements(sqls): schema_editor.execute(statement,params=None)
        else:
            super()._run_sql(schema_editor,sqls)
