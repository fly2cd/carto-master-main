"""Closed backend dispatch used by preview, locked render and persisted validation."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path

from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..errors import ProtocolError
from .controlled_renderer import (FRONTEND_BUILD, MAPLIBRE_VERSION, OVERLAY_ENGINE_VERSION,
    RENDERER_VERSION, BrowserLimits, ControlledBrowserRenderer, browser_version, discover_browser)
from .webmap_renderer import (RendererCapabilityProfile, RendererCapabilityRegistry,
                             RenderReceiptValidator, WebMapRendererAdapter)


class BrowserRenderBackend:
    def __init__(self, *, path_guard, output_root, attestation_key, browser=None, limits=None, registry, **_):
        self.registry, self.key = registry, attestation_key
        selected = Path(browser).resolve() if browser else discover_browser()
        if selected is None or not selected.is_file():
            raise ProtocolError("RENDER_BROWSER_UNAVAILABLE", "A controlled Chromium browser is required")
        self.profile = RendererCapabilityProfile(
            renderer_id="maplibre-web", frontend_build=FRONTEND_BUILD, renderer_version=RENDERER_VERSION,
            maplibre_version=MAPLIBRE_VERSION, overlay_engine_version=OVERLAY_ENGINE_VERSION,
            browser_engine=browser_version(selected), webgl_available=True,
            supported_export_formats=("svg", "png", "pdf"), max_canvas_width=4096, max_canvas_height=4096,
            device_pixel_ratio=2, available_fonts=("Noto Sans SC", "Microsoft YaHei", "SimHei", "SimSun"),
            offline_rendering=True)
        output_root = path_guard.resolve(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        self.renderer = ControlledBrowserRenderer(allowed_roots=list(path_guard.allowed_roots), output_root=output_root,
            attestation_key=attestation_key, limits=limits or BrowserLimits(), browser=selected)
        self.environment_fingerprint = self.renderer.environment_fingerprint

    def environment_snapshot(self):
        return {"renderer_id": self.profile.renderer_id, "renderer_version": self.profile.renderer_version,
                "frontend_build": self.profile.frontend_build, "maplibre_version": self.profile.maplibre_version,
                "overlay_engine_version": self.profile.overlay_engine_version, "fingerprint": self.environment_fingerprint}

    def validate_scene(self, scene, execution=None):
        if scene.get("renderer_id") != "maplibre-web":
            raise ProtocolError("RENDER_BACKEND_MISMATCH", "Browser backend requires a browser scene")
        if execution is not None:
            LayoutResolver(self.registry).validate_execution(scene, execution)
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([self.profile]), self.renderer)
        if adapter.compile_scene(scene) != scene:
            raise ProtocolError("RENDER_SCENE_NOT_CANONICAL", scene["scene_id"])

    @staticmethod
    def scene_texts(scene):
        return [o["content"] for o in scene["overlays"] if o.get("type") in {"text", "attribution"}
                and o.get("coordinate_space") == "page"]

    def render(self, session_id, scene):
        self.validate_scene(scene)
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([self.profile]), self.renderer)
        receipt = adapter.submit_render(session_id, scene, self.profile.renderer_id, FRONTEND_BUILD)
        adapter.validate_receipt(receipt, self.key)
        return receipt

    def validate_receipt(self, scene, receipt, *, verify_outputs=True, expected_session_id=None):
        self.validate_scene(scene)
        if expected_session_id is not None and receipt["session_id"] != expected_session_id:
            raise ProtocolError("RENDER_RECEIPT_SESSION_MISMATCH", "Receipt belongs to a different attempt")
        session = {"session_id": receipt["session_id"], "scene_id": scene["scene_id"], "scene_revision": scene["revision"],
                   "scene_digest": sha256_digest(scene), "renderer_id": self.profile.renderer_id,
                   "frontend_build": FRONTEND_BUILD, "profile_digest": self.profile.profile_digest(),
                   "scene": deepcopy(scene), "status": "submitted"}
        RenderReceiptValidator(self.registry).validate(receipt, session, self.profile, self.key,
            expected_environment_fingerprint=self.environment_fingerprint,
            expected_controls=self.renderer.receipt_controls(),
            path_guard=self.renderer.path_guard if verify_outputs else None)


def create_render_backend(renderer_id, **kwargs):
    if renderer_id == "maplibre-web":
        return BrowserRenderBackend(**kwargs)
    if renderer_id == "rasterio-matplotlib-page":
        from .raster_formal_renderer import RasterFormalRenderer
        kwargs.pop("browser", None)
        kwargs.pop("limits", None)
        return RasterFormalRenderer(**kwargs)
    raise ProtocolError("RENDER_BACKEND_NOT_AVAILABLE", str(renderer_id))
