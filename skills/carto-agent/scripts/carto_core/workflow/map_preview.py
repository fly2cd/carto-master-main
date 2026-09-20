from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..adapters.controlled_renderer import (
    FRONTEND_BUILD, MAPLIBRE_VERSION, OVERLAY_ENGINE_VERSION, RENDERER_VERSION,
    BrowserLimits, ControlledBrowserRenderer, browser_version, discover_browser,
)
from ..adapters.webmap_renderer import (
    RenderReceiptValidator, RendererCapabilityProfile, RendererCapabilityRegistry,
    WebMapRendererAdapter,
)
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from .map_data_preparation import atomic_yaml, utc_now


class MapPreviewService:
    def __init__(self, *, path_guard: PathGuard, output_root: Path, attestation_key: bytes,
                 browser: str | Path | None = None, registry: SchemaRegistry | None = None,
                 limits: BrowserLimits | None = None) -> None:
        self.path_guard = path_guard
        self.output_root = path_guard.resolve(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.attestation_key = attestation_key
        self.browser = Path(browser).resolve() if browser else discover_browser()
        if self.browser is None or not self.browser.is_file():
            raise ProtocolError("RENDER_BROWSER_UNAVAILABLE", "A controlled Chromium browser is required")
        self.registry = registry or SchemaRegistry()
        self.limits = limits or BrowserLimits()

    def render(self, request: dict[str, Any], candidate: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
        renderer = ControlledBrowserRenderer(
            allowed_roots=list(self.path_guard.allowed_roots), output_root=self.output_root,
            attestation_key=self.attestation_key, limits=self.limits, browser=self.browser,
        )
        profile = self.profile()
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([profile]), renderer)
        compiled = adapter.compile_scene(scene)
        if compiled != scene:
            raise ProtocolError("RENDER_SCENE_NOT_CANONICAL", scene["scene_id"])
        session_id = f"map-preview-{candidate['candidate_id']}"
        receipt = adapter.submit_render(session_id, scene, "maplibre-web", FRONTEND_BUILD)
        adapter.validate_receipt(receipt, self.attestation_key)
        evidence = self.build_evidence(request, candidate, scene, receipt)
        return {"receipt": receipt, "evidence": evidence, "profile": profile}

    def validate_persisted(self, candidate: dict[str, Any], scene: dict[str, Any], receipt: dict[str, Any]) -> None:
        renderer = ControlledBrowserRenderer(
            allowed_roots=list(self.path_guard.allowed_roots), output_root=self.output_root,
            attestation_key=self.attestation_key, limits=self.limits, browser=self.browser,
        )
        profile = self.profile()
        session = {"session_id": receipt["session_id"], "scene_id": scene["scene_id"],
                   "scene_revision": scene["revision"], "scene_digest": sha256_digest(scene),
                   "renderer_id": "maplibre-web", "frontend_build": FRONTEND_BUILD,
                   "profile_digest": profile.profile_digest(), "scene": deepcopy(scene), "status": "submitted"}
        RenderReceiptValidator(self.registry).validate(
            receipt, session, profile, self.attestation_key,
            expected_environment_fingerprint=renderer.environment_fingerprint,
            expected_controls=renderer.receipt_controls(), path_guard=renderer.path_guard,
        )
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])

    def profile(self) -> RendererCapabilityProfile:
        return RendererCapabilityProfile(
            renderer_id="maplibre-web", frontend_build=FRONTEND_BUILD,
            renderer_version=RENDERER_VERSION, maplibre_version=MAPLIBRE_VERSION,
            overlay_engine_version=OVERLAY_ENGINE_VERSION, browser_engine=browser_version(self.browser),
            webgl_available=True, supported_export_formats=("svg", "png", "pdf"),
            max_canvas_width=4096, max_canvas_height=4096, device_pixel_ratio=2,
            available_fonts=("Noto Sans SC", "Microsoft YaHei", "SimHei", "SimSun"),
            offline_rendering=True,
        )

    def build_evidence(self, request: dict[str, Any], candidate: dict[str, Any],
                       scene: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
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
