#!/usr/bin/env python3
"""Run on the connected preparation machine, then transfer static/vendor offline."""
import hashlib
import argparse
import json
import io
import tarfile
from pathlib import Path
import sys
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from apps.core.vendor import vendor_errors

ASSETS = {
    "inter-latin.woff2": ("https://registry.npmjs.org/@fontsource/inter/-/inter-5.2.8.tgz", "package/files/inter-latin-400-normal.woff2"),
    "inter.LICENSE": ("https://registry.npmjs.org/@fontsource/inter/-/inter-5.2.8.tgz", "package/LICENSE"),
    "bootstrap.min.css": ("https://raw.githubusercontent.com/twbs/bootstrap/v5.3.8/dist/css/bootstrap.min.css", None),
    "htmx.min.js": ("https://raw.githubusercontent.com/bigskysoftware/htmx/v2.0.8/dist/htmx.min.js", None),
    "alpine-csp.min.js": ("https://registry.npmjs.org/@alpinejs/csp/-/csp-3.15.0.tgz", "package/dist/cdn.min.js"),
    "bootstrap.LICENSE": ("https://raw.githubusercontent.com/twbs/bootstrap/v5.3.8/LICENSE", None),
    "htmx.LICENSE": ("https://raw.githubusercontent.com/bigskysoftware/htmx/v2.0.8/LICENSE", None),
    "alpine.LICENSE": ("https://raw.githubusercontent.com/alpinejs/alpine/v3.15.0/LICENSE.md", None),
}


ALLOWED_DOWNLOAD_HOSTS = {'raw.githubusercontent.com', 'registry.npmjs.org'}


def approved_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS or parsed.username or parsed.password:
        raise ValueError('Vendor downloads require an approved HTTPS origin.')
    return url


class ApprovedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        approved_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify local files without network access")
    args = parser.parse_args()
    root = BASE_DIR / "static" / "vendor"
    if args.check:
        errors = vendor_errors(root)
        if errors:
            parser.exit(1, "\n".join(errors) + "\n")
        print("Local vendor assets verified.")
        return
    root.mkdir(parents=True, exist_ok=True)
    downloaded = {}
    # Download all before publishing any files, so failures don't enable half a bundle.
    for name, (url, member) in ASSETS.items():
        with build_opener(ApprovedRedirects()).open(approved_url(url), timeout=30) as response:
            downloaded[name] = response.read(16 * 1024 * 1024 + 1)
            if len(downloaded[name]) > 16 * 1024 * 1024 or not downloaded[name]:
                raise ValueError(f"Invalid asset size: {name}")
        if member:
            with tarfile.open(fileobj=io.BytesIO(downloaded[name]), mode="r:gz") as archive:
                entry = archive.getmember(member)
                if not entry.isfile() or entry.size > 16 * 1024 * 1024:
                    raise ValueError(f"Invalid package member: {name}")
                stream = archive.extractfile(entry)
                if stream is None:
                    raise ValueError(f"Missing package member: {name}")
                with stream:
                    downloaded[name] = stream.read()
    manifest = {}
    for name, content in downloaded.items():
        (root / name).write_bytes(content)
        manifest[name] = {"source": ASSETS[name][0], "archive_member": ASSETS[name][1], "sha256": hashlib.sha256(content).hexdigest()}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared local assets. Review and commit the files and manifest before offline distribution.")


if __name__ == "__main__":
    main()

