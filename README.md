<p align="center">
  <img src="docs/assets/trace-banner.svg" width="1120" alt="TRACE — private security-testing documentation for local or server use">
</p>

<h1 align="center">Test Records, Assessment &amp; Collaborative Evidence</h1>

<p align="center">
  <strong>Security testing. Clearly documented.</strong><br>
  Run locally or on your own server.
</p>

<p align="center">
  <img src="docs/assets/badge-python.svg" width="120" height="30" alt="Python 3.13">
  <img src="docs/assets/badge-django.svg" width="148" height="30" alt="Django 5.2 LTS">
  <img src="docs/assets/badge-sqlite.svg" width="148" height="30" alt="SQLite database">
  <img src="docs/assets/badge-self-hosted.svg" width="164" height="30" alt="Self-hosted">
</p>

<p align="center">
  <a href="#development-startup">Get started</a> ·
  <a href="#current-implementation">Features</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="docs/evidence.md">Evidence</a> ·
  <a href="docs/concurrent-editing.md">Concurrent editing</a>
</p>

---

TRACE is an open-source, self-hosted penetration testing documentation platform inspired by the workflow of Lockheed Martin DART. It uses Python 3.13 and Django 5.2 LTS as a modular monolith. Run it on your own machine or on a server; each installation keeps its database and private files on local disk, and users connect through browsers.

The current phase provides secure accounts, engagement-scoped access control and engagement management: a searchable mission-style list, scoped overview, lifecycle, notes, milestones and team administration. Asset inventory and structured test cases are implemented, including assignment, status workflows, local templates, notes, references and progress. Findings now provide the primary tester documentation workflow, with independent review and reusable templates. Private evidence uploads, scoped associations, authenticated downloads, integrity verification and removal are implemented. Reusable, versioned reports produce editable DOCX, PDF and self-contained HTML from consistent snapshots. Report setups can select additional engagement evidence directly, including screenshots without a related finding; enable **Include images**, save and generate a new revision to embed them.

## Current implementation

- Custom `accounts.User` established in its first migration; no public registration or default credentials.
- System Admin-created users, login/logout, account profile and password changes, account activation/deactivation.
- Strong Django PBKDF2 password hashing, with Django scrypt support. No plaintext or reversible password storage.
- Engagement-specific Lead, Tester, Reviewer and Viewer memberships; active superusers are separate global System Admins.
- Central authorization helpers, scoped object lookup, atomic version checks, side-by-side conflict review and explicit manual merging.
- Optional expiring editor presence and scoped HTMX status/dashboard refreshes that preserve unsaved forms.
- Engagement client/context/scope/dates/handling markings, planned → active/paused → completed → archived lifecycle, notes, milestones and measured milestone progress.
- Protected deletion with a separate, explicitly confirmed operator purge for archived engagement-only records. Engagements containing assets, test cases, findings or evidence remain protected from this purge.
- Engagement asset inventory and structured test cases with validated local relationships, scoped assignments, reusable procedure templates and category/status progress.
- Engagement findings with safe narrative formatting, severity/status/search/sorting, related assets/tests, versioned edits, independent approval and shared template snapshots.
- Private evidence files with SHA-256 provenance, safe thumbnails, attachment downloads, versioned metadata and retryable cleanup.
- Shared database-backed login throttling for application and Django-admin sign-in, including malformed forms.
- Audit records for login success/failure, logout, account changes and membership operations. Passwords, session tokens and raw submitted usernames are excluded from authentication events.
- Responsive Bootstrap-compatible sidebar/topbar layouts and locally owned CSS/JavaScript. HTMX and Alpine CSP are supported through a prepared local asset bundle.
- Flight blue, Neutral graphite and Ubuntu aubergine palettes, each with light, dark or system appearance. Open **Your profile** through your username in the top bar to change Appearance. Changes apply immediately without saving the profile form. Flight blue/light is the default; preferences stay in the current browser and apply throughout the application, including sign-in, with no account or server changes. If browser storage is blocked, selections still apply for the current page. With JavaScript disabled, the default light palette remains available.
- Consistent report snapshots with editable Word, offline PDF/HTML, safe previews, selected finding order, reusable templates and retained revision hashes.
- Separate development/production settings, structured JSON logging, health probe, SQLite WAL setup command and tests.

## Development startup

See the [installation guide](docs/installation.md) for Linux, macOS, Windows/WSL2, pinned offline wheels and optional Compose. See [operations](docs/operations.md) for backup/restore and updates, and [PostgreSQL](docs/postgresql.md) for the optional database and validated migration path.

Install Python 3.13 and the [offline PDF system dependencies](docs/reports.md#offline-pdf-dependencies), then run from the repository root:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/test.txt
python manage.py migrate
python manage.py configure_sqlite
python manage.py createsuperuser
python scripts/serve.py --development
```

The evidence filesystem safeguards and parser limits require Linux or macOS (POSIX). On Windows, run the application inside a Linux environment. `manage.py` defaults to `config.settings.development`; WSGI/ASGI default to production. Environment files are not automatically loaded. `.env.example` documents the variables; set them in your shell/service manager.

Open `http://127.0.0.1:8000/`. The superuser is the initial System Admin. Create standard users through **Users → Create user**. New accounts have no engagement access. No external email is needed; securely distribute initial credentials yourself. Users change their own passwords after signing in. An operator can reset a forgotten password with `python manage.py changepassword USERNAME`.

Open **Engagements → New engagement** as a System Admin, select an existing active Lead, and enter client, scope, dates and handling markings. Alternatively, seed an engagement through the operator command:

```sh
python manage.py create_engagement "Example assessment" --admin ADMIN_USERNAME --lead LEAD_USERNAME
```

The assigned Lead or a System Admin can edit engagement details, activate/pause/complete/archive it, manage milestones and maintain team access. Testers and Reviewers can add notes and edit/delete their own notes; Leads and System Admins can manage all notes. Completed/archived engagement content is read-only. Asset, test-case and finding screens are available from each engagement. See the [UI conventions guide](docs/ui-conventions.md) for operational dashboards, scoped search, navigation, themes and accessible forms. See the [audit and revision history guide](docs/audit-history.md) for scoped history, redaction, verification, exports and retention. See the [findings guide](docs/findings.md) for documentation and review. See the [evidence guide](docs/evidence.md) for private uploads, downloads, limits and cleanup. See the [reporting guide](docs/reports.md) for report generation, offline PDF dependencies and template customization. See the [asset and test-case guide](docs/assets-and-testcases.md), and the [engagement workflow guide](docs/engagements.md) for lifecycle rules, HTMX behavior and deliberate administrative deletion.

## Development demo data

After migrations and administrator setup, populate fictional aerospace red-team exercises:

```sh
python manage.py seed_demo --admin ADMIN_USERNAME --settings=config.settings.development
```

This creates Asterion Aerospace & Defense training engagements: active Operation KESTREL and completed Operation TALON, with 10 assets, 11 test cases, four findings, seven milestones, discussion notes, six locally generated evidence files and two assessment reports with DOCX/PDF/HTML revisions on a fresh seed. All data is synthetic; no Lockheed Martin systems or observations are represented. Sign in using your existing administrator account. The six demo role accounts start with unusable passwords and have no generated credentials.

Reruns preserve existing exercises and edits, including removed evidence. The command refuses production/custom settings, does not reset data and does not extend engagement purge support. See [demo data](docs/demo-data.md) for behavior and recovery details.

## Roles and account access

| Capability | Lead | Tester | Reviewer | Viewer | System Admin |
| --- | --- | --- | --- | --- | --- |
| View engagement | Yes | Yes | Yes | Yes | All engagements |
| Manage memberships | Yes | No | No | No | Yes |
| Edit engagement and lifecycle | Yes | No | No | No | Yes |
| Manage milestones | Yes | No | No | No | Yes |
| Create/edit assets and test cases | Yes | Yes | No | No | Yes |
| Add test-case discussion notes | Yes | Yes | Yes | No | Yes |
| Add notes / edit own notes | Yes | Yes | Yes | No | Yes |
| Edit another author’s note | Yes | No | No | No | Yes |
| Write tests and findings | Yes | Yes | No | No | Yes |
| Review findings | Yes | No | Yes | No | Yes |
| Attach evidence | Yes | Yes | No | No | Yes |
| Download evidence | Yes | Yes | Yes | Yes | Yes |
| Generate reports | Yes | Yes | Yes | No | Yes |
| View engagement audit | Yes | No | Yes | No | Yes |
| Create/disable accounts | No | No | No | No | Yes |

Lead, Tester, Reviewer and System Admin users can configure and generate reports in authorized engagements; Viewers cannot export reports. Evidence uploads are Lead/Tester/Admin operations; all engagement roles can download. Only the uploader, a Lead or an Admin can edit/remove evidence. UI visibility never authorizes an operation. Staff status alone grants neither application administration nor engagement access. The same user can be Lead in one engagement and Viewer in another.

Invisible engagement IDs return 404; members without the required capability receive 403. Child IDs are resolved through their claimed, authorized engagement. Membership edits include a version and return 409 on stale submissions. Leads cannot change their own membership; another Lead or System Admin must do so. Removing/demoting a Lead requires another active Lead. Disabling an account revokes access on its next request and increments a session generation so reactivation cannot revive old cookies; a System Admin can repair an engagement whose only Lead is disabled. The last active System Admin cannot be disabled through the account UI. Full server/database operators remain able to repair administrative state.

Own-profile fields are allowlisted; posted user IDs, usernames and privilege flags cannot alter another account or grant global access. Password changes preserve the current session and invalidate other sessions through Django's session-authentication hash. Administrative user editing in Django admin is read-only so it cannot bypass account services; bootstrap/global privilege changes use trusted operator management commands.

## Login protections and audit

Production requires HTTPS, secure HttpOnly session cookies, CSRF protection, explicit hosts and a private random secret. Login uses Django's safe redirect checks, including the HTTPS requirement for secure requests. Logout requires POST and CSRF.

The authentication backend shares database-backed limits across workers: five failed/in-flight attempts per normalized account and thirty per peer source in a fifteen-minute window. Success releases its reservation; expiry restores access. Limits apply to both application and administrator sign-in. Throttled form submissions return 429 with `Retry-After`. Unknown/disabled users receive generic errors. The source is the actual WSGI peer address; forwarded headers supplied by a client are ignored. Behind a reverse proxy the application source bucket may be shared by all clients; retain proxy rate limits too.

An operator can clear a specific bucket without default credentials:

```sh
python manage.py reset_login_throttle --username USERNAME
python manage.py reset_login_throttle --source PEER_IP
```

Authentication audit records store keyed HMAC fingerprints for attempted account/source correlation, not raw attempted usernames or addresses. They include a generated request ID where available and never include request bodies, passwords, authentication hashes or session tokens. System Admin can inspect audit events in Django admin; events are read-only there. A database operator can still alter records. Plan retention/rotation for audit data and expired throttle rows before a long-running deployment.

## Local frontend preparation

On a connected preparation machine:

```sh
python scripts/vendor_assets.py
python scripts/vendor_assets.py --check
```

The script retrieves pinned Bootstrap 5.3.8 and HTMX 2.0.8 from upstream source releases, and Alpine CSP 3.15.0 from its package registry, using Python's standard library. It downloads licenses and writes a SHA-256 manifest in `static/vendor/`. No Node installation or CDN is used. Review and transfer the resulting files with the source; restart the server after preparation. The browser only requests local files. No remote fonts, analytics, cloud services or runtime package downloads are used.

The local vendor files, licenses and SHA-256 manifest are prepared and verified. When libraries are absent, development uses its bundled application stylesheet and standard forms. Production deployment checks reject missing/tampered vendor files. The current controls use native HTML and application JavaScript; HTMX/Alpine are available for later interactions.

For offline installation, use `scripts/prepare_offline.py` on a matching connected machine and `scripts/verify_wheels.py` before installing with `--no-index`. The [installation guide](docs/installation.md) includes exact commands, native PDF prerequisites and prebuilt-image transfer.

## Concurrent editing

Several testers can use the same installation. Every editable domain record has an integer version. Updates compare the loaded version in the authorized scope and increment it atomically; stale submissions return HTTP 409 with submitted and current values. Manual merging requires an explicit review step and a separate save. Optional editor presence expires after 60 seconds and never locks a record. Status/dashboard refreshes do not replace edit inputs. See the [concurrent editing guide](docs/concurrent-editing.md) for the workflow and SQLite limits.

## Storage and SQLite

SQLite is the default and needs no external service. Optional PostgreSQL uses Django's standard backend and portable integrity guards; see [configuration and validated transfer](docs/postgresql.md). Unsupported backend names fail closed.

Private storage is outside public static files:

```text
storage/
  db/tdt.sqlite3
  evidence/
  reports/
  backups/
```

Set `TRACE_STORAGE_ROOT` to move the whole private root. SQLite, WAL and shared-memory files must remain on the server's local disk. Never place them on SMB/NFS or a synchronized folder. `configure_sqlite` enables persistent WAL mode once with application workers stopped. It is explicit rather than performed on every connection. Connections use a ten-second busy timeout and `IMMEDIATE` transactions; `ATOMIC_REQUESTS` is disabled. Password hashing happens outside write transactions. SQLite still has one writer at a time; measure contention with the expected team workload and keep write transactions short. [Django SQLite guidance](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes).

No public media route exists. Evidence files are served only by engagement-authorized endpoints; report artifacts also remain private and require report-generation permission. Do not expose storage through nginx/static hosting. The `backup_tdt` command captures a consistent SQLite snapshot plus referenced evidence/report files and a SHA-256 manifest under exclusive maintenance. `restore_tdt` validates and restores into a new private root; see [recovery procedures](docs/operations.md).

## Production

Use the [native virtualenv/systemd or optional Compose instructions](docs/installation.md). Both use Waitress through `python scripts/serve.py`, bind host access to loopback by default, refuse pending migrations and create no default credentials. Use a trusted reverse proxy with a private-CA HTTPS certificate; [nginx](deploy/nginx.conf), [systemd](deploy/trace.service) and protected environment examples are supplied. LAN binding requires explicit configuration. Production enforces secure cookies, CSRF/host policy and HTTPS; only local minimal readiness is exempt from redirects.

Do not publish the application directly to the internet. Keep operational data outside static files/images. See [operations](docs/operations.md) for maintenance gates, consistent backups, safe restore, health checks, log rotation, restart, updates and rollback.

## Health and checks

`GET /health/` returns only `{"status":"ok"}` with 200 when a database probe succeeds, or `{"status":"unavailable"}` with 503. It does not expose versions, users, paths or failure details. It probes connectivity, not migration state or the whole application.

```sh
python manage.py migrate --noinput
python manage.py makemigrations --check --dry-run
python manage.py check
python -m pytest
python scripts/vendor_assets.py --check
```

Run these checks directly in your local development environment. Test settings isolate storage in a temporary directory and use file-backed SQLite; password hashing remains strong in tests.

Standalone tests runnable without Django:

```sh
python -m unittest discover -s tests -p test_logging.py -v
python -m unittest discover -s tests -p test_vendor.py -v
```

See [architecture](docs/architecture.md), [project conventions](AGENTS.md) and the [MIT license](LICENSE).

## Upgrading from TDT branding

Use `TRACE_*` environment variables for new configuration. Existing `TDT_*` variables remain supported; explicitly provided `TRACE_*` values take precedence, including empty values that fail production validation. Preserve your existing secret key and storage root when updating the deployment.

The SQLite file keeps the name `storage/db/tdt.sqlite3`, and Compose keeps the `tdt-data` volume key to retain existing data. Authentication HMAC namespaces also remain stable so renaming does not reset throttle buckets or invalidate sessions. No database migration or file rename is required for branding. The Python distribution is now `trace-redteam`; Django app labels and migration history are unchanged.

The Compose service is now `trace`. When updating an existing Compose deployment, use the same project name and stop the old service with `docker compose down --remove-orphans` before starting the renamed service. This command preserves named volumes; do not add a volume-removal flag.

## Asset inventory and test cases

Open an engagement, then select **Assets** or **Test cases**. Leads, Testers and System Admins can create/edit these records; other members can read them. Assets validate their type-specific address fields and may have an active engagement member as owner. Test cases can be assigned to active Leads/Testers in the same engagement and linked to that engagement's assets only. Assignment/ownership never grants authorization.

The test list supports owner, status, category and asset filters, search, sorting, pagination, category progress and status counts. Resolved progress includes passed, failed and not-applicable cases. Text is displayed as escaped plain text with indentation and line breaks preserved. Discussion notes and URL/local-document references have their own versioned records.

Start cases in **Not started**, move to **In progress**, then record an outcome. Passed/failed outcomes require a nonempty actual result. Resume blocked/finished cases through **In progress** before changing outcomes. Completion timestamps are recorded automatically; reopening clears completion while retaining the original start and prior result text. Completed/archived engagements freeze these records too.

A System Admin can publish or retire shared procedures in **Test templates**. To load the bundled local starter templates using an existing administrator:

```sh
python manage.py load_test_templates --admin ADMIN_USERNAME
```

You can supply a local JSON file before `--admin`; files are bounded to one MiB/100 templates, imports are atomic, and existing names are skipped. Template content is shared with signed-in users and excludes results, assignments and asset links. Creating from a template copies its procedure fields and records its version; later template edits do not rewrite existing test cases. See [the workflow guide](docs/assets-and-testcases.md) for the full transition and access rules.

## Security and release review

Read the [security limitations and vulnerability reporting instructions](SECURITY.md). Installation, maintenance and recovery commands are in [installation](docs/installation.md), [operations](docs/operations.md) and [upgrades](docs/upgrading.md). Synthetic training data is documented in [samples](samples/README.md).

Optional development checks use `python -m pip install -r requirements/quality.txt`, then Ruff, Mypy, Bandit and dependency advisory scans. The supplied GitHub Actions workflow runs these alongside tests; running locally needs no GitHub service. Runtime rendering and bundled assets remain offline-capable.

Evidence storage defaults to **5 GiB per engagement / 20 GiB total**, with configurable disk warnings and free-space reserves. System Admins can set engagement overrides and open **Storage capacity**; see [storage controls and reconciliation](docs/storage-controls.md).
