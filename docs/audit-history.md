# Audit and revision history

## View and export

Leads, Reviewers and System Admins can open engagement **Audit history** and filter by entity, actor, action and inclusive UTC dates. **System audit** is Admin-only and includes authentication, account, shared-template, retention and purged-engagement events.

Members who can view a finding/test case can inspect its **Revision history**. History is read-only; copy desired values into the normal versioned editor to make a new revision. Older records may start with a labelled baseline representing first observation, not an invented creation history.

JSON exports use the same scope/permissions, are downloaded as attachments and are themselves audited. Filtered exports can contain chain gaps; they are readable extracts rather than complete chain proofs. Revoked membership removes history access.

## Captured data and permissions

Services commit business changes, audit events and finding/test-case revisions together. Authentication signals write separate events; session persistence is outside that transaction. Direct SQL and trusted bootstrap/reset commands remain operator boundaries.

Business values use explicit field schemas and credential redaction; metadata uses a narrow allowlist. Passwords, hashes, session-generation fields, upload bytes/storage names and raw requests are excluded. Failed authentication stores keyed fingerprints rather than submitted usernames. Redaction cannot reliably recognize arbitrary unlabelled/encoded secrets: keep credentials outside narrative text.

History remains sensitive private data. Removing a note/evidence item does not erase retained history; evidence bytes are not copied into it. Pages disable caching and HTMX history snapshots. Django admin provides read-only event/revision access.

## Tamper detection and its limits

Events form an ordered SHA-256 chain with a head and retention anchor. Database guards reject ordinary edits/deletes. Verify the retained chain and revision bindings with:

```sh
python manage.py verify_audit --admin ADMIN_USERNAME
```

Keep the printed sequence/hash checkpoint separately for later comparison. Same-database hashes are not immutable storage or non-repudiation: a privileged operator can replace events, triggers and chain state. Full verification is separate from append-time tail checks. Failed verification requires investigation/restoration, not silent resealing.

## Retention and authorized cleanup

| Variable | Default | Behavior |
| --- | --- | --- |
| `TRACE_AUDIT_RETENTION_DAYS` | `365` | Minimum event age for cleanup; `0` or negative disables cleanup. No automatic deletion. |
| `TRACE_AUDIT_MAX_EVENT_BYTES` | `2097152` | Combined before/after serialized bytes; oversized changes fail atomically. |
| `TRACE_AUDIT_EXPORT_LIMIT` | `10000` | Maximum events per filtered export. |
| `TRACE_AUDIT_EXPORT_MAX_BYTES` | `33554432` | Maximum serialized event bytes per export. Narrow filters when exceeded. |

Cleanup is explicit and requires an active System Admin. Review retention needs, protect a backup and save a checkpoint first.

```sh
# Dry run: inspect the head sequence and eligible count.
python manage.py cleanup_audit --admin ADMIN_USERNAME

# Substitute the reviewed head_sequence; 123 is an example.
python manage.py cleanup_audit --admin ADMIN_USERNAME --apply --expected-sequence 123 --batch-size 500
```

Each batch removes at most 500 eligible events from the oldest contiguous prefix and their bound revisions, advances the retention anchor and appends an attributed cleanup event atomically. Intervening appends require a fresh dry run. Newer timestamps stop the prefix. Business records, evidence bytes and report artifacts stay intact.

Cleanup does not securely erase SQLite pages, WAL, snapshots or backups; apply the separate storage/backup retention policy.
