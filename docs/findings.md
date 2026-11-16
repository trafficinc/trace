# Findings workflow

Open an engagement and choose **Findings → New finding**, or choose a shared **Finding template**, then an authorized engagement. Copying creates an independent draft. The list supports severity/status filters, bounded text search and deterministic sorting/pagination. Completed/archived engagements are read-only.

Lead, Tester and System Admin can edit draft content and relationships. Submit a draft for review to freeze its content. A Lead, Reviewer or System Admin other than its author can confirm it. Reviewers can return submitted findings to draft for corrections. Confirmed findings can become remediated or accepted risk. Reopening a confirmed, remediated or accepted-risk finding returns it to review; a reviewer can then return it to draft. Existing permissions require Lead/Tester/Admin to submit or reopen. Approval always requires another person.

Every edit and transition includes the saved version. A stale change returns HTTP 409 with submitted and saved values side by side. Open the saved record in a new tab or explicitly prepare and save a manual merge; see [concurrent editing](concurrent-editing.md). Membership/engagement authorization is checked again inside the mutation. Asset and test-case choices belong to the same engagement; attribution never grants access.

## Narrative formatting

Description, technical details, impact, reproduction steps, remediation recommendations and references support:

- Headings with `#` through `####`.
- `**bold**` and `*emphasis*`.
- Lists using `- ` or numbered steps using `1. `.
- Inline backticks and triple-backtick fenced code blocks.
- Links using `[label](https://example.com)` (HTTP/HTTPS only).

HTML is escaped and displayed as text. Images, scripts, styles and embedded content are unsupported. Local citations can be plain text. No reference is fetched. Original text and code indentation remain available for future reports. This is a limited formatting syntax, not full Markdown.

## CVSS

Optional CVSS vectors must be complete CVSS 3.0/3.1 base vectors containing each of AV, AC, PR, UI, S, C, I and A exactly once. Extended vectors and CVSS 2/4 are currently unsupported. A maintained calculator could not be installed because package network access was unavailable; scores remain unset rather than accepting a submitted or guessed score. Severity is an explicit tester selection.

## Shared templates and future modules

System Admins curate generic shared definitions. Never enter customer information in a shared template. Templates have no engagement, assets, tests, finding status, customer author or reviewer. A copy records the template version, starts as draft and never changes after template updates/retirement. Retire a template by clearing Available in its editor.

Findings have private [evidence attachments](evidence.md) through engagement-scoped links. Narrative revision history remains deferred. [Reports](reports.md) retain source snapshots and let authorized users include/exclude/order findings. Findings block operator engagement purges until a reviewed retention workflow is available.
