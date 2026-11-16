# Architecture

TRACE is a Python 3.13 / Django 5.2 LTS modular monolith. One application serves pages and manages the database and private files. SQLite is the default; PostgreSQL is optional. Runtime assets and report rendering work offline.

## Code layout

| Location | Purpose |
| --- | --- |
| `config/` | Settings, URLs and application entry points |
| `apps/` | Accounts, engagements, assets, test cases, findings, evidence, reports and audit |
| `apps/core/` | Shared HTTP, database, concurrency, logging and storage helpers |
| `templates/`, `static/` | Pages and local frontend assets |
| `report_templates/` | Trusted report templates |
| `tests/`, `scripts/` | Tests and maintenance tools |
| `storage/` | Private data and backups; excluded from source control |

Each domain owns its models, forms, views, URLs, migrations and services. Views validate input, call services and render responses. Services enforce business rules and never import views.

## Access and changes

`engagements.permissions` controls access in both views and services. An active superuser is a System Admin; other users have a Lead, Tester, Reviewer or Viewer role in each engagement. Ownership and assignment grant no access. Unknown capabilities are denied, and child records are always scoped to the authorized engagement.

Mutating services use short explicit transactions:

1. Lock the engagement and recheck permissions and lifecycle state.
2. Validate records and relationships within that engagement.
3. Compare the submitted integer version, update atomically and increment it.
4. Commit the change and audit records together.

Stale edits return HTTP 409 and preserve the submitted draft. Services never retry over newer edits. Hashing, file processing and rendering run outside write locks.

Completed and archived content is read-only, while team access remains maintainable. Protected relationships prevent deletion; the operator purge workflow rejects unsupported modules.

See [roles and access](engagements.md#roles-and-access), [concurrent editing](concurrent-editing.md) and [protected deletion](engagements.md#protected-deletion-and-administrative-purge).

## Authentication and history

The custom `accounts.User` uses Django authentication, password protection, sessions and CSRF controls. System Admins create accounts; bootstrap uses `createsuperuser`. There is no public registration or default credential. Sign-in is throttled and failures remain generic. Disabling an account invalidates its sessions.

JSON logs use allowlisted event IDs and generated request IDs, excluding sensitive request data and raw exception text. Audit metadata is also allowlisted. See [audit history](audit-history.md).

## Database and private files

SQLite requires local disk, a ten-second busy timeout and explicit `IMMEDIATE` transactions. `ATOMIC_REQUESTS` is disabled. Enable WAL with `configure_sqlite` while workers are stopped. PostgreSQL uses row and advisory locks. Database guards protect relationships and audit integrity, including bulk writes. See [PostgreSQL](postgresql.md).

Private files have no public media route. Downloads recheck access and integrity; uploads and rendering stage work outside locks and recheck access before publication. Reports use consistent snapshots and immutable revisions. See [evidence](evidence.md), [storage controls](storage-controls.md) and [reports](reports.md).

## UI and operations

Django templates and local Bootstrap, HTMX and Alpine CSP assets provide the UI. Forms work without JavaScript. Private responses disable caching and HTMX history snapshots; polling preserves unsaved drafts. See [UI conventions](ui-conventions.md).

Management commands default to development settings; WSGI/ASGI default to production. Production uses Waitress behind a trusted HTTPS proxy with explicit secrets and hosts. No implicit environment-file loader is installed. See [installation](installation.md).

Backup, restore and transfer require exclusive maintenance access with writers stopped. Backups include the database and referenced private files; restores use a new storage root. See [operations](operations.md), [development checks](../README.md#development-checks) and [security limitations](../SECURITY.md).
