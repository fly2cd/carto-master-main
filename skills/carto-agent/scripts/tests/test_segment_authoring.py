# -*- coding: utf-8 -*-
"""Segment authoring foundation tests (plan phase 1).

Proves: confirmed style/layout design -> closed segment package -> integrity verify,
with no business_contracts/prototype, tamper rejection, closed-world contract rejection,
and unknown-kind rejection. The scenario staging path is guarded separately by the
existing suite; here we assert the segment branch behaves and does not require scenario
artifacts.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.repository.segment_authoring import (
    author_segment_package, verify_segment_package, build_segment_payloads,
)
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from tests.fixtures.schema_cases import VALID_CASES


class SegmentAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="seg-author-"))
        self.guard = PathGuard([self.tmp])
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.registry = SchemaRegistry()
        self.common = dict(
            namespace="local", version="1.0.0",
            summary="segment authoring foundation test",
            requested_at="2026-11-23T00:00:00Z", lock_id="lock-seg-0001",
            registry=self.registry,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _author(self, kind, template_id, contract):
        return author_segment_package(
            self.guard, self.work, kind=kind, template_id=template_id,
            contract=contract, **self.common)

    def _verify(self, kind, template_id, contract):
        return verify_segment_package(
            self.guard, self.work, kind=kind, template_id=template_id,
            contract=contract, **self.common)

    def test_author_style_package_is_closed_and_segment_shaped(self):
        snap = self._author("map-style", "seg-style", deepcopy(VALID_CASES["style"]))
        self.assertIn("package_digest", snap)
        pkg = self.work / "staging/package"
        manifest = yaml.safe_load((pkg / "manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual("map-style", manifest["package"]["kind"])
        self.assertNotIn("business_contracts", manifest)
        self.assertTrue((pkg / "contracts/cartography.yaml").is_file())
        self.assertFalse((pkg / "prototypes").exists())
        self.assertEqual([], manifest["dependencies"])
        lock = yaml.safe_load((pkg / "dependencies.lock.yaml").read_text(encoding="utf-8"))
        self.assertEqual([], lock["dependencies"])
        self.assertEqual("map-style", lock["package"]["kind"])

    def test_author_layout_package_uses_layout_contract_path(self):
        self._author("map-layout", "seg-layout", deepcopy(VALID_CASES["layout"]))
        pkg = self.work / "staging/package"
        manifest = yaml.safe_load((pkg / "manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual("map-layout", manifest["package"]["kind"])
        self.assertTrue((pkg / "contracts/layout.yaml").is_file())
        self.assertFalse((pkg / "contracts/cartography.yaml").exists())

    def test_verify_existing_is_idempotent(self):
        contract = deepcopy(VALID_CASES["style"])
        first = self._author("map-style", "seg-style", contract)
        again = self._verify("map-style", "seg-style", contract)
        self.assertEqual(first["package_digest"], again["package_digest"])

    def test_tampered_contract_is_rejected(self):
        contract = deepcopy(VALID_CASES["style"])
        self._author("map-style", "seg-style", contract)
        target = self.work / "staging/package/contracts/cartography.yaml"
        target.write_bytes(target.read_bytes() + b"\n# tampered")
        with self.assertRaisesRegex(ProtocolError, "STAGING_PACKAGE_CONTEXT_MISMATCH"):
            self._verify("map-style", "seg-style", contract)

    def test_invalid_contract_is_rejected_closed_world(self):
        bad = deepcopy(VALID_CASES["style"])
        bad.pop("typography")  # required field missing
        with self.assertRaises(ProtocolError):
            self._author("map-style", "seg-style", bad)
        self.assertFalse((self.work / "staging/package").exists())

    def test_unknown_kind_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "SEGMENT_KIND_UNSUPPORTED"):
            self._author("map-brand", "seg-x", deepcopy(VALID_CASES["style"]))

    def test_payloads_are_deterministic(self):
        contract = deepcopy(VALID_CASES["layout"])
        a = build_segment_payloads("map-layout", "local", "seg-layout", "1.0.0", contract,
                                   summary="s", requested_at="2026-11-23T00:00:00Z",
                                   lock_id="lock-seg-0001", registry=self.registry)
        b = build_segment_payloads("map-layout", "local", "seg-layout", "1.0.0", contract,
                                   summary="s", requested_at="2026-11-23T00:00:00Z",
                                   lock_id="lock-seg-0001", registry=self.registry)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()