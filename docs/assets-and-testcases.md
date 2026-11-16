# Asset inventory and structured test cases

Open an engagement and choose **Assets** or **Test cases** in its navigation. These screens follow the mission/work-list pattern: searchable tables, status labels and row actions, then complete detail and edit pages. Forms and links work without JavaScript; the prepared local HTMX bundle enables filtered result replacements, partial note/reference updates and inline editor validation. Findings, evidence uploads and report generation remain out of scope.

## Access and lifecycle

| Operation | Lead | Tester | Reviewer | Viewer | System Admin |
| --- | --- | --- | --- | --- | --- |
| Read engagement assets/tests | Yes | Yes | Yes | Yes | All engagements |
| Create/edit assets and test cases | Yes | Yes | No | No | Yes |
| Add discussion notes | Yes | Yes | Yes | No | Yes |
| Edit/delete own discussion note | Yes | Yes | Yes | No | Yes |
| Edit/delete another author's note | Yes | No | No | No | Yes |
| Maintain case references | Yes | Yes | No | No | Yes |
| Publish/edit/retire shared templates | No | No | No | No | Yes |

Completed and archived engagements freeze inventory, test documentation, discussion and references. A passed/failed test in an open engagement can still receive documentation corrections or discussion; changing its outcome requires reopening it. Assignment and ownership do not grant engagement access. A removed or disabled member cannot gain access through an old assignment.

Every view scopes the parent and child IDs, including HTMX requests. Services independently authorize and validate inside short transactions, commit audit events with changes, and use compare-and-swap versions. HTTP 409 preserves a stale draft for reconciliation. User-entered target addresses, result text and procedure contents are excluded from audit metadata and application logs.

## Inventory

An asset has a UUID, engagement, name, type, hostname, IP/CIDR, HTTP/HTTPS URL, description, environment, scope status, optional owner, creator, timestamps and integer version.

- Host: requires a hostname or IP address.
- Application: requires an HTTP/HTTPS URL.
- Network: requires an IP address or CIDR.
- Service: requires a hostname, address or URL.
- Other: supports descriptive inventory without a required network identifier.

Hostnames support short internal names and DNS labels. IP/CIDR validation supports IPv4 and IPv6. Inventory stores metadata and never scans or fetches a target. Scope statuses are in scope, out of scope and pending confirmation. Assets can be linked for documentation regardless of that label; the scope label does not authorize testing activity.

Owners must be active members of this engagement, including non-tester roles. Existing attribution may remain after a user is removed/disabled; edit forms prompt for an eligible replacement or clearing the owner. Search covers name, hostname, address, URL and description. Filters include owner, type, scope and environment. Lists paginate twenty records and support allowlisted sorting.

## Test documentation

A test case records title, description, category, objective, methodology, procedure, expected/actual results, status, optional assigned tester, automatic start/completion times, optional related assets, record notes, creator, timestamps and version. Categories are team-authored text, not a fixed external taxonomy.

Assignment is limited to active Leads/Testers who hold an explicit membership in this engagement. A global administrator without a membership is not automatically an eligible assignee. If an assignment becomes ineligible, the next edit must clear or replace it. Related assets must belong to the same engagement. Model/form/service checks plus SQLite relationship triggers cover normal writes, M2M/bulk inserts, relationship updates and attempted movement of linked parents.

Structured fields are plain text. Leading/trailing whitespace, indentation and newlines are preserved. Detail views use escaped text with pre-wrap styling; HTML, scripts and Markdown HTML are not executed. References are separate records with a label and HTTP/HTTPS URL or local citation such as a document section or ticket ID. Local citations are text, not file-read operations. URLs are not fetched by TRACE.

Discussion notes are separate author-attributed records with independent revisions, in addition to the case's record-notes field. Reviewers may comment without modifying the procedure or execution outcome. Note/reference editing and deletion use scoped IDs, version checks and confirmation pages. Supporting records paginate independently.

## State transitions

New cases always start **Not started**, without execution timestamps.

| Current status | Allowed next statuses |
| --- | --- |
| Not started | In progress, blocked, not applicable |
| In progress | Blocked, passed, failed, not applicable |
| Blocked | In progress, not applicable |
| Passed | In progress |
| Failed | In progress |
| Not applicable | In progress |

Saving documentation with the same status is allowed. Passed/failed outcomes require a nonblank actual result. First entry into in-progress sets start time; terminal outcomes set completion time. Reopening clears completion but keeps the first start and prior result text so users can decide how to document a retest. A not-applicable decision may complete without an execution start. No user-submitted timestamp overrides are accepted.

List filters include assigned tester (`owner`), status, category and asset, with search/sorting/pagination. Status and category progress reflect all matching records, not just the visible page. **Resolved** means passed, failed or not applicable; N/A is explicitly distinguished from a pass. Database indexes begin with engagement and cover common owner/status/category/name/title/environment/scope/update filters; relationship foreign keys support asset joins. Substring searches remain ordinary SQLite searches, not an advertised full-text index.

## Reusable local templates

The shared library stores reusable title, description, category, objective, methodology, procedure and expected result, with name, active/retired state, provenance and version. All signed-in users can read active templates. Only System Admin can publish/edit/retire them. Do not put engagement-specific results in this shared library.

Choose **New test case**, select a blueprint and click **Load selection**, or use **Reusable templates → Use template** from an engagement. The copied draft is editable. Saving records the source template/version while leaving status not-started and assignments/assets empty unless the user explicitly chooses them. Later template edits/retirement do not rewrite existing cases. If the blueprint changed after a draft was opened, a version conflict preserves that draft for reconciliation.

An operator can publish bundled starter procedures:

```sh
python manage.py load_test_templates --admin ADMIN_USERNAME
```

An optional local JSON filename can precede `--admin`. The JSON is an array of template-field objects, at most 100 records and one MiB. Existing names are skipped; invalid input rolls back the complete import. This needs an existing active System Admin and performs no runtime network calls. It creates procedures, not credentials or assessment results.

## Retention

Asset/test-case parents and asset relationships use protected foreign keys. This phase provides create/read/update screens; it does not add a hard-delete interface for inventory or test-case history. Notes/references have explicitly confirmed deletion. The older engagement purge refuses engagements containing assets/tests until a reviewed module retention workflow is implemented.
