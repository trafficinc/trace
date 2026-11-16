"""Asset validation tests use temporary fixtures, never fake distribution assets."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from apps.core.vendor import REQUIRED_ASSETS, vendor_errors


class VendorTests(unittest.TestCase):
    def test_missing_assets_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(vendor_errors(temp))

    def test_hashes_and_required_licenses_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = b"test fixture only"
            manifest = {}
            for name in REQUIRED_ASSETS:
                (root / name).write_bytes(content)
                manifest[name] = {"sha256": hashlib.sha256(content).hexdigest()}
            (root / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(vendor_errors(root), [])
            (root / "bootstrap.min.css").write_bytes(b"altered")
            self.assertTrue(vendor_errors(root))

    def test_malformed_manifest_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "manifest.json").write_text("[]")
            self.assertTrue(vendor_errors(temp))
