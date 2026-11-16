# Evidence quotas and disk capacity

Evidence uploads have three independent limits: the per-file bound, engagement/server evidence budgets, and minimum free disk space. Existing files are never deleted to satisfy a lower quota. No uploaded file is executed, and private storage/download authorization remains unchanged.

## Configuration

Set these environment variables before starting **all** workers. There is no automatic `.env` loader for native Python commands; the supplied Compose file forwards these values from its protected environment file.

| Setting | Default | Meaning |
| --- | ---: | --- |
| `TRACE_EVIDENCE_MAX_BYTES` | 52428800 | 50 MiB per file; the existing content/size validation still applies |
| `TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES` | 5368709120 | 5 GiB default per engagement |
| `TRACE_EVIDENCE_TOTAL_QUOTA_BYTES` | 21474836480 | 20 GiB evidence budget across the server |
| `TRACE_STORAGE_MIN_FREE_BYTES` | 1073741824 | Keep at least 1 GiB available on private evidence/database filesystems |
| `TRACE_STORAGE_WARNING_PERCENT` | 20 | Warn System Admins at or below this free percentage, or when the byte reserve is reached |
| `TRACE_UPLOAD_TEMP_MIN_FREE_BYTES` | 16777216 | 16 MiB reserve on a separate temporary-buffer filesystem |

Byte values are nonnegative integers, up to 1 PiB. Zero quota blocks further uploads; it does **not** mean unlimited. A zero free-space reserve disables that reserve. Warning percentages must be 1–99. `manage.py check` rejects invalid bounds. Match per-file settings with Waitress/nginx body limits and temporary filesystem sizes.

If paths share a filesystem device, its largest applicable reserve is used once. A small dedicated temporary mount therefore does not need the 1 GiB private-storage reserve; Compose supplies a bounded 256 MiB `/tmp` mount. Capacity checks use blocks available to the service user, not blocks reserved for an OS administrator. An unreadable required upload-capacity probe fails closed; unavailable report/backup probes raise administrative warnings.

## User interface and permissions

Engagement **Evidence** lists and upload forms show charged bytes, the engagement limit and remaining allowance. Charges include pending uploads. Ordinary members see only their authorized engagement's allowance, never global usage or disk capacity.

Active System Admins can use **Manage evidence quota** to set an engagement override in bytes. Blank inherits the configured default; zero blocks new uploads. This administrative policy can be maintained on a closed engagement without reopening its content. Changes use integer compare-and-swap versions and transactional before/after audit records. Stale submissions return HTTP 409, preserve the entered quota and show the current saved policy. Open the current policy in a new tab to review and manually merge a value; stale forms cannot overwrite it.

The sidebar's **Storage capacity** page shows global evidence charges, upload-processing reservations and available disk space, including report/backup volumes. It refreshes its authorized HTMX fragment every 30 seconds. System Admin dashboards show a warning/link when capacity needs attention. No filesystem paths, global totals or other engagement allowances are disclosed to ordinary members. Sensitive pages and partials remain private/no-store.

Quota rejection returns HTTP 413. Insufficient disk headroom returns 507; unavailable capacity checks or busy coordination return 503. The upload parser drains the rejected file without writing it so descriptions and relationship selections after the file part are preserved. Select the file again before retrying; browsers cannot restore its selection. Existing per-file limits still bound request processing.

## Accounting and concurrency

A committed evidence charge is its original size plus thumbnail size. Pending uploads reserve their measured bytes before writing; neither browser MIME nor declared length determines admission. Images reserve their actual regenerated thumbnail before that file is written. Both HTTP uploads and direct service calls use the same accounting.

Admission and publication check engagement and server budgets atomically in short transactions. Integer versions and `F` increments prevent lost updates. File streaming, hashing, image parsing, space probes and deletion happen outside database writer transactions. A private POSIX coordination lease serializes capacity decisions across processes; SQLite still has one writer. The lease file is opened with no-follow/exclusive-creation safeguards, and lock retries apply only to acquiring that idempotent coordination lease, never to replacing business data.

Physical processing reservations conservatively allow three times the measured original plus 2 MiB, accounting for request buffering, private staging, the final copy and bounded thumbnails. Reservations remain conservative through completion, and free space is checked again before publication. An upload may therefore be refused before its final file alone would fill the remaining space. Temporary staging is not charged twice as committed evidence. Successful deletion releases its corresponding evidence charge; deferred deletion stays charged. Interrupted uploads clean their own uncommitted files and reservations; uncertain outcomes retain charges for reconciliation. Committed originals are never removed by failure cleanup.

Existing evidence is charged immediately from metadata without filesystem work during schema migrations. Legacy tombstones are conservatively charged until reconciliation confirms cleanup. Existing over-quota data remains readable; new growth is refused. Quotas count evidence, not report revisions, SQLite bytes, backups or unrelated files. Those files still consume the free space seen by admission probes.

## Operator reconciliation

Use an existing active System Admin. The default is a dry run that does not delete files or change accounting:

```sh
python manage.py reconcile_evidence_storage --admin ADMIN_USERNAME
```

To apply, stop **all** application workers and administrative writers first, then acknowledge exclusive maintenance:

```sh
python manage.py reconcile_evidence_storage --admin ADMIN_USERNAME --apply --maintenance
```

The command adopts legacy accounting, releases missing/deleted-file charges, retries safe deferred cleanup and removes old unreferenced files through the existing guarded sweep. It never removes a live evidence original/thumbnail. Missing live evidence is reported and stays charged; investigate integrity rather than silently accepting missing data. Active upload leases and open-file leases are respected even if timestamps are old. Pending abandoned uploads and unknown orphans use a 24-hour grace period; `--older-than-hours` permits a minimum of one hour. Output contains counts, not filenames, file contents or request data. Applied reconciliation and quota changes are audited.

The same procedure is useful after a restore: backups intentionally omit tombstoned/orphaned bytes, so restored operational accounting can temporarily be conservative. Inspect first, then apply reconciliation under the recovered instance's exclusive maintenance gate. Retain backups according to their independent policy; this command does not purge engagements or erase backup media.

## Host-level boundary

Application reservations coordinate this server's evidence workflows. They cannot reserve blocks against unrelated processes, prevent arbitrary report/backup growth, or intercept reverse-proxy/WSGI buffering that happens before Django handles the upload. Keep proxy body buffers bounded, protect temporary volumes, and use filesystem/container quotas plus monitoring when a hard storage boundary is required. Leave room for SQLite/WAL and recovery operations; do not rely on the application as the sole protection for a shared disk.
