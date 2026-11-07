"""Truthful formal attestation for the local Rasterio + Matplotlib page backend.

This is an in-process, project-path-restricted renderer, not an OS/network sandbox.
It wraps internal page outputs in the same formal receipt/evidence workflow as the
browser backend, without claiming Chromium, WebGL or browser resource controls.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import hmac
from pathlib import Path
import platform
import re
from typing import Any
import zlib

from ..canonical import sha256_digest
from ..compiler.raster_scene import RasterSceneCompiler, RASTER_RENDERER_ID
from ..errors import ProtocolError, SecurityError
from ..artifacts import file_digest, utc_now
from ..workflow.raster_preparation import RasterPreparationService
from .geospatial_mcp import _publish_bytes
from .raster_page_renderer import RasterPageRenderer, page_renderer_digest, VERSION
from .raster_renderer import _dependencies
from .webmap_renderer import compute_renderer_attestation


def formal_renderer_digest() -> str:
    root = Path(__file__).resolve().parents[3]
    paths = [Path(__file__), root / "scripts/carto_core/compiler/raster_scene.py",
             root / "scripts/carto_core/workflow/raster_bundle.py", root / "scripts/carto_core/adapters/render_backend.py",
             *[root / "schemas" / (name + ".schema.json") for name in
               ("render-scene", "render-receipt", "prepared-data-bundle", "common")]]
    return sha256_digest({"page_renderer": page_renderer_digest(),
                          "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


@dataclass(frozen=True, slots=True)
class RasterRendererProfile:
    renderer_id: str
    renderer_version: str
    renderer_code_digest: str
    runtime: dict[str, str]
    platform: str
    machine: str
    supported_export_formats: tuple[str, ...] = ("svg", "pdf", "png")
    max_canvas_width: int = 4096
    max_canvas_height: int = 4096
    max_page_pixels: int = 16000000

    @classmethod
    def current(cls):
        np, rio, mpl, _, _, pil, _ = _dependencies()
        try:
            import fontTools
            from matplotlib import ft2font
        except ImportError:
            raise ProtocolError("RASTER_RENDER_DEPENDENCY_MISSING", "The raster-rendering extra including fonttools is required") from None
        runtime = {"python": platform.python_version(), "rasterio": rio.__version__, "gdal": rio.__gdal_version__,
                   "numpy": np.__version__, "matplotlib": mpl.__version__, "pillow": pil.__version__,
                   "freetype": ft2font.__freetype_version__, "fonttools": fontTools.__version__,
                   "zlib": zlib.ZLIB_RUNTIME_VERSION}
        return cls(RASTER_RENDERER_ID, VERSION, formal_renderer_digest(), runtime, platform.platform(), platform.machine())

    def profile_digest(self):
        return sha256_digest(asdict(self))

    @property
    def environment_fingerprint(self):
        return sha256_digest({"backend_profile": asdict(self)})

    def environment_snapshot(self):
        return {"renderer_id": self.renderer_id, "renderer_version": self.renderer_version,
                "renderer_code_digest": self.renderer_code_digest, "runtime": deepcopy(self.runtime),
                "fingerprint": self.environment_fingerprint}


class RasterFormalRenderer:
    def __init__(self, *, path_guard, output_root, attestation_key, project_root, context, registry):
        if project_root is None or context is None:
            raise SecurityError("RASTER_EXECUTION_CONTEXT_REQUIRED", "Inject the trusted project root and execution context")
        if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
            raise SecurityError("RENDER_ATTESTATION_KEY_INVALID", "Attestation requires at least 32 bytes")
        self.path_guard, self.output_root = path_guard, path_guard.resolve(output_root)
        self.context, self.key, self.registry = context, attestation_key, registry
        self.preparation = RasterPreparationService(project_root=project_root,
            allowed_roots=list(path_guard.allowed_roots), registry=registry)
        # Outputs may not escape this project even if a host allows multiple projects.
        self.preparation.project_guard.resolve(self.output_root)
        self.compiler = RasterSceneCompiler(self.preparation)
        self.page_renderer = RasterPageRenderer(self.preparation)
        self.profile = RasterRendererProfile.current()
        self.environment_fingerprint = self.profile.environment_fingerprint

    def environment_snapshot(self):
        return self.profile.environment_snapshot()

    @staticmethod
    def controls():
        return {"input_policy": "frozen-project-local", "network_isolation": "not-provided",
                "process_isolation": "in-process", "max_source_pixels": 16000000, "max_page_pixels": 16000000}

    def validate_scene(self, scene, execution=None):
        inputs = (self.compiler.validate_scene(scene, self.context) if execution is None else
                  self.compiler.validate_execution(scene, execution, self.context))
        if execution is not None and execution["environment"] != self.environment_snapshot():
            raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Raster code/runtime differs from the frozen execution")
        return inputs

    def scene_texts(self, scene):
        return [item["text"] for item in self.validate_scene(scene)["page"]["texts"]]

    def _directory(self, session_id):
        # Schema identifier validation precedes any path construction.
        identifier = self.registry.schemas["common"]["$defs"]["identifier"]
        if not isinstance(session_id, str) or any(
                len(value) > identifier["maxLength"] or re.fullmatch(identifier["pattern"], value) is None
                for value in (session_id, "receipt-" + session_id)):
            raise SecurityError("RENDER_SESSION_ID_INVALID", "Expected a bounded local session/receipt identifier")
        return self.path_guard.resolve(self.output_root / session_id)

    def _receipt(self, session_id, scene, page_ref, page, started, completed):
        resources = [{"resource_id": item["id"], "digest": item["ref"]["digest"], "status": "loaded"}
                     for item in scene["resources"]]
        resource_digest = sha256_digest(resources)
        execution_digest = sha256_digest({"scene_digest": sha256_digest(scene), "resource_set_digest": resource_digest,
            "renderer_profile_digest": self.profile.profile_digest(), "environment_fingerprint": self.environment_fingerprint,
            "random_seed": scene["random_seed"]})
        outputs = []
        media = {"pdf": "application/pdf", "png": "image/png", "svg": "image/svg+xml"}
        for kind in scene["export"]["targets"]:
            asset = page["outputs"][kind]
            outputs.append({"target": kind, "media_type": media[kind], "size_bytes": asset["size_bytes"],
                "composition": "raster" if kind == "png" else "mixed",
                "artifact_ref": {"id": "map-" + kind, "version": "1.0.0", "digest": asset["artifact_ref"]["digest"],
                                 "uri": str(self._directory(session_id) / ("map." + kind))}})
        receipt = {"schema_version": 1, "receipt_id": "receipt-" + session_id, "session_id": session_id,
            "scene_id": scene["scene_id"], "scene_revision": scene["revision"], "scene_digest": sha256_digest(scene),
            "random_seed": scene["random_seed"], "environment_fingerprint": self.environment_fingerprint,
            "resource_set_digest": resource_digest, "execution_digest": execution_digest,
            "renderer_id": RASTER_RENDERER_ID, "renderer_profile_digest": self.profile.profile_digest(),
            "renderer_version": VERSION, "renderer_code_digest": self.profile.renderer_code_digest,
            "runtime": deepcopy(self.profile.runtime), "page_output_ref": page_ref, "status": "succeeded",
            "viewport": deepcopy(scene["viewport"]), "resource_evidence": resources, "output_artifacts": outputs,
            "controls": self.controls(), "composition": {"map_body": "rasterio-categorical-rgba",
                "overlays": "matplotlib-vector", "svg": "raster-map-with-glyph-paths", "png": "rasterized-composite",
                "pdf": "raster-map-with-embedded-truetype"}, "warnings": [],
            "render_started_at": started, "render_completed_at": completed, "attestation_algorithm": "hmac-sha256"}
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, self.key)
        self.registry.validate("render-receipt", receipt)
        return receipt

    def render(self, session_id, scene):
        self._directory(session_id)  # reject invalid paths/identities before drawing
        inputs = self.validate_scene(scene)
        started = utc_now()
        artifact = self.page_renderer.render(inputs["page"], self.context)
        page = self.preparation._json_ref(artifact.ref(), "raster-page-output")
        if page["environment"] != self.profile.runtime or page["request_ref"] != scene["page_request_ref"]:
            raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Rendered page differs from the frozen request/runtime")
        for kind in scene["export"]["targets"]:
            data = self.preparation.snapshot_bytes(page["outputs"][kind], "page-" + kind, "." + kind)
            _publish_bytes(self.path_guard, self._directory(session_id) / ("map." + kind), data)
        return self._receipt(session_id, scene, artifact.ref(), page, started, utc_now())

    def validate_receipt(self, scene, receipt, *, verify_outputs=True, expected_session_id=None):
        self.registry.validate("render-receipt", receipt)
        if receipt["renderer_id"] != RASTER_RENDERER_ID:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", "A browser receipt cannot attest a raster scene")
        if not hmac.compare_digest(receipt["renderer_attestation"], compute_renderer_attestation(receipt, self.key)):
            raise SecurityError("RENDER_ATTESTATION_INVALID", "Renderer attestation does not verify")
        if expected_session_id is not None and receipt["session_id"] != expected_session_id:
            raise ProtocolError("RENDER_RECEIPT_SESSION_MISMATCH", "Receipt belongs to a different attempt")
        self.validate_scene(scene)
        page = self.page_renderer.load_verified(receipt["page_output_ref"], self.context)
        if page["request_ref"] != scene["page_request_ref"] or page["environment"] != self.profile.runtime:
            raise ProtocolError("RENDER_RECEIPT_PAGE_MISMATCH", "Receipt page is not the frozen scene")
        started = datetime.fromisoformat(receipt["render_started_at"].replace("Z", "+00:00"))
        completed = datetime.fromisoformat(receipt["render_completed_at"].replace("Z", "+00:00"))
        if completed < started:
            raise ProtocolError("RENDER_RECEIPT_TIME_INVALID", "Completion precedes rendering")
        expected = self._receipt(receipt["session_id"], scene, receipt["page_output_ref"], page,
                                 receipt["render_started_at"], receipt["render_completed_at"])
        if receipt != expected:
            raise ProtocolError("RENDER_RECEIPT_BINDING_MISMATCH", "Receipt differs from verified scene, runtime or resources")
        if verify_outputs:
            for item in receipt["output_artifacts"]:
                path = self.path_guard.resolve(item["artifact_ref"]["uri"], must_exist=True)
                if not path.is_file() or path.stat().st_size != item["size_bytes"]:
                    raise ProtocolError("FORMAL_RENDER_OUTPUT_DRIFT", item["target"])
                if file_digest(path) != item["artifact_ref"]["digest"]:
                    raise ProtocolError("FORMAL_RENDER_OUTPUT_DRIFT", item["target"])
