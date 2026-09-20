from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import sys

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.cli import main as cli_main
from carto_core.errors import ProtocolError, SecurityError
from carto_core.security.approval import ApprovalReceipt, sign_receipt
from carto_core.workflow.template_workflow import TemplateCreationWorkflow


KEY = b"test-only-secret-that-is-at-least-32-bytes"
EXPECTED_PACKAGE_FILES = {
    "manifest.yaml",
    "checksums.sha256",
    "templates/design_spec.md",
    "contracts/scenario.yaml",
    "contracts/data.schema.yaml",
    "contracts/spatial-behavior.yaml",
    "contracts/portrayal.yaml",
    "contracts/delivery.yaml",
    "contracts/quality-gates.yaml",
    "fixtures/flood-risk.synthetic.geojson",
    "prototypes/risk-overview.yaml",
    "dependencies.lock.yaml",
}


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _geojson(role: str) -> dict[str, object]:
    metadata = {
        "data_nature": "synthetic",
        "contains_production_data": False,
        "contains_sensitive_coordinates": False,
        "source_crs": "EPSG:4326",
    }
    if role == "risk":
        features = [{
            "type": "Feature",
            "id": "synthetic-risk-input",
            "properties": {"risk_pct": 42.0},
            "geometry": {"type": "Polygon", "coordinates": [[[0.0, 0.0], [0.02, 0.0], [0.02, 0.02], [0.0, 0.02], [0.0, 0.0]]]},
        }]
    else:
        features = [{
            "type": "Feature",
            "id": "synthetic-shelter-input",
            "properties": {"capacity": 120},
            "geometry": {"type": "Point", "coordinates": [0.01, 0.01]},
        }]
    return {"type": "FeatureCollection", "carto_metadata": metadata, "features": features}


class TemplateWorkflowTests(unittest.TestCase):
    def _project(self, root: Path, *, kind: str = "map-scenario") -> tuple[Path, Path, Path, TemplateCreationWorkflow]:
        project = root / "project"
        data = project / "data"
        data.mkdir(parents=True)
        risk = data / "risk.geojson"
        shelter = data / "shelter.geojson"
        risk.write_text(json.dumps(_geojson("risk"), ensure_ascii=False), encoding="utf-8")
        shelter.write_text(json.dumps(_geojson("shelter"), ensure_ascii=False), encoding="utf-8")
        provenance = {
            "source_type": "derived",
            "source_ref": "fixture:up2-template",
            "version": "1.0.0",
            "retrieved_at": "2026-09-18T00:00:00Z",
            "classification": "internal",
        }
        data_profile = {
            "data_nature": "synthetic",
            "contains_production_data": False,
            "contains_sensitive_coordinates": False,
            "source_crs": {"authority": "EPSG", "code": "4326"},
        }
        manifest = {
            "schema_version": 1,
            "manifest_id": "flood-sources",
            "sources": [
                {"source_id": "risk-source", "kind": "geojson", "location_ref": "data/risk.geojson", "digest": _digest(risk), "provenance": provenance, "license": "project-approved", "captured_at": "2026-09-18T00:00:00Z", "data_profile": data_profile},
                {"source_id": "shelter-source", "kind": "geojson", "location_ref": "data/shelter.geojson", "digest": _digest(shelter), "provenance": provenance, "license": "project-approved", "captured_at": "2026-09-18T00:00:00Z", "data_profile": data_profile},
            ],
        }
        manifest_path = project / "source-manifest.yaml"
        _write_yaml(manifest_path, manifest)
        request = {
            "schema_version": 1,
            "request_id": "flood-template-request",
            "kind": kind,
            "namespace": "local",
            "template_id": "flood-scenario",
            "version": "1.0.0",
            "profile": "flood-risk-overview",
            "purpose": "Synthetic flood-risk engineering preview",
            "audience": ["emergency-planner"],
            "reuse_intent": "Reuse with approved synthetic role-compatible inputs",
            "supported_uses": ["engineering-preview"],
            "excluded_uses": ["navigation", "formal-delivery"],
            "authoring_mode": "standard",
            "targets": ["svg", "pdf", "png"],
            "scope": "project:project-one",
            "subject": {"tenant_id": "tenant-one", "project_id": "project-one", "requester_subject_id": "operator-one", "approver_subject_id": "reviewer-one", "environment": "local"},
            "source_manifest_path": "source-manifest.yaml",
            "data_nature": "synthetic",
            "contains_production_data": False,
            "contains_sensitive_coordinates": False,
            "source_crs": {"authority": "EPSG", "code": "4326"},
            "display_crs": {"authority": "EPSG", "code": "3857"},
            "role_bindings": {"risk_area_source": "risk-source", "shelter_source": "shelter-source"},
            "decisions": [],
            "requested_at": "2026-09-18T00:00:00Z",
        }
        request_path = project / "request.yaml"
        _write_yaml(request_path, request)
        workdir = project / "runs" / "template-one"
        workflow = TemplateCreationWorkflow(allowed_roots=[root], project_root=project, workdir=workdir)
        return project, request_path, workdir, workflow

    def _approval(self, project: Path, brief: dict[str, object], *, action: str = "approve-template-brief", object_type: str = "template-brief", subject_id: str = "reviewer-one", nonce: str = "nonce-0000000000000001") -> Path:
        now = datetime.now(UTC)
        unsigned = ApprovalReceipt(
            1,
            "template-approval-one",
            "trusted-local",
            subject_id,
            "tenant-one",
            action,
            object_type,
            sha256_digest(brief),
            "project:project-one",
            "carto-security",
            "local",
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=10)).isoformat(),
            nonce,
        )
        path = project / "approval.yaml"
        _write_yaml(path, asdict(sign_receipt(unsigned, KEY)))
        return path

    def _ready(self, root: Path) -> tuple[Path, Path, Path, TemplateCreationWorkflow, dict[str, object]]:
        project, request, workdir, workflow = self._project(root)
        workflow.analyze(request)
        result = workflow.brief(request)
        return project, request, workdir, workflow, result["brief"]

    def test_analyze_brief_approval_author_creates_closed_staging_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            result = workflow.author(
                request,
                self._approval(project, brief),
                approval_key=KEY,
                nonce_db="approval-nonces.sqlite3",
                policy_id="carto-security",
                issuer="trusted-local",
            )
            package = workdir / "staging" / "package"
            actual = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
            self.assertEqual(EXPECTED_PACKAGE_FILES, actual)
            manifest = yaml.safe_load((package / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["files"]), set(manifest["checksums"]))
            checksum_paths = {line.split("  ", 1)[1] for line in (package / "checksums.sha256").read_text(encoding="utf-8").splitlines()}
            self.assertEqual(EXPECTED_PACKAGE_FILES - {"checksums.sha256"}, checksum_paths)
            prototype = yaml.safe_load((package / "prototypes/risk-overview.yaml").read_text(encoding="utf-8"))
            self.assertEqual("not-run", prototype["renderer_execution"])
            self.assertTrue(prototype["render_required"])
            portrayal = yaml.safe_load((package / "contracts/portrayal.yaml").read_text(encoding="utf-8"))
            refs = {(layer["map_expression_ref"]["id"], layer["map_expression_ref"]["version"]) for layer in portrayal["layers"]}
            self.assertEqual({("choropleth/sequential", "1.0.0"), ("proportional-symbol/count", "1.0.0")}, refs)
            self.assertFalse((workdir / "template-index.yaml").exists())
            self.assertFalse((workdir / "publication-receipt.yaml").exists())
            self.assertEqual(3, len(list((workdir / "receipts").glob("*.json"))))
            self.assertEqual("pending", result["state"]["status"])
            self.assertEqual("validate", result["state"]["step"])

    def test_author_requires_independent_t1_approval_and_bound_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow, brief = self._ready(root)
            with self.assertRaises(ProtocolError) as missing:
                workflow.author(request, None, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("BRIEF_NOT_CONFIRMED", missing.exception.code)
            wrong_gate = self._approval(project, brief, action="approve-map-brief", object_type="map-brief")
            with self.assertRaises(SecurityError) as gate_error:
                workflow.author(request, wrong_gate, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("APPROVAL_ACTION_MISMATCH", gate_error.exception.code)
            wrong_identity = self._approval(project, brief, subject_id="reviewer-two", nonce="nonce-0000000000000002")
            with self.assertRaises(SecurityError) as identity_error:
                workflow.author(request, wrong_identity, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("APPROVAL_IDENTITY_MISMATCH", identity_error.exception.code)
            stale_brief = deepcopy(brief)
            stale_brief["purpose"] = "Previously approved purpose"
            stale = self._approval(project, stale_brief, nonce="nonce-0000000000000003")
            with self.assertRaises(SecurityError) as stale_error:
                workflow.author(request, stale, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("APPROVAL_OBJECT_MISMATCH", stale_error.exception.code)

    def test_resume_detects_input_analysis_and_brief_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow = self._project(root)
            workflow.analyze(request)
            request_value = yaml.safe_load(request.read_text(encoding="utf-8"))
            request_value["purpose"] = "Changed purpose"
            _write_yaml(request, request_value)
            with self.assertRaises(ProtocolError) as input_drift:
                workflow.brief(request)
            self.assertEqual("JOB_INPUT_DRIFT", input_drift.exception.code)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            analysis_path = workdir / "analysis/template-analysis.yaml"
            analysis = yaml.safe_load(analysis_path.read_text(encoding="utf-8"))
            analysis["open_questions"] = ["Changed after brief"]
            _write_yaml(analysis_path, analysis)
            with self.assertRaises(ProtocolError) as prerequisite_drift:
                workflow.author(request, self._approval(project, brief), approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("JOB_PREREQUISITE_DRIFT", prerequisite_drift.exception.code)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            brief_path = workdir / "template_brief.yaml"
            changed = deepcopy(brief)
            changed["purpose"] = "Changed after approval"
            _write_yaml(brief_path, changed)
            with self.assertRaises(ProtocolError) as output_drift:
                workflow.author(request, self._approval(project, brief), approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("JOB_PREREQUISITE_DRIFT", output_drift.exception.code)

    def test_author_recovers_consumed_t1_before_package_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            approval = self._approval(
                project, brief, nonce="nonce-t1-recovery-before-package-0001"
            )
            with patch(
                "carto_core.workflow.template_workflow.MapScenarioAuthor.author",
                side_effect=OSError("injected crash after approval consumption"),
            ):
                with self.assertRaises(OSError):
                    workflow.author(
                        request, approval, approval_key=KEY,
                        nonce_db="nonce.sqlite3", policy_id="carto-security",
                        issuer="trusted-local",
                    )
            self.assertTrue((workdir / "approvals/t1-template-brief.yaml").is_file())
            self.assertFalse((workdir / "staging/package").exists())

            recovered_workflow = TemplateCreationWorkflow(
                allowed_roots=[root], project_root=project, workdir=workdir,
            )
            recovered = recovered_workflow.author(
                request, approval, approval_key=KEY,
                nonce_db="nonce.sqlite3", policy_id="carto-security",
                issuer="trusted-local",
            )
            self.assertEqual("pending", recovered["state"]["status"])
            self.assertEqual("validate", recovered["state"]["step"])
            self.assertTrue(recovered["idempotent_replay"])

    def test_author_recovers_exact_package_written_before_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            approval = self._approval(
                project, brief, nonce="nonce-t1-recovery-after-package-0001"
            )
            with patch.object(
                workflow.state_store,
                "complete_step",
                side_effect=OSError("injected crash after package write"),
            ):
                with self.assertRaises(OSError):
                    workflow.author(
                        request, approval, approval_key=KEY,
                        nonce_db="nonce.sqlite3", policy_id="carto-security",
                        issuer="trusted-local",
                    )
            package_root = workdir / "staging/package"
            before = {
                path.relative_to(package_root).as_posix(): path.read_bytes()
                for path in package_root.rglob("*")
                if path.is_file()
            }

            recovered_workflow = TemplateCreationWorkflow(
                allowed_roots=[root], project_root=project, workdir=workdir,
            )
            recovered = recovered_workflow.author(
                request, approval, approval_key=KEY,
                nonce_db="nonce.sqlite3", policy_id="carto-security",
                issuer="trusted-local",
            )
            after = {
                path.relative_to(package_root).as_posix(): path.read_bytes()
                for path in package_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertTrue(recovered["idempotent_replay"])
            self.assertEqual("validate", recovered["state"]["step"])

    def test_staging_package_is_create_once_and_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, brief = self._ready(root)
            approval = self._approval(project, brief)
            workflow.author(request, approval, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            marker = workdir / "staging/package/templates/design_spec.md"
            before = marker.read_bytes()
            with self.assertRaises(ProtocolError) as raised:
                workflow.author(request, approval, approval_key=KEY, nonce_db="nonce.sqlite3", policy_id="carto-security", issuer="trusted-local")
            self.assertEqual("STAGING_PACKAGE_EXISTS", raised.exception.code)
            self.assertEqual(before, marker.read_bytes())

    def test_non_scenario_kinds_remain_unavailable(self) -> None:
        for kind in ("map-brand", "map-style", "map-layout"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _, request, _, workflow = self._project(root, kind=kind)
                with self.assertRaises(ProtocolError) as raised:
                    workflow.analyze(request)
                self.assertEqual("CAPABILITY_NOT_AVAILABLE", raised.exception.code)

    def test_source_attestation_and_digest_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow = self._project(root)
            risk = project / "data/risk.geojson"
            value = json.loads(risk.read_text(encoding="utf-8"))
            value["carto_metadata"]["contains_sensitive_coordinates"] = True
            risk.write_text(json.dumps(value), encoding="utf-8")
            manifest = yaml.safe_load((project / "source-manifest.yaml").read_text(encoding="utf-8"))
            manifest["sources"][0]["digest"] = _digest(risk)
            _write_yaml(project / "source-manifest.yaml", manifest)
            with self.assertRaises(SecurityError) as raised:
                workflow.analyze(request)
            self.assertEqual("SYNTHETIC_SOURCE_ATTESTATION_INVALID", raised.exception.code)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow = self._project(root)
            shelter = project / "data/shelter.geojson"
            value = json.loads(shelter.read_text(encoding="utf-8"))
            value["features"][0]["geometry"]["coordinates"] = [181.0, 0.0]
            shelter.write_text(json.dumps(value), encoding="utf-8")
            manifest = yaml.safe_load((project / "source-manifest.yaml").read_text(encoding="utf-8"))
            manifest["sources"][1]["digest"] = _digest(shelter)
            _write_yaml(project / "source-manifest.yaml", manifest)
            with self.assertRaises(ProtocolError) as raised:
                workflow.analyze(request)
            self.assertEqual("GEOJSON_COORDINATES_INVALID", raised.exception.code)

    def test_workflow_paths_must_stay_under_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_temp, tempfile.TemporaryDirectory() as outside_temp:
            allowed = Path(allowed_temp)
            outside = Path(outside_temp)
            project = allowed / "project"
            project.mkdir()
            with self.assertRaises(SecurityError) as project_error:
                TemplateCreationWorkflow(allowed_roots=[allowed], project_root=outside, workdir="runs/job")
            self.assertEqual("PATH_OUTSIDE_ALLOWED_ROOT", project_error.exception.code)
            with self.assertRaises(SecurityError) as workdir_error:
                TemplateCreationWorkflow(allowed_roots=[allowed], project_root=project, workdir=outside / "job")
            self.assertEqual("PATH_OUTSIDE_ALLOWED_ROOT", workdir_error.exception.code)

    def test_cli_exposes_workflow_and_defers_later_phases(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as help_exit:
                cli_main(["create-template", "--help"])
        self.assertEqual(0, help_exit.exception.code)
        help_text = stdout.getvalue()
        self.assertIn("analyze", help_text)
        self.assertIn("validate", help_text)
        self.assertIn("publish", help_text)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = cli_main(["create-template", "render", "--project-root", str(project), "--workdir", "runs/job", "--allowed-root", str(root)])
            self.assertEqual(2, code)
            self.assertIn("CAPABILITY_NOT_AVAILABLE", stderr.getvalue())
            self.assertFalse((project / "runs/job").exists())


if __name__ == "__main__":
    unittest.main()

