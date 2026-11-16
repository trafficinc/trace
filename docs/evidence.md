# Private evidence workflow

Open an engagement and choose **Evidence → Upload evidence**. Lead, Tester and active System Admin users can upload while the engagement is writable. Select one file, describe it and link it to at least one finding or test case in that engagement. A single file can link to multiple cases and findings. Related records show evidence links. Descriptions preserve whitespace and are escaped plain text. Browser security prevents preserving selected files after a failed upload; descriptions and selections remain bound for correction.

All engagement roles can inspect metadata, download and verify integrity, including after completion/archive. Only the uploader, a Lead or a System Admin can edit descriptions/links or remove a file. The file itself and its original metadata never change; upload a new item to replace content. Version conflicts preserve submitted drafts.

## Supported content and limits

Install project dependencies with `python -m pip install -r requirements/runtime.txt`; Pillow is a required maintained image dependency. No runtime downloads, external services, shell commands supplied by users, scanners or uploaded executables are used. Evidence storage requires Linux/macOS POSIX file descriptors and advisory locks; use a local disk.

| Setting | Default | Meaning |
| --- | --- | --- |
| TRACE_EVIDENCE_MAX_BYTES | 52428800 | Per-file streamed limit, including requests with misleading size metadata; maximum supported 1 GiB |
| TRACE_EVIDENCE_ALLOWED_TYPES | png,jpeg,pdf,text,pcap | Allowed content identifiers; add zip explicitly if needed |
| TRACE_EVIDENCE_IMAGE_PIXELS | 12000000 | Maximum image pixel count; supported up to 20 million |
| TRACE_EVIDENCE_IMAGE_SIDE | 8192 | Maximum width/height; supported up to 16384 |

Upload one file per request. PNG/JPEG images are parsed and decoded; UTF-8 text rejects binary controls; PDF requires a recognized header and trailing EOF marker; classic PCAP requires valid global/packet lengths. ZIP is disabled by default; optional support bounds directory entry counts/declared sizes and rejects traversal/symlink members without extracting anything. PDF/ZIP/PCAP identification does not establish that a file is safe to open in another application. Office formats, SVG, GIF, TIFF, arbitrary executables and other binary formats are unsupported. Active filenames and obvious active HTML/SVG/script document content are rejected. Text logs can contain hostile output; the application never renders their content. Browser MIME and filename suffixes never establish an allowed content type.

Images use a fixed Pillow worker with pixel/dimension bounds, a 5-second CPU limit and 10-second wall timeout. Linux additionally enforces a 512 MiB address-space cap; macOS retains the other limits if the OS rejects that cap. Animated images are rejected. Only metadata-free regenerated RGB PNG thumbnails (maximum 512 × 512) display inline; original images remain attachments.

## Storage, integrity and downloads

Metadata and SHA-256 digests live in SQLite. Files use random names inside `storage/evidence/<engagement UUID hex>/` by default (under TRACE_STORAGE_ROOT). Directories are owner-only 0700; files are 0600 and nonexecutable. Stored paths never use client filenames. Root, directory and file symlinks, hardlinked files, permissive file/directory modes and overlap with public static directories are rejected. Do not serve any private storage directory through a web server or media URL.

Authenticated download endpoints scope the UUID through an authorized engagement and recheck current access. Each original is streamed as an attachment with application/octet-stream, a server-selected filename, nosniff, sandbox CSP and private no-store caching. Only regenerated PNG thumbnails use inline responses. Private file paths and original file contents are never placed in application logs or audit metadata.

Choose **Verify stored integrity** on the evidence detail page to recompute original/thumbnail digests and sizes. Mismatched or unavailable files produce a failed result and an audit event; every download also checks integrity before streaming. Corrupt files are refused rather than silently replaced or rehashed into a new baseline.

## Removal and interrupted-upload cleanup

**Remove evidence** is a versioned, authorized tombstone operation. After the database commits, the file and thumbnail are unlinked; UUID, provenance, description, links and audit records remain. A rollback leaves files intact. Open downloads retain leases, so their cleanup can be deferred. Unlinking does not erase existing backups or guarantee physical overwrite on SSDs/filesystem snapshots.

If the process crashes, disk cleanup fails or a reader still holds a file, run the operator cleanup command against the development database/storage:

```sh
python manage.py cleanup_evidence
```

It retries tombstone cleanup and removes unreferenced random-name files older than 24 hours. `--older-than-hours HOURS` changes the grace period (minimum 1 hour). Active uploads/downloads hold leases and are skipped. Current DB references are checked before unlinking; live evidence is retained. No background queue or runtime network service is needed. This command never purges metadata or engagements. Engagements containing evidence remain protected from the separate archived-engagement purge.

Backups must coordinate SQLite, private originals and thumbnails. Do not copy a database without its evidence files or restore one without verifying file integrity.

## Reporting

Authorized report generators can include bounded, regenerated PNG images and evidence references in [report revisions](reports.md). Original documents/artifacts are never opened or embedded. Existing report revisions keep their copied image pixels after source evidence is removed; coordinate export retention separately from source evidence retention. Report files and snapshots remain private, with no report hard-delete endpoint.

## Quotas and disk warnings

Evidence lists and upload forms now show engagement usage. System Admins can set audited, versioned engagement overrides and inspect server storage capacity. Defaults are 5 GiB per engagement, 20 GiB total evidence and a 1 GiB private-filesystem reserve. Pending uploads and thumbnails count; failed deletion does not refund capacity. See [storage controls](storage-controls.md) for configuration, HTTP failure statuses, concurrent reservations, reconciliation and host-level limits.
