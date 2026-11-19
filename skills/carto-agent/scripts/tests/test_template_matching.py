"""S0 advisory segment matching: pure algorithms, policy gate, read-only retrieval.

All repository fixtures are synthetic packages published into TemporaryDirectory
through the real TemplateRepository.publish path; no bundled library assets,
no real business data, no approvals. Matching is advisory: these tests also
assert it never mutates repository state.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core import cli
from carto_core.artifacts import file_digest
from carto_core.errors import ProtocolError
from carto_core.repository.template_matching import (
    MatchingPolicy,
    bounds_iou,
    default_policy_path,
    delta_e76,
    jaccard,
    levenshtein_ratio,
    rank_segment_candidates,
    score_layout,
    score_style,
)
from carto_core.repository.template_repository import TemplateRepository
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from tests.fixtures.schema_cases import D, VALID_CASES


def make_policy(**overrides) -> MatchingPolicy:
    document = deepcopy(VALID_CASES["template-matching-policy"])
    document.update(overrides)
    return MatchingPolicy(
        version=document["version"],
        confirmation_status=document["confirmation_status"],
        match_threshold=float(document["match_threshold"]),
        color_delta_e_max=float(document["color_delta_e_max"]),
        defaults_relative_deviation_max=float(document["defaults_relative_deviation_max"]),
        capacity_relative_deviation_max=float(document["capacity_relative_deviation_max"]),
    )


class MatchingPrimitiveTests(unittest.TestCase):
    def test_delta_e76_known_values(self) -> None:
        self.assertEqual(delta_e76("#000000", "#000000"), 0.0)
        # CIELAB anchors: L*(black)=0, L*(white)=100, a*=b*=0 for both.
        self.assertAlmostEqual(delta_e76("#000000", "#FFFFFF"), 100.0, places=4)
        # Red vs a one-step red: small perceptual distance, not the sRGB 1.0.
        self.assertLess(delta_e76("#FF0000", "#FE0000"), 1.0)
        self.assertGreater(delta_e76("#FF0000", "#FE0000"), 0.0)
        self.assertAlmostEqual(delta_e76("#FF0000", "#00FF00"),
                               delta_e76("#00FF00", "#FF0000"))

    def test_delta_e76_perceptual_ranking_anchor(self) -> None:
        # Regression anchor from the design evaluation (_eval_color_prov.py):
        # the sRGB prototype ranked accent-silver closer to the brand primary
        # blue than the light brand blue; perceptually the order is reversed.
        primary, light_blue, silver = "#3296FA", "#B9E1FF", "#898C8E"
        self.assertLess(delta_e76(primary, light_blue), delta_e76(primary, silver))

    def test_color_tolerance_semantics_are_perceptual(self) -> None:
        # 4.0 ΔE76 is a perceptual closeness band: near-identical blues pass,
        # clearly different hues fail. In the old sRGB space even the closest
        # distinct brand colours were ~40 units apart and nothing ever passed.
        policy = make_policy()
        self.assertLessEqual(delta_e76("#3296FA", "#3395F9"), policy.color_delta_e_max)
        self.assertGreater(delta_e76("#3296FA", "#C6A86E"), policy.color_delta_e_max)

    def test_invalid_hex_rejected(self) -> None:
        for value in ("#FFF", "GGGGGG", "#12345", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                delta_e76(value, "#000000")

    def test_levenshtein_ratio_known_values(self) -> None:
        self.assertEqual(levenshtein_ratio("", ""), 1.0)
        self.assertEqual(levenshtein_ratio("abc", ""), 0.0)
        self.assertEqual(levenshtein_ratio("kitten", "sitting"), 1.0 - 3 / 7)
        self.assertEqual(levenshtein_ratio("same", "same"), 1.0)

    def test_jaccard_known_values(self) -> None:
        self.assertEqual(jaccard(set(), set()), 1.0)
        self.assertEqual(jaccard({"a"}, set()), 0.0)
        self.assertEqual(jaccard({"a", "b"}, {"b", "c"}), 1 / 3)

    def test_bounds_iou_known_values(self) -> None:
        self.assertEqual(bounds_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        self.assertEqual(bounds_iou([0, 0, 10, 10], [20, 20, 10, 10]), 0.0)
        # half-overlap: inter 50, union 150
        self.assertAlmostEqual(bounds_iou([0, 0, 10, 10], [5, 0, 10, 10]), 1 / 3)
        self.assertEqual(bounds_iou([0, 0, 0, 10], [0, 0, 10, 10]), 0.0)


class SegmentScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = make_policy()
        self.cartography = deepcopy(VALID_CASES["cartography"])
        self.layout = deepcopy(VALID_CASES["layout"])

    def test_identical_segments_score_one(self) -> None:
        self.assertAlmostEqual(score_style(self.cartography, deepcopy(self.cartography), self.policy), 1.0)
        self.assertAlmostEqual(score_layout(self.layout, deepcopy(self.layout), self.policy), 1.0)

    def test_style_disqualifiers(self) -> None:
        other_lang = deepcopy(self.cartography)
        other_lang["visual_language"] = "editorial"
        self.assertIsNone(score_style(self.cartography, other_lang, self.policy))
        other_colors = deepcopy(self.cartography)
        other_colors["symbolization"]["color_system"] = "qualitative"
        self.assertIsNone(score_style(self.cartography, other_colors, self.policy))

    def test_style_defaults_deviation_uses_policy(self) -> None:
        changed = deepcopy(self.cartography)
        changed["defaults"]["line_width_mm"] = self.cartography["defaults"]["line_width_mm"] * 2
        strict = make_policy(defaults_relative_deviation_max=0.0)
        loose = make_policy(defaults_relative_deviation_max=1.0)
        self.assertLess(score_style(self.cartography, changed, strict),
                        score_style(self.cartography, changed, loose))

    def test_layout_disqualifiers(self) -> None:
        other_canvas = deepcopy(self.layout)
        other_canvas["canvas"]["width"] = 100
        self.assertIsNone(score_layout(self.layout, other_canvas, self.policy))
        other_category = deepcopy(self.layout)
        other_category["category"] = "poster"
        self.assertIsNone(score_layout(self.layout, other_category, self.policy))

    def test_layout_shifted_frames_lower_score(self) -> None:
        shifted = deepcopy(self.layout)
        shifted["frames"][0]["bounds"] = [200, 200, 100, 60]
        score = score_layout(self.layout, shifted, self.policy)
        self.assertIsNotNone(score)
        self.assertLess(score, 1.0)

    def test_scores_stay_within_unit_interval(self) -> None:
        for scorer, segment in ((score_style, self.cartography), (score_layout, self.layout)):
            score = scorer(segment, deepcopy(segment), self.policy)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = make_policy()
        self.layout = deepcopy(VALID_CASES["layout"])

    def _entry(self, template_id: str, namespace: str = "local") -> dict:
        return {"namespace": namespace, "kind": "map-layout", "id": template_id,
                "version": "1.0.0", "digest": D}

    def test_identical_candidate_matches_and_disqualified_excluded(self) -> None:
        disqualified = deepcopy(self.layout)
        disqualified["category"] = "poster"
        candidates = [(self._entry("same-layout"), deepcopy(self.layout)),
                      (self._entry("other-category"), disqualified)]
        ranked = rank_segment_candidates("map-layout", self.layout, candidates, self.policy)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["template_ref"]["id"], "same-layout")
        self.assertTrue(ranked[0]["matched"])
        self.assertAlmostEqual(ranked[0]["score"], 1.0)

    def test_threshold_comes_from_policy(self) -> None:
        shifted = deepcopy(self.layout)
        shifted["frames"][0]["bounds"] = [200, 200, 100, 60]
        candidates = [(self._entry("shifted-layout"), shifted)]
        strict = make_policy(match_threshold=1.0)
        ranked = rank_segment_candidates("map-layout", self.layout, candidates, strict)
        self.assertEqual(len(ranked), 1)
        self.assertFalse(ranked[0]["matched"])
        loose = make_policy(match_threshold=0.0)
        self.assertTrue(rank_segment_candidates("map-layout", self.layout, candidates, loose)[0]["matched"])

    def test_tie_order_is_deterministic(self) -> None:
        candidates = [(self._entry("z-layout"), deepcopy(self.layout)),
                      (self._entry("a-layout"), deepcopy(self.layout))]
        ranked = rank_segment_candidates("map-layout", self.layout, candidates, self.policy)
        self.assertEqual([item["template_ref"]["id"] for item in ranked], ["a-layout", "z-layout"])
        self.assertNotIn("_sort", ranked[0])

    def test_unsupported_kind_rejected(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            rank_segment_candidates("map-scenario", self.layout, [], self.policy)
        self.assertEqual(caught.exception.code, "SEGMENT_KIND_UNSUPPORTED")


class MatchingPolicyTests(unittest.TestCase):
    def test_packaged_policy_is_valid_and_pending(self) -> None:
        policy = MatchingPolicy.load()
        self.assertEqual(policy.confirmation_status, "pending-business-review")
        self.assertEqual(policy.match_threshold, 0.80)
        self.assertTrue(default_policy_path().is_file())

    def test_tampered_policy_rejected(self) -> None:
        registry = SchemaRegistry()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.yaml"
            for mutation in ({"match_threshold": 1.5}, {"unknown_lever": True}, {"confirmation_status": "approved"}):
                document = deepcopy(VALID_CASES["template-matching-policy"])
                document.update(mutation)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                    MatchingPolicy.load(path, registry)


class RepositoryRetrievalTests(unittest.TestCase):
    """Synthetic map-layout packages published through the real publish path."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.guard = PathGuard([self.root])
        self.repo_root = self.root / "repo"
        self.repository = TemplateRepository(path_guard=self.guard, root=self.repo_root,
                                             repository_scope="local:test")
        self.registry = self.repository.registry

    def publish_layout(self, template_id: str, contract: dict | None = None, *,
                       with_contract: bool = True) -> dict:
        contract = deepcopy(VALID_CASES["layout"]) if contract is None else contract
        contract["layout_id"] = template_id
        staging = self.root / f"staging-{template_id}"
        (staging / "contracts").mkdir(parents=True)
        # manifest.files excludes manifest.yaml itself; its digest is tracked by the index.
        files = ["dependencies.lock.yaml"]
        if with_contract:
            (staging / "contracts" / "layout.yaml").write_text(json.dumps(contract), encoding="utf-8")
            files.append("contracts/layout.yaml")
        lock = deepcopy(VALID_CASES["dependency-lock"])
        (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "package": {"namespace": "local", "kind": "map-layout", "id": template_id,
                        "version": "1.0.0", "status": "published", "summary": "Synthetic S0 matching fixture"},
            "dependency_lock": "dependencies.lock.yaml",
            "files": files,
            "checksums": {},
        }
        for relative in files:
            manifest["checksums"][relative] = file_digest(staging / relative)
        (staging / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
        manifest_digest = file_digest(staging / "manifest.yaml")
        checksum_lines = [f"{manifest['checksums'][relative][7:]}  {relative}" for relative in files]
        checksum_lines.append(f"{manifest_digest[7:]}  manifest.yaml")
        (staging / "checksums.sha256").write_text("\n".join(sorted(checksum_lines)) + "\n", encoding="utf-8")
        snapshot = {"package_digest": file_digest(staging / "checksums.sha256"),
                    "manifest_digest": manifest_digest, "manifest": manifest,
                    "dependency_lock_digest": D}
        evidence = {"evidence_digest": D}
        approval = {"synthetic": "s0-matching-test", "template_id": template_id}
        return self.repository.publish(package_root=staging, snapshot=snapshot, evidence=evidence,
                                       approval=approval, idempotency_key=f"s0-matching-{template_id}-0001")

    def test_empty_repository_returns_no_candidates(self) -> None:
        self.assertEqual(self.repository.segment_candidates(kind="map-layout"), [])

    def test_published_contract_is_retrieved_and_scored(self) -> None:
        self.publish_layout("test-layout")
        candidates = self.repository.segment_candidates(kind="map-layout")
        self.assertEqual(len(candidates), 1)
        entry, contract = candidates[0]
        self.assertEqual(entry["id"], "test-layout")
        self.assertEqual(contract["layout_id"], "test-layout")
        ranked = rank_segment_candidates("map-layout", VALID_CASES["layout"], candidates, make_policy())
        self.assertTrue(ranked[0]["matched"])

    def test_other_kinds_are_not_retrieved(self) -> None:
        self.publish_layout("test-layout")
        self.assertEqual(self.repository.segment_candidates(kind="map-style"), [])

    def test_missing_contract_file_is_skipped(self) -> None:
        self.publish_layout("no-contract", with_contract=False)
        self.assertEqual(self.repository.segment_candidates(kind="map-layout"), [])

    def test_corrupted_package_fails_closed(self) -> None:
        self.publish_layout("test-layout")
        contract_path = next(self.repo_root.glob("packages/local/map-layout/test-layout/1.0.0/contracts/layout.yaml"))
        contract_path.write_text(json.dumps({**VALID_CASES["layout"], "category": "poster"}), encoding="utf-8")
        with self.assertRaises(ProtocolError) as caught:
            self.repository.segment_candidates(kind="map-layout")
        self.assertEqual(caught.exception.code, "PUBLISHED_PACKAGE_CORRUPT")

    def test_unsupported_kind_rejected(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            self.repository.segment_candidates(kind="map-scenario")
        self.assertEqual(caught.exception.code, "SEGMENT_KIND_UNSUPPORTED")

    def test_retrieval_does_not_mutate_index(self) -> None:
        self.publish_layout("test-layout")
        before = self.repository.index_path.read_bytes()
        self.repository.segment_candidates(kind="map-layout")
        self.assertEqual(self.repository.index_path.read_bytes(), before)


class CliMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo_root = self.root / "repo"
        self.repo_root.mkdir()

    def run_cli(self, request_document: dict) -> tuple[int, dict]:
        request_path = self.root / "match-request.json"
        request_path.write_text(json.dumps(request_document), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["template", "match", str(request_path),
                "--repository-root", str(self.repo_root),
                "--repository-scope", "local:test",
                "--allowed-root", str(self.root)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        stream = stdout.getvalue() if code == 0 else stderr.getvalue()
        return code, json.loads(stream)

    def test_empty_library_returns_valid_empty_result(self) -> None:
        request = deepcopy(VALID_CASES["template-match-request"])
        code, payload = self.run_cli(request)
        self.assertEqual(code, 0)
        result = payload["match"]
        SchemaRegistry().validate("template-match-result", result)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["confirmation_status"], "pending-business-review")

    def test_unknown_request_field_rejected(self) -> None:
        request = deepcopy(VALID_CASES["template-match-request"])
        request["auto_select"] = True
        code, payload = self.run_cli(request)
        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "SCHEMA_VALIDATION_FAILED")

    def test_segment_must_match_kind_contract(self) -> None:
        request = {"schema_version": 1, "kind": "map-layout",
                   "segment": deepcopy(VALID_CASES["cartography"])}
        code, payload = self.run_cli(request)
        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "SCHEMA_VALIDATION_FAILED")

    def test_scenario_kind_rejected(self) -> None:
        request = {"schema_version": 1, "kind": "map-scenario",
                   "segment": deepcopy(VALID_CASES["layout"])}
        code, payload = self.run_cli(request)
        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "SCHEMA_VALIDATION_FAILED")

    def test_match_does_not_create_workflow_state(self) -> None:
        request = deepcopy(VALID_CASES["template-match-request"])
        code, _ = self.run_cli(request)
        self.assertEqual(code, 0)
        # An empty library is never even materialised as an index file.
        self.assertEqual(list(self.repo_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()