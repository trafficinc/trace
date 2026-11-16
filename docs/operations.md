# Operations, backup and recovery

Run server commands as the unprivileged service owner with `umask 077` and the protected production environment loaded; see [installation](installation.md). Select production settings explicitly. Keep the database/private files on local disk outside static paths and container layers.

## Maintenance and readiness

Stop **all** workers, developer servers, upload/report/cleanup jobs and administrative writers before maintenance. Keep the proxy closed until validation completes. Backup/restore/transfer require the exclusive `.maintenance.lock`; `--maintenance` acknowledges this obligation but does not stop processes. Third-party writers that ignore the gate remain the operator's responsibility.

For systemd:

```sh
sudo systemctl stop trace
# Perform maintenance as trace with the protected environment loaded.
sudo systemctl start trace
sudo systemctl restart trace
sudo systemctl status trace
sudo journalctl -u trace --since '15 minutes ago'
```

For Compose, use `docker compose --env-file PRIVATE_ENV stop trace`, then `start trace` afterward. Maintenance commands use `docker compose --env-file PRIVATE_ENV run --rm trace python manage.py ...` against the same volume. Never delete its data volume to fix startup.

`GET /health/` returns `{"status":"ok"}` or a generic database-unavailable 503. It checks connectivity, not the entire application or migration state. Set `TRACE_HEALTH_HOST` to an allowed host for the local image probe. Application data still requires HTTPS.

Logs use JSON, controlled event IDs and generated request IDs. Configure journald/Docker rotation and a separate nginx privacy/rotation policy. Avoid sensitive query strings and Django SQL debug logs. See [audit history](audit-history.md) for business records.

## Consistent SQLite backups

Create a mode-0700 backup parent. Stop writers, then capture and validate with an active System Admin's attribution:

```sh
python manage.py backup_tdt --admin ADMIN_USERNAME --maintenance --output /private/backups/BACKUP_NAME --settings=config.settings.production
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --validate-only --settings=config.settings.production
```

The command pairs a consistent SQLite snapshot with referenced live evidence, thumbnails and report artifacts. It verifies database/foreign-key/audit integrity and file hashes/sizes, preserves private modes and never overwrites output. Tombstoned/orphaned bytes are excluded. Never manually copy a live SQLite database/WAL as a backup.

Backups contain sensitive documentation, password hashes, sessions and private files. Encrypt/restrict them and retain multiple generations. Keep a separately trusted manifest/checkpoint; hashes are not signatures. Protect the matching source/image, secret/configuration and CA material separately. Rehearse recovery periodically. For PostgreSQL, use the [coordinated database/file procedure](postgresql.md#postgresql-backups).

## Restore without overwriting a live installation

Use the matching source/image first. Stop writers and preserve the current installation if readable. Validate, then restore to a **new, nonexistent** destination under an owner-only parent:

```sh
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --validate-only --settings=config.settings.production
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --maintenance --destination /var/lib/trace-recovery/restored --settings=config.settings.production
```

Restore checks paths, permissions, file inventory/hashes, database integrity, migrations and audit checkpoints before publishing a new root. It never replaces existing storage. It is an OS-operator operation that can recover a damaged database without authenticating against it.

Point `TRACE_STORAGE_ROOT` at the new root, retain the matching secret/configuration and reload the environment. Update systemd `ReadWritePaths` for the new location and run `sudo systemctl daemon-reload` if needed. While workers remain stopped:

```sh
python manage.py check --deploy --fail-level WARNING --settings=config.settings.production
python manage.py showmigrations --plan --settings=config.settings.production
# Back up the restored copy before applying a newer release's schema changes.
python manage.py migrate --noinput --settings=config.settings.production
python manage.py configure_sqlite --settings=config.settings.production
python manage.py verify_audit --admin ADMIN_USERNAME --settings=config.settings.production
```

Start in restricted access, check accounts/engagement isolation, evidence integrity/downloads and report generation, then reopen the proxy. Never place old database bytes beneath running workers or run two writable instances against the same files. Restore does not securely erase discarded storage.

For Compose, preserve the named volume. With workers stopped, restore beneath a new private parent:

```sh
docker compose --env-file PRIVATE_ENV run --rm trace python -c "from pathlib import Path; Path('/storage/recovery').mkdir(mode=0o700, exist_ok=True)"
docker compose --env-file PRIVATE_ENV run --rm trace python manage.py restore_tdt --source /storage/backups/BACKUP_NAME --maintenance --destination /storage/recovery/restored --settings=config.settings.production
```

Set `TRACE_CONTAINER_STORAGE_ROOT=/storage/recovery/restored` in the protected environment. Run the checks above through `compose run`, then apply the environment with `docker compose --env-file PRIVATE_ENV up -d --no-build --force-recreate`. Preserve the original root and secret for rollback.

## Updates, rollback and recovery

Follow [upgrading](upgrading.md) for the release procedure. After schema changes, rollback requires the matching pre-update database and private files restored into a new root; old code may not support the new schema.

## Storage accounting maintenance

Inspect evidence accounting after restore: omitted orphan/tombstone bytes can leave conservative charges. Apply [reconciliation](storage-controls.md#operator-reconciliation) only with all writers stopped. Reports/backups need independent retention and host-level capacity controls.
