# Evidence

Open **Evidence → Upload evidence** in an engagement. Leads, Testers and System Admins can upload one file at a time while it is writable. Describe the file and link it to at least one finding or test case in the same engagement.

## Access and lifecycle

All engagement roles can inspect metadata, download and verify integrity, including after completion/archive. Only the uploader, Lead or Admin can edit descriptions/links or remove evidence while writable. Original content/provenance is immutable; upload a new item to replace a file.

Edits use version checks and [conflict review](concurrent-editing.md). Failed uploads preserve descriptions and relationship selections, but the browser requires selecting the file again.

## Supported content and limits

| Setting | Default | Meaning |
| --- | --- | --- |
| TRACE_EVIDENCE_MAX_BYTES | 52428800 | Per-file streamed limit, including requests with misleading size metadata; maximum supported 1 GiB |
| TRACE_EVIDENCE_ALLOWED_TYPES | png,jpeg,pdf,text,pcap | Allowed content identifiers; add zip explicitly if needed |
| TRACE_EVIDENCE_IMAGE_PIXELS | 12000000 | Maximum image pixel count; supported up to 20 million |
| TRACE_EVIDENCE_IMAGE_SIDE | 8192 | Maximum width/height; supported up to 16384 |

PNG/JPEG images are decoded with bounded Pillow workers; animations are rejected. UTF-8 text, PDF and classic PCAP receive format checks. Optional ZIP support checks entries without extracting them. Identification does not establish that a document is safe to open elsewhere. Office files, SVG, GIF, TIFF and executables are unsupported; browser MIME types/suffixes are not trusted.

Image parsing has a five-second CPU limit, ten-second wall timeout and 512 MiB memory cap on Linux. macOS retains pixel/dimension/CPU/time limits where the memory cap is unavailable. Only regenerated, metadata-free PNG thumbnails up to 512 × 512 display inline. Originals download as attachments.

## Storage, integrity and downloads

Files live under `TRACE_STORAGE_ROOT`, outside static files, with random storage names, owner-only directories (`0700`) and nonexecutable files (`0600`). Unsafe links, permissions and public-path overlap are rejected. Never expose private storage through a media/static route.

Downloads recheck engagement access and SHA-256/size before streaming. Originals use attachment responses with nosniff, sandbox policy and private/no-store caching. **Verify stored integrity** checks original/thumbnail hashes; missing or corrupt files fail explicitly and are audited, without changing the baseline.

## Removal and interrupted-upload cleanup

Removal records a versioned tombstone and audit event, then unlinks bytes after commit. Metadata/history remains. Active downloads can defer cleanup; unlinking does not erase backups or guarantee physical media erasure.

Retry deferred cleanup with:

```sh
python manage.py cleanup_evidence
```

The command also removes unreferenced random-name files older than twenty-four hours. `--older-than-hours HOURS` changes the grace period (minimum one hour). It respects active leases and current references and retains metadata. Evidence blocks the limited engagement purge.

## Reporting

[Reports](reports.md) can include references and bounded regenerated images. They never embed original documents. Existing revisions retain copied image pixels after evidence removal, so report retention is separate.

## Quotas and disk warnings

Default evidence budgets are 5 GiB per engagement and 20 GiB total, with a 1 GiB private-filesystem reserve. Pending uploads, thumbnails and deferred deletions count. System Admins manage overrides and global capacity; members see their engagement allowance. See [storage controls](storage-controls.md) for configuration, error statuses and reconciliation, and [operations](operations.md) for coordinated backups.
