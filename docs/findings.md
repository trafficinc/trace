# Findings

Open **Findings → New finding** within an engagement, or copy a shared template. Filter the list by severity/status or search its text. Completed/archived engagements are read-only.

## Access and review

Leads, Testers and System Admins edit draft content and related assets/tests. Relationships stay within the engagement. Submit a draft to freeze its content for review.

A Lead, Reviewer or System Admin other than the author can confirm it or return it to draft for corrections. Authors cannot approve their own findings. Confirmed findings can become remediated or accepted risk. Reopening returns them to review; a reviewer can then return them to draft. Submission/reopening requires Lead, Tester or Admin.

Edits and transitions are versioned. HTTP 409 preserves stale drafts for [conflict review](concurrent-editing.md). [Revision history](audit-history.md) lets members inspect retained versions without overwriting current content.

## Narrative formatting

Narratives support headings (`#` through `####`), bold/emphasis, bullet/numbered lists, inline/fenced code and HTTP/HTTPS links. Code indentation is preserved. HTML is escaped; images, scripts, styles and embedded content are unsupported. Plain local citations are allowed. References are never fetched. This is a limited syntax rather than full Markdown.

## CVSS

Optional vectors must be complete CVSS 3.0/3.1 base vectors with AV, AC, PR, UI, S, C, I and A each present once. Extended vectors and CVSS 2/4 are unsupported. Scores are not calculated; select severity explicitly.

## Templates and related workflows

System Admins curate generic shared templates. Keep customer information out of them. Copies record the template version, start as independent drafts and omit customer relationships/review state. Template changes or retirement never update existing findings. Clear **Available** to retire a template.

Attach private [evidence](evidence.md) through scoped links and select findings in [reports](reports.md). Findings block operator engagement purges until a reviewed retention workflow exists.
