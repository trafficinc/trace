# Upgrade and rollback

## Update

1. Prepare a reviewed release with matching pinned wheels/native dependencies, verified vendor assets and any container images. Rehearse on an isolated restored backup. Preserve the prior release, protected configuration and secret.
2. Enter [maintenance](operations.md#maintenance-and-readiness), stop all writers and create/validate a coordinated database/private-file backup.
3. Install into a new virtualenv/image rather than updating the running release. Load its protected production environment, then run:

```sh
python manage.py migrate --noinput --settings=config.settings.production
python manage.py configure_sqlite --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
python manage.py check --deploy --fail-level WARNING --settings=config.settings.production
python manage.py verify_audit --admin ADMIN_USERNAME --settings=config.settings.production
```

Use `configure_sqlite` only for SQLite, with workers stopped. Start on loopback and validate readiness, HTTPS login, engagement isolation, evidence integrity and all three report formats before reopening access. Keep the old release/backup through the recovery window.

## Rollback

Before schema changes, return to the untouched prior release if compatible. After schema changes, restore the matching pre-update database **and private files into a new root**, select the prior release/configuration and revalidate. See [restore](operations.md#restore-without-overwriting-a-live-installation).

Old code may not support a new schema. Reverse migrations require a rehearsed data-preserving plan. Reverting to a backup loses later writes unless separately reconciled. Never overwrite a live database, remove a named data volume or purge engagements as a recovery shortcut.

## Configuration compatibility

Use `TRACE_*` environment variables for new configuration. Existing `TDT_*` variables remain supported; explicitly provided `TRACE_*` values take precedence, including empty values that fail production validation. Preserve the existing secret key and storage root when updating.

Keep the SQLite filename `storage/db/tdt.sqlite3` and Compose volume key `tdt-data` to retain existing data. No database migration or file rename is needed for these names. Authentication HMAC namespaces remain stable, and Django app labels and migration history are unchanged. The Python distribution is `trace-redteam`.

The Compose service is `trace`. When updating a deployment that used a different service name, keep the same Compose project name and stop the old service with `docker compose down --remove-orphans` before starting the new release. This preserves named volumes; do not add a volume-removal flag.
