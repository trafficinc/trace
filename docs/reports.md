# Reports

Open **Reports → New report** in an engagement. Leads, Testers, Reviewers and active System Admins can configure, generate, preview and download reports; Viewers cannot.

## Set up a report

1. Enter title, summary, methodology, recommendations, header/footer and handling marking. The marking starts from the engagement and can be explicitly changed or cleared.
2. Select findings and give each a distinct position. Confirmed findings are selected initially; other statuses can be included and stay labelled.
3. Optionally select a logo from active engagement image evidence and choose **Additional evidence to include**. These supplement evidence associated with selected findings/tests; duplicates and removed evidence are omitted.
4. Enable **Include images** to embed supported thumbnails, then save and generate a revision. Other file types remain references.

Setup edits are versioned and use [conflict review](concurrent-editing.md). Completion/archive freezes setup, but existing setups can still generate derived exports. Shared templates omit customer content and evidence selections.

## Generate and preview

**Generate DOCX, PDF and HTML** captures one consistent dataset and creates a numbered revision. Outputs use recorded findings/tests and supplied text; no assessment results are invented. Rendering happens outside write locks, and publication rechecks access.

Ready revisions offer editable DOCX, PDF, self-contained HTML and a sandboxed **Safe preview**. Downloads verify hashes and current report permission. Handling markings appear on the title page; Word and PDF/printed HTML also retain page headers/footers.

Revisions retain source/setup/template versions, actor/time, renderer versions and hashes. Their private JSON snapshot has no web download route. Later edits, template retirement and evidence removal do not change existing artifacts or embedded images. Reports block engagement purge; backups must include their private files.

## Offline PDF dependencies

Python dependencies include python-docx and WeasyPrint. PDF also requires native Pango libraries and fonts, installed before offline use.

Debian/Ubuntu:

```sh
sudo apt-get update
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
python -m pip install -r requirements/test.txt
```

macOS with Homebrew:

```sh
brew install pango
python -m pip install -r requirements/test.txt
```

Apple Silicon detects `/opt/homebrew/lib`; set `TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES` for other locations, such as `/usr/local/lib`. Reports use local DejaVu fonts/system fallbacks. Keep libraries/fonts consistent for reproducible layout. The Dockerfile includes these dependencies; see [offline installation](installation.md#offline-installation) for isolated hosts.

## Customize templates safely

System Admins curate **Report templates** with a name, palette, availability and ordered sections. Include every section exactly once:

```text
executive_summary
scope
objectives
methodology
test_summary
severity_summary
findings
evidence
recommendations
```

Choose a template and **Load template** before saving a new report. Its palette/order/version are copied; later template changes leave setups and revisions unchanged. Create a new report to use another template. Keep customer narratives, logos, evidence and markings in the engagement report.

Template options are data, not executable Django/Jinja, HTML, CSS or macros. Trusted maintainers can customize `report_templates/engagement.html`, `static/css/report.css` and `apps/reports/rendering.py`. Keep resources local; PDF fetching accepts only bounded regenerated PNG data URIs. Existing artifacts remain unchanged.

## Resource limits and reproducibility

| Setting | Default | Reviewed ceiling |
| --- | --- | --- |
| TRACE_REPORT_MAX_FINDINGS | 200 selected | 500 |
| TRACE_REPORT_MAX_TESTS | 1000 | 1000 |
| TRACE_REPORT_MAX_EVIDENCE | 500 references | 500 |
| TRACE_REPORT_MAX_IMAGES | 20, including logo | 50 |
| TRACE_REPORT_MAX_IMAGE_BYTES | 8 MiB aggregate | 16 MiB |
| TRACE_REPORT_MAX_SNAPSHOT_BYTES | 16 MiB text/embedded images | 16 MiB |
| TRACE_REPORT_MAX_ARTIFACT_BYTES | 100 MiB per artifact | 100 MiB |
| TRACE_REPORT_RENDER_TIMEOUT | 90 seconds | 90 seconds |

The editor supports 500 available findings. Embedded PNGs are at most 512 × 512 and 2 MiB each; logos count toward image limits. Corrupt/unavailable sources fail explicitly. Narrow the selection/content when limits are reached.

All formats render in a fixed credential-free subprocess. The PDF worker bounds input to 24 MiB, CPU to sixty seconds, wall time to ninety seconds and pages to 300; Linux also caps memory at 1 GiB. macOS retains other bounds where memory caps are unavailable. `TRACE_REPORT_CONCURRENT_EXPORTS` defaults to 1 (range 1–8); capacity rejection creates no revision. These limits provide resource isolation, not an OS security sandbox.

Canonical snapshots give stable ordering and repeatable HTML/DOCX. PDF bytes/layout can vary with renderer, native libraries and fonts. Downloads retain original artifact bytes rather than regenerating them.

## Failed/interrupted generation and cleanup

Failures retain revision metadata and fixed failure codes. To clean abandoned output:

```sh
python manage.py cleanup_reports
```

This removes unreferenced files older than twenty-four hours and marks old pending revisions failed. `--older-than-hours HOURS` changes the grace period (minimum one hour). Active leases, referenced artifacts and history are retained. Coordinate file retention and [backups](operations.md) separately from source evidence.
