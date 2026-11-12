from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import SecurityError
from carto_core.security.approval import ApprovalReceipt, sign_receipt, verify_receipt
from carto_core.security.paths import PathGuard
from carto_core.security.sensitive import redact_for_log

D = "sha256:" + "a" * 64


class PathSecurityTests(unittest.TestCase):
    def test_allows_path_under_registered_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = root / "project" / "input.geojson"
            item.parent.mkdir()
            item.write_text("{}", encoding="utf-8")
            self.assertEqual(PathGuard([root]).resolve(item, must_exist=True), item.resolve())

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "allowed"
            root.mkdir()
            with self.assertRaises(SecurityError) as raised:
                PathGuard([root]).resolve("../outside.txt", base_root=root)
            self.assertEqual(raised.exception.code, "PATH_OUTSIDE_ALLOWED_ROOT")

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unsupported")
    def test_rejects_link_escape_when_creation_is_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "allowed"
            outside = base / "outside"
            root.mkdir(); outside.mkdir()
            link = root / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symbolic link creation is not permitted")
            with self.assertRaises(SecurityError):
                PathGuard([root]).resolve(link / "value.txt")


class ApprovalTests(unittest.TestCase):
    def _receipt(self) -> ApprovalReceipt:
        now = datetime.now(timezone.utc)
        return ApprovalReceipt(
            "receipt-one", "approve-freeze", D,
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=5)).isoformat(),
        )

    def _verification_kwargs(self) -> dict[str, str]:
        return {"expected_action": "approve-freeze", "expected_object_digest": D}

    def test_signed_receipt_verifies_and_tampered_digest_is_rejected(self) -> None:
        key = b"test-only-16-bytes"
        receipt = sign_receipt(self._receipt(), key)
        verify_receipt(receipt, key, **self._verification_kwargs())
        with self.assertRaises(SecurityError):
            verify_receipt(receipt, key, **{**self._verification_kwargs(), "expected_object_digest": "sha256:" + "b" * 64})

    def test_tampered_action_is_rejected(self) -> None:
        key = b"test-only-16-bytes"
        receipt = sign_receipt(self._receipt(), key)
        with self.assertRaises(SecurityError) as raised:
            verify_receipt(receipt, key, expected_action="wrong-action", expected_object_digest=D)
        self.assertEqual(raised.exception.code, "APPROVAL_ACTION_MISMATCH")

    def test_weak_hmac_key_is_rejected(self) -> None:
        with self.assertRaises(SecurityError) as raised:
            sign_receipt(self._receipt(), b"short")
        self.assertEqual(raised.exception.code, "APPROVAL_KEY_WEAK")

    def test_expired_receipt_is_rejected(self) -> None:
        key = b"test-only-16-bytes"
        now = datetime.now(timezone.utc)
        receipt = ApprovalReceipt("receipt-expired", "approve-freeze", D,
                                  (now - timedelta(hours=2)).isoformat(),
                                  (now - timedelta(hours=1)).isoformat())
        signed = sign_receipt(receipt, key)
        with self.assertRaises(SecurityError) as raised:
            verify_receipt(signed, key, **self._verification_kwargs())
        self.assertEqual(raised.exception.code, "APPROVAL_TIME_INVALID")

    def test_approval_cli_verifies_successfully(self) -> None:
        key_text = "test-only-16-bytes"
        receipt = sign_receipt(self._receipt(), key_text.encode("utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt_path = root / "approval.json"
            receipt_path.write_text(
                json.dumps(asdict(receipt), ensure_ascii=False), encoding="utf-8"
            )
            command = [
                sys.executable,
                str(SCRIPTS_ROOT / "carto.py"),
                "approval", "verify", str(receipt_path),
                "--allowed-root", str(root),
                "--key-env", "CARTO_TEST_APPROVAL_KEY",
                "--action", "approve-freeze",
                "--object-digest", D,
            ]
            environment = {**os.environ, "CARTO_TEST_APPROVAL_KEY": key_text}
            result = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)


class MiscellaneousSecurityTests(unittest.TestCase):
    def test_log_redaction_is_recursive(self) -> None:
        value = {"accessToken": "secret", "nested": {"route_coordinates": [1, 2], "safe": "ok"}}
        self.assertEqual(redact_for_log(value), {"accessToken": "[REDACTED]", "nested": {"route_coordinates": "[REDACTED]", "safe": "ok"}})

    @unittest.skipUnless(os.name == "nt", "Windows alternate streams are platform-specific")
    def test_windows_alternate_stream_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SecurityError) as raised:
                PathGuard([temp]).resolve("map.geojson:secret", base_root=temp)
            self.assertEqual(raised.exception.code, "PATH_ALTERNATE_STREAM")


if __name__ == "__main__":
    unittest.main()