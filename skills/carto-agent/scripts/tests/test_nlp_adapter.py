# -*- coding: utf-8 -*-
"""NLP requirement-candidate adapter tests (design §5.4).

Proves the untrusted candidate protocol (no publish/approval fields), real source-span locators,
two-layer acceptance (trusted deterministic re-verification vs tentative confirmation), the
author-proposed-never-hard rule, and the bounded repair budget (at most 2 repairs).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.nlp_adapter import (
    adapt_with_retry, normalize_candidate, validate_candidate)
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry

COUNT_2 = {"kind": "count", "role": "main-map", "op": "eq", "value": 2}
ORIENT_LAND = {"kind": "enum", "path": "/canvas/orientation", "op": "eq", "value": "landscape"}
RELATION = {"kind": "relation", "relation": "contained-legend",
            "scope": "each-main-map", "mode": "independent"}


def _loc(source, sub):
    start = source.index(sub)
    return {"start": start, "end": start + len(sub)}


def _claim(cid, predicate, source, sub, origin="user-stated", strength="hard"):
    return {"id": cid, "origin": origin, "strength": strength,
            "predicate": predicate, "source_locator": _loc(source, sub)}


def _candidate(claims, source_ref="artifact:msg-1"):
    return {"schema_version": 1, "source_ref": source_ref, "claims": claims}


class NlpAdapterTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.source = "A3 横向，两个主图，每个主图内置图例。"

    def _normalize(self, candidate):
        return normalize_candidate(candidate, self.source, requirement_id="req-nlp",
                                   object_scope="layout", registry=self.registry)

    def test_confirmed_count_and_orientation_keep_hard(self):
        cand = _candidate([
            _claim("c-count", COUNT_2, self.source, "两个主图"),
            _claim("c-orient", ORIENT_LAND, self.source, "横向"),
        ])
        out = self._normalize(cand)
        self.assertEqual([], out["tentative"])
        self.assertEqual(2, len(out["conversion_evidence"]))
        self.assertTrue(all(c["strength"] == "hard" for c in out["requirement"]["conditions"]))
        self.registry.validate("design-requirement", out["requirement"])

    def test_publish_field_rejected_closed_world(self):
        cand = _candidate([_claim("c-count", COUNT_2, self.source, "两个主图")])
        cand["publish"] = True
        with self.assertRaises(ProtocolError):
            validate_candidate(cand, self.source, self.registry)

    def test_locator_out_of_bounds_rejected(self):
        claim = _claim("c-count", COUNT_2, self.source, "两个主图")
        claim["source_locator"]["end"] = len(self.source) + 5
        with self.assertRaisesRegex(ProtocolError, "NLP_LOCATOR_OUT_OF_BOUNDS"):
            validate_candidate(_candidate([claim]), self.source, self.registry)

    def test_inverted_locator_rejected(self):
        claim = _claim("c-count", COUNT_2, self.source, "两个主图")
        claim["source_locator"] = {"start": 5, "end": 5}
        with self.assertRaisesRegex(ProtocolError, "NLP_LOCATOR_OUT_OF_BOUNDS"):
            validate_candidate(_candidate([claim]), self.source, self.registry)

    def test_author_proposed_never_confirmed_hard(self):
        cand = _candidate([_claim("c-count", COUNT_2, self.source, "两个主图",
                                  origin="author-proposed", strength="hard")])
        out = self._normalize(cand)
        self.assertEqual(["c-count"], out["tentative"])
        self.assertEqual("soft", out["requirement"]["conditions"][0]["strength"])
        self.assertEqual([], out["conversion_evidence"])

    def test_complex_relation_stays_tentative(self):
        cand = _candidate([_claim("c-rel", RELATION, self.source, "每个主图内置图例")])
        out = self._normalize(cand)
        self.assertEqual(["c-rel"], out["tentative"])
        self.assertEqual("soft", out["requirement"]["conditions"][0]["strength"])
        self.assertTrue(out["requirement"]["open_questions"])

    def test_unverified_count_stays_tentative(self):
        # span lacks a numeral equal to 2 -> model claim not self-certified.
        cand = _candidate([_claim("c-count", COUNT_2, self.source, "主图")])
        out = self._normalize(cand)
        self.assertEqual(["c-count"], out["tentative"])

    def test_orientation_mismatch_stays_tentative(self):
        source = "纵向页面"
        claim = _claim("c-orient", ORIENT_LAND, source, "纵向")
        out = normalize_candidate(_candidate([claim]), source, requirement_id="req-nlp",
                                  object_scope="layout", registry=self.registry)
        self.assertEqual(["c-orient"], out["tentative"])

    def test_duplicate_claim_rejected(self):
        claim = _claim("c-count", COUNT_2, self.source, "两个主图")
        with self.assertRaisesRegex(ProtocolError, "NLP_CLAIM_DUPLICATE"):
            validate_candidate(_candidate([claim, deepcopy(claim)]), self.source, self.registry)

    def test_question_unknown_condition_rejected(self):
        cand = _candidate([_claim("c-count", COUNT_2, self.source, "两个主图")])
        cand["open_questions"] = [{"id": "q-x", "condition_ids": ["nope"],
                                   "question": "?", "blocking_for": "creation"}]
        with self.assertRaisesRegex(ProtocolError, "NLP_QUESTION_UNKNOWN_CONDITION"):
            validate_candidate(cand, self.source, self.registry)

    def test_bounded_retry_succeeds_after_one_repair(self):
        good = _candidate([_claim("c-count", COUNT_2, self.source, "两个主图")])
        calls = []

        def generate(attempt):
            calls.append(attempt)
            if attempt == 0:
                bad = deepcopy(good)
                bad["claims"][0]["source_locator"]["end"] = 9999
                return bad
            return good

        out = adapt_with_retry(generate, self.source, registry=self.registry)
        self.assertEqual([0, 1], calls)
        self.assertEqual("c-count", out["claims"][0]["id"])

    def test_bounded_retry_exhaustion_fails_closed(self):
        calls = []

        def generate(attempt):
            calls.append(attempt)
            bad = _candidate([_claim("c-count", COUNT_2, self.source, "两个主图")])
            bad["publish"] = True  # always invalid
            return bad

        with self.assertRaisesRegex(ProtocolError, "NLP_ADAPTATION_FAILED"):
            adapt_with_retry(generate, self.source, registry=self.registry)
        self.assertEqual([0, 1, 2], calls)  # initial + 2 repairs, never infinite


if __name__ == "__main__":
    unittest.main()