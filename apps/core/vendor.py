"""Inventory validation shared by system checks and asset preparation."""
import hashlib
import json
from pathlib import Path

REQUIRED_ASSETS = (
    "inter-latin.woff2", "inter.LICENSE",
    "bootstrap.min.css", "htmx.min.js", "alpine-csp.min.js",
    "bootstrap.LICENSE", "htmx.LICENSE", "alpine.LICENSE",
)


def vendor_errors(directory):
    root = Path(directory)
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        for name in REQUIRED_ASSETS:
            content = (root / name).read_bytes()
            if not content or hashlib.sha256(content).hexdigest() != manifest[name]["sha256"]:
                return [f"Invalid local vendor asset: {name}"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["Local frontend assets or their SHA-256 manifest are missing or invalid."]
    return []
