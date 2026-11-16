#!/usr/bin/env python3
"""Optional CONNECTED release check; sends only public vendor names and versions."""
import json
from pathlib import Path
import sys
import urllib.request

PACKAGES = {"bootstrap": ["5.3.8"], "htmx.org": ["2.0.8"], "@alpinejs/csp": ["3.15.0"], "@fontsource/inter": ["5.2.8"]}


def main():
    request = urllib.request.Request("https://registry.npmjs.org/-/npm/v1/security/advisories/bulk",
        data=json.dumps(PACKAGES).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Advisory response exceeded limit.")
    advisories = json.loads(raw)
    if not isinstance(advisories, dict):
        raise ValueError("Invalid advisory response.")
    result = {"packages": PACKAGES, "advisories": advisories}
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Checked {len(PACKAGES)} bundled packages; {sum(len(items) for items in advisories.values())} advisories.")
    return int(bool(advisories))


if __name__ == "__main__":
    raise SystemExit(main())
