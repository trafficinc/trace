# User interface conventions

TRACE is a private, locally served workspace. It uses Django templates, Bootstrap 5.3 components, HTMX fragments and the Alpine CSP bundle. All library code, styles and the Inter Latin font are packaged in `static/vendor`, with upstream licenses and a verified SHA-256 manifest. There are no runtime CDN, cloud, analytics or external font dependencies. System fonts provide a fallback for other characters.

## Operational views

The workspace dashboard summarizes the current user's authorized engagements, active cases and open findings. A System Admin sees all engagements. Other accounts see only current memberships, regardless of whether their role differs across engagements. Engagement rows are paginated ten at a time. Active-case and open-finding panels show at most ten recently updated records, with links to domain lists/search for deeper work. Assigned cases are explicitly labelled “Assigned to you.”

Active test cases are not started, in progress or blocked, in engagements that are neither completed nor archived. Open findings are draft, under review or confirmed; unresolved findings on closed engagements remain visible. Counts use independent scoped aggregates, avoiding multiplication from joining several child collections. Read panels do not fetch finding narratives or full audit bodies. Related engagement/assignee data uses joins; query counts stay constant as visible row counts grow.

The engagement dashboard displays actual test execution, open findings by severity and documentation activity. Test execution is the proportion of passed, failed or not applicable cases; the breakdown keeps those outcomes distinct. Milestone completion remains its own progress indicator. Severity drill-downs use the same open-state definition as the count. Empty progress has a zero count and never invents activity or completion.

Activity is a deliberately limited summary of documentation events: action, username, engagement and time, without narrative values, authentication material, audit metadata, evidence bytes or report exports. The member summary covers the last seven days and is not a time-worked or productivity measurement. Full audit inspection continues to require `VIEW_AUDIT`; the dashboard does not confer that capability. Supplied handling markings are retained on engagement pages and mixed-engagement dashboard/search rows.

## Navigation, search and tables

The global sidebar and breadcrumb navigation identify the workspace, engagement, section and current action. Report and audit navigation reflect the user's engagement role; endpoints independently enforce permissions. On small screens the drawer has open/close buttons, updates `aria-expanded`, accepts Escape and returns focus to its opener. With JavaScript disabled, navigation remains visible above content.

Workspace search offers separate engagement, asset, test-case, finding and evidence-metadata categories. Queries are scoped through current authorized engagements before matching, counting or pagination. An explicit foreign engagement scope returns the same unavailable response as a missing one, even for an empty query. Search never reads upload bytes, credentials or authentication records. Terms are limited to 200 characters, treated as literal ORM search input and escaped in output. Empty terms do not enumerate records. Evidence removal tombstones are excluded.

Domain lists keep their search/filter/sort controls. Reports and evidence add title/filename/type/size filters as appropriate. Ordinary result pages use twenty rows, with stable ID tie-breaks and links that preserve filters. Report revision history and shared report templates are also paginated. Tables use semantic headings and scrollable regions on narrow screens; important statuses always have text labels rather than relying on color alone. Long URLs, titles and evidence names wrap without becoming executable markup. Text documentation remains escaped and preserves newlines/indentation; rich findings keep their established safe renderer.

## Forms, accessibility and feedback

`BootstrapFormRenderer` adds `form-control`, `form-select` and `form-check-input` classes through a shared bound-field class. It retains Django's label associations, required-field behavior, ARIA descriptions and invalid-field markers without modifying widget instances. Forms use native controls, visible labels, keyboard focus rings, an accessible skip link and explicit submit actions. Multi-line fields retain their existing strip/whitespace policy.

Failed bound forms preserve submitted values and field errors. Full-page failures show a prominent validation summary; local JavaScript focuses that summary or the first error list after a failed submission. Success messages use `role="status"`; permission failures use generic accessible explanations with a route back to the workspace. Foreign records and internal exception details are not disclosed. Conflict resolution continues to use versioned compare-and-swap saves and its existing draft-preserving UI.

Keep CSS and JavaScript in local static files. Avoid inline handlers, user-controlled HTML, HTML `safe` shortcuts, color-only meaning and CSS that hides focus indicators. Respect reduced-motion preferences. Controls have adequate touch height on narrow screens. For new tables, use a caption (visually hidden if needed), `scope` on headers, and a labelled, focusable scrolling region. These are accessibility conventions and automated semantic checks, not a claim of WCAG certification.

## Themes and private partials

Profile → Appearance offers light, dark and system modes plus the existing palettes. Only display preferences are stored under `trace.display` in local storage; no assessment data or search results are stored there. A pre-paint local script sets Bootstrap's theme attribute and shared color tokens. Browser storage failures leave the default theme usable.

Authenticated pages and partials are `Cache-Control: no-store, private`. HTML shells disable HTMX local history snapshots. Endpoints serving full pages and fragments vary on `HX-Request`; each fragment checks current authorization. Search/filter forms work with ordinary GET navigation as well as HTMX. Their results are escaped, and private content never uses a public cache.

Dashboard polls refresh only read-only regions every thirty seconds. They pause in hidden tabs, defer swaps while keyboard focus is inside the region, and stop on access errors. They never contain edit forms, update loaded form versions or replace unsaved drafts. Existing editor status/presence polling and conflict handling retain their independent protection. Future partials must preserve other unfinished forms and must not use an HTMX header as authorization.

Breadcrumb labels use the shared component and truncate after 20 characters. The full label remains in the native hover tooltip (`title`) and accessible name (`aria-label`); titles are escaped like other submitted text.

Evidence pages show only engagement-scoped quota usage. Global storage/disk details and policy editing require an active System Admin. Quota conflicts preserve submitted values with HTTP 409 and an explicit saved-policy link in a new tab. Upload capacity errors preserve text/relationship inputs with 413/507 (or 503 when capacity cannot be checked); the browser requires selecting the file again. The admin capacity fragment polls every 30 seconds independently of edit forms.
