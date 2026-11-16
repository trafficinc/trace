# Architecture

TRACE is a Python 3.13 / Django 5.2 LTS modular monolith: one application serves browser pages and owns the database and private files. SQLite is the default; PostgreSQL is optional. Runtime assets and report rendering work offline.

## Repository structure

| Location | Responsibility |
| --- | --- |
| `config/` | Settings, URLs and WSGI/ASGI entry points |
| `apps/accounts/` | Custom user, authentication, throttling and account administration |
| `apps/engagements/` | Engagements, memberships, central permissions, notes and milestones |
| `apps/assets/` | Engagement inventory |
| `apps/testcases/` | Test procedures, execution, discussion, references and templates |
| `apps/findings/` | Findings, independent review and shared definitions |
| `apps/evidence/` | Private uploads, integrity, quotas and cleanup |
| `apps/reports/` | Report setups, snapshots, rendering and private artifacts |
| `apps/audit/` | Business history, revisions, verification and retention |
| `apps/core/` | Shared HTTP, concurrency, database, logging, dashboard and storage helpers |
| `templates/`, `static/` | Django presentation and local CSS, JavaScript, fonts and vendor assets |
| `report_templates/` | Trusted report source templates |
| `tests/`, `scripts/` | Verification and preparation tooling |
| `storage/` | Private database, evidence, reports and backups; excluded from source control |

Each domain owns its models, forms, views, URLs, migrations and services. Shared helpers belong in core; domain services do not import views.

## Request and mutation flow

Views resolve the authorized engagement, validate forms, call services and render or redirect. Significant mutations follow this sequence:

1. Start a short explicit transaction and acquire the engagement mutation lock.
2. Recheck the actor's current permissions and the engagement's lifecycle state.
3. Resolve child records within that engagement and validate relationships.
4. Compare the submitted integer version and update atomically, incrementing it.
5. Commit the mutation and its audit records together.

`apps/core/concurrency.py` supplies compare-and-swap updates. A stale version returns HTTP 409 with the submitted draft preserved. Manual merging requires explicit review and a separate versioned save; services never refresh a version and retry over another edit. Relationship changes use the owning record's version. See [concurrent editing](concurrent-editing.md).

Password hashing, file streaming, parsing, integrity checks and report rendering happen outside database write locks. File workflows stage work first, recheck authorization at publication and retain enough metadata for safe cleanup after interruption.

## Identity and authorization

`accounts.User` extends Django's `AbstractUser` and is established in the first accounts migration. Use `settings.AUTH_USER_MODEL` or `get_user_model()` for references. Keep existing migration history intact.

An active superuser is a global **System Admin**. Staff status alone grants no application authority. Other users hold Lead, Tester, Reviewer or Viewer memberships per engagement; a person's role can differ between engagements. See [roles and access](engagements.md#roles-and-access).

`engagements.permissions` centralizes access through `visible_engagements`, `has_permission`, `get_engagement` and `get_scoped_object`. Both HTTP endpoints and direct service calls enforce it. Unknown capabilities fail closed. Invisible engagements and foreign child IDs return 404; forbidden actions within a visible engagement return 403. Ownership, assignment, UUIDs and HTMX headers grant no access.

Completed/archived content is read-only. Team access and administrative quota policies remain maintainable. Existing report setups can generate derived exports without changing closed source content. Domain records use protected relationships; the limited operator [purge workflow](engagements.md#protected-deletion-and-administrative-purge) refuses unsupported modules.

## Authentication and audit

Django supplies password hashing, validators, sessions, CSRF protection and safe redirects. Accounts are created by System Admins; initial administrators use `createsuperuser`. There is no public registration or default credential. Disabling an account invalidates existing sessions, including after reactivation. Password changes preserve the current session and invalidate other sessions. The last active System Admin cannot be disabled through the account UI.

Database-backed throttling covers application and Django-admin sign-in: five account attempts and thirty peer-source attempts per fifteen-minute window. Errors remain generic. Source attribution uses the actual peer address; proxy deployments may share a bucket. Operators can clear a selected bucket with `reset_login_throttle --username USERNAME` or `--source PEER_IP`.

Application logs are JSON with allowlisted event IDs and generated request IDs. They exclude request bodies/URLs/headers, credentials, ORM debug output and raw exception text. Audit metadata is separately allowlisted; business history uses explicit redacted schemas. Mutations and their history commit together. [Audit history](audit-history.md) explains access, exports, retention and hash-chain limitations.

## Database and storage

SQLite uses local disk, a ten-second busy timeout and explicit `IMMEDIATE` transactions; `ATOMIC_REQUESTS` is disabled. Enable WAL with `configure_sqlite` while workers are stopped. WAL permits readers alongside one writer. Network and synchronized filesystems are unsupported.

PostgreSQL uses Django's standard backend, engagement row locks and a transaction-scoped application writer advisory lock to preserve mutation ordering. Database constraints and backend guards protect cross-engagement relationships, immutable provenance and audit records, including bulk writes. See [PostgreSQL](postgresql.md) for configuration and validated transfer.

Static assets are public; evidence, report artifacts and backups are private. No public media route exists. POSIX file operations enforce owner-only storage and reject unsafe paths/links. Downloads recheck engagement access and stored hashes. Evidence removal retains a tombstone; cleanup respects active readers. Quotas charge pending uploads and deferred deletions. See [evidence](evidence.md) and [storage controls](storage-controls.md).

Report generation captures one consistent read snapshot, then verifies images and renders outside write transactions. A final transaction rechecks access before publishing immutable revisions. Trusted templates render user content as data. Rendering runs in bounded, credential-free subprocesses; this is resource isolation, not a complete OS sandbox. See [reports](reports.md).

## Presentation and hosting

Django templates, native forms and local Bootstrap/HTMX/Alpine CSP assets provide the UI. Forms work without JavaScript. Private responses disable caching and HTMX history snapshots; polls refresh read-only regions without replacing drafts. See [UI conventions](ui-conventions.md).

Development commands default to development settings; WSGI/ASGI default to production. Production uses Waitress behind a trusted HTTPS proxy with explicit secrets/hosts. No implicit environment-file loader or runtime cloud service is required. See [installation](installation.md).

Backup, restore and transfer use an exclusive maintenance gate with all writers stopped. SQLite backups pair a verified database snapshot with its referenced private files. Restore publishes a new root rather than overwriting live storage. See [operations](operations.md), [development checks](../README.md#development-checks) and [security limitations](../SECURITY.md).
