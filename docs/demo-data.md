# Demo data

After migrations and administrator creation, run against development storage:

```sh
python manage.py seed_demo --admin ADMIN_USERNAME --settings=config.settings.development
```

The named user must be an existing active System Admin. Only development and isolated test settings are accepted. Sign in with your existing administrator; the command creates no usable passwords.

Private evidence/report directories must be owned by the application user with mode `0700`. For default storage with broader permissions, use `chmod 700 storage/evidence storage/reports`; check configured paths for custom storage. [PDF dependencies](reports.md#offline-pdf-dependencies) are required.

## Contents

The fictional client is **Asterion Aerospace & Defense**. All records carry **SYNTHETIC TRAINING DATA — NOT CLASSIFIED**, use reserved addresses and contain no real customer observations.

| Exercise | State | Contents on a fresh seed |
| --- | --- | --- |
| Operation KESTREL | Active | Seven assets, eight tests, three findings, four milestones, notes, three evidence files and a report |
| Operation TALON | Completed | Three assets, three tests, one finding, three milestones, notes, three evidence files and a report |

Six demo accounts provide Leads, Testers, Reviewer and Viewer memberships. They have unusable passwords and no global privileges. Evidence consists of four text worksheets and two synthetic diagrams. Each report has a DOCX/PDF/HTML revision and private snapshot. Shared templates are not populated.

## Reruns and recovery

Reruns preserve edits, passwords, versions, lifecycle state, existing reports and intentionally removed evidence. There is no reset/purge option. For throwaway runs, choose a separate development storage root before migrating and seeding.

Keep the identifying exercise note and reserved Lead membership intact. Ambiguous identities or conflicting usernames cause an error rather than adopting unrelated content. Concurrent seed commands are blocked by a private storage lock.

If an upload fails, rerun to add missing artifacts to a writable exercise. Existing bytes/descriptions/links stay unchanged. Changed link targets can require manual review. Concurrent engagement edits prevent automatic closure; complete the exercise through normal lifecycle controls if appropriate.

Untouched report setups can resume interrupted/failed exports; pending generations need to finish or use [report cleanup](reports.md#failedinterrupted-generation-and-cleanup). Existing edited setups and ready revisions remain unchanged.

Completed/archived exercises stay read-only. Missing setups are not added to them. Fresh seeds create TALON's setup before completion; a closed exercise with an existing setup can generate further revisions. The seed does not extend engagement purge support.
