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
