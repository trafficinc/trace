# Engagement workflow

Open **Engagements** to search, filter and sort the engagements you can access. Select an overview for scope, dates, team, milestones and notes. Supplied handling markings appear on engagement pages; no default classification is assumed.

System Admins create engagements through **New engagement**, assigning an existing active Lead. They create standard accounts through **Users → Create user**; new accounts have no engagement access until added to a team.

## Roles and access

Roles apply per engagement. Active superusers are global System Admins; staff status alone grants no access.

| Capability | Lead | Tester | Reviewer | Viewer | System Admin |
| --- | --- | --- | --- | --- | --- |
| View engagement and download evidence | Yes | Yes | Yes | Yes | All engagements |
| Edit engagement/lifecycle, milestones and team | Yes | No | No | No | Yes |
| Write assets, tests and draft findings | Yes | Yes | No | No | Yes |
| Add engagement/test discussion notes | Yes | Yes | Yes | No | Yes |
| Review findings | Yes | No | Yes | No | Yes |
| Upload evidence | Yes | Yes | No | No | Yes |
| Generate reports | Yes | Yes | Yes | No | Yes |
| View engagement audit | Yes | No | Yes | No | Yes |
| Manage accounts and shared templates | No | No | No | No | Yes |

Authors manage their own notes; Leads/Admins can manage others' notes. Evidence editing/removal also allows its uploader. Finding approval requires a different person from its author, including for Admins. See each workflow guide for action-specific rules.

Leads cannot change their own membership. Removing/demoting a Lead requires another active Lead. A System Admin can replace a disabled sole Lead. Disabling a user revokes access and invalidates old sessions; reactivation does not restore those sessions.

## Lifecycle

| Current status | Allowed next statuses |
| --- | --- |
| Planned | Active, archived |
| Active | Paused, completed, archived |
| Paused | Active, completed, archived |
| Completed | Archived |
| Archived | None |

Leads/Admins edit metadata and confirm lifecycle actions. Completed/archived content is read-only, with no reopen operation. Team access remains maintainable. Completion retains unfinished milestones. Scheduled end dates cannot precede start dates; actual completion/archive timestamps are separate.

## Notes and milestones

Testers/Reviewers can add notes and edit/delete their own. Leads/Admins manage all notes and milestones. Deletion requires confirmation and the current version. Text is escaped plain text.

Milestones have an optional due date and a completion flag. Progress is completed milestones divided by all milestones, including off-page rows; an empty plan shows 0/0 and 0%. This is separate from test execution. Open overdue milestones have text labels as well as color.

## Saving and history

Edits and actions carry integer versions. Stale submissions return HTTP 409 and preserve drafts for [explicit conflict review](concurrent-editing.md). Ordinary forms work without JavaScript.

Services recheck access and read-only state under the engagement lock, with [audit records](audit-history.md) committed alongside changes. Foreign objects return 404; forbidden actions within visible engagements return 403. See [architecture](architecture.md) for implementation rules.

## Protected deletion and administrative purge

Archive engagements for ordinary retention. There is no web hard-delete endpoint. The limited operator purge supports archived engagement-only records; assets, tests, findings, evidence, reports and other unsupported records block it.

Back up first. An operator must supply the exact UUID, current version and existing active System Admin attribution:

```sh
python manage.py purge_engagement ENGAGEMENT_UUID \
  --admin ADMIN_USERNAME \
  --version CURRENT_VERSION \
  --confirm ENGAGEMENT_UUID \
  --reason retention
```

Reasons are `retention`, `duplicate` or `test-data`. The command refuses wrong confirmations, stale versions and nonarchived engagements. It permanently removes supported notes, milestones and memberships while retaining audit events and their engagement UUID references.
