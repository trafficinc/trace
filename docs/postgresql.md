# PostgreSQL

SQLite is the default. Optional PostgreSQL uses Django's standard backend and Psycopg 3; PostgreSQL 17 is covered by the integration scenario. Private evidence/reports remain on the application host's POSIX local disk.

## Configuration

Install `requirements/postgres.txt`; for offline preparation, include `--postgres`. Use a dedicated database owner/application role rather than a database superuser:

```sh
createuser --pwprompt trace
createdb --owner=trace trace
```

Set these in the protected service environment:

```text
TRACE_DB_ENGINE=postgresql
TRACE_DB_NAME=trace
TRACE_DB_USER=trace
TRACE_DB_PASSWORD=<privately supplied value>
TRACE_DB_HOST=127.0.0.1
TRACE_DB_PORT=5432
TRACE_DB_SSLMODE=prefer
```

For remote databases use `verify-full`, a trusted certificate/CA configuration such as `PGSSLROOTCERT`, and a private network/firewall policy. `prefer` does not guarantee verified TLS. Keep passwords out of shell history and source control.

Fresh installations use normal production migration/static/admin setup; skip `configure_sqlite`. For Docker, build with `TRACE_WITH_POSTGRES=1` and pass database settings through the protected environment. Default Compose does not start PostgreSQL.

## Integrity and concurrency parity

Supported replacement migrations preserve applied history while installing backend-specific integrity guards. Both databases enforce engagement relationships, immutable provenance and audit/revision protection. Versioned mutations retain application-writer ordering; PostgreSQL adds engagement row locks. Read snapshots use repeatable-read/read-only transactions. See [architecture](architecture.md#database-and-storage).

## SQLite → PostgreSQL transfer

Use the **same reviewed release** on both ends and an **empty** destination. This is an exclusive offline transfer.

1. Rehearse on an isolated restore. Stop all writers and create/validate a [coordinated backup](operations.md#consistent-sqlite-backups). Preserve the source release and secret.
2. With the source SQLite configuration selected, export:

```sh
python manage.py export_database --admin ADMIN_USERNAME --maintenance --output /private/transfer/trace.json --settings=config.settings.production
```

Use an owner-only parent and a new output. The sensitive export includes users/password hashes and a companion manifest with hashes, counts and audit checkpoint. Sessions/admin logs are omitted; permissions are regenerated. Preserve the secret and full-precision serialized timestamps. Manifests must come from a trusted operator; hashes are not signatures.

3. Select the empty PostgreSQL database and a **separate private storage root**, then run:

```sh
python manage.py migrate --noinput --settings=config.settings.production
python manage.py import_postgres --source /private/transfer/trace.json --maintenance --settings=config.settings.production
```

Import refuses nonempty destinations, validates the manifest/schema inventory and loads transactionally. It temporarily disables user triggers as table owner, then checks relationships, counts and audit continuity, resets sequences and restores triggers before commit. Failure rolls back. Never bypass checks with `--fake` or reseal altered history.

4. Restore/copy matching evidence/reports from the coordinated backup into the new root, retaining `0700` directories/`0600` files. `restore_tdt` can prepare the root before PostgreSQL is selected; keep its SQLite file for rollback. Never share private files between two writable instances.
5. Run deployment checks and `verify_audit` with production settings. Validate account access, roles, evidence integrity, report generation and new-record creation before reopening the proxy.
6. Retain the stopped SQLite source and backup. Rollback after PostgreSQL accepts writes requires a reviewed reconciliation plan; there is no automatic reverse merge.

## PostgreSQL backups

`backup_tdt` is SQLite-only. Stop writers, take `pg_dump --format=custom` and copy matching private files/hash inventory from the same stopped instance. Restore into a new database/root, verify relationships/audit/file hashes and revalidate access before switching. Protect credentials with libpq's private password/service files, not command arguments. A database dump alone cannot recover evidence.

## Integration verification

Install `requirements/postgres.txt` alongside test dependencies. Set `TRACE_TEST_PG_DSN` privately to a dedicated disposable server with database-creation privileges, then run:

```sh
python -m pytest tests/test_postgres.py -v
```

The helper creates/drops a UUID-named database and checks migration, transfer, concurrency and integrity guards. Never supply an application/production server connection. See the [development checks](../README.md#development-checks) for the standard suite.
