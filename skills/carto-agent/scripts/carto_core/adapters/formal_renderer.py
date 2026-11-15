"""Unified formal renderer with renderer-id attestation partitions."""
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
from ..compiler.vector_scene import VectorSceneCompiler
from ..errors import ProtocolError, SecurityError
from ..artifacts import file_digest, publish_bytes, utc_now
from ..workflow.preparation_bundle import BundlePreparer
from ..workflow.raster_preparation import RasterPreparationService
from ..workflow.vector_preparation import VectorPreparationService
from .raster_renderer import _dependencies
from .webmap_renderer import compute_renderer_attestation
from .page_renderer import (
    PageRenderer, page_renderer_digest,
    RASTER_RENDERER_ID as PAGE_RASTER_ID, RASTER_VERSION,
    VECTOR_RENDERER_ID as PAGE_VECTOR_ID, VECTOR_VERSION,
)


def _formal_renderer_digest_raster(page_digest: str) -> str:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "scripts/carto_core/compiler/grid_layout.py",
        root / "scripts/carto_core/compiler/raster_legends.py",
        root / "schemas/grid-parameters.schema.json",
        root / "schemas/bundle-inputs.schema.json",
        root / "scripts/carto_core/compiler/appearance.py",
        root / "scripts/carto_core/compiler/page_bindings.py",
        root / "scripts/carto_core/compiler/raster_page_contract.py",
        root / "scripts/carto_core/artifacts.py",
        Path(__file__),
        root / "scripts/carto_core/compiler/raster_scene.py",
        root / "scripts/carto_core/workflow/preparation_bundle.py",
        root / "scripts/carto_core/adapters/render_backend.py",
    ]
    paths += [root / "schemas" / (name + ".schema.json") for name in
              ("render-scene", "render-receipt", "prepared-data-bundle", "common",
               "page-bindings", "resolved-appearance", "cartography", "layout", "category-counts",
               "bundle-inputs")]
    return sha256_digest({"page_renderer": page_digest,
                          "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


def _formal_renderer_digest_vector(page_digest: str) -> str:
    root = Path(__file__).resolve().parents[3]
    paths = [
        Path(__file__),
        root / "scripts/carto_core/compiler/vector_scene.py",
        root / "scripts/carto_core/workflow/preparation_bundle.py",
        root / "scripts/carto_core/adapters/render_backend.py",
        root / "scripts/carto_core/adapters/page_renderer.py",
        root / "scripts/carto_core/adapters/static_page_renderer.py",
        root / "scripts/carto_core/workflow/static_assets.py",
        root / "scripts/carto_core/compiler/vector_page.py",
        root / "scripts/carto_core/compiler/vector_portrayal.py",
        root / "scripts/carto_core/compiler/portrayal_resolver.py",
        root / "scripts/carto_core/workflow/vector_preparation.py",
        root / "scripts/carto_core/compiler/grid_layout.py",
        root / "scripts/carto_core/compiler/layout.py",
        root / "scripts/carto_core/compiler/appearance.py",
    ]
    paths += [root / "schemas" / (name + ".schema.json") for name in
              ("render-scene", "render-receipt", "common", "prepared-data-bundle", "bundle-inputs",
               "page-bindings", "vector-input", "encoding-ir", "vector-prepared-data",
               "resolved-portrayal", "resolved-layout", "layout", "cartography", "resolved-appearance")]
    return sha256_digest({"page_renderer": page_digest,
                          "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


def formal_renderer_digest() -> str:
    """Public digest for the raster formal renderer (backward-compatible entry point)."""
    return _formal_renderer_digest_raster(page_renderer_digest("raster"))


@dataclass(frozen=True, slots=True)
class RendererProfile:
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
    def current(cls, renderer_id: str = RASTER_RENDERER_ID) -> "RendererProfile":
        np, rio, mpl, _, _, pil, _ = _dependencies()
        try:
            import fontTools
            from matplotlib import ft2font
        except ImportError:
            raise ProtocolError("RENDER_DEPENDENCY_MISSING", "fonttools is required") from None
        runtime = {"python": platform.python_version(), "rasterio": rio.__version__, "gdal": rio.__gdal_version__,
                   "numpy": np.__version__, "matplotlib": mpl.__version__, "pillow": pil.__version__,
                   "freetype": ft2font.__freetype_version__, "fonttools": fontTools.__version__,
                   "zlib": zlib.ZLIB_RUNTIME_VERSION}
        if renderer_id == PAGE_VECTOR_ID:
            from ..workflow.vector_preparation import dependencies as _vec_deps
            _fiona, _shapely, *_ = _vec_deps()
            runtime = {"python": platform.python_version(), "rasterio": rio.__version__,
                       "gdal": rio.__gdal_version__, "numpy": np.__version__,
                       "matplotlib": mpl.__version__, "pillow": pil.__version__,
                       "freetype": ft2font.__freetype_version__, "fonttools": fontTools.__version__,
                       "zlib": zlib.ZLIB_RUNTIME_VERSION,
                       "fiona": _fiona.__version__, "shapely": _shapely.__version__,
                       "vector_gdal": _fiona.__gdal_version__}
        version = VECTOR_VERSION if renderer_id == PAGE_VECTOR_ID else RASTER_VERSION
        digest = (_formal_renderer_digest_vector(page_renderer_digest("vector")) if renderer_id == PAGE_VECTOR_ID
                  else _formal_renderer_digest_raster(page_renderer_digest("raster")))
        return cls(renderer_id, version, digest, runtime, platform.platform(), platform.machine())

    def profile_digest(self) -> str:
        return sha256_digest(asdict(self))

    @property
    def environment_fingerprint(self) -> str:
        return sha256_digest({"backend_profile": asdict(self)})

    def environment_snapshot(self) -> dict[str, Any]:
        return {"renderer_id": self.renderer_id, "renderer_version": self.renderer_version,
                "renderer_code_digest": self.renderer_code_digest, "runtime": deepcopy(self.runtime),
                "fingerprint": self.environment_fingerprint}


class FormalRenderer:
    """Unified formal renderer. renderer_id selects the attestation partition and geometry strategy."""

    def __init__(self, *, path_guard, output_root, attestation_key, project_root, context, registry,
                 renderer_id: str = None):
        self.renderer_id = renderer_id or RASTER_RENDERER_ID
        is_vector = self.renderer_id == PAGE_VECTOR_ID

        if project_root is None or context is None:
            raise SecurityError("EXECUTION_CONTEXT_REQUIRED", "Inject the trusted project root and execution context")
        if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
            raise SecurityError("RENDER_ATTESTATION_KEY_INVALID", "Attestation requires at least 32 bytes")

        self.path_guard, self.output_root = path_guard, path_guard.resolve(output_root)
        self.context, self.key, self.registry = context, attestation_key, registry

        if is_vector:
            self.preparation = VectorPreparationService(project_root=project_root,
                allowed_roots=list(path_guard.allowed_roots), registry=registry)
            self.compiler = VectorSceneCompiler(self.preparation, BundlePreparer)
        else:
            self.preparation = RasterPreparationService(project_root=project_root,
                allowed_roots=list(path_guard.allowed_roots), registry=registry)
            self.compiler = RasterSceneCompiler(self.preparation, BundlePreparer)
        self.preparation.project_guard.resolve(self.output_root)

        self.page_renderer = PageRenderer(self.preparation)
        self.profile = RendererProfile.current(self.renderer_id)
        self.environment_fingerprint = self.profile.environment_fingerprint

    @property
    def renderer_version(self) -> str:
        return self.profile.renderer_version

    @property
    def page_output_schema(self) -> str:
        return "page-output"

    @property
    def map_composition(self) -> str:
        return "vector" if self.renderer_id == PAGE_VECTOR_ID else "mixed"

    @property
    def composition(self) -> dict[str, str]:
        if self.renderer_id == PAGE_VECTOR_ID:
            return {"map_body": "matplotlib-native-vector", "overlays": "matplotlib-vector",
                    "svg": "vector-map-with-glyph-paths", "png": "rasterized-composite",
                    "pdf": "vector-map-with-embedded-truetype"}
        return {"map_body": "rasterio-categorical-rgba", "overlays": "matplotlib-vector",
                "svg": "raster-map-with-glyph-paths", "png": "rasterized-composite",
                "pdf": "raster-map-with-embedded-truetype"}

    def environment_snapshot(self) -> dict[str, Any]:
        return self.profile.environment_snapshot()

    def controls(self) -> dict[str, Any]:
        if self.renderer_id == PAGE_VECTOR_ID:
            return {"input_policy": "frozen-project-local", "network_isolation": "not-provided",
                    "process_isolation": "in-process",
                    "max_source_features": 10000, "max_source_vertices": 200000,
                    "max_source_bytes": 33554432, "max_page_pixels": 16000000}
        return {"input_policy": "frozen-project-local", "network_isolation": "not-provided",
                "process_isolation": "in-process", "max_source_pixels": 16000000, "max_page_pixels": 16000000}

    def validate_scene(self, scene: dict[str, Any], execution: dict[str, Any] = None) -> Any:
        inputs = (self.compiler.validate_scene(scene, self.context) if execution is None else
                  self.compiler.validate_execution(scene, execution, self.context))
        if execution is not None and execution["environment"] != self.environment_snapshot():
            raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Code/runtime differs from the frozen execution")
        return inputs

    def scene_texts(self, scene: dict[str, Any]) -> list[str]:
        return [item["text"] for item in self.validate_scene(scene)["page"]["texts"]]

    def _directory(self, session_id: str) -> Path:
        identifier = self.registry.schemas["common"]["$defs"]["identifier"]
        if not isinstance(session_id, str) or any(
                len(value) > identifier["maxLength"] or re.fullmatch(identifier["pattern"], value) is None
                for value in (session_id, "receipt-" + session_id)):
            raise SecurityError("RENDER_SESSION_ID_INVALID", "Expected a bounded local session/receipt identifier")
        return self.path_guard.resolve(self.output_root / session_id)

    def _receipt(self, session_id: str, scene: dict[str, Any], page_ref: dict[str, str],
                 page: dict[str, Any], started: str, completed: str) -> dict[str, Any]:
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
                "composition": "raster" if kind == "png" else self.map_composition,
                "artifact_ref": {"id": "map-" + kind, "version": "1.0.0", "digest": asset["artifact_ref"]["digest"],
                                 "uri": str(self._directory(session_id) / ("map." + kind))}})
        receipt = {"schema_version": 1, "receipt_id": "receipt-" + session_id, "session_id": session_id,
            "scene_id": scene["scene_id"], "scene_revision": scene["revision"], "scene_digest": sha256_digest(scene),
            "random_seed": scene["random_seed"], "environment_fingerprint": self.environment_fingerprint,
            "resource_set_digest": resource_digest, "execution_digest": execution_digest,
            "renderer_id": self.renderer_id, "renderer_profile_digest": self.profile.profile_digest(),
            "renderer_version": self.renderer_version, "renderer_code_digest": self.profile.renderer_code_digest,
            "runtime": deepcopy(self.profile.runtime), "page_output_ref": page_ref, "status": "succeeded",
            "viewport": deepcopy(scene["viewport"]), "resource_evidence": resources, "output_artifacts": outputs,
            "controls": self.controls(), "composition": deepcopy(self.composition), "warnings": [],
            "render_started_at": started, "render_completed_at": completed, "attestation_algorithm": "hmac-sha256"}
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, self.key)
        self.registry.validate("render-receipt", receipt)
        return receipt

    def render(self, session_id: str, scene: dict[str, Any]) -> dict[str, Any]:
        self._directory(session_id)
        inputs = self.validate_scene(scene)
        started = utc_now()
        artifact = self.page_renderer.render(inputs["page"], self.context)
        page = self.preparation.document(artifact.ref(), self.page_output_schema) if not (
            self.renderer_id == PAGE_VECTOR_ID) else self.preparation.document(artifact.ref(), self.page_output_schema)
        if page["environment"] != self.profile.runtime or page["request_ref"] != scene["page_request_ref"]:
            raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Rendered page differs from the frozen request/runtime")
        for kind in scene["export"]["targets"]:
            data = self.preparation.snapshot_bytes(page["outputs"][kind], "page-" + kind, "." + kind)
            publish_bytes(self.path_guard, self._directory(session_id) / ("map." + kind), data)
        return self._receipt(session_id, scene, artifact.ref(), page, started, utc_now())

    def validate_receipt(self, scene: dict[str, Any], receipt: dict[str, Any], *,
                         verify_outputs: bool = True, expected_session_id: str = None) -> None:
        self.registry.validate("render-receipt", receipt)
        if receipt["renderer_id"] != self.renderer_id:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", "Receipt renderer_id does not match this backend")
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