# Engagement workflow

The two principal screens are the engagement list and an engagement-specific overview. Their structure follows the supplied DART mission/work-list references: a table with direct row actions, then a scoped workspace containing a status-colored milestone table. Test-case and asset workflows are now available from the engagement. Finding, evidence and report workflows remain deferred.

## List and overview

Open **Engagements** in the sidebar. Search name, client/organization or scope; filter by status; sort by name, client, start date, status or most recent update. Pagination shows 20 engagements per page and includes only engagements visible to the current user. System Admins see all engagements.

Each row shows name, short UUID, client, status, start/end dates, completed/total milestones and permitted actions. The complete UUID is available on the overview. Select **Overview** to see description, objectives, scope, timeline, team, milestones and notes. Handling markings supplied by the team appear on engagement pages; TRACE does not invent a default classification.

System Admins create engagements with **New engagement** and select an existing active Lead. Creation writes the engagement, initial Lead membership and audit events in one transaction. The creator is recorded independently of the assigned Lead. Legacy records retain unknown creators until a separate provenance process establishes them.

## Lifecycle

| Current status | Allowed next statuses |
| --- | --- |
| Planned | Active, archived |
| Active | Paused, completed, archived |
| Paused | Active, completed, archived |
| Completed | Archived |
| Archived | None |

Leads and System Admins edit metadata and change lifecycle state. Lifecycle actions have a confirmation page and submitted version. Opening a confirmation page does not change a record. Repeated/stale submissions cannot silently overwrite newer state.

Completed and archived engagements have read-only details, notes and milestones. Team membership can still be changed to grant/revoke access or recover an engagement whose Lead is disabled. There is no reopen operation in this phase. Completion records its timestamp and preserves unfinished milestones; it does not fabricate completion or rewrite the team's work plan.

Start/end dates are optional, but end date cannot precede start date. These are scheduled dates; actual completion/archive times are separate UTC timestamps.

## Notes and milestones

Lead/System Admin can manage all notes and milestones. Testers and Reviewers can add notes and edit/delete their own; Viewers read them. Other authors' notes require Lead/Admin authority to change. Note and milestone deletion requires a confirmation and current revision. All content is escaped plain text.

Milestones have a title, description, optional due date, completion flag, completion timestamp, creator, timestamps and integer version. Mark complete/reopen changes only that milestone and updates displayed progress. Overdue open milestones have a visible text label as well as row color.

Progress is completed milestones divided by all milestones, not test execution or findings. An empty plan shows 0/0 and 0%. Notes paginate ten per page; milestones paginate twenty. Totals include every milestone, not just the visible page.

List filtering/pagination and note/milestone updates use HTMX when the prepared local library bundle is available. Standard form submissions and links work without JavaScript. Errors preserve submitted drafts; 409 indicates a stale record. The conflict screen compares submitted and saved values. Open the current version in a new tab or explicitly prepare a manual merge, then save it as a separate action. See [concurrent editing](concurrent-editing.md). Private HTMX history snapshots are disabled.

## Authorization and audit

Every view starts with engagement-scoped authorization. Services independently recheck permission inside a short transaction and lock the parent engagement before mutations. Note/milestone IDs must belong to the claimed parent; UUID guessing is not an authorization mechanism. Role-forbidden writes return 403; invisible/foreign objects return 404.

Engagement, membership and child records have independent integer versions. Metadata edits and lifecycle actions compare the engagement version. Child edits/toggles/deletes compare their own version, while the parent lock prevents them crossing a completed/archived state change. Audit failure rolls back the corresponding mutation.

Audit records contain actor, action, IDs, record version and approved metadata such as status or changed field names. Unrestricted note bodies, scope prose and handling text are not copied into audit metadata. An immutable engagement UUID reference survives an approved purge.

## Protected deletion and administrative purge

Use archive for ordinary retention. There is no engagement delete button or HTTP delete route. Memberships, notes, milestones and linked audit records use protected foreign keys, so ordinary model/queryset deletion cannot remove a populated engagement.

An operator with server access can deliberately purge an archived engagement through a separate management command. Back up before a permanent purge. Inspect the exact UUID and current version, then use an existing active System Admin for attribution:

```sh
python manage.py purge_engagement ENGAGEMENT_UUID \
  --admin ADMIN_USERNAME \
  --version CURRENT_VERSION \
  --confirm ENGAGEMENT_UUID \
  --reason retention
```

Permitted reasons are `retention`, `duplicate`, and `test-data`. The command refuses nonarchived engagements, wrong UUID confirmation, stale versions and engagements containing assets or test cases, whose retention workflow is not implemented. It permanently removes notes, milestones and memberships, retains audit events and their engagement UUID reference, and commits all changes atomically. This is an operator workflow, not a browser-accessible deletion API.
