"""Local image/itinerary tool capabilities bound through ToolGateway.

These are the migrated leadership-visit algorithms that carry capability
semantics (authorization, typed I/O, immutable evidence, budget): the
registered-affine projection (geo-to-image-pixels), display-window detection
(image-display-bounds), the bounded callout layout solver (annotation-layout)
and the data-directory inventory (data-summary). Renderer internals and pure
deterministic math stay outside the gateway on purpose: renderers are governed
by RenderReceipt, compile-time transforms by the frozen scene digests.

Handlers resolve their digest-bound references through PathGuard and re-verify
bytes before running the algorithm, so the evidence artifact always binds the
bytes that were actually processed — the same contract the raster statistics
handler enforces.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from ..artifacts import file_digest
from ..canonical import sha256_digest
from ..contracts.execution import ExecutionContext
from ..errors import ProtocolError
from ..repository.immutable_store import ImmutableArtifactStore
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from .annotation_solver import check_layout, solve_layout
from .geo_to_image_pixels import project_features
from .image_display import display_bounds
from .image_layout import inspect_png
from .tool_gateway import ToolGateway

PROJECTION_CAPABILITY = "geo-to-image-pixels"
DISPLAY_CAPABILITY = "image-display-bounds"
ANNOTATION_CAPABILITY = "annotation-layout"
DATA_SUMMARY_CAPABILITY = "data-summary"

_CAPABILITY_HANDLERS: dict[str, tuple[str, str]] = {
    PROJECTION_CAPABILITY: ("image-projection-request", "image-projection-result"),
    DISPLAY_CAPABILITY: ("image-display-request", "image-display-result"),
    ANNOTATION_CAPABILITY: ("annotation-layout-request", "annotation-layout-result"),
    DATA_SUMMARY_CAPABILITY: ("data-summary-request", "data-summary-result"),
}


def _resolve_image_bytes(guard: PathGuard, project_root: Path, ref: dict[str, Any]) -> bytes:
    path = guard.resolve(ref["uri"], base_root=project_root, must_exist=True)
    if not path.is_file():
        raise ProtocolError("IMAGE_TOOL_INPUT_INVALID", "basemap reference must be a regular file")
    if file_digest(path) != ref.get("digest"):
        raise ProtocolError("IMAGE_TOOL_INPUT_DRIFT", "basemap bytes differ from the request reference")
    return path.read_bytes()


def _load_verified_document(guard: PathGuard, project_root: Path, ref: dict[str, Any]) -> dict[str, Any]:
    path = guard.resolve(ref["uri"], base_root=project_root, must_exist=True)
    document = load_document(path)
    if not isinstance(document, dict) or sha256_digest(document) != ref.get("digest"):
        raise ProtocolError("IMAGE_TOOL_INPUT_DRIFT", f"document differs from its reference: {ref.get('uri')}")
    return document


def _projection_handler(guard: PathGuard, project_root: Path) -> Callable[[dict[str, Any], ExecutionContext], dict[str, Any]]:
    def handle(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        image_bytes = _resolve_image_bytes(guard, project_root, request["image_ref"])
        parameters = _load_verified_document(guard, project_root, request["parameters_ref"])
        stops = _load_verified_document(guard, project_root, request["stops_ref"])
        route = (_load_verified_document(guard, project_root, request["route_ref"])
                 if "route_ref" in request else {"type": "FeatureCollection", "features": []})
        return project_features(parameters, image_bytes, stops, route)
    return handle


def _display_handler(guard: PathGuard, project_root: Path) -> Callable[[dict[str, Any], ExecutionContext], dict[str, Any]]:
    def handle(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        image_bytes = _resolve_image_bytes(guard, project_root, request["image_ref"])
        window = display_bounds(image_bytes, white_threshold=request["white_threshold"])
        return {"schema_version": 1, "display_window": window, "source_size": inspect_png(image_bytes)}
    return handle


def _annotation_handler() -> Callable[[dict[str, Any], ExecutionContext], dict[str, Any]]:
    def handle(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        value = {key: deepcopy(request[key]) for key in
                 ("items", "hard_lines", "hard_boxes", "canvas", "gap_px", "seed", "iterations")}
        result = solve_layout(deepcopy(value))
        # The solver result is re-verified without re-optimizing; tampered results
        # cannot pass through as evidence.
        check_layout(value, result)
        return result
    return handle


def _data_summary_handler(guard: PathGuard, project_root: Path) -> Callable[[dict[str, Any], ExecutionContext], dict[str, Any]]:
    def handle(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        from .file_parser import summarize_directory
        directory = guard.resolve(request["data_dir"], base_root=project_root, must_exist=True)
        if not directory.is_dir():
            raise ProtocolError("DATA_SUMMARY_DIR_INVALID", "data_dir must resolve to a directory")
        summary = summarize_directory(directory)
        return {"schema_version": 1, "data_dir": request["data_dir"], **summary}
    return handle


def _bind_handlers(guard: PathGuard, project_root: Path,
                   capabilities: tuple[str, ...]) -> Callable[[ToolGateway], None]:
    builders = {
        PROJECTION_CAPABILITY: lambda: _projection_handler(guard, project_root),
        DISPLAY_CAPABILITY: lambda: _display_handler(guard, project_root),
        ANNOTATION_CAPABILITY: _annotation_handler,
        DATA_SUMMARY_CAPABILITY: lambda: _data_summary_handler(guard, project_root),
    }

    def bind(gateway: ToolGateway) -> None:
        for capability in capabilities:
            input_schema, output_schema = _CAPABILITY_HANDLERS[capability]
            gateway.register(capability, builders[capability](),
                             input_schema=input_schema, output_schema=output_schema)
    return bind


def _make_gateway(store: ImmutableArtifactStore, registry: SchemaRegistry,
                  bind: Callable[[ToolGateway], None]) -> ToolGateway:
    policy_path = registry.schema_root.parent / "policies/tool-bindings.yaml"
    gateway = ToolGateway(policy_path, store, registry)
    bind(gateway)
    return gateway


def make_image_gateway(store: ImmutableArtifactStore, registry: SchemaRegistry, *,
                       guard: PathGuard, project_root: Path) -> ToolGateway:
    """Gateway with the three image-basemap capabilities bound (scenario compile + validation)."""
    bind = _bind_handlers(guard, project_root,
                          (PROJECTION_CAPABILITY, DISPLAY_CAPABILITY, ANNOTATION_CAPABILITY))
    return _make_gateway(store, registry, bind)


def make_data_summary_gateway(store: ImmutableArtifactStore, registry: SchemaRegistry, *,
                              guard: PathGuard, project_root: Path) -> ToolGateway:
    """Gateway with the read-only data-summary capability bound (operator CLI)."""
    bind = _bind_handlers(guard, project_root, (DATA_SUMMARY_CAPABILITY,))
    return _make_gateway(store, registry, bind)
