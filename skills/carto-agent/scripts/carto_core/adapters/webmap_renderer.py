from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from ..canonical import canonical_json_bytes, sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class RendererCapabilityProfile:
    """Capability handshake returned by a controlled renderer."""

    renderer_id: str
    frontend_build: str
    renderer_version: str
    maplibre_version: str
    overlay_engine_version: str
    browser_engine: str
    webgl_available: bool
    supported_export_formats: tuple[str, ...]
    max_canvas_width: int
    max_canvas_height: int
    device_pixel_ratio: float
    available_fonts: tuple[str, ...]
    offline_rendering: bool

    def profile_digest(self) -> str:
        return sha256_digest(asdict(self))


class RendererCapabilityRegistry:
    """Registry of immutable trusted renderer profiles."""

    def __init__(self, profiles: list[RendererCapabilityProfile] | None = None) -> None:
        self._profiles: dict[str, RendererCapabilityProfile] = {}
        for profile in profiles or []:
            self.register(profile)

    def register(self, profile: RendererCapabilityProfile) -> None:
        if profile.renderer_id in self._profiles:
            raise SecurityError("RENDERER_PROFILE_DUPLICATE", profile.renderer_id)
        if profile.max_canvas_width <= 0 or profile.max_canvas_height <= 0 or profile.device_pixel_ratio <= 0:
            raise ProtocolError("RENDERER_PROFILE_INVALID", profile.renderer_id)
        if not profile.supported_export_formats or len(profile.supported_export_formats) != len(set(profile.supported_export_formats)):
            raise ProtocolError("RENDERER_PROFILE_INVALID", profile.renderer_id)
        self._profiles[profile.renderer_id] = profile

    def get(self, renderer_id: str) -> RendererCapabilityProfile:
        try:
            return self._profiles[renderer_id]
        except KeyError as exc:
            raise SecurityError("RENDERER_PROFILE_UNKNOWN", renderer_id) from exc

    def is_trusted(self, renderer_id: str, frontend_build: str) -> bool:
        profile = self._profiles.get(renderer_id)
        return profile is not None and profile.frontend_build == frontend_build


class RenderSceneSemanticValidator:
    """Validate cross-object references and renderer capability requirements."""

    _SOURCE_KINDS = {
        "geojson": {"geojson"},
        "vector": {"vector-tiles"},
        "raster": {"raster-tiles"},
        "image": {"image"},
    }

    @staticmethod
    def _unique(items: list[dict[str, Any]], section: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for item in items:
            item_id = item["id"]
            if item_id in indexed:
                raise ProtocolError("RENDER_SCENE_DUPLICATE_ID", f"{section}:{item_id}")
            indexed[item_id] = item
        return indexed

    def validate(
        self,
        scene: dict[str, Any],
        profile: RendererCapabilityProfile | None = None,
    ) -> None:
        resources = self._unique(scene["resources"], "resources")
        sources = self._unique(scene["map"]["sources"], "sources")
        self._unique(scene["map"]["layers"], "layers")
        self._unique(scene["overlays"], "overlays")

        requirements = scene["renderer_requirements"]
        if scene["renderer_id"] != requirements["renderer_id"]:
            raise ProtocolError("RENDERER_REQUIREMENT_MISMATCH", scene["renderer_id"])

        for source in sources.values():
            resource = resources.get(source["resource_id"])
            if resource is None:
                raise ProtocolError("RENDER_SOURCE_RESOURCE_UNKNOWN", source["resource_id"])
            if resource["kind"] not in self._SOURCE_KINDS[source["type"]]:
                raise ProtocolError("RENDER_SOURCE_RESOURCE_INCOMPATIBLE", source["id"])

        for layer in scene["map"]["layers"]:
            if layer["source_id"] not in sources:
                raise ProtocolError("RENDER_LAYER_SOURCE_UNKNOWN", layer["source_id"])
            if "minzoom" in layer and "maxzoom" in layer and layer["minzoom"] > layer["maxzoom"]:
                raise ProtocolError("RENDER_LAYER_ZOOM_RANGE_INVALID", layer["id"])

        for overlay in scene["overlays"]:
            if overlay["type"] in {"symbol", "complex-symbol"}:
                resource = resources.get(overlay["symbol_ref"])
                if resource is None or resource["kind"] not in {"icon", "sprite", "symbol"}:
                    raise ProtocolError("RENDER_SYMBOL_RESOURCE_UNKNOWN", overlay["symbol_ref"])
            if overlay["coordinate_space"] == "feature" and overlay["source_id"] not in sources:
                raise ProtocolError("RENDER_FEATURE_SOURCE_UNKNOWN", overlay["source_id"])

        if profile is not None:
            self._validate_profile(scene, profile)

    @staticmethod
    def _validate_profile(scene: dict[str, Any], profile: RendererCapabilityProfile) -> None:
        requirements = scene["renderer_requirements"]
        viewport = scene["viewport"]
        if scene["renderer_id"] != profile.renderer_id:
            raise SecurityError("RENDERER_SCENE_MISMATCH", scene["renderer_id"])
        if viewport["width_px"] > profile.max_canvas_width or viewport["height_px"] > profile.max_canvas_height:
            raise ProtocolError("RENDER_VIEWPORT_UNSUPPORTED", f"{viewport['width_px']}x{viewport['height_px']}")
        if viewport["device_pixel_ratio"] > profile.device_pixel_ratio:
            raise ProtocolError("RENDER_DPR_UNSUPPORTED", str(viewport["device_pixel_ratio"]))
        if requirements["minimum_device_pixel_ratio"] > profile.device_pixel_ratio:
            raise ProtocolError("RENDER_MINIMUM_DPR_UNSUPPORTED", str(requirements["minimum_device_pixel_ratio"]))
        if requirements["require_webgl"] and not profile.webgl_available:
            raise ProtocolError("RENDER_WEBGL_UNAVAILABLE", profile.renderer_id)
        if requirements["require_offline_rendering"] and not profile.offline_rendering:
            raise ProtocolError("RENDER_OFFLINE_UNAVAILABLE", profile.renderer_id)
        unsupported = set(scene["export"]["targets"]) - set(profile.supported_export_formats)
        if unsupported:
            raise ProtocolError("RENDER_EXPORT_UNSUPPORTED", ",".join(sorted(unsupported)))
        missing_fonts = set(requirements["required_fonts"]) - set(profile.available_fonts)
        if missing_fonts:
            raise ProtocolError("RENDER_FONT_UNAVAILABLE", ",".join(sorted(missing_fonts)))
        available_capabilities = {"svg-overlay"}
        if profile.webgl_available:
            available_capabilities.update({"geographic-anchor", "feature-anchor"})
        if profile.webgl_available and profile.offline_rendering:
            available_capabilities.add("headless-export")
        missing = set(requirements["required_capabilities"]) - available_capabilities
        if missing:
            raise ProtocolError("RENDER_CAPABILITY_UNAVAILABLE", ",".join(sorted(missing)))


class RenderSessionGateway:
    """Stateful trusted bridge to a controlled renderer."""

    def __init__(self, registry: RendererCapabilityRegistry) -> None:
        self._registry = registry
        self._sessions: dict[str, dict[str, Any]] = {}
        self._semantic_validator = RenderSceneSemanticValidator()

    def start(self, session_id: str, renderer_id: str, frontend_build: str) -> dict[str, Any]:
        if session_id in self._sessions:
            raise ProtocolError("RENDER_SESSION_DUPLICATE", session_id)
        if not self._registry.is_trusted(renderer_id, frontend_build):
            raise SecurityError("RENDERER_NOT_TRUSTED", f"{renderer_id}@{frontend_build}")
        profile = self._registry.get(renderer_id)
        self._sessions[session_id] = {
            "session_id": session_id,
            "status": "started",
            "renderer_id": renderer_id,
            "frontend_build": frontend_build,
            "profile_digest": profile.profile_digest(),
        }
        return {"session_id": session_id, "status": "started", "renderer_profile_digest": profile.profile_digest()}

    def submit_scene(self, session_id: str, scene: dict[str, Any]) -> dict[str, Any]:
        session = self._get_mutable(session_id)
        if session["status"] != "started":
            raise ProtocolError("RENDER_SESSION_STATE_INVALID", session["status"])
        SchemaRegistry().validate("render-scene", scene)
        profile = self._registry.get(session["renderer_id"])
        self._semantic_validator.validate(scene, profile)
        scene_snapshot = deepcopy(scene)
        digest = sha256_digest(scene_snapshot)
        session.update({
            "status": "submitted",
            "scene_id": scene_snapshot["scene_id"],
            "scene_revision": scene_snapshot["revision"],
            "scene_digest": digest,
            "scene": scene_snapshot,
        })
        return {
            "session_id": session_id,
            "scene_id": scene_snapshot["scene_id"],
            "scene_revision": scene_snapshot["revision"],
            "scene_digest": digest,
            "renderer_profile_digest": session["profile_digest"],
            "status": "submitted",
        }

    def get(self, session_id: str) -> dict[str, Any]:
        return deepcopy(self._get_mutable(session_id))

    def _get_mutable(self, session_id: str) -> dict[str, Any]:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise ProtocolError("RENDER_SESSION_UNKNOWN", session_id) from exc

    def close(self, session_id: str) -> dict[str, Any]:
        session = self._get_mutable(session_id)
        session["status"] = "closed"
        return {"session_id": session_id, "status": "closed"}


def compute_renderer_attestation(receipt: dict[str, Any], key: bytes) -> str:
    if len(key) < 32:
        raise SecurityError("RENDER_ATTESTATION_KEY_WEAK", "Attestation key must be at least 32 bytes")
    payload = dict(receipt)
    payload.pop("renderer_attestation", None)
    return hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


class RenderReceiptValidator:
    """Verify a signed receipt against its submitted session and renderer profile."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self._registry = registry or SchemaRegistry()

    def validate(
        self,
        receipt: dict[str, Any],
        session: dict[str, Any],
        profile: RendererCapabilityProfile,
        attestation_key: bytes,
    ) -> None:
        self._registry.validate("render-receipt", receipt)
        expected_attestation = compute_renderer_attestation(receipt, attestation_key)
        if not hmac.compare_digest(receipt["renderer_attestation"], expected_attestation):
            raise SecurityError("RENDER_ATTESTATION_INVALID", receipt["receipt_id"])
        if receipt["status"] != "succeeded":
            raise ProtocolError("RENDER_RECEIPT_FAILED", receipt["receipt_id"])
        expected = {
            "session_id": session["session_id"],
            "scene_id": session["scene_id"],
            "scene_revision": session["scene_revision"],
            "scene_digest": session["scene_digest"],
            "renderer_id": profile.renderer_id,
            "renderer_profile_digest": profile.profile_digest(),
            "frontend_build_version": profile.frontend_build,
            "renderer_version": profile.renderer_version,
            "maplibre_version": profile.maplibre_version,
            "overlay_engine_version": profile.overlay_engine_version,
            "browser_version": profile.browser_engine,
        }
        for field, value in expected.items():
            if receipt[field] != value:
                raise ProtocolError("RENDER_RECEIPT_BINDING_MISMATCH", field)

        scene = session["scene"]
        if receipt["viewport"] != {key: scene["viewport"][key] for key in ("width_px", "height_px", "device_pixel_ratio")}:
            raise ProtocolError("RENDER_RECEIPT_VIEWPORT_MISMATCH", receipt["scene_id"])
        started = datetime.fromisoformat(receipt["render_started_at"].replace("Z", "+00:00"))
        completed = datetime.fromisoformat(receipt["render_completed_at"].replace("Z", "+00:00"))
        if completed < started:
            raise ProtocolError("RENDER_RECEIPT_TIME_INVALID", receipt["receipt_id"])

        evidence = {item["resource_id"]: item for item in receipt["resource_evidence"]}
        if len(evidence) != len(receipt["resource_evidence"]):
            raise ProtocolError("RENDER_RESOURCE_EVIDENCE_DUPLICATE", receipt["receipt_id"])
        scene_resource_ids = {resource["id"] for resource in scene["resources"]}
        unknown_evidence = set(evidence) - scene_resource_ids
        if unknown_evidence:
            raise ProtocolError("RENDER_RESOURCE_EVIDENCE_UNKNOWN", ",".join(sorted(unknown_evidence)))
        for resource in scene["resources"]:
            if resource["required"] and evidence.get(resource["id"], {}).get("status") != "loaded":
                raise ProtocolError("RENDER_REQUIRED_RESOURCE_NOT_LOADED", resource["id"])
            if resource["id"] in evidence and evidence[resource["id"]]["digest"] != resource["ref"]["digest"]:
                raise ProtocolError("RENDER_RESOURCE_DIGEST_MISMATCH", resource["id"])

        targets = [item["target"] for item in receipt["output_artifacts"]]
        if len(targets) != len(set(targets)) or set(targets) != set(scene["export"]["targets"]):
            raise ProtocolError("RENDER_OUTPUT_TARGET_MISMATCH", receipt["receipt_id"])


class WebMapRendererAdapter:
    """Backend adapter for the MapLibre GL JS and SVG overlay renderer pipeline."""

    DEFAULT_RENDERER = "maplibre-web"

    def __init__(self, registry: RendererCapabilityRegistry | None = None) -> None:
        self._registry = registry or RendererCapabilityRegistry()
        self._gateway = RenderSessionGateway(self._registry)
        self._semantic_validator = RenderSceneSemanticValidator()
        self._receipt_validator = RenderReceiptValidator()

    def capabilities(self) -> set[str]:
        return {"maplibre-web", "svg-overlay", "controlled-render-session"}

    def compile_scene(self, request: dict[str, Any]) -> dict[str, Any]:
        scene = deepcopy(request)
        scene.setdefault("schema_version", 1)
        scene.setdefault("renderer_id", self.DEFAULT_RENDERER)
        SchemaRegistry().validate("render-scene", scene)
        self._semantic_validator.validate(scene)
        return scene

    def submit_render(
        self,
        session_id: str,
        scene: dict[str, Any],
        renderer_id: str,
        frontend_build: str,
    ) -> dict[str, Any]:
        self._gateway.start(session_id, renderer_id, frontend_build)
        try:
            return self._gateway.submit_scene(session_id, scene)
        except Exception:
            self._gateway.close(session_id)
            raise

    def validate_receipt(self, receipt: dict[str, Any], attestation_key: bytes) -> None:
        session = self._gateway.get(receipt["session_id"])
        if session["status"] != "submitted":
            raise ProtocolError("RENDER_SESSION_STATE_INVALID", session["status"])
        profile = self._registry.get(session["renderer_id"])
        self._receipt_validator.validate(receipt, session, profile, attestation_key)
        self._gateway.close(receipt["session_id"])
