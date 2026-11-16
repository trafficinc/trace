# UI conventions

Use Django templates, native forms and the shared application components. Keep CSS, JavaScript, fonts and vendor assets local; runtime pages must work without external requests.

## Navigation and tables

- Keep the workspace, engagement and current action clear in the sidebar and breadcrumbs. Use the shared breadcrumb component, retaining full labels in accessible names and hover titles.
- Use table-first lists with search, filters, stable sorting and pagination. Preserve filters in navigation links; ordinary result pages show twenty rows.
- Give tables captions, scoped headers and labelled, focusable scrolling regions on small screens. Wrap long values and label statuses with text as well as color.
- Scope queries before searching, counting or paginating. Workspace search covers metadata, not file contents or authentication data; empty queries do not enumerate records.
- The mobile drawer supports Escape, `aria-expanded` and focus return. Without JavaScript, navigation stays visible.

## Dashboards

Show only authorized data and measured progress. Test execution counts passed, failed and not-applicable cases separately; milestone completion is a different measure. Empty datasets show zero progress.

Use bounded summaries and independent aggregates. Avoid fetching narratives or full audit bodies for dashboard rows. Activity shows action, actor, engagement and time, without granting audit access or implying time worked. Retain supplied handling markings on engagement and mixed-engagement views.

## Forms and feedback

Use the shared `BootstrapFormRenderer`, visible labels, native controls, keyboard focus indicators and the skip link. Preserve text indentation/newlines according to each form's field policy. Escape submitted text; findings use their limited safe renderer.

Failed forms retain drafts and show field errors plus a validation summary. Handling banners use saved markings when a draft is rejected. Focus the summary or first error after failure. Use `role="status"` for success messages and generic permission/error explanations. Version conflicts use the shared [review and manual-merge workflow](concurrent-editing.md).

Keep scripts and styles in static files. Avoid inline handlers, arbitrary `safe` HTML, color-only meaning and hidden focus indicators. Respect reduced motion and provide usable touch controls. Check affected pages at desktop/mobile widths and with a keyboard.

## Themes

**Your profile → Appearance** controls palette and light/dark/system mode. Store only display preferences in browser storage (`trace.display`). Keep assessment data out of local storage. Storage failures must leave the default theme usable.

## Private HTMX behavior

Private pages and fragments use `Cache-Control: no-store, private`; shells disable HTMX local history snapshots. Full-page/fragment endpoints vary on `HX-Request` and independently authorize every request. Ordinary forms and GET links remain functional.

Poll only read-only regions. Dashboard polls run every thirty seconds, pause in hidden tabs, defer swaps while focus is inside the region and stop on access errors. Never replace unsaved inputs or update a form's loaded version. Conflicts replace only the submitted form; preserve other unfinished forms.

Evidence pages show engagement allowance only. Global capacity and quota editing require System Admin. Failed uploads preserve text/relationships, but users must select the file again. See [storage controls](storage-controls.md) for error statuses and quota behavior.
