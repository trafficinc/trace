# Upgrade and rollback

Use the complete [operations procedure](operations.md#updates-rollback-and-recovery), not an in-place dependency update on a running instance.

Prepare pinned wheels/images and verify vendor hashes on a connected preparation machine. Rehearse the release on a separately restored backup. Drain access, stop all writers and create/validate a coordinated database/private-file backup under exclusive maintenance. Preserve the prior code/image, protected configuration, secret and backup.

Install the new release in a new virtualenv or image. With the explicit production environment loaded, run:

```sh
python manage.py migrate --noinput --settings=config.settings.production
python manage.py configure_sqlite --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
python manage.py check --deploy --fail-level WARNING --settings=config.settings.production
python manage.py verify_audit --admin ADMIN_USERNAME --settings=config.settings.production
```

Use `configure_sqlite` only for SQLite, while workers are stopped. Validate loopback readiness, HTTPS login, engagement isolation, evidence integrity and all three report formats before reopening access.

If schema changes have run, rollback means restoring the matching pre-upgrade database **and private files into a new root**, then selecting the prior release/configuration. Do not assume old code supports the new schema. Account for writes accepted after the backup. Never overwrite a live database, discard a named data volume or execute a live engagement purge as a recovery shortcut.

## Configuration compatibility

Use `TRACE_*` environment variables for new configuration. Existing `TDT_*` variables remain supported; explicitly provided `TRACE_*` values take precedence, including empty values that fail production validation. Preserve the existing secret key and storage root when updating.

Keep the SQLite filename `storage/db/tdt.sqlite3` and Compose volume key `tdt-data` to retain existing data. No database migration or file rename is needed for these names. Authentication HMAC namespaces remain stable, and Django app labels and migration history are unchanged. The Python distribution is `trace-redteam`.

The Compose service is `trace`. When updating a deployment that used a different service name, keep the same Compose project name and stop the old service with `docker compose down --remove-orphans` before starting the new release. This preserves named volumes; do not add a volume-removal flag.
