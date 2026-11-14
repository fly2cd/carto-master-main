from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.map_lock import MapSpecLockCompiler
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import D, INVALID_CASES, VALID_CASES


def _design_review_ref(digest=D):
    return {"id": "design-review-record", "version": "1.0.0", "digest": digest,
            "uri": "design-reviews/design-review-one.yaml"}


class DesignReviewSchemaTests(unittest.TestCase):
    """The design-review record is a typed, bound contract -- never a free boolean."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def test_valid_record_passes(self) -> None:
        self.registry.validate("design-review-record", VALID_CASES["design-review-record"])

    def test_invalid_case_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-review-record", INVALID_CASES["design-review-record"])

    def test_structured_findings_are_accepted(self) -> None:
        record = deepcopy(VALID_CASES["design-review-record"])
        record["findings"] = [
            {"severity": "warning", "summary": "legend crowded", "disposition": "resolved"},
            {"severity": "info", "summary": "title length within capacity"},
        ]
        self.registry.validate("design-review-record", record)

    def test_missing_candidate_ref_rejected(self) -> None:
        record = deepcopy(VALID_CASES["design-review-record"])
        record.pop("candidate_ref")
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-review-record", record)

    def test_unknown_severity_rejected(self) -> None:
        record = deepcopy(VALID_CASES["design-review-record"])
        record["findings"] = [{"severity": "critical", "summary": "not an allowed severity"}]
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-review-record", record)

    def test_free_form_confirmed_flag_is_rejected(self) -> None:
        record = deepcopy(VALID_CASES["design-review-record"])
        record["confirmed"] = True
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-review-record", record)


class DesignReviewLockBindingTests(unittest.TestCase):
    """MapSpecLock carries the design review only when one was recorded, and never loses it."""

    def setUp(self) -> None:
        self.compiler = MapSpecLockCompiler()
        self.candidate = deepcopy(VALID_CASES["resolved-map"])
        self.evidence = deepcopy(VALID_CASES["map-preview-evidence"])
        self.receipt = deepcopy(VALID_CASES["render-receipt"])
        self.preflight = deepcopy(VALID_CASES["validation-report"])
        self.request = {"run_id": self.candidate["run_id"], "project_id": self.candidate["project_id"]}
        self.kwargs = {"brief_approval_ref": "approvals/brief.yaml",
                       "freeze_approval_ref": "approvals/freeze.yaml"}

    def _compile(self, design_review_ref=None):
        return self.compiler.compile(
            self.request, self.candidate, self.evidence, self.receipt, self.preflight,
            design_review_ref=design_review_ref, **self.kwargs)

    def _verify(self, lock, design_review_ref=None):
        self.compiler.verify_existing(
            lock, self.request, self.candidate, self.evidence, self.receipt, self.preflight,
            design_review_ref=design_review_ref, **self.kwargs)

    def test_lock_omits_design_review_when_absent(self) -> None:
        lock = self._compile()
        self.assertNotIn("design_review_ref", lock)

    def test_lock_includes_and_validates_design_review(self) -> None:
        ref = _design_review_ref()
        lock = self._compile(ref)
        self.assertEqual(lock["design_review_ref"], ref)

    def test_verify_existing_replays_with_matching_ref(self) -> None:
        ref = _design_review_ref()
        lock = self._compile(ref)
        self._verify(lock, ref)

    def test_verify_existing_requires_recorded_design_review(self) -> None:
        ref = _design_review_ref()
        lock = self._compile(ref)
        with self.assertRaisesRegex(ProtocolError, "DESIGN_REVIEW_REQUIRED"):
            self._verify(lock, None)

    def test_verify_existing_rejects_different_design_review(self) -> None:
        ref = _design_review_ref()
        lock = self._compile(ref)
        other = _design_review_ref(digest="sha256:" + "1" * 64)
        with self.assertRaisesRegex(ProtocolError, "MAP_SPEC_LOCK_CONTEXT_MISMATCH"):
            self._verify(lock, other)


if __name__ == "__main__":
    unittest.main()
