# Concurrent editing

Edits carry the integer version loaded with the form. Saving compares that version atomically and increments it. Two people can edit different records; competing edits to the same record cannot silently overwrite each other. Relationship changes share their owning record's version.

## Resolve a conflict

1. Two testers open version 3. The first saves version 4.
2. The second submits version 3 and receives HTTP 409. Version 4 stays intact.
3. The comparison shows submitted and saved values. Open the saved record in a new tab if needed.
4. Edit the preserved draft and choose **Use reviewed version for manual merge**. This prepares a draft against the reviewed version without saving.
5. Review it and choose **Save manually merged values**. Another intervening edit requires another comparison.

Review tokens expire after fifteen minutes and are bound to the user, endpoint, record and version. There is no force-overwrite or automatic merge/retry. Read-only records cannot be merged. Ordinary forms support the same process.

Drafts stay in the response form, outside sessions, URLs and audit logs. Passwords must be re-entered and are excluded from comparisons. Selected upload files cannot be retained by the browser.

## Presence and refreshes

Editor status refreshes every twenty seconds; dashboard regions every thirty seconds. They never replace inputs or change a form's loaded version. Access errors stop polling while preserving drafts. Sign in or check access in another tab.

**Share editor presence** is optional. Its twenty-second heartbeat expires after sixty seconds without activity; **Stop sharing editor presence** removes it. Presence grants no lock or permission. Set `TRACE_EDITOR_PRESENCE_ENABLED=0` to disable it without changing version protection.

## Database limits

SQLite permits one writer across the installation. Its ten-second busy timeout can still end in HTTP 503 under contention. More workers or longer timeouts do not add write capacity. WAL allows concurrent readers, with setup performed while workers are stopped. Keep SQLite and private storage on local disk.

Content mutations are never automatically retried or rebased. After a lock/storage failure, inspect the current record before manually retrying with the same expected version. Only the idempotent presence heartbeat has bounded BUSY/LOCKED retries. Reduce optional presence activity if writes queue; measure capacity with the expected workload.

See [architecture](architecture.md#database-and-storage) for transaction ordering and optional PostgreSQL support.
