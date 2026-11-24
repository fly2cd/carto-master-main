# -*- coding: utf-8 -*-
"""Phase 2 four-branch creation orchestration tests (design §7/§7.1/§12.1).

Covers draft/version separation (derive_draft never bumps a business version or reserves a
library identity), the four-branch execution decision (reuse/instantiate return a published
ref; derive/create produce a project draft; clarify/unsupported/search-incomplete stop), and
fail-closed input/binding guards. CLI orchestrate reuses the read-only resolve path.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.compiler.creation_orchestration import orchestrate_creation
from carto_core.compiler.design_requirements import assess_candidate, resolve_requirement
from carto_core.compiler.template_derivation import derive_draft, draft_identity
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.repository.template_repository import TemplateRepository
from carto_core.artifacts import file_digest
from tests.fixtures.schema_cases import D, VALID_CASES
from tests.test_design_requirements import FACT_A3_DUAL, REQ_A3_DUAL


class DeriveDraftTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.base = deepcopy(VALID_CASES["style"])
        self.base_ref = {"kind": "map-style", "id": self.base["style_id"],
                         "version": self.base["version"], "digest": D}
        self.change = {"typography": {**self.base["typography"], "title_pt": 20}}

    def _derive(self, change=None, allowed=("typography",), revision=1):
        return derive_draft(self.base, self.change if change is None else change,
                            schema="style", id_field="style_id", kind="map-style",
                            allowed_keys=allowed, base_ref=self.base_ref,
                            draft_id="demo", revision=revision, registry=self.registry)

    def test_draft_identity_is_project_scoped_not_business_version(self):
        new, prov = self._derive()
        self.assertEqual("draft-demo", new["style_id"])
        self.assertEqual("0.0.0-draft.r1", new["version"])
        self.assertEqual(20, new["typography"]["title_pt"])
        # base contract is untouched; no business patch bump.
        self.assertEqual(self.base["version"], VALID_CASES["style"]["version"])
        self.registry.validate("style", new)

    def test_provenance_separates_package_ref_and_contract_digest(self):
        new, prov = self._derive()
        self.assertEqual(self.base_ref, prov["base_ref"])
        self.assertEqual(sha256_digest(self.base), prov["base_contract_digest"])
        self.assertEqual(sha256_digest(new), prov["content_digest"])
        # bare contract digest must not impersonate the package digest.
        self.assertNotEqual(prov["base_contract_digest"], prov["base_ref"]["digest"])

    def test_identity_key_forbidden_even_if_allowed(self):
        with self.assertRaisesRegex(ProtocolError, "DERIVATION_KEY_FORBIDDEN"):
            self._derive(change={"version": "9.9.9"}, allowed=("typography", "version"))
        with self.assertRaisesRegex(ProtocolError, "DERIVATION_KEY_FORBIDDEN"):
            self._derive(change={"style_id": "hijack"}, allowed=("typography", "style_id"))

    def test_disallowed_key_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "DERIVATION_KEY_FORBIDDEN"):
            self._derive(change={"visual_language": "editorial"})

    def test_empty_change_set_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "DERIVATION_CHANGE_SET_EMPTY"):
            self._derive(change={})

    def test_invalid_revision_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "DRAFT_REVISION_INVALID"):
            self._derive(revision=0)
        with self.assertRaisesRegex(ProtocolError, "DRAFT_REVISION_INVALID"):
            draft_identity("demo", True)


class OrchestrateCreationTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.ref = deepcopy(VALID_CASES["design-resolution-result"]["assessments"][0]["candidate_ref"])

    def _assessment(self, fact=None, **kw):
        a = assess_candidate(REQ_A3_DUAL, fact or FACT_A3_DUAL, **kw)
        a["candidate_ref"] = deepcopy(self.ref)
        return a

    def _resolution(self, assessments, **kw):
        return resolve_requirement(REQ_A3_DUAL, assessments, **kw)

    def _orchestrate(self, resolution, **kw):
        return orchestrate_creation(REQ_A3_DUAL, resolution, draft_id="demo", revision=1,
                                    registry=self.registry, **kw)

    def test_reuse_returns_published_ref_no_draft(self):
        res = self._resolution([self._assessment(parameter_status="not-applicable",
                                                 execution_admission="allowed", validation_coverage="covered")])
        out = self._orchestrate(res)
        self.assertEqual("reuse", out["branch"])
        self.assertEqual("return-published-ref", out["action"])
        self.assertEqual(self.ref, out["published_ref"])
        self.assertNotIn("draft_ref", out)
        self.registry.validate("design-resolution-result", out)

    def test_instantiate_returns_published_ref(self):
        res = self._resolution([self._assessment(parameter_status="satisfied",
                                                 execution_admission="allowed", validation_coverage="covered")])
        out = self._orchestrate(res)
        self.assertEqual("instantiate", out["branch"])
        self.assertEqual("return-published-ref", out["action"])

    def test_stop_branches_do_not_create(self):
        cases = {
            "unsupported": [self._assessment(execution_admission="not-implemented", validation_coverage="covered")],
            "clarify": [self._assessment({**deepcopy(FACT_A3_DUAL), "roles_complete": False})],
        }
        for branch, assessments in cases.items():
            out = self._orchestrate(self._resolution(assessments))
            self.assertEqual(branch, out["branch"])
            self.assertEqual("stop", out["action"])
            self.assertNotIn("draft_ref", out)
            self.assertNotIn("published_ref", out)
        out = self._orchestrate(self._resolution([], search_complete=False))
        self.assertEqual("search-incomplete", out["branch"])
        self.assertEqual("stop", out["action"])

    def test_create_requires_design_fail_closed(self):
        res = self._resolution([])
        self.assertEqual("create", res["branch"])
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_INPUT_MISSING"):
            self._orchestrate(res, schema="style", id_field="style_id", kind="map-style")

    def test_create_produces_project_draft(self):
        res = self._resolution([])
        design = deepcopy(VALID_CASES["style"])
        out = self._orchestrate(res, design=design, schema="style", id_field="style_id", kind="map-style")
        self.assertEqual("draft", out["action"])
        ref = out["draft_ref"]
        self.assertEqual("draft-demo", ref["id"])
        self.assertEqual("0.0.0-draft.r1", ref["version"])
        self.assertEqual("map-style", ref["kind"])
        self.assertNotIn("base_ref", ref)
        self.registry.validate("design-resolution-result", out)

    def test_derive_requires_inputs_fail_closed(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]
        res = self._resolution([self._assessment(fact, execution_admission="allowed", validation_coverage="covered")])
        self.assertEqual("derive", res["branch"])
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_INPUT_MISSING"):
            self._orchestrate(res, schema="style", id_field="style_id", kind="map-style")

    def test_derive_produces_draft_with_base_provenance(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]
        res = self._resolution([self._assessment(fact, execution_admission="allowed", validation_coverage="covered")])
        base = deepcopy(VALID_CASES["style"])
        base_ref = {"kind": "map-style", "id": base["style_id"], "version": base["version"], "digest": D}
        change = {"typography": {**base["typography"], "title_pt": 20}}
        out = self._orchestrate(res, base=base, base_ref=base_ref, change_set=change,
                                schema="style", id_field="style_id", kind="map-style", allowed_keys=("typography",))
        self.assertEqual("draft", out["action"])
        ref = out["draft_ref"]
        self.assertEqual(base_ref, ref["base_ref"])
        self.assertEqual(sha256_digest(base), ref["base_contract_digest"])
        self.assertEqual(change, ref["change_set"])
        self.assertEqual("0.0.0-draft.r1", ref["version"])
        self.registry.validate("design-resolution-result", out)

    def test_requirement_binding_mismatch_rejected(self):
        res = self._resolution([])
        other = deepcopy(REQ_A3_DUAL)
        other["requirement_id"] = "req-other"
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_REQUIREMENT_MISMATCH"):
            orchestrate_creation(other, res, draft_id="demo", revision=1, registry=self.registry)

    def test_revision_mismatch_rejected(self):
        res = self._resolution([])
        other = deepcopy(REQ_A3_DUAL)
        other["revision"] = 2
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_REVISION_MISMATCH"):
            orchestrate_creation(other, res, draft_id="demo", revision=1, registry=self.registry)

    def test_reuse_without_usable_candidate_fails_closed(self):
        res = self._resolution([])
        res["branch"] = "reuse"  # inconsistent decision: no usable candidate
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_NO_USABLE_CANDIDATE"):
            self._orchestrate(res)


class CliOrchestrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orchestrate-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.req_path = self.root / "requirement.json"
        self.req_path.write_text(json.dumps(REQ_A3_DUAL), encoding="utf-8")
        self.guard = PathGuard([self.root])
        self.repository = TemplateRepository(path_guard=self.guard, root=self.repo,
                                             repository_scope="local:test")

    def _args(self, **extra):
        from argparse import Namespace
        base = dict(template_command="orchestrate", requirement=str(self.req_path),
                    repository_root=str(self.repo), repository_scope="local:test",
                    allowed_root=[str(self.root)], draft_id="demo", revision=1,
                    base=None, base_ref=None, change_set=None, design=None)
        base.update(extra)
        return Namespace(**base)

    def _write(self, name, doc):
        path = self.root / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def test_empty_library_create_missing_design_fails_closed(self):
        from carto_core.cli import match_cmd
        with self.assertRaisesRegex(ProtocolError, "ORCHESTRATION_INPUT_MISSING"):
            match_cmd.handle(self._args())

    def test_empty_library_create_draft(self):
        from carto_core.cli import match_cmd
        design = deepcopy(VALID_CASES["resolved-layout"]["contract"])
        path = self._write("design.json", design)
        out = match_cmd.handle(self._args(design=path))["orchestration"]
        self.assertEqual("create", out["branch"])
        self.assertEqual("draft", out["action"])
        self.assertEqual("map-layout", out["draft_ref"]["kind"])
        self.assertEqual("draft-demo", out["draft_ref"]["id"])
        SchemaRegistry().validate("design-resolution-result", out)

    def test_published_reuse_returns_ref_no_draft(self):
        from carto_core.cli import match_cmd
        req = {"schema_version": 1, "requirement_id": "req-a4", "revision": 1, "object_scope": "layout",
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
        out = match_cmd.handle(self._args())["orchestration"]
        self.assertEqual("reuse", out["branch"])
        self.assertEqual("return-published-ref", out["action"])
        self.assertEqual("cand-a4", out["published_ref"]["id"])
        self.assertNotIn("draft_ref", out)

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
                                "version": "1.0.0", "status": "published", "summary": "Synthetic orchestrate fixture"},
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
            approval={"synthetic": "orchestrate-test", "template_id": template_id},
            idempotency_key=f"orchestrate-{template_id}-0001",
            publication_object={"schema_version": 1, "run_id": "orchestrate-run", "request_digest": D,
                                "package_ref": {"kind": "map-layout", "id": template_id,
                                                "version": "1.0.0", "digest": snapshot["package_digest"]},
                                "evidence_ref": {"id": "template-validation-evidence", "version": "1.0.0",
                                                 "digest": D, "uri": "evidence.yaml"},
                                "repository_scope": "local:test", "repository_root": self.repo.as_posix(),
                                "idempotency_key": f"orchestrate-{template_id}-0001"})


if __name__ == "__main__":
    unittest.main()