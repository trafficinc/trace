# Operations, backup and recovery

Use the same explicit production environment for all server commands; see [installation](installation.md). Run as the unprivileged service owner with `umask 077`. Keep SQLite and private files on local disk, outside public static paths and container layers. Never copy a live SQLite file/WAL manually as a backup.

## Maintenance and readiness

The supported WSGI/ASGI entry points hold a shared `.maintenance.lock` for their process lifetime. Backup, restore and database transfer take it exclusively and refuse to run while those workers remain active. Stop **all** workers, developer servers, upload/cleanup/report jobs and other administrative writers first. `--maintenance` acknowledges that operator obligation; it does not stop processes for you. Raw SQL and third-party processes that ignore the gate remain an operator responsibility. Keep the proxy in a maintenance state until validation is complete.

```sh
sudo systemctl stop trace
# Run maintenance commands as trace with the production environment loaded.
sudo systemctl start trace
sudo systemctl restart trace
sudo systemctl status trace
sudo journalctl -u trace --since '15 minutes ago'
```

For Compose, use `docker compose --env-file PRIVATE_ENV stop trace` before maintenance and `start trace` afterward. Commands run through `compose run --rm trace python manage.py ...` use the same volume. Restart with `docker compose --env-file PRIVATE_ENV restart trace`; never delete its data volume to fix a startup error.

`GET /health/` returns only `{"status":"ok"}` or a generic database-unavailable 503. It performs a real query, exposes no versions/paths/entities and is not cached. HTTPS is still required for all application data. The image health check calls this endpoint locally; set `TRACE_HEALTH_HOST` to one of the explicit allowed hosts. No default administrator or test data is created by readiness/startup.

Application logs are JSON with generated request IDs and controlled event identifiers; request bodies, URLs, passwords and raw exception messages are excluded. Limit journald retention (`SystemMaxUse`, `MaxRetentionSec`) to your host policy. For Docker, configure the daemon's `local` logging driver or `json-file` `max-size`/`max-file` limits and verify rotation. nginx access logs need a separate privacy policy: avoid logging sensitive query strings, use restrictive ownership and distribution logrotate rules. Do not enable Django SQL debug logs. Logs are not a replacement for the private audit history.

## Consistent SQLite backups

Create a mode-0700 backup parent outside static storage. Stop writers and use an active System Admin's username for attribution:

```sh
python manage.py backup_tdt --admin ADMIN_USERNAME --maintenance --output /private/backups/BACKUP_NAME
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --validate-only
```

`backup_tdt` uses Python's SQLite backup API, validates database consistency/foreign keys and audit continuity, then copies only committed live evidence/thumbnail and report artifact references from that exact snapshot. It checks each file against its stored SHA-256 and size, preserving owner-only modes. Tombstoned/orphaned bytes are excluded. A database snapshot is a standalone SQLite file, not a WAL sidecar copy. The private manifest records every included path, byte count, SHA-256, migration set, audit checkpoint, time and operator ID. Interrupted or failed backups remove unpublished staging directories. An existing output is never overwritten.

Backups include sensitive documentation, account password hashes, sessions, evidence bytes and report snapshots. Encrypt backups at rest/in transit using your approved storage tooling, restrict access and keep a separately trusted manifest/checkpoint. The manifest is an integrity inventory, **not a signature or proof against a privileged administrator who can replace both data and hashes**. Store configuration/secret keys, CA material and the exact source/image release separately under the same operational protection. `backup_tdt` does not put those secrets into its manifest or messages. A matching secret key is needed to preserve encrypted/signature-derived application behavior; lost keys and restored sessions require a deliberate incident/recovery policy.

Schedule backups during a documented maintenance window and periodically rehearse restore on an isolated test instance. Retain multiple generations according to your policy; do not clean historical backups merely because the newest directory exists. PostgreSQL needs `pg_dump`/server backups coordinated with the same file maintenance window; this SQLite-specific command refuses a PostgreSQL connection.

## Restore without overwriting a live installation

Use the matching source/image release first. Stop all writers and keep a safety backup of the current installation if it is readable. Run validation before publishing anything:

```sh
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --validate-only
python manage.py restore_tdt --source /private/backups/BACKUP_NAME --maintenance --destination /var/lib/trace-recovery/restored
```

The destination must **not exist** and its parent must be owner-only and writable by the operator. For example, use a protected `/var/lib/trace-recovery` parent owned by the service account, then restore into `/var/lib/trace-recovery/restored` rather than changing `/var/lib` permissions. Restore is an OS-operator command, not a web endpoint; it can recover a damaged database without relying on accounts inside that damaged database. It still requires the exclusive maintenance gate of the configured instance.

Restore rejects traversal paths, symlinks, linked files, unexpected/missing files, hash/size errors, corrupt SQLite, broken foreign keys, mismatched file references/migrations and broken audit checkpoints. It copies into a private staging directory and publishes a new storage root only after verification. It never replaces an existing root. This protects the original installation for rollback.

After restoring, point `TRACE_STORAGE_ROOT` at the new root, preserve the correct secret/configuration, reload that environment in the maintenance shell, and validate before admitting users. With the supplied systemd hardening, update `ReadWritePaths` to permit the new root and run `sudo systemctl daemon-reload` before starting the service. Other storage paths must likewise be reflected in the service sandbox:


```sh
python manage.py check --deploy --fail-level WARNING --settings=config.settings.production
python manage.py showmigrations --plan --settings=config.settings.production
# With a newer reviewed release, back up the restored copy before schema changes.
python manage.py migrate --noinput --settings=config.settings.production
python manage.py configure_sqlite --settings=config.settings.production
python manage.py verify_audit --admin ADMIN_USERNAME --settings=config.settings.production
```

Check account access, cross-engagement isolation, evidence downloads/integrity and report generation on the restored instance, then start workers and reopen the proxy. Do not restore old database bytes beneath running workers or keep two writable instances using the same private files. The command restores logical contents and owner-only permissions; it does not implement secure erasure of discarded disks, SQLite pages, snapshots or backup media.

For Compose recovery, keep the original named volume. With the service stopped, create an owner-only recovery parent inside it and restore into a new child:

```sh
docker compose --env-file PRIVATE_ENV run --rm trace python -c "from pathlib import Path; Path('/storage/recovery').mkdir(mode=0o700, exist_ok=True)"
docker compose --env-file PRIVATE_ENV run --rm trace python manage.py restore_tdt --source /storage/backups/BACKUP_NAME --maintenance --destination /storage/recovery/restored
```

Set `TRACE_CONTAINER_STORAGE_ROOT=/storage/recovery/restored` in the protected Compose environment file, run the migration/deployment/audit checks with `compose run`, then apply the new environment with `docker compose --env-file PRIVATE_ENV up -d --no-build --force-recreate`. The volume still mounts at `/storage`; the recovered instance uses its new child root. Preserve the original snapshot and secret for rollback. Do not remove the volume or overwrite the old database in place.

## Updates, rollback and recovery

1. Prepare a reviewed release with pinned wheels, vendor hashes, native dependencies and (if used) a tested container image. Preserve the old release/image and protected configuration. Read migration notes and test on an isolated restored backup.
2. Enter maintenance, drain the proxy, stop all writers and create/validate a fresh coordinated backup.
3. Build a new virtualenv for the new release with its pinned requirements, or load/build the new image. Never update packages inside the running release.
4. Apply migrations with the new code, collect static files, run deployment checks and verify the audit chain. Start the new release on loopback and check readiness, authentication, evidence and reports before reopening access.
5. If validation fails **before migrations**, switch back to the untouched release. After schema changes, do not assume old code can read the new schema. Restore the pre-update database **and matching private files** into a new root, select the prior release and revalidate. Reverse migrations only after an explicitly rehearsed, data-preserving rollback plan.
6. Keep both backup and old release until the recovery window closes. Changes accepted after the backup are not magically included in rollback; reconcile them under a documented incident plan.

SQLite WAL supports concurrent readers but one writer at a time. Keep transactions short, use local storage and the configured busy timeout, and perform large exports/file processing outside write transactions. Optional PostgreSQL retains a transaction-scoped application writer advisory lock to preserve the same lifecycle/authentication/audit ordering, plus engagement row locks. It supports the standard backend and operational tooling; it is not advertised as eliminating every write-contention limit.

## Storage accounting maintenance

See [storage controls](storage-controls.md) for evidence quotas, disk-space warnings and the dry-run-first `reconcile_evidence_storage` command. Apply reconciliation only under exclusive maintenance. After restoring a backup, inspect the recovered copy's accounting before applying cleanup: omitted orphan/tombstone files can leave conservative charges. Reports/backups have independent retention and still need host-level capacity limits.
