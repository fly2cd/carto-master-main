"""Segment validation via a platform validation host (plan phase-1 裁决2).

The host is a deterministic synthetic scenario shell built from the admitted scenario's
contract builders (canonical style + layout + spatial_behavior + portrayal + fixture). It
is NOT a published business template and never enters the business index. To validate a
segment, the segment-under-test is injected into the shell's embedded slot (style or
layout); the complementary slot keeps the canonical host contract. The existing scenario
``validation_scene`` builds the frozen sample scene and the generic raster renderer
produces a real RenderReceipt — no parallel page engine, no fabricated evidence.

Color note: the synthetic fixture uses the registered categorical palette, so category
colors come from the classification contract, not the style (Path A color authority is a
separate increment). This host therefore verifies typography/layout/appearance effects of
a segment now; style-driven category-color verification lands with Path A.
"""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..artifacts import artifact_ref, atomic_yaml, file_digest
from ..canonical import sha256_digest
from ..errors import CartoError, ProtocolError, SecurityError
from ..repository.segment_authoring import segment_identity
from ..repository.template_matching import SEGMENT_CONTRACTS
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard

HOST_ID = "general-thematic-raster-host"
HOST_VERSION = "1.0.0"
VALIDATOR_VERSION = "1.0.0"
_FIXTURE_REL = "fixtures/validation-input.csv"


def _select_font(font_path: str | Path | None) -> Path:
    candidates: list[Path] = []
    if font_path is not None:
        candidates.append(Path(font_path))
    windows = os.environ.get("WINDIR")
    if windows:
        candidates.extend([
            Path(windows) / "Fonts" / "NotoSansSC-VF.ttf",
            Path(windows) / "Fonts" / "msyh.ttc",
            Path(windows) / "Fonts" / "simhei.ttf",
            Path(windows) / "Fonts" / "simsun.ttc",
        ])
    candidates.extend([
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ProtocolError("RENDER_FONT_UNAVAILABLE", "No approved local font was found")


def build_host(registry: SchemaRegistry, host_root: Path, *, kind: str,
               design: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Resolve the registered validation host and build its shell via the component hook.

    The kernel never imports a concrete scenario module: the host shell construction lives
    in the scenario's registered ``segment_validation_host`` component (plan 裁决2).
    """
    from ..scenario_registry import ScenarioRegistry
    profile = ScenarioRegistry(registry).for_segment_validation_host()
    return profile.component("segment_validation_host")(
        kind, design, host_root=host_root, registry=registry)


def _render(scene: dict[str, Any], *, workspace: Path, attestation_key: bytes,
            context: Any, registry: SchemaRegistry, session_id: str) -> tuple[dict, Any]:
    from ..adapters.render_backend import create_render_backend
    workspace = Path(workspace)
    (workspace / "render").mkdir(parents=True, exist_ok=True)
    renderer = create_render_backend(
        scene["renderer_id"], path_guard=PathGuard([workspace]),
        output_root=workspace / "render", attestation_key=attestation_key,
        project_root=workspace, context=context, registry=registry)
    receipt = renderer.render(session_id, scene)
    renderer.validate_receipt(scene, receipt)
    return receipt, renderer.profile


class SegmentPackageValidator:
    """Static segment checks + host-based sample rendering + segment evidence assembly."""

    def __init__(self, *, path_guard: PathGuard, package_root: Path, evidence_root: Path,
                 attestation_key: bytes, registry: SchemaRegistry,
                 font_path: str | Path | None, context: Any) -> None:
        self.path_guard = path_guard
        self.package_root = Path(package_root)
        self.evidence_root = Path(evidence_root)
        self.attestation_key = attestation_key
        self.registry = registry
        self.font_path = font_path
        self.context = context

    def _static(self, expected: dict[str, Any], design: dict[str, Any],
                results: list[dict[str, Any]]) -> dict[str, Any]:
        from ..repository.staging_package import StagingPackageWriter
        manifest = load_document(self.package_root / "manifest.yaml")
        self.registry.validate("manifest", manifest)
        package = manifest["package"]
        identity = segment_identity(expected["kind"], expected["namespace"],
                                    expected["id"], expected["version"])
        if {k: package[k] for k in ("namespace", "kind", "id", "version")} != identity:
            raise ProtocolError("VALIDATION_IDENTITY_MISMATCH", expected["id"])
        contract_path, schema_name = SEGMENT_CONTRACTS[package["kind"]]
        contract = load_document(self.package_root / contract_path)
        self.registry.validate(schema_name, contract)
        if sha256_digest(contract) != sha256_digest(design):
            raise ProtocolError("VALIDATION_DESIGN_DRIFT", expected["id"])
        # Closed-package integrity (checksums + file set + lock), segment branch. The writer
        # is constructed normally and its public verify_closed_package is used (no private
        # cross-object reach; encapsulation guard).
        writer = StagingPackageWriter(self.path_guard, self.package_root.parents[1], self.registry)
        checksums = dict(manifest["checksums"])
        all_checksums = {"manifest.yaml": file_digest(self.package_root / "manifest.yaml"), **checksums}
        writer.verify_closed_package(self.package_root, manifest, all_checksums)
        lock = load_document(self.package_root / manifest["dependency_lock"])
        return {
            "manifest": manifest,
            "package_digest": file_digest(self.package_root / "checksums.sha256"),
            "manifest_digest": file_digest(self.package_root / "manifest.yaml"),
            "dependency_lock_digest": sha256_digest(lock),
            "design_digest": sha256_digest(design),
        }

    def validate(self, expected: dict[str, Any], expected_targets: list[str],
                 design: dict[str, Any]) -> dict[str, Any]:
        from ..scenario_registry import ScenarioRegistry
        results: list[dict[str, Any]] = []
        try:
            snapshot = self._static(expected, design, results)
            results.append(self._result("segment.package-closed", True,
                                        {"package_digest": snapshot["package_digest"]}))
            results.append(self._result("segment.contract-valid", True,
                                        {"kind": expected["kind"], "design_digest": snapshot["design_digest"]}))
        except (CartoError, OSError, ValueError, TypeError) as exc:
            results.append(self._result("segment.package-closed", False, exc))
            return self._evidence(expected, snapshot_fallback(expected), results,
                                  renderer=None, receipt=None, scene=None, host=None)
        if sorted(expected_targets) != ["pdf", "png"]:
            results.append(self._result("segment.target-capability", False,
                                        ProtocolError("RENDER_TARGET_UNSUPPORTED", "segment sample requires pdf and png")))
            return self._evidence(expected, snapshot, results, renderer=None, receipt=None, scene=None, host=None)
        try:
            font = _select_font(self.font_path)
            host_root, host_snapshot, descriptor, category_colors = build_host(
                self.registry, self.evidence_root / "host", kind=expected["kind"], design=design)
            host_profile = ScenarioRegistry(self.registry).for_segment_validation_host()
            scene = host_profile.component("validation_scene")(
                host_root, host_snapshot, ["pdf", "png"], font, VALIDATOR_VERSION,
                context=self.context, workspace=self.evidence_root / "host" / "fixture",
                registry=self.registry, category_colors=category_colors)
            session_id = f"segment-validation-{snapshot['package_digest'][7:23]}-{sha256_digest(scene)[7:23]}"
            receipt, profile = _render(
                scene, workspace=self.evidence_root / "host" / "fixture",
                attestation_key=self.attestation_key, context=self.context,
                registry=self.registry, session_id=session_id)
            renderer_binding = {
                "renderer_id": profile.renderer_id,
                "renderer_profile_digest": profile.profile_digest(),
                "adapter_version": "1.1.0",
                "renderer_version": receipt["renderer_version"],
                "renderer_code_digest": receipt["renderer_code_digest"],
                "runtime": deepcopy(receipt["runtime"]),
                "environment_fingerprint": receipt["environment_fingerprint"],
            }
            results.append(self._result("segment.sample-render", True,
                                        {"receipt_digest": sha256_digest(receipt)}))
            try:
                results.extend(self._reference_comparison(expected, receipt, design))
            except (CartoError, OSError, ValueError) as exc:
                results.append(self._result("reference.round-trip", False, exc))
            host_ref = self._write_host(descriptor)
            return self._evidence(expected, snapshot, results, renderer=renderer_binding,
                                  receipt=receipt, scene=scene, host=host_ref)
        except (CartoError, OSError, ValueError) as exc:
            results.append(self._result("segment.sample-render", False, exc))
            return self._evidence(expected, snapshot, results, renderer=None, receipt=None, scene=None, host=None)

    def verify_evidence(self, evidence: dict[str, Any], expected: dict[str, Any],
                        expected_targets: list[str], design: dict[str, Any]) -> dict[str, Any]:
        from ..adapters.webmap_renderer import compute_renderer_attestation
        self.registry.validate("segment-validation-evidence", evidence)
        body = dict(evidence)
        supplied = body.pop("evidence_digest")
        if sha256_digest(body) != supplied:
            raise ProtocolError("VALIDATION_EVIDENCE_DIGEST_MISMATCH", evidence["evidence_id"])
        if evidence["status"] != "passed" or evidence["counts"]["blocker"] or evidence["counts"]["error"]:
            raise ProtocolError("TEMPLATE_VALIDATION_FAILED", evidence["evidence_id"])
        snapshot = self._static(expected, design, [])
        for key, value in {
            "package_ref": self._package_ref(snapshot, expected),
            "manifest_digest": snapshot["manifest_digest"],
            "dependency_lock_digest": snapshot["dependency_lock_digest"],
            "design_digest": snapshot["design_digest"],
        }.items():
            if evidence[key] != value:
                raise ProtocolError("VALIDATION_EVIDENCE_STALE", key)
        receipt_path = self.path_guard.resolve(evidence["render_receipt_ref"]["uri"], must_exist=True)
        receipt = load_document(receipt_path)
        self.registry.validate("render-receipt", receipt)
        if sha256_digest(receipt) != evidence["render_receipt_ref"]["digest"]:
            raise ProtocolError("VALIDATION_RENDER_RECEIPT_DRIFT", str(receipt_path))
        if receipt.get("renderer_attestation") != compute_renderer_attestation(receipt, self.attestation_key):
            raise ProtocolError("VALIDATION_RENDER_ATTESTATION_INVALID", receipt.get("receipt_id", "unknown"))
        scene_ref = evidence["render_scene_ref"]
        scene_path = self.path_guard.resolve(scene_ref["uri"], must_exist=True)
        scene = load_document(scene_path)
        self.registry.validate("render-scene", scene)
        if sha256_digest(scene) != scene_ref["digest"] or receipt["scene_digest"] != scene_ref["digest"]:
            raise ProtocolError("VALIDATION_RENDER_SCENE_DRIFT", str(scene_path))
        # Re-render the frozen scene through the generic backend and compare the receipt.
        host_root, host_snapshot, descriptor, _ = build_host(
            self.registry, self.evidence_root / "host", kind=expected["kind"], design=design)
        if sha256_digest(descriptor) != evidence["host_ref"]["digest"]:
            raise ProtocolError("VALIDATION_HOST_DRIFT", evidence["host_ref"]["uri"])
        rerendered_receipt, _ = _render(scene, workspace=self.evidence_root / "host" / "fixture",
                attestation_key=self.attestation_key, context=self.context,
                registry=self.registry, session_id=f"segment-reverify-{sha256_digest(scene)[7:23]}")
        # §5.3.7: re-render must reproduce the frozen preview outputs by content digest, not
        # merely re-invoke render and discard the result. A renderer/code drift that changes
        # the output for the same frozen scene is caught here (deterministic replay invariant).
        rerendered_digests = {i["target"]: i["artifact_ref"]["digest"]
                              for i in rerendered_receipt["output_artifacts"]}
        frozen_digests = {i["target"]: i["artifact_ref"]["digest"]
                          for i in evidence["preview_artifacts"]}
        if rerendered_digests != frozen_digests:
            raise ProtocolError("VALIDATION_RERENDER_DRIFT", evidence["evidence_id"])
        receipt_artifacts = {i["target"]: i["artifact_ref"] for i in receipt["output_artifacts"]}
        evidence_artifacts = {i["target"]: i["artifact_ref"] for i in evidence["preview_artifacts"]}
        if receipt_artifacts != evidence_artifacts or set(receipt_artifacts) != set(expected_targets):
            raise ProtocolError("VALIDATION_PREVIEW_BINDING_MISMATCH", evidence["evidence_id"])
        for artifact in evidence["preview_artifacts"]:
            path = self.path_guard.resolve(artifact["artifact_ref"]["uri"], must_exist=True)
            if file_digest(path) != artifact["artifact_ref"]["digest"]:
                raise ProtocolError("VALIDATION_PREVIEW_DRIFT", artifact["target"])
        return snapshot

    def _reference_comparison(self, expected: dict[str, Any], receipt: dict[str, Any],
                              design: dict[str, Any]) -> list[dict[str, Any]]:
        """Declaration-driven post-validate perceptual comparison (phase 2 §5.3.3/§5.3.4).

        Whether the comparison is REQUIRED is decided by the request declaring a reference
        source (expected['reference_declared']), NOT by file existence: a declared reference
        whose evidence is missing/corrupt fails closed (deleting the file cannot cancel the
        check); an ordinary segment without a reference declaration is unaffected. Effective
        colors come from the design's discrete symbol roles when bound (§5.3.4); without a
        role binding the host canonical colors only prove the validation partner, not that
        user colors took effect (user_color_bound=False).
        """
        if not expected.get("reference_declared"):
            return []
        reference_dir = self.package_root.parents[1] / "reference"
        proposal_path = reference_dir / "proposal.yaml"
        reference_path = reference_dir / "reference.png"
        if not proposal_path.is_file() or not reference_path.is_file():
            return [self._result("reference.round-trip", False,
                                 ProtocolError("REFERENCE_EVIDENCE_MISSING",
                                               "declared reference evidence is missing or unreadable"))]
        from .reference_segment import compare_reference_render
        from ..compiler.style_colors import style_discrete_colors
        reference_png = reference_path.read_bytes()
        proposal = load_document(proposal_path)
        proposed_colors = proposal["recovered"]["ramps"][0]["colors"]
        role_colors = style_discrete_colors(design) if expected["kind"] == "map-style" else {}
        effective_colors = sorted(role_colors.values()) if role_colors else None
        png_artifact = next((i for i in receipt["output_artifacts"] if i["target"] == "png"), None)
        if png_artifact is None:
            return [self._result("reference.round-trip", False,
                                 ProtocolError("REFERENCE_COMPARISON_NO_PNG", "rendered sample has no png"))]
        rendered_path = self.path_guard.resolve(png_artifact["artifact_ref"]["uri"], must_exist=True)
        report = compare_reference_render(reference_png, rendered_path.read_bytes(),
                                          proposed_colors=proposed_colors,
                                          effective_colors=effective_colors, registry=self.registry)
        deviation = report["redline_deviation"]
        return [
            self._result("reference.round-trip", True,
                         {**report["round_trip"], "user_color_bound": bool(role_colors)}),
            self._result("reference.redline-deviation", not deviation["requires_authorization"], deviation),
        ]

    def _write_host(self, descriptor: dict[str, Any]) -> dict[str, str]:
        host_path = self.evidence_root / "validation-host.yaml"
        atomic_yaml(host_path, descriptor)
        return {"id": "validation-host", "version": HOST_VERSION,
                "digest": sha256_digest(descriptor), "uri": str(host_path)}

    def _package_ref(self, snapshot: dict[str, Any], expected: dict[str, Any]) -> dict[str, str]:
        return {"kind": expected["kind"], "id": expected["id"],
                "version": expected["version"], "digest": snapshot["package_digest"]}

    def _evidence(self, expected, snapshot, results, *, renderer, receipt, scene, host) -> dict[str, Any]:
        counts = {sev: sum(1 for r in results if r["severity"] == sev and r["status"] == "failed")
                  for sev in ("blocker", "error", "warning", "info")}
        passed = not (counts["blocker"] or counts["error"]) and receipt is not None
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "evidence_id": f"seg-validation-{snapshot['package_digest'][7:23]}",
            "namespace": expected["namespace"],
            "package_ref": self._package_ref(snapshot, expected),
            "manifest_digest": snapshot["manifest_digest"],
            "dependency_lock_digest": snapshot["dependency_lock_digest"],
            "design_digest": snapshot["design_digest"],
            "host_ref": host or {"id": "validation-host", "version": HOST_VERSION,
                                 "digest": sha256_digest({}), "uri": "validation-host.yaml"},
            "checker_set_digest": sha256_digest({"phase": "segment-validate", "version": VALIDATOR_VERSION}),
            "status": "passed" if passed else "failed",
            "counts": counts, "results": results, "created_at": _utc_now(),
        }
        if renderer is not None:
            evidence["renderer"] = renderer
        if receipt is not None:
            receipt_path = self.evidence_root / "render-receipt.yaml"
            evidence["render_receipt_ref"] = {"id": "fixture-render-receipt", "version": "1.0.0",
                                              "digest": sha256_digest(receipt), "uri": str(receipt_path)}
            evidence["preview_artifacts"] = [{"target": i["target"], "artifact_ref": i["artifact_ref"]}
                                             for i in receipt["output_artifacts"]]
        if scene is not None:
            evidence["render_scene_ref"] = {"id": "fixture-render-scene", "version": "1.0.0",
                                            "digest": sha256_digest(scene),
                                            "uri": str(self.evidence_root / "render-scene.yaml")}
        evidence["evidence_digest"] = sha256_digest(evidence)
        self.registry.validate("segment-validation-evidence", evidence)
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        if receipt is not None:
            atomic_yaml(self.evidence_root / "render-receipt.yaml", receipt)
        if scene is not None:
            atomic_yaml(self.evidence_root / "render-scene.yaml", scene)
        atomic_yaml(self.evidence_root / "segment-validation-evidence.yaml", evidence)
        return evidence

    def _result(self, check_id: str, passed: bool, details: Any) -> dict[str, Any]:
        if isinstance(details, Exception):
            details = {"code": getattr(details, "code", type(details).__name__), "message": str(details)[:500]}
        return {"check_id": check_id, "version": VALIDATOR_VERSION,
                "status": "passed" if passed else "failed",
                "severity": "info" if passed else "blocker", "details": details}


def snapshot_fallback(expected: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_digest({"expected": expected})
    return {"package_digest": digest, "manifest_digest": digest,
            "dependency_lock_digest": digest, "design_digest": digest}


def _utc_now() -> str:
    from ..artifacts import utc_now
    return utc_now()