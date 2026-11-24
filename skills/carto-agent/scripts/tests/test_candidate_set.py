from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.compiler.map_candidate import MapCandidateCompiler
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import D, INVALID_CASES, VALID_CASES


def _candidate_entry(variant_id, run_id="run-one", status="passed"):
    return {"variant_id": variant_id, "candidate_id": f"candidate-{run_id}-{variant_id}",
            "resolved_map_digest": D, "render_scene_digest": D,
            "preflight_status": status, "preflight_report_digest": D}


class CandidateSetSchemaTests(unittest.TestCase):
    """The candidate-set protocol presents compared candidates and forbids any selection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def _valid(self):
        return deepcopy(VALID_CASES["candidate-set"])

    def test_valid_set_passes(self) -> None:
        self.registry.validate("candidate-set", self._valid())

    def test_invalid_case_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            self.registry.validate("candidate-set", INVALID_CASES["candidate-set"])

    def test_selection_field_is_rejected(self) -> None:
        # Program must not rank/select: a 'selected' field is not part of the contract.
        for forbidden in ("selected", "selected_candidate_id", "ranking", "best"):
            value = self._valid()
            value[forbidden] = "variant-a"
            with self.subTest(field=forbidden), self.assertRaises(ProtocolError):
                self.registry.validate("candidate-set", value)

    def test_empty_candidates_rejected(self) -> None:
        value = self._valid()
        value["candidates"] = []
        with self.assertRaises(ProtocolError):
            self.registry.validate("candidate-set", value)

    def test_more_than_eight_candidates_rejected(self) -> None:
        value = self._valid()
        value["candidates"] = [_candidate_entry(f"variant-{i}") for i in range(9)]
        with self.assertRaises(ProtocolError):
            self.registry.validate("candidate-set", value)

    def test_bad_preflight_status_rejected(self) -> None:
        value = self._valid()
        value["candidates"][0]["preflight_status"] = "maybe"
        with self.assertRaises(ProtocolError):
            self.registry.validate("candidate-set", value)

    def test_missing_digest_rejected(self) -> None:
        value = self._valid()
        value["candidates"][0].pop("resolved_map_digest")
        with self.assertRaises(ProtocolError):
            self.registry.validate("candidate-set", value)


class CompileVariantsTests(unittest.TestCase):
    """compile_variants compiles each external variant deterministically and never selects."""

    def setUp(self) -> None:
        self.registry = SchemaRegistry()
        self.compiler = MapCandidateCompiler(path_guard=mock.MagicMock(), registry=self.registry)
        self.request = {"run_id": "run-one", "project_id": "project-one",
                        "template": {"kind": "map-scenario", "id": "general-thematic-map", "version": "3.0.0"}}
        self.contracts = {"scenario": {"embedded": {}}}
        self.seen_contracts = []

    def _stub_compile(self, status="passed"):
        def fake_compile(request, intent, plan, bundle, installation, contracts, font_path):
            self.seen_contracts.append(deepcopy(contracts))
            return {
                "candidate": {"candidate_id": "candidate-run-one", "execution": {},
                              "execution_digest": D, "variant_marker": request.get("output_profile")},
                "scene": {"scene_id": "scene", "marker": request.get("revised_cartography")},
                # preflight computed against the pre-rewrite candidate_id; compile_variants
                # must re-run check_candidate so subject_digest binds the rewritten id.
                "preflight": {"status": status, "report_id": "stale", "subject_digest": "stale"},
            }
        return fake_compile

    @staticmethod
    def _stub_check(status):
        def fake_check(request, candidate, scene, contracts, *, bundle=None):
            return {"status": status, "report_id": "preflight-one",
                    "subject_digest": sha256_digest(candidate)}
        return fake_check

    def _run(self, variants, status="passed"):
        with mock.patch.object(self.compiler, "compile", side_effect=self._stub_compile(status)), \
                mock.patch.object(self.compiler, "check_candidate", side_effect=self._stub_check(status)):
            return self.compiler.compile_variants(
                self.request, {}, {}, {}, {}, deepcopy(self.contracts), Path("font.ttf"), variants)

    def test_each_variant_gets_suffixed_candidate_id(self) -> None:
        result = self._run([{"variant_id": "variant-a"}, {"variant_id": "variant-b"}])
        ids = [c["candidate_id"] for c in result["candidate_set"]["candidates"]]
        self.assertEqual(ids, ["candidate-run-one-variant-a", "candidate-run-one-variant-b"])
        self.assertEqual(set(result["compiled"]), {"variant-a", "variant-b"})

    def test_preflight_recomputed_after_id_rewrite(self) -> None:
        # Guards the drift fix: the report's subject_digest must bind the rewritten candidate.
        result = self._run([{"variant_id": "variant-a"}])
        compiled = result["compiled"]["variant-a"]
        self.assertEqual(compiled["candidate"]["candidate_id"], "candidate-run-one-variant-a")
        self.assertEqual(compiled["preflight"]["subject_digest"], sha256_digest(compiled["candidate"]))
        self.assertNotEqual(compiled["preflight"]["subject_digest"], "stale")

    def test_candidate_set_carries_no_selection(self) -> None:
        result = self._run([{"variant_id": "variant-a"}, {"variant_id": "variant-b"}])
        for forbidden in ("selected", "selected_candidate_id", "ranking", "best"):
            self.assertNotIn(forbidden, result["candidate_set"])

    def test_empty_variants_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CANDIDATE_VARIANTS_REQUIRED"):
            self._run([])

    def test_duplicate_variant_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CANDIDATE_VARIANT_DUPLICATE"):
            self._run([{"variant_id": "variant-a"}, {"variant_id": "variant-a"}])

    def test_variant_limit_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CANDIDATE_VARIANTS_LIMIT"):
            self._run([{"variant_id": f"variant-{i}"} for i in range(9)])

    def test_design_overrides_are_injected_per_variant(self) -> None:
        self._run([{"variant_id": "variant-a", "revised_cartography": {"typography": {"title_pt": 18}}},
                   {"variant_id": "variant-b", "output_profile": {"width_mm": 400}}])
        self.assertEqual(self.seen_contracts[0]["scenario"]["embedded"]["style"],
                         {"typography": {"title_pt": 18}})
        self.assertEqual(self.seen_contracts[1]["scenario"]["embedded"]["layout"]["canvas"]["width"], 400)

    def test_preflight_status_is_recorded_per_candidate(self) -> None:
        result = self._run([{"variant_id": "variant-a"}], status="failed")
        self.assertEqual(result["candidate_set"]["candidates"][0]["preflight_status"], "failed")

    def test_deterministic_except_timestamp(self) -> None:
        first = self._run([{"variant_id": "variant-a"}, {"variant_id": "variant-b"}])["candidate_set"]
        self.seen_contracts.clear()
        second = self._run([{"variant_id": "variant-a"}, {"variant_id": "variant-b"}])["candidate_set"]
        first.pop("created_at")
        second.pop("created_at")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
