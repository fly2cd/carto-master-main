from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..adapters.controlled_renderer import BrowserLimits
from ..adapters.render_backend import create_render_backend
from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from ..artifacts import atomic_yaml, utc_now


class MapPreviewService:
    def __init__(self, *, path_guard: PathGuard, output_root: Path, attestation_key: bytes,
                 browser: str | Path | None = None, registry: SchemaRegistry | None = None,
                 limits: BrowserLimits | None = None, project_root: Path | None = None, context=None) -> None:
        self.path_guard = path_guard
        self.output_root = path_guard.resolve(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.attestation_key = attestation_key
        self.browser = browser
        self.registry = registry or SchemaRegistry()
        self.limits = limits or BrowserLimits()
        self.project_root, self.context = project_root, context

    def backend(self, scene):
        return create_render_backend(scene["renderer_id"], path_guard=self.path_guard, output_root=self.output_root,
            attestation_key=self.attestation_key, browser=self.browser, limits=self.limits, registry=self.registry,
            project_root=self.project_root, context=self.context)

    def _validate_candidate_scene(self, candidate: dict[str, Any], scene: dict[str, Any]) -> None:
        self.registry.validate("resolved-map", candidate)
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        LayoutResolver(self.registry).validate_execution(scene, candidate["execution"])

    def render(self, request: dict[str, Any], candidate: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
        self._validate_candidate_scene(candidate, scene)
        backend = self.backend(scene)
        backend.validate_scene(scene, candidate["execution"])
        receipt = backend.render(f"map-preview-{candidate['candidate_id']}", scene)
        backend.validate_receipt(scene, receipt, expected_session_id=f"map-preview-{candidate['candidate_id']}")
        evidence = self.build_evidence(request, candidate, scene, receipt)
        return {"receipt": receipt, "evidence": evidence, "profile": asdict(backend.profile)}

    def validate_persisted(self, candidate: dict[str, Any], scene: dict[str, Any], receipt: dict[str, Any]) -> None:
        self._validate_candidate_scene(candidate, scene)
        backend = self.backend(scene)
        backend.validate_scene(scene, candidate["execution"])
        backend.validate_receipt(scene, receipt, expected_session_id=f"map-preview-{candidate['candidate_id']}")

    def build_evidence(self, request: dict[str, Any], candidate: dict[str, Any],
                       scene: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        self._validate_candidate_scene(candidate, scene)
        checks = [
            {"check_id": "template.candidate-binding", "owner": "template", "status": "passed", "severity": "blocker", "details": {}},
            {"check_id": "data.resource-digests", "owner": "data", "status": "passed", "severity": "blocker", "details": {}},
            {"check_id": "plan.execution-digest", "owner": "plan", "status": "passed", "severity": "blocker", "details": {}},
            {"check_id": "adapter.render-attestation", "owner": "adapter", "status": "passed", "severity": "blocker", "details": {}},
        ]
        body = {
            "schema_version": 1, "evidence_id": f"preview-{request['run_id']}",
            "project_id": request["project_id"], "run_id": request["run_id"],
            "candidate_digest": sha256_digest(candidate),
            "candidate_execution_digest": candidate["execution_digest"],
            "render_scene_digest": sha256_digest(scene),
            "render_receipt_ref": {"id": receipt["receipt_id"], "version": "1.0.0", "digest": sha256_digest(receipt)},
            "render_execution_digest": receipt["execution_digest"],
            "environment_fingerprint": receipt["environment_fingerprint"],
            "output_artifacts": [{"target": item["target"], "artifact_ref": item["artifact_ref"]}
                                 for item in receipt["output_artifacts"]],
            "checks": checks, "status": "passed", "created_at": utc_now(),
        }
        evidence = {**body, "evidence_digest": sha256_digest(body)}
        self.registry.validate("map-preview-evidence", evidence)
        return evidence

    @staticmethod
    def validate_evidence(evidence: dict[str, Any], candidate: dict[str, Any],
                          scene: dict[str, Any], receipt: dict[str, Any], registry: SchemaRegistry) -> None:
        registry.validate("map-preview-evidence", evidence)
        body = dict(evidence)
        supplied = body.pop("evidence_digest")
        if sha256_digest(body) != supplied:
            raise ProtocolError("PREVIEW_EVIDENCE_DIGEST_MISMATCH", evidence["evidence_id"])
        expected = {
            "project_id": candidate["project_id"],
            "run_id": candidate["run_id"],
            "candidate_digest": sha256_digest(candidate),
            "candidate_execution_digest": candidate["execution_digest"],
            "render_scene_digest": sha256_digest(scene),
            "render_receipt_ref": {"id": receipt["receipt_id"], "version": "1.0.0", "digest": sha256_digest(receipt)},
            "render_execution_digest": receipt["execution_digest"],
            "environment_fingerprint": receipt["environment_fingerprint"],
            "output_artifacts": [
                {"target": item["target"], "artifact_ref": item["artifact_ref"]}
                for item in receipt["output_artifacts"]
            ],
        }
        for key, value in expected.items():
            if evidence[key] != value:
                raise ProtocolError("PREVIEW_EVIDENCE_BINDING_MISMATCH", key)
        checks = evidence["checks"]
        check_ids = [item["check_id"] for item in checks]
        if len(check_ids) != len(set(check_ids)):
            raise ProtocolError("PREVIEW_EVIDENCE_CHECK_DUPLICATE", evidence["evidence_id"])
        expected_owners = {"template", "data", "plan", "adapter"}
        owners = {item["owner"] for item in checks}
        if owners != expected_owners:
            raise ProtocolError("PREVIEW_EVIDENCE_OWNER_COVERAGE_MISMATCH", evidence["evidence_id"])
        if evidence["status"] != "passed" or any(item["status"] != "passed" for item in checks):
            raise ProtocolError("PREVIEW_EVIDENCE_FAILED", evidence["evidence_id"])


def freeze_object_digest(request: dict[str, Any], candidate: dict[str, Any], evidence: dict[str, Any]) -> str:
    return sha256_digest({
        "candidate_digest": sha256_digest(candidate),
        "execution_digest": candidate["execution_digest"],
        "preview_evidence_digest": evidence["evidence_digest"],
        "project_id": request["project_id"], "scope": request["scope"],
        "environment": request["environment"],
        "environment_fingerprint": evidence["environment_fingerprint"],
    })
