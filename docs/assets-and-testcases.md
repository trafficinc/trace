# Assets and test cases

Open an engagement and choose **Assets** or **Test cases**. Use searchable tables to find records, then open their detail or edit pages.

## Access and lifecycle

Leads, Testers and System Admins create/edit assets and cases and maintain case references. Reviewers can also discuss cases; Viewers can read. Authors manage their own discussion notes, while Leads/Admins can manage others'. Completed/archived engagements freeze all these records.

Ownership and assignment grant no access. All edits are versioned; stale submissions preserve drafts for [conflict review](concurrent-editing.md). See [engagement roles](engagements.md#roles-and-access).

## Inventory

Record an asset's name, type, address, description, environment, scope status and optional owner.

| Type | Required identifier |
| --- | --- |
| Host | Hostname or IP address |
| Application | HTTP/HTTPS URL |
| Network | IP address or CIDR |
| Service | Hostname, address or URL |
| Other | No network identifier required |

Hostnames can be internal names; addresses support IPv4/IPv6. Inventory stores metadata without scanning or fetching targets. In-scope/out-of-scope/pending labels document scope and do not authorize testing.

Owners must be active engagement members. Historical attribution may remain after removal/disablement, but the next edit must clear or replace an ineligible owner. Search/filter by address, name, owner, type, environment or scope.

## Test documentation

Cases contain a category, objective, methodology, procedure, expected/actual results, status, optional assignee and related assets. Assign only active Leads/Testers with membership in this engagement. A global Admin needs such membership to be assigned. The next edit must clear or replace an ineligible assignee. Linked assets must belong to the same engagement.

Plain-text fields preserve indentation and newlines and escape HTML. References accept HTTP/HTTPS URLs or plain local citations; TRACE does not fetch them. Separate discussion notes let Reviewers comment without changing execution results. Note/reference edits and deletions require their current versions.

## State transitions

New cases start **Not started**.

| Current status | Allowed next statuses |
| --- | --- |
| Not started | In progress, blocked, not applicable |
| In progress | Blocked, passed, failed, not applicable |
| Blocked | In progress, not applicable |
| Passed / failed / not applicable | In progress |

Passed/failed outcomes require an actual result. First entry into in-progress records the start; terminal outcomes record completion. Reopening clears completion while retaining the first start and prior result text. A not-applicable case may complete without starting.

Documentation corrections are allowed without changing status in open engagements. To change a finished outcome, reopen through **In progress**. Filters and category/status totals cover all matching records, including off-page rows. Resolved means passed, failed or not applicable; N/A remains distinct from pass.

## Reusable local templates

All signed-in users can read active shared templates; only System Admins curate them. Templates contain reusable procedures, never engagement results, assignments or asset links.

Choose a template through **New test case → Load selection** or **Reusable templates → Use template**. Saving copies its fields and source version into an independent case. Later template changes/retirement leave existing cases unchanged. A source-version conflict preserves the draft.

Load bundled procedures with an existing active System Admin:

```sh
python manage.py load_test_templates --admin ADMIN_USERNAME
```

An optional local JSON filename can precede `--admin`. Imports accept an array of up to 100 template objects/one MiB, skip existing names and roll back completely on invalid input.

## Retention

Assets, cases and relationships use protected foreign keys and block the engagement purge. There is no hard-delete interface for assets/cases. Discussion notes and references have confirmed deletion. See [architecture](architecture.md) for transaction and database integrity rules.
