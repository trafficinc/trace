# Local frontend assets

This directory contains actual locally served Bootstrap 5.3.8 CSS, HTMX 2.0.8, Alpine CSP 3.15.0 and the Inter Latin regular font from Fontsource Inter 5.2.8, plus their upstream licenses. Sources, archive members and SHA-256 digests are recorded in `manifest.json`. Inter uses the SIL Open Font License. System fonts remain a fallback for characters outside the Latin subset.

`python scripts/vendor_assets.py --check` verifies the distribution offline. To deliberately refresh the pinned bundle, run `python scripts/vendor_assets.py` with network access on the preparation machine, review the files and manifest, and transfer them with the application. Runtime templates, styles and scripts make no CDN or external font requests. Bootstrap JavaScript is unnecessary for the native controls used here; application navigation uses local CSP-compatible JavaScript.
