# Development demo data

Run after `migrate` and `createsuperuser`, against development storage only:

```sh
python manage.py seed_demo --admin ADMIN_USERNAME --settings=config.settings.development
```

`--admin` must name an existing active System Admin. The command accepts only `config.settings.development` or the isolated `config.settings.test` configuration. It refuses custom and production settings even when DEBUG is enabled. It creates no administrator or usable passwords, makes no network requests and requires the existing text/PNG evidence types and POSIX private-storage support.

The private evidence and report directories must be owned by the application user with mode `0700`. If the default development directory was supplied by a checkout with broader permissions, run `chmod 700 storage/evidence storage/reports` before seeding. For custom storage, check the configured `EVIDENCE_ROOT` and `REPORT_ROOT` instead. The command rejects unsafe storage rather than changing its permissions automatically.

## Exercises

The fictional client is **Asterion Aerospace & Defense**, modeled on the workflow of a large military aerospace contractor. No real Lockheed Martin assets, people, weaknesses, credentials or program information are used. Every engagement carries the explicit handling marking **SYNTHETIC TRAINING DATA — NOT CLASSIFIED**. Addresses use `.test` names and reserved documentation IP ranges.

| Exercise | State | Content |
| --- | --- | --- |
| Operation KESTREL — Engineering Enclave | Active | Seven assets, eight tests across all six test states, three draft/reviewed findings, four milestones with two complete, team notes and three evidence files plus a generated assessment report |
| Operation TALON — Supplier Access Validation | Completed | Three assets, three completed/not-applicable tests, one independently reviewed remediated finding, three completed milestones, team notes and three retained evidence files plus a generated assessment report |

The exercises cover supplier authorization, engineering segmentation, privileged-session review, artifact permissions and SOC coordination. Flight hardware, classified programs, live factory controls and production systems are explicitly excluded. Procedures describe offline training worksheets rather than live attack instructions. Results are fabricated exercise observations; saved start/completion timestamps reflect when the command performs the service transitions. Scheduled dates are relative to the initial seed date.

There are six fictional role accounts: `demo.kestrel.lead`, `demo.talon.lead`, `demo.redteam.operator`, `demo.redteam.analyst`, `demo.redteam.reviewer` and `demo.redteam.observer`. Each engagement has its own Lead plus the two Testers, Reviewer and Viewer. New demo accounts have unusable passwords and no staff/superuser privileges. Use the existing administrator sign-in to explore the data; normal account and membership workflows remain available.

Evidence includes four plain-text review worksheets and two clearly labeled synthetic policy diagrams. Each diagram goes through the normal isolated image parser and receives a sanitized thumbnail. Files are stored privately by the existing upload service, linked to the correct tests/findings and protected by the normal download authorization. No external resources are fetched. Each newly seeded exercise also gets a report setup with a synthetic executive summary, methodology, recommendations, supplied handling markings and findings in a fixed order. One generated revision includes DOCX, PDF, self-contained HTML and its preserved JSON snapshot. Diagrams use the normal bounded report-image path. Global templates are not populated. Offline PDF system libraries are required just as for ordinary reports; see [report dependencies](reports.md).

## Reruns and recovery

The command never clears a database, purges an engagement, replaces existing content or resets versions, passwords or lifecycle state. It identifies seeded exercises through their identifying exercise note and reserved Lead membership; changing an engagement's name does not produce a duplicate. A conflicting reserved username, ambiguous engagement identity or changed identifying note causes an error instead of adopting unrelated content. Keep the identifying exercise note intact if you intend to rerun the command.

Each exercise's initial metadata is created in one bounded transaction through domain services, including audit records, scoped relationships and valid status transitions. Files and thumbnails are prepared outside database transactions. If metadata creation fails, that exercise's metadata rolls back; already created demo users or other exercises remain. If evidence attachment fails, rerunning can add the missing artifacts to the existing writable exercise without rebuilding its metadata. Evidence filenames and uploader identities are checked; tombstones are included, so intentionally removed files are not recreated. Existing file bytes, descriptions and links are not replaced.

The completed exercise closes only from its initial active version. A concurrent or subsequent engagement edit prevents automatic closure; the command never refreshes a version and retries over an operator's edit. Review and complete that exercise through the normal lifecycle UI if needed. An already completed/archived engagement remains read-only on reruns, even if an artifact is missing. Renamed evidence-link targets cause a preservation error when a missing artifact would need that link.

A nonblocking owner-only lock in private evidence storage prevents concurrent seed commands from duplicating uploads. The operating system releases the lock when the process exits; the lock file may remain safely in place. There is no reset or deletion option. Existing asset/test/finding/evidence retention restrictions continue to apply; do not use the engagement-only purge workflow to remove this dataset. For throwaway runs, configure a separate development storage directory before migration and seeding.

## Existing demo installations

Rerun the same seed command to add a report to an existing writable exercise that has no reports. Existing report setups and ready revisions are never replaced or duplicated, including renamed or edited reports. An untouched seed setup can resume after an interrupted or failed export; generation runs outside database write transactions. A pending generation must finish or be handled with the normal report cleanup procedure before another seed export.

Already completed/archived exercises without report setups stay read-only: the seed does not reopen them or bypass lifecycle permissions. Fresh demo installations create report setups before closing TALON, then generate a snapshot reflecting its completed state. Existing closed exercises can generate further revisions from a setup that already exists.
