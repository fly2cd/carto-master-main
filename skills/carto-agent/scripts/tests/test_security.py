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
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import SecurityError
from carto_core.security.approval import ApprovalReceipt, InMemoryNonceStore, SqliteNonceStore, sign_receipt, verify_receipt
from carto_core.security.authorization import Action, Role, SubjectContext, authorize
from carto_core.security.paths import PathGuard
from carto_core.security.sensitive import DataClassification, ExternalAccessPolicy, redact_for_log

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
        return ApprovalReceipt(1, "receipt-one", "trusted-local", "user-one", "tenant-one", "approve-freeze", "resolved-map", D, "project:flood", "carto-security", "local", (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=5)).isoformat(), "nonce-0000000001")

    def test_signed_receipt_verifies_once_and_replay_fails(self) -> None:
        key = b"test-only-secret-that-is-at-least-32-bytes"
        receipt = sign_receipt(self._receipt(), key)
        nonces = InMemoryNonceStore()
        kwargs = self._verification_kwargs()
        verify_receipt(receipt, key, nonces, **kwargs)
        with self.assertRaises(SecurityError) as raised:
            verify_receipt(receipt, key, nonces, **kwargs)
        self.assertEqual(raised.exception.code, "APPROVAL_REPLAYED")

    def test_tampered_digest_is_rejected(self) -> None:
        key = b"test-only-secret-that-is-at-least-32-bytes"
        receipt = sign_receipt(self._receipt(), key)
        with self.assertRaises(SecurityError):
            verify_receipt(receipt, key, InMemoryNonceStore(), **{**self._verification_kwargs(), "expected_object_digest": "sha256:" + "b" * 64})

    def test_persistent_nonce_store_rejects_replay_across_instances(self) -> None:
        key = b"test-only-secret-that-is-at-least-32-bytes"
        receipt = sign_receipt(self._receipt(), key)
        with tempfile.TemporaryDirectory() as temp:
            database = str(Path(temp) / "approval-nonces.sqlite3")
            verify_receipt(receipt, key, SqliteNonceStore(database), **self._verification_kwargs())
            with self.assertRaises(SecurityError) as raised:
                verify_receipt(receipt, key, SqliteNonceStore(database), **self._verification_kwargs())
            self.assertEqual(raised.exception.code, "APPROVAL_REPLAYED")

    def test_approval_context_must_match(self) -> None:
        key = b"test-only-secret-that-is-at-least-32-bytes"
        receipt = sign_receipt(self._receipt(), key)
        with self.assertRaises(SecurityError) as raised:
            verify_receipt(receipt, key, InMemoryNonceStore(), **{**self._verification_kwargs(), "expected_environment": "production"})
        self.assertEqual(raised.exception.code, "APPROVAL_ENVIRONMENT_MISMATCH")

    def test_weak_hmac_key_is_rejected(self) -> None:
        with self.assertRaises(SecurityError) as raised:
            sign_receipt(self._receipt(), b"short")
        self.assertEqual(raised.exception.code, "APPROVAL_KEY_WEAK")

    def test_approval_cli_rejects_replay_across_processes(self) -> None:
        key_text = "test-only-secret-that-is-at-least-32-bytes"
        receipt = sign_receipt(self._receipt(), key_text.encode("utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt_path = root / "approval.json"
            nonce_path = root / "approval-nonces.sqlite3"
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
                "--scope", "project:flood",
                "--policy-id", "carto-security",
                "--tenant-id", "tenant-one",
                "--issuer", "trusted-local",
                "--subject-id", "user-one",
                "--object-type", "resolved-map",
                "--environment", "local",
                "--nonce-db", str(nonce_path),
            ]
            environment = {**os.environ, "CARTO_TEST_APPROVAL_KEY": key_text}
            first = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            second = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 2, second.stdout)
            self.assertEqual(json.loads(second.stderr)["code"], "APPROVAL_REPLAYED")

    @staticmethod
    def _verification_kwargs() -> dict[str, str]:
        return {
            "expected_action": "approve-freeze", "expected_object_digest": D,
            "expected_scope": "project:flood", "expected_policy_id": "carto-security",
            "expected_tenant_id": "tenant-one", "expected_issuer": "trusted-local",
            "expected_subject_id": "user-one", "expected_object_type": "resolved-map",
            "expected_environment": "local",
        }


class AuthorizationAndPrivacyTests(unittest.TestCase):
    def test_rbac_and_namespace_are_both_required(self) -> None:
        reviewer = SubjectContext("reviewer-one", frozenset({Role.REVIEWER}), frozenset({"project-one"}), "tenant-one")
        authorize(reviewer, Action.APPROVE_FREEZE, "project-one")
        with self.assertRaises(SecurityError):
            authorize(reviewer, Action.PUBLISH_TEMPLATE, "project-one")
        with self.assertRaises(SecurityError):
            authorize(reviewer, Action.APPROVE_FREEZE, "project-two")
        admin = SubjectContext("admin-one", frozenset({Role.ADMIN}), frozenset(), "tenant-one")
        with self.assertRaises(SecurityError):
            authorize(admin, Action.MANAGE_POLICY, "project-one")

    def test_sensitive_location_cannot_reach_public_service_by_default(self) -> None:
        policy = ExternalAccessPolicy(frozenset({"public-geocoder"}), allow_public_for_internal=True)
        with self.assertRaises(SecurityError):
            policy.require_allowed(service_id="public-geocoder", classification=DataClassification.CONFIDENTIAL, data_kind="leadership_itinerary", explicit_approval=True)
        with self.assertRaises(SecurityError):
            policy.require_allowed(service_id="public-geocoder", classification=DataClassification.PUBLIC, data_kind="emergency_location", explicit_approval=False)

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
