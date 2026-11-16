# Concurrent editing

TRACE can run locally or as a shared server. Each person uses their own account and engagement role. Several testers can read/edit different records simultaneously; competing edits to the same record cannot silently overwrite one another.

## Versioned records

The existing integer versions cover account profiles/access/password changes, engagements/lifecycle, memberships, engagement notes/milestones, assets, test cases, test notes/references, shared test/finding/report templates, findings/review, evidence descriptions/links/removal and report setup/finding order. No existing record needed a new version column. Relationship rows are changed within their owning record's versioned transaction. Immutable audit/file provenance and server-generated throttle/presence state are not user-editable documents.

Every edit/action form submits the version it loaded. Services scope the record to current permissions and its engagement before updating, then issue an atomic UPDATE filtered by primary key, authorized scope and expected version, incrementing with F("version") + 1. State checks, relationships and audit records share a short explicit transaction. A stale visible record is a conflict; missing and restricted IDs remain safely scoped 404/403 responses without revealing saved values. A read/check followed by an ordinary model save is never the final update mechanism.

## Resolve a conflict

1. Two testers open finding version 3.
2. Tester A saves; the finding becomes version 4.
3. Tester B submits version 3. The server returns HTTP 409 and leaves version 4 intact.
4. The conflict page shows B's submitted values, current saved values and both versions. B can open the saved record in a new tab while retaining the draft.
5. To merge, B edits the preserved draft and clicks **Use reviewed version for manual merge**. This only prepares the draft against the explicitly reviewed saved version; it does not save content.
6. B reviews the draft and clicks **Save manually merged values**. The save still performs CAS. If anyone changed the record again, another 409 comparison is required.

The reviewed snapshot is signed and bound to the user, endpoint, record and version for 15 minutes. Expiry, tampering or an intervening change requires a new comparison. There is no force-overwrite button, automatic latest-version substitution or automatic narrative merge. A record that became read-only cannot be merged. Normal non-JavaScript forms support the same review/prepare/save process.

Comparison text is escaped, preserving line breaks/indentation. The response keeps the submitted draft; it is not saved in a session, URL, presence row or audit log. Passwords/hashes are never displayed in comparisons; password changes require re-entry. File upload data is not retained by conflict review.

## Informational presence and refreshes

An editor's saved-version/status panel refreshes every 20 seconds. Dashboard engagement cards refresh every 30 seconds using scoped HTMX GETs. Neither refresh targets edit inputs or replaces the version loaded into a form. A newer saved version produces a status notice; it never changes the draft. HTMX local history snapshots remain disabled.

**Share editor presence** is optional and starts a CSRF-protected heartbeat every 20 seconds. Presence expires after 60 seconds without a heartbeat; **Stop sharing editor presence** removes the caller's entry. Other displayed editors must still be active and authorized for the same record/engagement. Presence is a hint, never a lock or permission grant; another tester can save while presence is active. Disable the feature with `TRACE_EDITOR_PRESENCE_ENABLED=0`. Version protection and read-only status checks remain active.

Conflict fragments replace only the submitted form. A section refresh is held if it would replace another unfinished form. Failed HTMX saves preserve inputs; an expired session or revoked access stops informational polling without navigating away. Sign in or check current access in another tab while retaining the draft.

## SQLite limits

SQLite permits one writer at a time across all engagements/records, including metadata, audit and presence writes. Editing different records succeeds without false version conflicts, but their write transactions still serialize. More application worker threads/processes do not create parallel database writers. The configured busy timeout waits up to 10 seconds for a lock; sustained contention can still produce a 503 rather than a save. A longer timeout alone does not increase write capacity.

Explicit IMMEDIATE transactions reserve the writer before permission/state reads. SQLite select_for_update is not a row lock and is not used as the concurrency mechanism. ATOMIC_REQUESTS remains disabled. Hashing, upload processing, thumbnail generation, integrity reads and filesystem cleanup stay outside content write locks. Configure WAL once with workers stopped using `python manage.py configure_sqlite`; WAL allows readers alongside a writer, not multiple simultaneous writers. Keep SQLite/WAL/shared-memory and private files on the host's local disk, never a network or synchronized filesystem. [Django SQLite guidance](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes).

Content mutations are never automatically retried or rebased. On a storage/lock failure, inspect the current record before manually retrying with the same expected version. Only the idempotent presence heartbeat retries identified SQLite BUSY/LOCKED errors: at most two additional attempts with 20/40 ms delays, retaining authorization checks on every attempt. Other database errors are not retried.

Measure contention with the expected team workload. Keep transactions short and reduce optional presence activity if writes queue. No fixed tester capacity is claimed. SQLite remains the supported database.
