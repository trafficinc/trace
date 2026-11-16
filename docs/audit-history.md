# Audit and revision history

Open an engagement's **Audit history** as a Lead, Reviewer or active System Admin. Filter by entity type, entity ID, actor ID, action and inclusive UTC dates. Each event shows the actor, time, business values before/after, version and chain commitments. A System Admin's **System audit** also includes authentication, account, shared-template, retention and purged-engagement events. Ordinary users cannot edit or delete history; there are no history mutation routes. Django administration is read-only for events and revisions.

Every member who can view a finding or test case can open its **Revision history**. Versions preserve documentation, workflow state, authors/reviewers/assignments and associated IDs. Text remains escaped, with indentation and newlines preserved. Revision history is read-only; manually copy the desired values into the regular versioned editor to make a new revision. Existing records get a clearly identified baseline at their next audited mutation. That baseline's timestamp means “first observed,” not its original creation time or author. Earlier events are sealed as legacy metadata during migration; missing historical values are never invented.

## Captured data and permissions

Domain services write business changes, audit events and finding/test-case revisions in the same short SQLite IMMEDIATE transaction. A failure anywhere rolls back all three. This includes engagement lifecycle, notes/milestones, memberships, assets, findings/reviews, test documentation/discussion/references, evidence metadata/removal, account changes, report setup/templates and generation transitions. Evidence access/integrity checks and report downloads also generate events. Authentication success/failure/logout signals write separate short audit transactions; session-cookie delivery and session persistence are not atomic with those signals. Direct SQL and Django's trusted bootstrap/reset commands are outside the domain-service audit boundary.

Business history uses explicit per-entity field schemas in `apps/audit/capture.py`. Metadata has a separate narrow allowlist. Password/hash/session-generation fields, raw upload contents, file storage names, unrestricted requests and authentication credentials are never captured. Authentication failures store keyed fingerprints and fixed reasons, not submitted usernames or passwords. Recognizable credentials in narrative text are conservatively redacted: credential-labelled lines, authorization/cookie headers, URL passwords, private-key blocks and selected token/hash formats. **Arbitrary unlabelled or encoded secrets cannot reliably be recognized.** Keep credentials in protected evidence or an appropriate secret store, rather than narrative documentation. Redacted revisions do not reconstruct removed credentials.

History itself remains sensitive private engagement data. Deleting a note or evidence record does not erase its retained redacted metadata/history. Evidence bytes are never duplicated into history. Membership revocation removes access to its history too. Engagement audit queries use the preserved engagement UUID; foreign IDs remain inaccessible. History responses disable browser caching and HTMX history snapshots. Exports are attachment-only JSON, avoiding spreadsheet formula execution, and use the same permissions and filters as the UI. Each successful export is audited after rechecking access. Exports exclude the export event itself and can contain chain gaps from filtering or other engagements: they are a readable, redacted extract, not a complete chain proof.

## Tamper detection and its limits

Each event commits a schema-versioned canonical JSON representation with SHA-256, an ordered sequence and its predecessor's digest. Frozen actor/engagement references remain committed if nullable foreign keys are detached. A singleton head and retention anchor track continuity. SQLite triggers reject ordinary event-body edits, unsealed inserts, revision edits and deletions outside retention. Before appending, the writer checks the current tail. Full verification scans the entire retained chain and checks revision bindings in a separate consistent read snapshot, without holding SQLite's writer lock:

```sh
python manage.py verify_audit --admin ADMIN_USERNAME
```

Keep the printed sequence/hash checkpoint separately if you need to compare against an independently held checkpoint later. This command does not automatically anchor checkpoints externally or compare them with earlier saved output. Application write guards are **not immutable storage or cryptographic non-repudiation**. A fully privileged database/server administrator can remove triggers, rewrite events, recompute hashes and replace the same-database head/anchor. Without independently enforced storage or external checkpoints, such a rewrite may be undetectable. Append-time tail checks do not substitute for periodic full verification. A failed check stops verification/retention and, for tail corruption, stops new audited mutations; investigate and restore a verified backup rather than silently resealing altered history.

SQLite still permits only one writer at a time. Global chain append runs inside the existing short business transaction, adding a bounded hash and head update. Simultaneous writers serialize through IMMEDIATE transactions and the configured busy timeout; no automatic replay of non-idempotent mutations occurs. Long verification/export serialization uses read operations, not write transactions.

## Retention and authorized cleanup

Configure these environment variables before starting the server:

| Variable | Default | Behavior |
| --- | --- | --- |
| `TRACE_AUDIT_RETENTION_DAYS` | `365` | Minimum event age for cleanup; `0` or negative disables cleanup. No automatic deletion. |
| `TRACE_AUDIT_MAX_EVENT_BYTES` | `2097152` | Combined before/after serialized bytes; oversized changes fail atomically. |
| `TRACE_AUDIT_EXPORT_LIMIT` | `10000` | Maximum events per filtered export. |
| `TRACE_AUDIT_EXPORT_MAX_BYTES` | `33554432` | Maximum serialized event bytes per export. Narrow filters when exceeded. |

Review applicable retention and engagement needs, protect a backup and save a verifier checkpoint. Run the operator command as an active System Admin; Lead/staff authority is insufficient:

```sh
# Dry run: verifies the retained chain and reports the head and eligible count.
python manage.py cleanup_audit --admin ADMIN_USERNAME

# Apply only the reviewed plan, substituting its actual head_sequence.
python manage.py cleanup_audit --admin ADMIN_USERNAME --apply --expected-sequence 123 --batch-size 500
```

Each batch removes only an eligible contiguous oldest prefix (maximum 500 events), together with revisions bound to those events. It advances the retained anchor to the last removed digest and transactionally appends an attributed cleanup event. It never deletes business records, evidence bytes or report artifacts. Any intervening audit append requires reviewing a fresh dry run. A failed cleanup rolls back deletion, checkpoint changes and its event together. Repeat review/apply for additional batches. Newer timestamps stop the prefix even if older timestamps occur later, accommodating clock changes without making chain holes. The cleanup command does not perform secure erasure of SQLite pages, WAL/journals, filesystem snapshots or backups; those require the operator's separate storage/backup retention policy.
