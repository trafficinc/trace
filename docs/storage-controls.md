# Evidence quotas and disk capacity

Uploads must fit the per-file limit, engagement/server budgets and available disk space. Lowering a quota does not delete existing files.

## Configuration

Set values consistently for all workers through the [installation environment](installation.md).

| Setting | Default | Meaning |
| --- | ---: | --- |
| `TRACE_EVIDENCE_MAX_BYTES` | 52428800 | 50 MiB per file; the existing content/size validation still applies |
| `TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES` | 5368709120 | 5 GiB default per engagement |
| `TRACE_EVIDENCE_TOTAL_QUOTA_BYTES` | 21474836480 | 20 GiB evidence budget across the server |
| `TRACE_STORAGE_MIN_FREE_BYTES` | 1073741824 | Keep at least 1 GiB available on private evidence/database filesystems |
| `TRACE_STORAGE_WARNING_PERCENT` | 20 | Warn System Admins at or below this free percentage, or when the byte reserve is reached |
| `TRACE_UPLOAD_TEMP_MIN_FREE_BYTES` | 16777216 | 16 MiB reserve on a separate temporary-buffer filesystem |

Byte values are nonnegative integers up to 1 PiB; per-file validation also applies its own supported ceiling. Zero quota blocks uploads; zero free-space reserve disables that reserve. Warning percentages are 1–99. `manage.py check` validates settings. Match application limits with proxy/body buffers and temporary volume sizes.

For paths on the same filesystem, the largest reserve applies once. Capacity uses blocks available to the service user. Failed required upload probes refuse admission; unavailable report/backup probes produce admin warnings.

## User interface and permissions

Members see charged usage, limit and remaining allowance for their engagement. System Admins use **Manage evidence quota** and **Storage capacity** for overrides and global disk/reservation data. Blank overrides inherit defaults; zero blocks new uploads. Quota policies remain maintainable on closed engagements.

Quota changes are audited and versioned. HTTP 409 preserves stale inputs for manual review. Upload errors preserve text/relationships; select the file again before retrying:

| Status | Meaning |
| --- | --- |
| 413 | Quota exceeded |
| 507 | Insufficient disk headroom |
| 503 | Capacity unavailable or coordination busy |

## Accounting and concurrency

Charges include originals, thumbnails and pending reservations. Deferred deletion remains charged until cleanup succeeds. Existing over-quota data stays readable; new growth is refused. Reports, database files and backups are outside evidence quotas but consume disk headroom.

Admission/publication check budgets atomically. Streaming, hashing, image parsing, disk probes and deletion stay outside database write locks. POSIX leases coordinate processes and protect active files. Processing reservations allow three times measured original bytes plus 2 MiB, so an upload can be rejected before its final file alone would fill the disk. Uncertain outcomes retain conservative charges for reconciliation.

## Operator reconciliation

Inspect with an existing active System Admin; the default is a dry run:

```sh
python manage.py reconcile_evidence_storage --admin ADMIN_USERNAME
```

To apply, stop **all** application workers and administrative writers, then acknowledge exclusive maintenance:

```sh
python manage.py reconcile_evidence_storage --admin ADMIN_USERNAME --apply --maintenance
```

Reconciliation repairs abandoned reservations/legacy accounting, retries deferred deletion and sweeps old unreferenced files. It never removes live evidence. Missing live files are reported and remain charged. Active leases are respected. The orphan grace period is twenty-four hours; `--older-than-hours` permits a minimum of one hour. Applied changes are audited.

Inspect accounting after restore too: omitted tombstone/orphan bytes can leave conservative charges. Reconciliation does not purge engagements or backups.

## Host-level boundary

Application reservations cannot reserve blocks against unrelated processes or bound report/backup growth and pre-Django proxy buffering. Use host/container quotas, bounded temporary buffers and monitoring for hard limits. Leave space for SQLite/WAL and recovery operations.
