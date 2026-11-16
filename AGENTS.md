# TRACE project conventions

## Scope and ownership

TRACE is a Python 3.13 / Django 5.2 LTS modular monolith. Inspect existing code before editing. Keep each domain's models, forms, views, URLs, migrations and services in its own `apps/` package. Current scope is foundation, accounts, engagement access control and engagement management (lifecycle, notes and milestones). Asset inventory and structured test cases are implemented. Findings, evidence and reports remain scaffolds until explicitly requested.

Use Django ORM and built-ins. Do not introduce React, Node tooling, Redis, Celery, runtime network services, CDNs or generic repository/service frameworks. Keep straightforward CRUD simple. Put significant operations in service functions with authorization and short explicit transactions. Views parse/validate input, call services and render/redirect; services must not import views. Shared HTTP/error helpers belong in core.

## Security

Use `settings.AUTH_USER_MODEL` / `get_user_model()`, never Django's concrete auth.User. Preserve accounts' first custom-user migration. Do not rewrite applied migrations or reset existing data. Use Django-supported password hashing and validators; never store/log plaintext or reversible passwords. Never create default credentials. Bootstrap administrators with `createsuperuser`.

All domain access uses engagements.permissions. Scope child objects through the authorized engagement. UI controls, UUIDs and HTMX headers are not authorization. System Admin is an active superuser, not a Lead or staff account. Mutating engagement/membership/note/milestone services acquire the engagement lock and recheck permissions and lifecycle state; future file/report/domain services must use the same policy. Unknown capabilities fail closed. Keep cross-engagement tests.

Use integer compare-and-swap versions for mutable records. Never automatically overwrite a newer record, retry with a fresh version, or replace unsaved edit inputs with polling. Commit audit records with mutations. Failed/disabled/throttled authentication must remain generic. Audit metadata is allowlisted; never include passwords, hashes, tokens, raw requests or unrestricted submitted strings.

Keep private storage outside static files. There is no public media route. Package actual vendor files and licenses locally; do not imitate missing libraries. Keep CSP-compatible scripts in static/js and styles in static/css. Never add an internet requirement to runtime.

## Settings and database

manage.py defaults to development; production WSGI/ASGI default to production. Explicitly select production settings for deployment checks and operations. Secrets and hosts come from environment variables. Keep development secrets out of production. No implicit .env loader is installed.

SQLite must use local disk, a busy timeout and explicit short transactions. Do not enable ATOMIC_REQUESTS. Enable WAL with configure_sqlite while workers are stopped, not on request/connection creation. Keep hashing, network/file operations and report generation outside database locks. SQLite remains the default. Optional PostgreSQL uses Django's standard backend, explicit row locks and portable database guards; keep equivalent authorization/CAS/integrity behavior.

## Logging and verification

Application logs are JSON with explicit event IDs. Add intended IDs to core.logging.EVENTS. Never log request bodies/URLs/headers, authentication material, exception messages or ORM debug output. Use generated request IDs; never trust a client ID as a log field.

Work on the user's requested local-development or server task. For meaningful application changes run:

- `python manage.py migrate --noinput`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py check`
- `python -m pytest`
- `python scripts/vendor_assets.py --check` for release assets

Run `python manage.py check --deploy --settings=config.settings.production` with real deployment configuration only when the user explicitly requests production deployment work. Documentation-only changes need focused documentation checks.

Test authorization both through HTTP/HTMX and direct service calls, with all roles and foreign engagement IDs. Use real file-backed SQLite for concurrency tests. Use fixtures without usable passwords for role-only tests; keep Django's strong password hashers for authentication tests. Never point tests at production.

Report changes made, relevant checks actually performed and blockers affecting the requested task. Never claim an unrun check passed. Do not append unrelated deployment, browser or container status disclaimers to development summaries or documentation. If dependencies or Python are unavailable, finish independent work and document the relevant blocker. Update README/architecture when behavior or installation changes. Keep runtime data and secrets out of source control.

## Engagement conventions

Use EngagementStatus for the fixed lifecycle. Completed/archived content is read-only, while team access remains maintainable. Notes are author-managed unless Lead/Admin; milestones and lifecycle are Lead/Admin-managed. Preserve integer versions on every mutable record and keep parent locks to coordinate mutations with closure. Report progress from actual milestones, never fabricated test/finding counts. Render supplied handling markings without assuming a default classification.

Use PROTECT for engagement-owned records. Never add a web hard-delete endpoint. The operator purge workflow only supports archived engagements with exact UUID, version, reason and System Admin attribution. Preserve audit engagement_ref values after purges; new module records must block purge until a reviewed retention path supports them. Do not execute a live purge while developing/testing.

Use scoped, Vary-aware HTMX fragments and keep ordinary forms working. Disable HTMX local history snapshots for private content. Failed bound forms must preserve drafts and show saved handling markings. The UI references mission-list.png and tests-list.png establish the table-first mission/work-list interaction; they guide the engagement/test-case tables and do not authorize building findings/evidence/report features.

## Assets and test cases

Use MANAGE_ASSETS / WRITE_TESTS for Lead/Tester content writes and WRITE_TEST_NOTES for Lead/Tester/Reviewer discussion. Global templates are System Admin-curated and shared with authenticated users. Never copy engagement results, assignments or assets into a shared template. Template-based creation is a versioned snapshot; existing cases must not change when a template is edited or retired.

Owners must be active engagement members; assignees must be active Leads/Testers in that engagement. Neither relationship grants permissions. Asset links must match the case engagement. Preserve explicit TestCaseAsset validation and SQLite INSERT/UPDATE/parent-update triggers, including for bulk writes. Common filters have engagement-first database indexes.

All mutations run in short explicit transactions (IMMEDIATE on SQLite, explicit row locks on PostgreSQL) and recheck parent read-only state. Keep test transitions in the service layer; passed/failed results require actual_result. Reopening clears completion while retaining first start/prior result. Plain text preserves indentation/newlines through strip=False forms and pre-wrap rendering; do not mark arbitrary text safe. References permit HTTP/HTTPS or plain local citations and never fetch resources. Do not extend the engagement purge to assets/testcases without a reviewed retention workflow.
