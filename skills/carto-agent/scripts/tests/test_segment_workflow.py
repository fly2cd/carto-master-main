# -*- coding: utf-8 -*-
"""Segment creation workflow tests (plan phase-1 foundation).

Proves typed kind dispatch and the segment analyze -> brief -> author chain reuse the
generic state machine, produce a closed segment package, and fail closed at validate
(roadmap-declared not_implemented) until the validation host is delivered. The scenario
parent workflow is untouched; its regression is guarded by the existing suite.
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

from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.segment_workflow import SegmentCreationWorkflow, create_template_workflow
from carto_core.workflow.template_workflow import TemplateCreationWorkflow
from tests.fixtures.schema_cases import VALID_CASES


class SegmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="seg-wf-"))
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.registry = SchemaRegistry()
        self.request = deepcopy(VALID_CASES["segment-create-request"])
        self.request_path = self.project / "segment-request.yaml"
        self._write_request()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_request(self):
        self.request_path.write_text(yaml.safe_dump(self.request, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _workflow(self, kind=None):
        return create_template_workflow(
            kind or self.request["kind"], allowed_roots=[self.tmp],
            project_root=self.project, workdir="work", registry=self.registry)

    def _write_publication_request(self, intent_state="ready"):
        pub = {"schema_version": 1, "publication_request_id": "pubreq-test",
               "request_id": self.request["request_id"], "kind": self.request["kind"],
               "intent_state": intent_state}
        if intent_state == "ready":
            pub["target"] = {"repository_scope": "local:templates",
                             "namespace": self.request["namespace"],
                             "template_id": self.request["template_id"],
                             "version": self.request["version"]}
        path = self.project / "publication-request.yaml"
        path.write_text(yaml.safe_dump(pub, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def test_factory_dispatch_is_closed(self):
        self.assertIs(type(self._workflow("map-style")), SegmentCreationWorkflow)
        self.assertIs(type(self._workflow("map-layout")), SegmentCreationWorkflow)
        self.assertIs(type(self._workflow("map-scenario")), TemplateCreationWorkflow)
        with self.assertRaisesRegex(ProtocolError, "TEMPLATE_KIND_UNSUPPORTED"):
            self._workflow("map-brand")

    def test_analyze_brief_author_style_chain(self):
        wf = self._workflow()
        analyzed = wf.analyze(self.request_path)
        self.assertEqual(("pending", "brief"), (analyzed["state"]["status"], analyzed["state"]["step"]))
        briefed = wf.brief(self.request_path)
        self.assertEqual(("pending", "author"), (briefed["state"]["status"], briefed["state"]["step"]))
        self.assertEqual("map-style", briefed["brief"]["kind"])
        authored = wf.author(self.request_path)
        self.assertEqual(("pending", "validate"), (authored["state"]["status"], authored["state"]["step"]))
        pkg = self.project / "work/staging/package"
        manifest = yaml.safe_load((pkg / "manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual("map-style", manifest["package"]["kind"])
        self.assertNotIn("business_contracts", manifest)
        self.assertTrue((pkg / "contracts/cartography.yaml").is_file())
        self.assertEqual(authored["package"]["package_digest"], authored["receipt"]["output_refs"][0]["digest"])

    def test_analyze_brief_author_layout_chain(self):
        self.request["kind"] = "map-layout"
        self.request["template_id"] = "seg-layout"
        self.request["design"] = deepcopy(VALID_CASES["layout"])
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        authored = wf.author(self.request_path)
        pkg = self.project / "work/staging/package"
        self.assertTrue((pkg / "contracts/layout.yaml").is_file())
        self.assertEqual("map-layout", authored["package"] and yaml.safe_load((pkg / "manifest.yaml").read_text(encoding="utf-8"))["package"]["kind"])

    def test_validate_renders_sample_via_host(self):
        from carto_core.scenarios.general_thematic.raster import style_contract
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        result = wf.validate(self.request_path, attestation_key=b"0" * 32)
        self.assertEqual("passed", result["evidence"]["status"])
        self.assertEqual("validated-draft", result["result_kind"])
        self.assertEqual(("succeeded", "validate"),
                         (result["state"]["status"], result["state"]["step"]))
        self.assertIn("render_receipt_ref", result["evidence"])
        self.assertIn("host_ref", result["evidence"])

    def test_invalid_design_rejected_at_analyze(self):
        self.request["design"].pop("typography")
        self._write_request()
        wf = self._workflow()
        with self.assertRaises(ProtocolError):
            wf.analyze(self.request_path)

    def test_scope_mismatch_denied(self):
        self.request["scope"] = "project:other-project"
        self._write_request()
        wf = self._workflow()
        with self.assertRaisesRegex(SecurityError, "PROJECT_SCOPE_DENIED"):
            wf.analyze(self.request_path)

    def test_empty_library_style_validate_and_publish(self):
        from dataclasses import asdict
        from carto_core.artifacts import atomic_yaml
        from carto_core.scenarios.general_thematic.raster import style_contract
        from tests.test_general_thematic import sign, APPROVAL_KEY, KEY
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self.request["subject"]["environment"] = "local"
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        wf.validate(self.request_path, attestation_key=KEY,
                    publication_request=self._write_publication_request())
        repo_root = self.tmp / "repo"
        prepared = wf.prepare_publication(
            self.request_path, repository_root=repo_root,
            repository_scope="local:templates", idempotency_key="seg-publish-0001")
        tp = sign("TP", "approve-template-publish", "template-publication", prepared["object_digest"],
                  subject_id=self.request["subject"]["approver_subject_id"],
                  scope=self.request["scope"], tenant_id=self.request["subject"]["tenant_id"])
        tp_path = self.project / "tp.yaml"
        atomic_yaml(tp_path, asdict(tp))
        result = wf.publish(
            self.request_path, tp_path, repository_root=repo_root,
            repository_scope="local:templates", idempotency_key="seg-publish-0001",
            approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)
        self.assertEqual("succeeded", result["state"]["status"])
        self.assertEqual("map-style", result["publication"]["package_ref"]["kind"])
        self.assertTrue((repo_root / "packages/local/map-style/seg-style/1.0.0/manifest.yaml").is_file())

    def test_empty_library_layout_validate_and_publish(self):
        from dataclasses import asdict
        from carto_core.artifacts import atomic_yaml
        from carto_core.scenarios.general_thematic.raster import layout_contract
        from tests.test_general_thematic import sign, APPROVAL_KEY, KEY
        self.request["kind"] = "map-layout"
        self.request["template_id"] = "seg-layout"
        self.request["design"] = layout_contract()
        self.request["targets"] = ["pdf", "png"]
        self.request["subject"]["environment"] = "local"
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        wf.validate(self.request_path, attestation_key=KEY,
                    publication_request=self._write_publication_request())
        repo_root = self.tmp / "repo"
        prepared = wf.prepare_publication(
            self.request_path, repository_root=repo_root,
            repository_scope="local:templates", idempotency_key="seg-layout-publish-0001")
        tp = sign("TP", "approve-template-publish", "template-publication", prepared["object_digest"],
                  subject_id=self.request["subject"]["approver_subject_id"],
                  scope=self.request["scope"], tenant_id=self.request["subject"]["tenant_id"])
        tp_path = self.project / "tp.yaml"
        atomic_yaml(tp_path, asdict(tp))
        result = wf.publish(
            self.request_path, tp_path, repository_root=repo_root,
            repository_scope="local:templates", idempotency_key="seg-layout-publish-0001",
            approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)
        self.assertEqual("succeeded", result["state"]["status"])
        self.assertEqual("map-layout", result["publication"]["package_ref"]["kind"])
        self.assertTrue((repo_root / "packages/local/map-layout/seg-layout/1.0.0/contracts/layout.yaml").is_file())

    def test_publish_rerender_drift_fails_closed(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from carto_core.artifacts import atomic_yaml
        from carto_core.scenarios.general_thematic.raster import style_contract
        from tests.test_general_thematic import sign, APPROVAL_KEY, KEY
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self.request["subject"]["environment"] = "local"
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        wf.validate(self.request_path, attestation_key=KEY,
                    publication_request=self._write_publication_request())
        repo_root = self.tmp / "repo"
        prepared = wf.prepare_publication(
            self.request_path, repository_root=repo_root,
            repository_scope="local:templates", idempotency_key="seg-drift-publish-0001")
        tp = sign("TP", "approve-template-publish", "template-publication", prepared["object_digest"],
                  subject_id=self.request["subject"]["approver_subject_id"],
                  scope=self.request["scope"], tenant_id=self.request["subject"]["tenant_id"])
        tp_path = self.project / "tp.yaml"
        atomic_yaml(tp_path, asdict(tp))
        drifted = {"output_artifacts": [
            {"target": "pdf", "artifact_ref": {"digest": "sha256:" + "f" * 64}},
            {"target": "png", "artifact_ref": {"digest": "sha256:" + "f" * 64}}]}
        with patch("carto_core.workflow.segment_validation._render", return_value=(drifted, None)):
            with self.assertRaisesRegex(ProtocolError, "VALIDATION_RERENDER_DRIFT"):
                wf.publish(self.request_path, tp_path, repository_root=repo_root,
                           repository_scope="local:templates", idempotency_key="seg-drift-publish-0001",
                           approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)

    def test_style_discrete_colors_drive_sample_render(self):
        from carto_core.scenarios.general_thematic.raster import style_contract
        from tests.test_general_thematic import KEY

        def make_style(c1):
            style = style_contract()
            style["symbol_roles"] = [
                {"role_id": "c1", "geometry_role": "raster-cell", "key_mode": "discrete",
                 "symbol": {"color": c1, "stroke": c1, "stroke_width_pt": 0.0, "radius_mm": 1.0}},
                {"role_id": "c2", "geometry_role": "raster-cell", "key_mode": "discrete",
                 "symbol": {"color": "#3C2FD5", "stroke": "#3C2FD5", "stroke_width_pt": 0.0, "radius_mm": 1.0}},
                {"role_id": "c3", "geometry_role": "raster-cell", "key_mode": "discrete",
                 "symbol": {"color": "#8F452C", "stroke": "#8F452C", "stroke_width_pt": 0.0, "radius_mm": 1.0}},
            ]
            return style

        digests = []
        for name, c1 in (("a", "#1F611F"), ("b", "#FF0000")):
            req = deepcopy(self.request)
            req["design"] = make_style(c1)
            req["targets"] = ["pdf", "png"]
            rp = self.project / f"req-{name}.yaml"
            rp.write_text(yaml.safe_dump(req, allow_unicode=True, sort_keys=False), encoding="utf-8")
            wf = create_template_workflow("map-style", allowed_roots=[self.tmp],
                                          project_root=self.project, workdir=f"work-{name}",
                                          registry=self.registry)
            wf.analyze(rp)
            wf.brief(rp)
            wf.author(rp)
            res = wf.validate(rp, attestation_key=KEY)
            self.assertEqual("passed", res["evidence"]["status"])
            digests.append(res["evidence"]["render_receipt_ref"]["digest"])
        # Different Style category colors must produce a different rendered sample.
        self.assertNotEqual(digests[0], digests[1])

    def test_create_workflow_for_request_peeks_kind(self):
        from carto_core.workflow.segment_workflow import create_workflow_for_request
        wf = create_workflow_for_request(
            self.request_path, allowed_roots=[self.tmp], project_root=self.project,
            workdir="work", registry=self.registry)
        self.assertIs(type(wf), SegmentCreationWorkflow)
        scenario = deepcopy(VALID_CASES["template-create-request"])
        scenario_path = self.project / "scenario-request.yaml"
        scenario_path.write_text(yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False), encoding="utf-8")
        wf2 = create_workflow_for_request(
            scenario_path, allowed_roots=[self.tmp], project_root=self.project,
            workdir="work", registry=self.registry)
        self.assertIs(type(wf2), TemplateCreationWorkflow)


    def test_default_draft_endpoint_leaves_index_unchanged(self):
        from carto_core.scenarios.general_thematic.raster import style_contract
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        result = wf.validate(self.request_path, attestation_key=b"0" * 32)
        self.assertEqual("validated-draft", result["result_kind"])
        self.assertEqual(("succeeded", "validate"),
                         (result["state"]["status"], result["state"]["step"]))
        self.assertFalse((self.tmp / "repo").exists())

    def test_intent_only_publication_request_stops_at_draft(self):
        from carto_core.scenarios.general_thematic.raster import style_contract
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        result = wf.validate(self.request_path, attestation_key=b"0" * 32,
                             publication_request=self._write_publication_request("intent-only"))
        self.assertEqual("validated-draft", result["result_kind"])
        self.assertEqual("validate", result["state"]["step"])

    def test_publication_request_binding_mismatch_rejected(self):
        from carto_core.scenarios.general_thematic.raster import style_contract
        self.request["design"] = style_contract()
        self.request["targets"] = ["pdf", "png"]
        self._write_request()
        wf = self._workflow()
        wf.analyze(self.request_path)
        wf.brief(self.request_path)
        wf.author(self.request_path)
        pub_path = self._write_publication_request()
        data = yaml.safe_load(pub_path.read_text(encoding="utf-8"))
        data["request_id"] = "another-request"
        pub_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ProtocolError, "PUBLICATION_REQUEST_BINDING_MISMATCH"):
            wf.validate(self.request_path, attestation_key=b"0" * 32, publication_request=pub_path)


if __name__ == "__main__":
    unittest.main()