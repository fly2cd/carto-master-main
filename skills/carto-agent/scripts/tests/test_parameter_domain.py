# -*- coding: utf-8 -*-
"""Phase 1 finite parameter domain + candidate assessment tests (design §6.7, N05/F06/F07)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.design_requirements import (
    assess_candidate, evaluate_predicate, layout_fact_view, resolve_requirement)
from carto_core.compiler.parameter_domain import (
    case_execution_admission, check_parameter_domain, layout_execution_admission,
    legacy_grid_allowed_cases)
from carto_core.compiler.layout import LayoutResolver
from carto_core.artifacts import file_digest
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.repository.template_repository import TemplateRepository
from tests.fixtures.schema_cases import D, VALID_CASES
from tests.test_design_requirements import FACT_A3_DUAL, REQ_A3_DUAL

ALLOWED = [{"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "outside"}]


class ParameterDomainTests(unittest.TestCase):
    def test_legacy_grid_domain_recognized_as_outside_cases(self):
        contract = {"grid": {"allowed_shapes": [[1, 2], [1, 1]],
                             "legend_modes": ["independent", "shared"]}}
        cases = legacy_grid_allowed_cases(contract)
        self.assertEqual(4, len(cases))
        self.assertTrue(all(c["legend_placement"] == "outside" for c in cases))

    def test_full_tuple_membership_satisfied(self):
        p = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "outside"}
        self.assertEqual("satisfied", check_parameter_domain(p, ALLOWED))

    def test_out_of_domain_violated_N05(self):
        p = {"rows": 1, "columns": 3, "legend_mode": "independent", "legend_placement": "outside"}
        self.assertEqual("violated", check_parameter_domain(p, ALLOWED))

    def test_fieldwise_legal_but_combo_not_allowed_F07(self):
        p = {"rows": 1, "columns": 2, "legend_mode": "shared", "legend_placement": "outside"}
        self.assertEqual("violated", check_parameter_domain(p, ALLOWED))

    def test_no_domain_or_no_parameters_is_unknown(self):
        p = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "outside"}
        self.assertEqual("unknown", check_parameter_domain(p, []))
        self.assertEqual("unknown", check_parameter_domain(None, ALLOWED))

    def test_inside_case_not_implemented_until_phase3(self):
        inside = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "inside"}
        self.assertEqual("not-implemented", case_execution_admission(inside, ALLOWED))

    def test_implemented_case_allowed(self):
        outside = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "outside"}
        self.assertEqual("allowed", case_execution_admission(outside, ALLOWED))


class AssessCandidateTests(unittest.TestCase):
    def test_usable_when_all_dimensions_pass(self):
        result = assess_candidate(REQ_A3_DUAL, FACT_A3_DUAL, parameter_status="not-applicable",
                                  execution_admission="allowed", validation_coverage="covered")
        self.assertTrue(result["usable"])
        self.assertEqual("satisfied", result["structural"]["aggregate"])

    def test_structural_satisfied_but_not_implemented_not_usable_F06(self):
        result = assess_candidate(REQ_A3_DUAL, FACT_A3_DUAL, parameter_status="not-applicable",
                                  execution_admission="not-implemented", validation_coverage="covered")
        self.assertEqual("satisfied", result["structural"]["aggregate"])
        self.assertFalse(result["usable"])

    def test_needs_validation_not_usable(self):
        result = assess_candidate(REQ_A3_DUAL, FACT_A3_DUAL, parameter_status="not-applicable",
                                  execution_admission="allowed", validation_coverage="needs-validation")
        self.assertFalse(result["usable"])

    def test_structural_violated_not_usable(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]
        result = assess_candidate(REQ_A3_DUAL, fact, execution_admission="allowed",
                                  validation_coverage="covered")
        self.assertFalse(result["usable"])

    def test_parameter_violated_not_usable(self):
        result = assess_candidate(REQ_A3_DUAL, FACT_A3_DUAL, parameter_status="violated",
                                  execution_admission="allowed", validation_coverage="covered")
        self.assertFalse(result["usable"])

    def test_default_unknown_dimensions_not_usable(self):
        result = assess_candidate(REQ_A3_DUAL, FACT_A3_DUAL)
        self.assertFalse(result["usable"])
        self.assertEqual("unknown", result["execution_admission"])


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.ref = deepcopy(VALID_CASES["design-resolution-result"]["assessments"][0]["candidate_ref"])

    def _assessment(self, fact=None, **kw):
        a = assess_candidate(REQ_A3_DUAL, fact or FACT_A3_DUAL, **kw)
        a["candidate_ref"] = deepcopy(self.ref)
        return a

    def test_usable_candidate_reuse(self):
        a = self._assessment(parameter_status="not-applicable", execution_admission="allowed",
                             validation_coverage="covered")
        result = resolve_requirement(REQ_A3_DUAL, [a])
        self.assertEqual("reuse", result["branch"])
        self.registry.validate("design-resolution-result", result)

    def test_usable_parameterized_instantiate(self):
        a = self._assessment(parameter_status="satisfied", execution_admission="allowed",
                             validation_coverage="covered")
        self.assertEqual("instantiate", resolve_requirement(REQ_A3_DUAL, [a])["branch"])

    def test_no_candidates_create(self):
        self.assertEqual("create", resolve_requirement(REQ_A3_DUAL, [])["branch"])

    def test_structural_satisfied_not_implemented_unsupported(self):
        a = self._assessment(execution_admission="not-implemented", validation_coverage="covered")
        self.assertEqual("unsupported", resolve_requirement(REQ_A3_DUAL, [a])["branch"])

    def test_unknown_clarify(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["roles_complete"] = False
        self.assertEqual("clarify", resolve_requirement(REQ_A3_DUAL, [self._assessment(fact)])["branch"])

    def test_violated_approximate_derive(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]
        a = self._assessment(fact, execution_admission="allowed", validation_coverage="covered")
        self.assertEqual("derive", resolve_requirement(REQ_A3_DUAL, [a])["branch"])

    def test_search_incomplete(self):
        self.assertEqual("search-incomplete",
                         resolve_requirement(REQ_A3_DUAL, [], search_complete=False)["branch"])


class CapabilityAdmissionTests(unittest.TestCase):
    CAP = {"output_profile": {"width_mm": 297, "height_mm": 210},
           "output_constraints": {"max_width_mm": 420, "max_height_mm": 297}}

    def _fact(self, w, h, inside=False):
        frames = [{"id": "map", "content_id": "v", "type": "map", "content_role": "main-map",
                   "bounds": [10, 25, 200, 150]}]
        if inside:
            frames.append({"id": "leg", "content_id": "l", "type": "legend",
                           "content_role": "legend-group", "inside_frame": "map",
                           "view_ids": ["v"], "bounds": [15, 30, 50, 40]})
        return {"canvas": {"width_mm": w, "height_mm": h}, "frames": frames, "roles_complete": True}

    def test_a4_profile_allowed(self):
        self.assertEqual("allowed", layout_execution_admission(self._fact(297, 210), self.CAP))

    def test_a3_upper_bound_not_full_chain_admission(self):
        self.assertEqual("not-implemented", layout_execution_admission(self._fact(420, 297), self.CAP))

    def test_beyond_constraints_forbidden(self):
        self.assertEqual("forbidden", layout_execution_admission(self._fact(500, 300), self.CAP))

    def test_inside_legend_not_implemented(self):
        self.assertEqual("not-implemented", layout_execution_admission(self._fact(297, 210, inside=True), self.CAP))

    def test_unknown_canvas_unknown(self):
        self.assertEqual("unknown", layout_execution_admission({"canvas": {}, "frames": []}, self.CAP))

    def test_grid_instantiation_propagates_roles_N04(self):
        from carto_core.scenarios.general_thematic.raster import layout_contract
        resolved = LayoutResolver().resolve(layout_contract(), 300,
                                            parameters={"rows": 1, "columns": 2, "legend_mode": "independent"})
        fact = layout_fact_view(resolved)
        self.assertTrue(fact["roles_complete"])
        status, actual, _ = evaluate_predicate({"kind": "count", "role": "main-map", "op": "eq", "value": 2}, fact)
        self.assertEqual("satisfied", status)
        self.assertEqual(2, actual)


class CliResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="resolve-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.req_path = self.root / "requirement.json"
        self.req_path.write_text(json.dumps(REQ_A3_DUAL), encoding="utf-8")
        self.guard = PathGuard([self.root])
        self.repository = TemplateRepository(path_guard=self.guard, root=self.repo,
                                             repository_scope="local:test")

    def _args(self):
        from argparse import Namespace
        return Namespace(template_command="resolve", requirement=str(self.req_path),
                         repository_root=str(self.repo), repository_scope="local:test",
                         allowed_root=[str(self.root)])

    def _publish_layout(self, template_id, contract):
        contract = deepcopy(contract)
        contract["layout_id"] = template_id
        staging = self.root / f"staging-{template_id}"
        (staging / "contracts").mkdir(parents=True)
        (staging / "contracts" / "layout.yaml").write_text(json.dumps(contract), encoding="utf-8")
        lock = deepcopy(VALID_CASES["dependency-lock"])
        (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
        files = ["dependencies.lock.yaml", "contracts/layout.yaml"]
        manifest = {"schema_version": 1,
                    "package": {"namespace": "local", "kind": "map-layout", "id": template_id,
                                "version": "1.0.0", "status": "published", "summary": "Synthetic resolve fixture"},
                    "dependency_lock": "dependencies.lock.yaml", "files": files, "checksums": {}}
        for relative in files:
            manifest["checksums"][relative] = file_digest(staging / relative)
        (staging / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
        manifest_digest = file_digest(staging / "manifest.yaml")
        lines = [f"{manifest['checksums'][r][7:]}  {r}" for r in files]
        lines.append(f"{manifest_digest[7:]}  manifest.yaml")
        (staging / "checksums.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
        snapshot = {"package_digest": file_digest(staging / "checksums.sha256"),
                    "manifest_digest": manifest_digest, "manifest": manifest, "dependency_lock_digest": D}
        return self.repository.publish(
            package_root=staging, snapshot=snapshot, evidence={"evidence_digest": D},
            approval={"synthetic": "resolve-test", "template_id": template_id},
            idempotency_key=f"resolve-{template_id}-0001",
            publication_object={"schema_version": 1, "run_id": "resolve-run", "request_digest": D,
                                "package_ref": {"kind": "map-layout", "id": template_id,
                                                "version": "1.0.0", "digest": snapshot["package_digest"]},
                                "evidence_ref": {"id": "template-validation-evidence", "version": "1.0.0",
                                                 "digest": D, "uri": "evidence.yaml"},
                                "repository_scope": "local:test", "repository_root": self.repo.as_posix(),
                                "idempotency_key": f"resolve-{template_id}-0001"})

    def test_empty_library_resolve_create(self):
        from carto_core.cli import match_cmd
        result = match_cmd.handle(self._args())
        self.assertEqual("create", result["resolution"]["branch"])
        SchemaRegistry().validate("design-resolution-result", result["resolution"])

    def test_unsupported_scope_rejected(self):
        from carto_core.cli import match_cmd
        req = deepcopy(REQ_A3_DUAL)
        req["object_scope"] = "scenario"
        self.req_path.write_text(json.dumps(req), encoding="utf-8")
        with self.assertRaisesRegex(ProtocolError, "REQUIREMENT_SCOPE_UNSUPPORTED"):
            match_cmd.handle(self._args())

    def test_published_single_map_candidate_assessed(self):
        from carto_core.cli import match_cmd
        contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
        contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
        contract["frames"] = [
            {"id": "map", "content_id": "main-view", "type": "map", "content_role": "main-map",
             "bounds": [10, 25, 215, 175], "coordinate_space": "page", "overflow_policy": "clip"},
            {"id": "title", "content_id": "title", "type": "title", "content_role": "title",
             "bounds": [10, 10, 277, 15], "coordinate_space": "page", "overflow_policy": "reject"},
        ]
        self._publish_layout("cand-single", contract)
        result = match_cmd.handle(self._args())["resolution"]
        SchemaRegistry().validate("design-resolution-result", result)
        self.assertEqual(1, len(result["assessments"]))
        # REQ_A3_DUAL needs 2 main-maps; a single-map candidate violates count -> derive suggestion.
        self.assertEqual("violated", result["assessments"][0]["structural_aggregate"])
        self.assertEqual("derive", result["branch"])

    def test_published_a4_single_map_satisfying_requirement_reuse(self):
        from carto_core.cli import match_cmd
        req = {"schema_version": 1, "requirement_id": "req-a4", "revision": 1, "object_scope": "layout",
               "context": {"business_scene": "general_thematic_mapping", "geometry": "raster"},
               "conditions": [
                   {"id": "w", "strength": "hard", "source_ref": "u",
                    "predicate": {"kind": "measure", "path": "/canvas/width", "op": "eq", "value": 297, "unit": "mm"}},
                   {"id": "h", "strength": "hard", "source_ref": "u",
                    "predicate": {"kind": "measure", "path": "/canvas/height", "op": "eq", "value": 210, "unit": "mm"}},
                   {"id": "o", "strength": "hard", "source_ref": "u",
                    "predicate": {"kind": "enum", "path": "/canvas/orientation", "op": "eq", "value": "landscape"}},
                   {"id": "c", "strength": "hard", "source_ref": "u",
                    "predicate": {"kind": "count", "role": "main-map", "op": "eq", "value": 1}}]}
        self.req_path.write_text(json.dumps(req), encoding="utf-8")
        contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
        contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
        contract["frames"] = [
            {"id": "map", "content_id": "main-view", "type": "map", "content_role": "main-map",
             "bounds": [10, 25, 215, 175], "coordinate_space": "page", "overflow_policy": "clip"},
            {"id": "title", "content_id": "title", "type": "title", "content_role": "title",
             "bounds": [10, 10, 277, 15], "coordinate_space": "page", "overflow_policy": "reject"},
        ]
        self._publish_layout("cand-a4", contract)
        result = match_cmd.handle(self._args())["resolution"]
        self.assertEqual("reuse", result["branch"])
        self.assertTrue(result["assessments"][0]["usable"])
        self.assertEqual("allowed", result["assessments"][0]["execution_admission"])


if __name__ == "__main__":
    unittest.main()