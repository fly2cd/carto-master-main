"""Single-publication-approval (no T1) acceptance guards.

Reuses the real raster publish-line fixture (PublishLineTests.setUp) so the object,
state transitions, nonce and target-binding are exercised against real code, not stubs.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.artifacts import atomic_yaml, load_document
from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError, SecurityError
from carto_core.workflow.approvals import ApprovalGateCoordinator
from tests import test_general_thematic as thematic
from tests.test_general_thematic import sign, APPROVAL_KEY, KEY


class SingleApprovalTests(unittest.TestCase):
    def setUp(self):
        thematic.PublishLineTests.setUp(self)

    def _validated(self):
        return thematic.PublishLineTests.run_to_validated(self)

    def _prepare(self, **over):
        kwargs = dict(repository_root=self.publish_kwargs["repository_root"],
                      repository_scope=self.publish_kwargs["repository_scope"],
                      idempotency_key=self.publish_kwargs["idempotency_key"])
        kwargs.update(over)
        return self.workflow.prepare_publication(self.request_path, **kwargs)

    def test_brief_no_longer_requests_approval(self):
        self.workflow.analyze(self.request_path)
        briefed = self.workflow.brief(self.request_path)
        self.assertNotIn("approval", briefed)
        self.assertEqual(("pending", "author"),
                         (briefed["state"]["status"], briefed["state"]["step"]))

    def test_author_without_approval_produces_draft_only(self):
        self.workflow.analyze(self.request_path)
        self.workflow.brief(self.request_path)
        authored = self.workflow.author(self.request_path)
        self.assertEqual(("pending", "validate"),
                         (authored["state"]["status"], authored["state"]["step"]))
        self.assertTrue((self.root / "work/staging/package/manifest.yaml").is_file())

    def test_prepare_is_idempotent_and_consumes_no_nonce(self):
        self._validated()
        ledger = self.root / "work/.nonce-ledger.db"
        before = ledger.read_bytes() if ledger.exists() else None
        first = self._prepare()
        second = self._prepare()
        self.assertTrue(second.get("idempotent_prepare"))
        self.assertEqual(first["object_digest"], second["object_digest"])
        after = ledger.read_bytes() if ledger.exists() else None
        self.assertEqual(before, after, "prepare must not consume approval nonces")
        self.assertEqual(("waiting_approval", "publish"),
                         (first["state"]["status"], first["state"]["step"]))

    def test_publish_without_tp_is_rejected(self):
        self._validated()
        self._prepare()
        with self.assertRaisesRegex(ProtocolError, "PUBLICATION_APPROVAL_REQUIRED"):
            self.workflow.publish(self.request_path, None, **self.publish_kwargs)

    def test_same_scope_different_root_cannot_reuse_approval(self):
        self._validated()
        prepared = self._prepare()
        other = dict(self.publish_kwargs, repository_root=self.root / "other-repo")
        with self.assertRaisesRegex(ProtocolError, "PUBLICATION_TARGET_MISMATCH"):
            self.workflow.publish(self.request_path, None, **other)
        # Even a TP signed for the original object must not publish to the other root.
        atomic_yaml(self.root / "tp.yaml", asdict(sign(
            "TP", "approve-template-publish", "template-publication", prepared["object_digest"],
            subject_id=self.request["subject"]["approver_subject_id"], scope=self.request["scope"],
            tenant_id=self.request["subject"]["tenant_id"])))
        with self.assertRaisesRegex(ProtocolError, "PUBLICATION_TARGET_MISMATCH"):
            self.workflow.publish(self.request_path, self.root / "tp.yaml", **other)

    def test_tampered_frozen_object_fails_closed(self):
        self._validated()
        self._prepare()
        obj_path = self.root / "work/publication/template-publication.yaml"
        original = obj_path.read_bytes()
        try:
            bad = load_document(obj_path)
            bad["repository_scope"] = "local:other"
            atomic_yaml(obj_path, bad, create_once=False)
            with self.assertRaisesRegex(ProtocolError, "PUBLICATION_OBJECT_DRIFT"):
                self.workflow.publish(self.request_path, None, **self.publish_kwargs)
        finally:
            obj_path.write_bytes(original)

    def test_old_t1_receipt_is_not_a_publication_approval(self):
        self._validated()
        prepared = self._prepare()
        atomic_yaml(self.root / "t1.yaml", asdict(sign(
            "T1", "approve-template-brief", "template-brief", prepared["object_digest"],
            subject_id=self.request["subject"]["approver_subject_id"], scope=self.request["scope"],
            tenant_id=self.request["subject"]["tenant_id"])))
        with self.assertRaises(SecurityError):
            self.workflow.publish(self.request_path, self.root / "t1.yaml", **self.publish_kwargs)

    def test_removed_gate_raises_protocol_error_not_keyerror(self):
        coordinator = ApprovalGateCoordinator(APPROVAL_KEY)
        digest = "sha256:" + "a" * 64
        receipt = sign("TP", "approve-template-publish", "template-publication", digest)
        with self.assertRaisesRegex(ProtocolError, "APPROVAL_GATE_UNKNOWN"):
            coordinator.require("T1", receipt, digest)


if __name__ == "__main__":
    unittest.main()