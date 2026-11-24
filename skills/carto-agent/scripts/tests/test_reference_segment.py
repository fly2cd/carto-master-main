# -*- coding: utf-8 -*-
"""Phase 2 closed-loop orchestration tests: reference -> draft segment request -> workflow."""
from __future__ import annotations

from copy import deepcopy
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from PIL import Image

from carto_core.compiler.reference_extraction import extract_palette
from carto_core.schema_registry import SchemaRegistry
from carto_core.scenarios.general_thematic.raster import style_contract
from carto_core.security.paths import PathGuard
from carto_core.workflow.reference_segment import (
    compare_reference_render, prepare_reference_segment_request)
from carto_core.workflow.segment_workflow import create_template_workflow
from tests.fixtures.schema_cases import VALID_CASES

_BANDS = [(31, 97, 31), (60, 47, 213), (204, 76, 2), (254, 196, 79)]


def _reference_png() -> bytes:
    img = Image.new("RGB", (64, 64))
    for i, rgb in enumerate(_BANDS):
        for y in range(16 * i, 16 * (i + 1)):
            for x in range(64):
                img.putpixel((x, y), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class PrepareReferenceSegmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ref-seg-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.work = self.project / "work"
        self.work.mkdir()
        self.image = self.project / "reference.png"
        self.png = _reference_png()
        self.image.write_bytes(self.png)
        self.guard = PathGuard([self.tmp])
        self.registry = SchemaRegistry()
        self.base = style_contract()
        self.meta = deepcopy(VALID_CASES["segment-create-request"])

    def _prepare(self, image=None, **overrides):
        params = dict(
            work_root=self.work, kind="map-style", base_design=self.base,
            request_id=self.meta["request_id"], proposal_id="prop-ref-1",
            license="CC-BY-4.0", selected_segments=["style"],
            namespace=self.meta["namespace"], template_id=self.meta["template_id"],
            version=self.meta["version"], purpose=self.meta["purpose"],
            audience=self.meta["audience"], reuse_intent=self.meta["reuse_intent"],
            supported_uses=self.meta["supported_uses"], excluded_uses=self.meta["excluded_uses"],
            authoring_mode=self.meta["authoring_mode"], targets=["png"],
            subject=self.meta["subject"], requested_at=self.meta["requested_at"], k=4)
        params.update(overrides)
        return prepare_reference_segment_request(
            self.guard, image or self.image, registry=self.registry, **params)

    def test_prepare_produces_valid_draft_with_reference_evidence(self):
        result = self._prepare()
        request = result["request"]
        self.registry.validate("segment-create-request", request)
        paths = {d["path"] for d in request["decisions"]}
        self.assertTrue({"/reference/intake_digest", "/reference/proposal_digest",
                         "/reference/recovery_error_delta_e2000"} <= paths)
        self.assertTrue((self.work / "reference/intake.yaml").is_file())
        self.assertTrue((self.work / "reference/proposal.yaml").is_file())
        self.assertLess(result["recovery_error_delta_e2000"], 2.0)

    def test_draft_flows_into_segment_workflow(self):
        result = self._prepare()
        request_path = self.project / "segment-request.yaml"
        request_path.write_text(yaml.safe_dump(result["request"], allow_unicode=True, sort_keys=False),
                                encoding="utf-8")
        wf = create_template_workflow("map-style", allowed_roots=[self.tmp],
                                      project_root=self.project, workdir="work", registry=self.registry)
        analyzed = wf.analyze(request_path)
        # reference provenance flows into the analysis evidence (toward TP)
        evidence_paths = {r["path"] for r in analyzed["analysis"]["evidence_records"]}
        self.assertIn("/reference/intake_digest", evidence_paths)
        wf.brief(request_path)
        authored = wf.author(request_path)
        self.assertEqual(("pending", "validate"),
                         (authored["state"]["status"], authored["state"]["step"]))

    def test_prepare_rejects_path_outside_allowed_roots(self):
        from carto_core.errors import SecurityError
        outside = self.tmp.parent / "outside-ref.png"
        outside.write_bytes(self.png)
        self.addCleanup(outside.unlink)
        with self.assertRaises(SecurityError):
            self._prepare(image=outside)


class CompareReferenceRenderTests(unittest.TestCase):
    def test_faithful_render_comparison_and_safe_deviation(self):
        png = _reference_png()
        proposed = extract_palette(png, k=4)
        report = compare_reference_render(png, png, proposed_colors=proposed)
        self.assertLess(report["round_trip"]["recovery_error_delta_e2000"], 2.0)
        self.assertLess(report["round_trip"]["implementation_error_delta_e2000"], 2.0)
        self.assertFalse(report["redline_deviation"]["requires_authorization"])

    def test_blocker_effective_colors_require_authorization(self):
        png = _reference_png()
        proposed = extract_palette(png, k=4)
        report = compare_reference_render(png, png, proposed_colors=proposed,
                                          effective_colors=["#FF0000", "#FE0000", "#00FF00", "#0000FF"])
        self.assertTrue(report["redline_deviation"]["requires_authorization"])
        self.assertGreater(report["round_trip"]["authorized_deviation_delta_e2000"], 0.0)


def _meta_params(meta, **overrides):
    params = dict(
        request_id=meta["request_id"], proposal_id="prop-ref-1", license="CC-BY-4.0",
        selected_segments=["style"], namespace=meta["namespace"], template_id=meta["template_id"],
        version=meta["version"], purpose=meta["purpose"], audience=meta["audience"],
        reuse_intent=meta["reuse_intent"], supported_uses=meta["supported_uses"],
        excluded_uses=meta["excluded_uses"], authoring_mode=meta["authoring_mode"],
        targets=["pdf", "png"], subject=meta["subject"], requested_at=meta["requested_at"], k=4)
    params.update(overrides)
    return params


class ValidateComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ref-val-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.work = self.project / "work"
        self.work.mkdir()
        self.image = self.project / "reference.png"
        self.image.write_bytes(_reference_png())
        self.guard = PathGuard([self.tmp])
        self.registry = SchemaRegistry()
        self.meta = deepcopy(VALID_CASES["segment-create-request"])

    def _run_validate(self, request):
        request_path = self.project / "segment-request.yaml"
        request_path.write_text(yaml.safe_dump(request, allow_unicode=True, sort_keys=False), encoding="utf-8")
        wf = create_template_workflow(request["kind"], allowed_roots=[self.tmp],
                                      project_root=self.project, workdir="work", registry=self.registry)
        wf.analyze(request_path)
        wf.brief(request_path)
        wf.author(request_path)
        return wf.validate(request_path, attestation_key=b"0" * 32)

    def test_reference_validate_binds_comparison_results(self):
        result = prepare_reference_segment_request(
            self.guard, self.image, work_root=self.work, kind="map-style",
            base_design=style_contract(), registry=self.registry,
            **_meta_params(self.meta))
        validated = self._run_validate(result["request"])
        results = validated["evidence"]["results"]
        check_ids = {r["check_id"] for r in results}
        self.assertIn("reference.round-trip", check_ids)
        self.assertIn("reference.redline-deviation", check_ids)
        rt = next(r for r in results if r["check_id"] == "reference.round-trip")
        self.assertIn("recovery_error_delta_e2000", rt["details"])

    def test_ordinary_segment_validate_has_no_reference_comparison(self):
        request = deepcopy(self.meta)
        request["design"] = style_contract()
        request["targets"] = ["pdf", "png"]
        validated = self._run_validate(request)
        check_ids = {r["check_id"] for r in validated["evidence"]["results"]}
        self.assertNotIn("reference.round-trip", check_ids)
        self.assertNotIn("reference.redline-deviation", check_ids)

    def test_declared_reference_missing_evidence_fails_closed(self):
        result = prepare_reference_segment_request(
            self.guard, self.image, work_root=self.work, kind="map-style",
            base_design=style_contract(), registry=self.registry,
            **_meta_params(self.meta))
        (self.work / "reference" / "proposal.yaml").unlink()
        validated = self._run_validate(result["request"])
        rt = next(r for r in validated["evidence"]["results"] if r["check_id"] == "reference.round-trip")
        self.assertEqual("failed", rt["status"])
        self.assertEqual("failed", validated["evidence"]["status"])


class CliReferencePrepareTests(unittest.TestCase):
    def test_cli_reference_prepare_writes_draft(self):
        from argparse import Namespace
        from carto_core.cli import template_cmd
        tmp = Path(tempfile.mkdtemp(prefix="ref-cli-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        project = tmp / "project"
        project.mkdir()
        (project / "reference.png").write_bytes(_reference_png())
        meta = deepcopy(VALID_CASES["segment-create-request"])
        config = {"image": "reference.png", "base_design": style_contract(),
                  "kind": "map-style", **_meta_params(meta, targets=["png"])}
        config_path = project / "reference-config.yaml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        args = Namespace(create_command="reference-prepare", config=str(config_path),
                         project_root=str(project), workdir="work", allowed_root=[str(tmp)],
                         output="segment-request.yaml")
        result = template_cmd.handle(args)
        out = Path(result["request_path"])
        self.assertTrue(out.is_file())
        request = yaml.safe_load(out.read_text(encoding="utf-8"))
        SchemaRegistry().validate("segment-create-request", request)
        self.assertTrue((project / "work/reference/reference.png").is_file())


if __name__ == "__main__":
    unittest.main()