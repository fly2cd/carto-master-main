"""Synthetic contract/preparation tests. No user datasets or business legend rows."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.tool_gateway import ToolGateway
from carto_core.canonical import sha256_digest
from carto_core.cli import main
from carto_core.compiler.raster_portrayal import parse_legend, resolve_classes, legend_items
from carto_core.errors import CartoError
from carto_core.repository.immutable_store import ImmutableArtifactStore
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.models import ExecutionContext
from carto_core.workflow.raster_preparation import RasterPreparationService
from tests.fixtures.schema_cases import VALID_CASES


class PreparationFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source_path = self.root / "classified.tif"
        self.legend_path = self.root / "legend.csv"
        self.source_path.write_bytes(b"II\x2a\x00" + b"synthetic-test-only")
        self.legend_path.write_bytes(b"\xef\xbb\xbfvalue,label,color\n1,Category A,#FF0000\n8,Absent category,#00FF00\n")
        self.request = deepcopy(VALID_CASES["raster-classification-request"])
        self.request["source"]["path"] = "classified.tif"
        self.request["legend"]["path"] = "legend.csv"
        self.service = RasterPreparationService(project_root=self.root, allowed_roots=[str(self.root)])
        self.context = ExecutionContext("test-run", "test-tenant", "test-project", "test-subject",
                                       frozenset({"operator"}), frozenset({"test-project"}),
                                       frozenset({"gis-raster-statistics"}))
        self.evidence = deepcopy(VALID_CASES["geospatial-result"])
        self.evidence.update(operation="statistics", statistics={"total_pixels":6,"valid_pixels":6,"masked_pixels":0,
                            "classes":[{"value":0,"count":2},{"value":1,"count":2},{"value":255,"count":2}]})
        self.sync_inputs()
        self.calls = []
        store = ImmutableArtifactStore(self.root / ".carto/geospatial/evidence", path_guard=self.service.project_guard)
        gateway = ToolGateway(SCRIPTS_ROOT.parent / "policies/tool-bindings.yaml", store)
        def statistics(request, context):
            self.calls.append(deepcopy(request))
            return deepcopy(self.evidence)
        gateway.register("gis-raster-statistics", statistics, input_schema="geospatial-request", output_schema="geospatial-result")
        self.adapter = SimpleNamespace(make_gateway=lambda: gateway)

    def sync_inputs(self):
        self.request["source"].update(size_bytes=self.source_path.stat().st_size)
        self.request["source"]["source_ref"]["digest"] = self.service.digest_bytes(self.source_path.read_bytes())
        self.request["legend"].update(size_bytes=self.legend_path.stat().st_size,
                                       digest=self.service.digest_bytes(self.legend_path.read_bytes()))
        self.evidence.update(source_ref=deepcopy(self.request["source"]["source_ref"]),
                             source_size_bytes=self.request["source"]["size_bytes"])

    def analyze(self):
        return self.service.analyze(self.request, self.context, self.adapter)

    @staticmethod
    def answers(baseline):
        return {"schema_version":1,"based_on_digest":baseline.digest,"entries":[
            {"value":0,"semantic":"background","display":"hidden","label":None,"color":None,"order":2,"include_in_legend":False},
            {"value":255,"semantic":"class","display":"color","label":"Category B","color":"#0000FF","order":3,"include_in_legend":True},
        ]}

    def ready(self):
        baseline = self.analyze()
        return self.service.clarify(baseline.ref(), self.answers(baseline), self.context)


class RasterClassificationTests(PreparationFixture, unittest.TestCase):
    def test_dynamic_questions_and_explicit_palette(self):
        for value in (0, 255, -7, 4000000000):
            with self.subTest(value=value):
                stats = {"classes":[{"value":value,"count":6}]}
                definitions = parse_legend(self.legend_path.read_bytes(), self.request["legend"])
                rows, questions = resolve_classes(self.request, definitions, stats)
                self.assertEqual([value], [q["value"] for q in questions])
                self.assertIsNone(next(r for r in rows if r["value"] == value)["semantic"])
        self.legend_path.write_bytes(b"value,label\n1,Category A\n")
        self.request["legend"]["color_column"] = None
        definitions = parse_legend(self.legend_path.read_bytes(), self.request["legend"])
        _, questions = resolve_classes(self.request, definitions, {"classes":[{"value":1,"count":1}]})
        self.assertEqual("missing-color", questions[0]["kind"])
        self.request["palette"] = "carto-categorical-v1"
        rows, questions = resolve_classes(self.request, definitions, {"classes":[{"value":1,"count":1}]})
        self.assertFalse(questions)
        self.assertTrue(rows[0]["color"].startswith("#"))

    def test_missing_name_and_color_prepare_as_questions(self):
        self.legend_path.write_bytes(b"value,label,color\n1,,\n")
        self.sync_inputs()
        report, _ = self.service.load_verified(self.analyze().ref())
        self.assertEqual({"unmapped-value", "missing-label", "missing-color"}, {q["kind"] for q in report["questions"]})
        self.assertEqual("needs-clarification", report["status"])

    def test_csv_rejects_ambiguity_and_invalid_content(self):
        cases = [b"value,label,color\n1,A,#FF0000\n1,B,#00FF00\n", b"value,label,label\n1,A,B\n",
                 b"value,label,color\n1.0,A,#FF0000\n", b"value,label,color\n1,A,red\n",
                 b"value,label,color\n1,A,#FF0000,extra\n", b"value,label,color\n1,A\n",
                 b"value,label,color\n1,\xff,#FF0000\n", b"value,label,color\n",
                 b"value,label,color\n4294967296,A,#FF0000\n"]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(CartoError):
                parse_legend(content, self.request["legend"])
        for key in ("value_column", "label_column"):
            spec = deepcopy(self.request["legend"]); spec[key] = "color"
            with self.assertRaises(CartoError):
                parse_legend(self.legend_path.read_bytes(), spec)

    def test_unmapped_values_are_not_implicitly_nodata_and_absent_legend_policy(self):
        report, evidence = self.service.load_verified(self.analyze().ref())
        self.assertEqual([0,255], [q["value"] for q in report["questions"]])
        self.assertEqual(6, evidence["statistics"]["valid_pixels"])
        self.assertEqual([1], [r["value"] for r in legend_items(report["rows"])])
        self.request["legend_policy"] = "all"
        other, _ = self.service.load_verified(self.analyze().ref())
        self.assertEqual([1,8], [r["value"] for r in legend_items(other["rows"])])

    def test_clarification_creates_new_snapshot_without_approval_or_reanalysis(self):
        original = self.source_path.read_bytes()
        baseline = self.analyze()
        ready = self.service.clarify(baseline.ref(), self.answers(baseline), self.context)
        self.assertNotEqual(baseline.digest, ready.digest)
        old, _ = self.service.load_verified(baseline.ref())
        report, evidence = self.service.load_verified(ready.ref())
        self.assertEqual("needs-clarification", old["status"])
        self.assertEqual("ready", report["status"])
        self.assertEqual(1, len(self.calls))
        self.assertEqual(original, self.source_path.read_bytes())
        self.assertEqual(0, evidence["statistics"]["masked_pixels"])
        self.assertEqual([1,255], [r["value"] for r in legend_items(report["rows"])])
        self.assertFalse(any("approval" in str(p) for p in self.root.rglob("*")))
        again = self.service.clarify(baseline.ref(), self.answers(baseline), self.context)
        self.assertEqual(ready.ref(), again.ref())

    def test_replacement_answers_bind_original_baseline_not_previous_response(self):
        baseline = self.analyze(); answers = self.answers(baseline)
        first = self.service.clarify(baseline.ref(), answers, self.context)
        answers["entries"][1]["label"] = "Corrected category"
        second = self.service.clarify(first.ref(), answers, self.context)
        self.assertNotEqual(first.digest, second.digest)
        answers["based_on_digest"] = first.digest
        with self.assertRaisesRegex(CartoError, "ANSWERS_STALE"):
            self.service.clarify(first.ref(), answers, self.context)

    def test_reject_stale_duplicate_unrelated_answers_and_scope(self):
        baseline = self.analyze()
        for mode in ("stale", "duplicate", "unrelated", "order"):
            answers = self.answers(baseline)
            if mode == "stale": answers["based_on_digest"] = "sha256:" + "0" * 64
            if mode == "duplicate": answers["entries"].append(deepcopy(answers["entries"][0]))
            if mode == "unrelated": answers["entries"][0]["value"] = 99
            if mode == "order": answers["entries"][0]["order"] = 0
            with self.subTest(mode=mode), self.assertRaises(CartoError):
                self.service.clarify(baseline.ref(), answers, self.context)
        self.context.subject_id = "other-user"
        with self.assertRaisesRegex(CartoError, "SCOPE_MISMATCH"):
            self.service.clarify(baseline.ref(), self.answers(baseline), self.context)

    def test_freeze_survives_original_source_change_but_not_snapshot_tampering(self):
        artifact = self.ready()
        self.source_path.write_bytes(b"changed-original")
        self.legend_path.write_bytes(b"changed-original")
        report, _ = self.service.load_verified(artifact.ref())
        snapshot = Path(report["source_snapshot"]["artifact_ref"]["uri"])
        snapshot.write_bytes(b"changed-snapshot")
        with self.assertRaisesRegex(CartoError, "SNAPSHOT_CHANGED"):
            self.service.load_verified(artifact.ref())

    def test_reject_forged_resolution_and_changed_evidence(self):
        ready = self.ready()
        report, _ = self.service.load_verified(ready.ref())
        report["rows"][0]["color"] = "#FFFF00"
        forged = self.service.save_document(report, "raster-prepared-data")
        with self.assertRaisesRegex(CartoError, "RESOLUTION_MISMATCH"):
            self.service.load_verified(forged.ref())
        Path(report["gis_result_ref"]["uri"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(CartoError, "REFERENCE_CHANGED"):
            self.service.load_verified(ready.ref())

    def test_reject_input_drift_and_sidecars_before_gateway(self):
        self.legend_path.write_bytes(b"changed")
        with self.assertRaisesRegex(CartoError, "LEGEND_CHANGED"):
            self.analyze()
        self.sync_inputs()
        Path(str(self.source_path) + ".msk").write_bytes(b"external-mask")
        with self.assertRaisesRegex(CartoError, "SIDECAR_UNSUPPORTED"):
            self.analyze()
        self.assertFalse(self.calls)

    def test_reject_malformed_ref_and_cross_namespace(self):
        ready = self.ready()
        for reference in ({}, {**ready.ref(), "extra":True}, {**ready.ref(), "id":"other"}):
            with self.assertRaises(CartoError):
                self.service.load_verified(reference)
        report, _ = self.service.load_verified(ready.ref())
        relocated = self.root / "copied.json"; relocated.write_bytes(ready.path.read_bytes())
        with self.assertRaisesRegex(CartoError, "REFERENCE_SCOPE_INVALID"):
            self.service.load_verified({**ready.ref(), "uri":str(relocated)})
        report["source_snapshot"]["artifact_ref"]["uri"] = str(self.source_path)
        forged = self.service.save_document(report, "raster-prepared-data")
        with self.assertRaisesRegex(CartoError, "SNAPSHOT_SCOPE_INVALID"):
            self.service.load_verified(forged.ref())

    def test_reject_unauthorized_gateway_and_inconsistent_statistics(self):
        self.context.authorized_capabilities = frozenset()
        with self.assertRaisesRegex(CartoError, "CAPABILITY_SCOPE_DENIED"):
            self.analyze()
        self.context.authorized_capabilities = frozenset({"gis-raster-statistics"})
        self.evidence["statistics"]["valid_pixels"] = 5
        with self.assertRaisesRegex(CartoError, "STATISTICS_INVALID"):
            self.analyze()

    def test_reject_unimplemented_crs_rotation_and_float_profiles(self):
        original = deepcopy(self.evidence)
        for mode in ("crs", "rotation", "float", "size"):
            self.evidence = deepcopy(original)
            if mode == "crs": self.evidence["raster_info"]["crs_type"] = "geographic"
            if mode == "rotation": self.evidence["raster_info"]["transform"][1] = 1
            if mode == "float": self.evidence["raster_info"]["bands"][0]["dtype"] = "float32"
            if mode == "size": self.evidence["raster_info"]["width"] = 100000
            with self.subTest(mode=mode), self.assertRaises(CartoError):
                self.analyze()

    def test_external_input_path_and_foreign_project_ref_are_denied(self):
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / "classified.tif"
            external.write_bytes(self.source_path.read_bytes())
            self.request["source"]["path"] = str(external)
            with self.assertRaisesRegex(CartoError, "PATH_OUTSIDE_ALLOWED_ROOT"):
                self.analyze()
        self.request["source"]["path"] = "classified.tif"
        ready = self.ready()
        sibling = self.root / "sibling-project"; sibling.mkdir()
        other_service = RasterPreparationService(project_root=sibling, allowed_roots=[str(self.root)])
        with self.assertRaisesRegex(CartoError, "PATH_OUTSIDE_ALLOWED_ROOT"):
            other_service.load_verified(ready.ref())

    def test_palette_capacity_and_csv_class_limits(self):
        self.request["palette"] = "carto-categorical-v1"
        self.request["legend"]["color_column"] = None
        content = ("value,label\n" + "".join(f"{i},Category {i}\n" for i in range(13))).encode()
        definitions = parse_legend(content, self.request["legend"])
        _, questions = resolve_classes(self.request, definitions, {"classes":[{"value":1,"count":1}]})
        self.assertEqual([(12,"missing-color")], [(q["value"],q["kind"]) for q in questions])
        content = ("value,label\n" + "".join(f"{i},Category {i}\n" for i in range(257))).encode()
        with self.assertRaisesRegex(CartoError, "CLASS_LIMIT"):
            parse_legend(content, self.request["legend"])

    def test_partial_answers_do_not_claim_ready(self):
        baseline = self.analyze(); answers = self.answers(baseline)
        answers["entries"].pop()
        artifact = self.service.clarify(baseline.ref(), answers, self.context)
        report, _ = self.service.load_verified(artifact.ref())
        self.assertEqual("needs-clarification", report["status"])
        self.assertEqual([255], [q["value"] for q in report["questions"]])

    def test_cli_analysis_and_clarification_hide_category_rows_in_stdout(self):
        request_path = self.root / "request.json"; request_path.write_text(json.dumps(self.request),encoding="utf-8")
        args = ["--project-root",str(self.root),"--allowed-root",str(self.root),"--run-id","test-run",
                "--tenant-id","test-tenant","--project-id","test-project","--subject-id","test-subject"]
        stream = io.StringIO()
        with patch("carto_core.adapters.geospatial_mcp.GeospatialMcpAdapter", return_value=self.adapter), redirect_stdout(stream):
            result = main(["data","analyze-classification",str(request_path),"--mcp-config",str(self.root/"config.json"),*args])
        self.assertEqual(0,result,stream.getvalue())
        output = json.loads(stream.getvalue())
        self.assertEqual("needs-clarification", output["status"])
        self.assertNotIn("Category A", stream.getvalue())
        ref_path = self.root / "ref.json"; ref_path.write_text(json.dumps(output["prepared_ref"]),encoding="utf-8")
        answer_path = self.root / "answers.json"
        answer_path.write_text(json.dumps(self.answers(SimpleNamespace(digest=output["prepared_ref"]["digest"]))),encoding="utf-8")
        stream = io.StringIO()
        with patch("carto_core.adapters.geospatial_mcp.GeospatialMcpAdapter", side_effect=AssertionError("No second MCP call")), redirect_stdout(stream):
            result = main(["data","clarify-classification",str(ref_path),"--answers",str(answer_path),*args])
        self.assertEqual(0,result,stream.getvalue())
        self.assertEqual("ready", json.loads(stream.getvalue())["status"])
        self.assertNotIn("Category B", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
