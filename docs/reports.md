# Reporting

Open an engagement and choose **Reports → New report**. Lead, Tester, Reviewer and active System Admin users have GENERATE_REPORTS; Viewers cannot configure, generate, preview or download reports. Every lookup/service is engagement-scoped. Assignment, authorship and UUID possession do not grant export access.

Save the report title, executive summary, methodology, recommendations, header/footer and exact handling marking. The initial marking is copied from the engagement; an authorized generator can explicitly change or clear it. No classification is assumed. Choose a logo from active PNG/JPEG evidence in this engagement, and enable/disable evidence images. Each included finding gets a distinct position; unchecked findings are excluded. Findings are initially selected only if confirmed, but authorized users can deliberately include other statuses, which remain labeled in the output.

Use **Additional evidence to include** to select engagement evidence directly, including screenshots linked only to test cases. Hold Ctrl (Windows/Linux) or Command (Mac) to select multiple items. This supplements evidence related to selected findings and their related test cases; duplicate references appear once. Removed evidence is omitted. **Include images** embeds supported, verified image thumbnails in **Evidence references**; other file types remain references. Save the setup, then generate a new revision and open its preview or download. Earlier revisions never change. Evidence selection does not modify finding or test-case links, and shared report templates do not copy these selections.

The HTML preview shows the supplied handling marking once on the title page. PDF/printed HTML and Word retain the marking on the title page and in page headers and footers.

Report setup is versioned. Stale edits return the normal 409 comparison/manual-merge workflow with the submitted finding selection intact. Setup cannot change after engagement completion/archive. Existing setup can still generate a derived export on a closed engagement without modifying source content.

## Generate and preview

**Generate DOCX, PDF and HTML** creates a numbered revision. All formats use one captured dataset, including the engagement, report options/template version, ordered findings, actual test summaries, severity counts, relevant evidence references and source record versions. The executive summary is supplied text; when blank, it summarizes only recorded test/selected-finding counts. No scanning or invented assessment results are involved.

The source is read in a separate read-only SQLite transaction. Image verification, rendering, hashing and file writing happen after that transaction closes and outside SQLite write locks. The final publication transaction rechecks access, completes the revision and commits audit/artifact metadata. Source edits during rendering do not alter the captured dataset or overwrite newer setup. Revoked access prevents publication.

Each ready revision offers editable **DOCX**, **PDF**, self-contained **HTML** and a **Safe preview**. Preview uses the stored HTML with a sandbox CSP, disabled scripts/forms and only inlined styles/PNG data. Original evidence documents/scripts are never rendered. Downloads require current GENERATE_REPORTS permission and verify SHA-256/size before streaming.

Revision history retains generation time/actor, setup version, renderer versions, status and artifact hashes. Canonical snapshot JSON is stored privately for provenance, alongside the three formats; it has no web download route. Later source/template/setup edits and source evidence deletion do not change existing revisions. Captured image pixels therefore require independent report-retention decisions. Engagements containing reports are protected from the separate archived-engagement purge.

## Offline PDF dependencies

DOCX uses **python-docx 1.2+**. PDF uses **WeasyPrint 70.x**, a maintained offline HTML/CSS renderer, plus its native Pango/font stack. Install native packages while preparing the host, then Python dependencies:

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

On Apple Silicon, `/opt/homebrew/lib` is detected by default. If native libraries are elsewhere, export `TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES` with the appropriate library directory, such as `/usr/local/lib`. The fixed PDF worker receives only this operator-controlled library setting and a minimal environment, not application secrets. Keep the native libraries and fonts consistent between machines for reproducible layout. Reports request DejaVu Sans/Mono and use installed system fallbacks if absent. Font packages are installed ahead of time; there are no remote fonts or runtime downloads.

The Dockerfile installs the native packages and fonts at image-build time. For isolated hosts, transfer matching native packages or a prepared image, plus the Python wheelhouse, source tree (including report_templates/static assets) and existing private storage. Rendering requires neither LibreOffice nor an external PDF service.

See the [WeasyPrint installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) and [resource/security guidance](https://doc.courtbouillon.org/weasyprint/stable/common_use_cases.html).

## Customize templates safely

System Admins curate **Report templates**. A reusable template contains:

- A name.
- A fixed palette: Flight blue, graphite or aubergine.
- Every supported section exactly once, in the desired order.
- Availability/retirement state and an integer version.

Supported section names are:

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

From New report, choose a template and click **Load template** before editing the draft. Saving copies its palette/section order/version. Template edits or retirement never change existing report setups or historical exports. Create a new report to use a different template. Customer narrative, logo/evidence, selections and handling markings belong to the engagement report, not the shared template.

Administrators submit data options, not Django/Jinja code, uploaded Word macros, raw HTML, arbitrary CSS or filesystem paths. Text such as `{{ secret }}` or `{% include ... %}` is literal report content, never compiled. Narratives use the existing escape-first formatting subset. DOCX preserves editable headings, emphasis, lists, whitespace, code and reference URLs; it does not execute fields derived from user input.

For deeper branding changes, a trusted source-code maintainer can edit `report_templates/engagement.html`, `static/css/report.css` and the adapter functions in `apps/reports/rendering.py`. These are fixed operator-owned files; no submitted path or template source is loaded. Keep CSS/fonts/images offline. PDF resource fetching accepts only bounded regenerated PNG data URIs and rejects HTTP, HTTPS, file, FTP and other resources. Old artifacts remain unchanged after code customization.

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

The setup editor supports 500 available findings. Regenerated images are PNGs at most 512 × 512, bounded to 2 MiB each and resized proportionally within report page dimensions. A logo is also subject to image limits. Source thumbnails are hash-verified and reparsed with the resource-limited Pillow worker before copying into a report.

The PDF worker caps input at 24 MiB, CPU at 60 seconds, wall time at 90 seconds and pages at 300. Linux enforces a 1 GiB address-space cap; macOS retains the other bounds when the OS rejects that cap. Large or unavailable/corrupt sources fail explicitly; the failed revision is retained and sources remain unchanged. Narrow the export selection/content rather than expecting unbounded output.

Canonical snapshot JSON uses stable keys; finding/test/evidence order is explicit or deterministic. Identical snapshots produce repeatable HTML/DOCX with fixed document properties and normalized DOCX ZIP ordering/timestamps. PDF identifiers and creation metadata derive from the snapshot, but PDF bytes/layout can vary with renderer/native library/font versions. Revision IDs/timestamps intentionally differ for new generation attempts. Original artifact bytes are retained instead of regenerating downloads against changing data.

## Failed/interrupted generation and cleanup

Generation is synchronous and bounded. A failure retains a fixed failure code and revision metadata without exposing parser exceptions or source content in application/audit logs. Partial files are removed after rollback. Ambiguous commits retain files referenced by committed artifact records. File leases protect active writers/readers from orphan cleanup.

For process termination or deferred cleanup:

```sh
python manage.py cleanup_reports
```

This removes unreferenced random-name files older than 24 hours and marks old pending revisions failed. `--older-than-hours HOURS` changes the grace period (minimum one hour). Current referenced artifacts and report/revision metadata remain. No public hard-delete or unreviewed engagement-retention path is added. Backups must coordinate SQLite and private report files.

## Render resource boundaries

HTML, DOCX and PDF adapters run together in a fixed credential-free subprocess, outside database transactions. Input/output sizes, wall time, CPU time and file output are bounded; Linux also caps address space at 1 GiB. A timeout kills the worker process group. Anonymous private temporary descriptors carry outputs; raw parser errors are not returned to users. `TRACE_REPORT_CONCURRENT_EXPORTS` defaults to 1 (allowed 1–8) and uses nonblocking process-shared slots. Capacity rejection preserves the submitted report and creates no generation revision. This is resource isolation, not an OS security sandbox. macOS does not reliably support the Linux memory cap; Windows native private storage remains unsupported as documented in installation.
