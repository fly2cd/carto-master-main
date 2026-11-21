"""leadership-visit candidate_compiler: request + plan + bundle -> frozen scene.

Pipeline (all deterministic, no LLM): ToolGateway capabilities
(geo-to-image-pixels -> image-display-bounds, optional annotation-layout) ->
LayoutResolver -> apply_grouped_style -> image page-request + RenderScene
(image_graphics embedded) -> resolved-map candidate bound to the intent.
The graphics list is the single source consumed both by
``adapters.image_page_renderer.ImagePageRenderer`` (PDF/PNG) and by
``scenarios.leadership_visit.frontend_document.FrontendDocumentBuilder``
(map_json), keeping the two outputs pixel-consistent. The migrated image
algorithms are invoked only through the authorized gateway (typed I/O schemas,
ToolResult evidence, budget accounting) — never as direct library calls.
"""
from __future__ import annotations

import posixpath
from copy import deepcopy
from pathlib import Path
from typing import Any

from ...adapters.annotation_solver import ALGORITHM as ANNOTATION_ALGORITHM
from ...adapters.geo_to_image_pixels import (
    METHOD as PROJECTION_METHOD,
    VERSION as PROJECTION_VERSION,
    normalize_extent,
)
from ...adapters.image_display import DEFAULT_WHITE_THRESHOLD
from ...adapters.image_page_renderer import environment_snapshot
from ...adapters.image_layout import contain_layout
from ...adapters.image_tools import (
    ANNOTATION_CAPABILITY,
    DISPLAY_CAPABILITY,
    PROJECTION_CAPABILITY,
    make_image_gateway,
)
from ...artifacts import artifact_ref, atomic_json, atomic_yaml, file_digest, utc_now
from ...backend_registry import IMAGE_ITINERARY_PAGE
from ...canonical import sha256_digest
from ...compiler.layout import LayoutResolver
from ...contracts.execution import ExecutionContext
from ...errors import ProtocolError
from ...repository.immutable_store import ImmutableArtifactStore
from ...schema_registry import SchemaRegistry, load_document
from ...security.paths import PathGuard
from .frontend_document import FrontendDocumentBuilder
from .request_contract import REQUEST_CONTRACT
from .style import MAIN_FRAME, apply_grouped_style

_TARGET_PREFIX = "leadership-map"
_DISPLAY_CRS = {"authority": "EPSG", "code": "4326"}
_MAIN_VIEW = "main-view"
_ROUTE_LAYER = "route-layer"


def _load_verified_document(path_guard: Any, project_root: Path, ref: dict[str, str]) -> dict[str, Any]:
    path = path_guard.resolve(ref["uri"], base_root=project_root, must_exist=True)
    document = load_document(path)
    if not isinstance(document, dict):
        raise ProtocolError("PREPARED_DOCUMENT_INVALID", ref["uri"])
    if sha256_digest(document) != ref.get("digest"):
        raise ProtocolError("PREPARED_DOCUMENT_DRIFT", ref["uri"])
    return document


class RouteCandidateCompiler:
    """Compiles a frozen image-itinerary RenderScene and resolved-map candidate."""

    def __init__(self, path_guard: Any, registry: SchemaRegistry | None = None,
                 *, project_root: Path | None = None, context: Any = None) -> None:
        self.guard = path_guard
        self.registry = registry or SchemaRegistry()
        self.project_root = Path(project_root) if project_root is not None else None
        self.context = context

    # ------------------------------------------------------------------
    # compile
    # ------------------------------------------------------------------

    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any],
                contracts: dict[str, Any], font_path: Path) -> dict[str, Any]:
        if self.project_root is None or self.context is None:
            raise ProtocolError("IMAGE_COMPILER_CONTEXT_REQUIRED", "Compiler requires the trusted project context")
        context = ExecutionContext.from_generate_request(request)
        if any(getattr(self.context, key) != getattr(context, key)
               for key in ("run_id", "project_id", "tenant_id", "subject_id")):
            raise ProtocolError("IMAGE_SCOPE_MISMATCH", "Compiler requires the trusted execution context")
        REQUEST_CONTRACT.validate_body(request)
        renderer_id = IMAGE_ITINERARY_PAGE.renderer_id
        decisions = plan.get("decisions", {})
        if decisions.get("renderer_id") != renderer_id:
            raise ProtocolError("IMAGE_PLAN_RENDERER_MISMATCH", "Plan must select the image itinerary renderer")
        if self.project_root is None:
            raise ProtocolError("IMAGE_COMPILER_CONTEXT_REQUIRED", "project root required")

        # --- Inputs: basemap, registration parameters, prepared itinerary ----
        basemap_request = request["basemap"]
        image_ref = basemap_request["image_ref"]
        image_path = self.guard.resolve(image_ref["uri"], base_root=self.project_root, must_exist=True)
        if file_digest(image_path) != image_ref.get("digest"):
            raise ProtocolError("IMAGE_INPUT_DRIFT", "basemap image differs from the request reference")
        image_bytes = image_path.read_bytes()
        parameters = _load_verified_document(self.guard, self.project_root, basemap_request["parameters_ref"])
        stops_document = route_document = None
        stops_binding = route_binding = None
        for binding in bundle.get("role_bindings", []):
            document = _load_verified_document(self.guard, self.project_root, binding["prepared_ref"])
            if binding.get("source_id") == "route-stops" or binding.get("role") == "route-stops":
                stops_document = document
                stops_binding = binding
            else:
                route_document = document
                route_binding = binding
        if stops_document is None or stops_binding is None:
            raise ProtocolError("IMAGE_BUNDLE_STOPS_REQUIRED", "Bundle must contain route-stops")
        bundle_uri = self._bundle_uri(bundle)

        # --- ToolGateway capabilities: projection + display window ------------
        # The migrated image algorithms run as authorized gateway capabilities
        # (typed I/O, ToolResult evidence, budget accounting); the compiler never
        # calls the algorithm entry points directly. Handlers re-resolve and
        # re-verify the digest-bound references, so the evidence always binds the
        # bytes actually processed.
        store = ImmutableArtifactStore(self.project_root / ".carto" / "image" / "evidence",
                                       path_guard=PathGuard([self.project_root]))
        gateway = make_image_gateway(store, self.registry, guard=self.guard,
                                     project_root=self.project_root)
        projection_input: dict[str, Any] = {
            "schema_version": 1,
            "image_ref": deepcopy(basemap_request["image_ref"]),
            "parameters_ref": deepcopy(basemap_request["parameters_ref"]),
            "stops_ref": deepcopy(stops_binding["prepared_ref"]),
        }
        if route_binding is not None:
            projection_input["route_ref"] = deepcopy(route_binding["prepared_ref"])
        projection, projection_receipt = self._invoke_tool(gateway, PROJECTION_CAPABILITY, projection_input)
        style = deepcopy(contracts["portrayal"]["image_itinerary"])
        self.registry.validate("image-itinerary-style", style)
        display_input = {"schema_version": 1,
                         "image_ref": deepcopy(basemap_request["image_ref"]),
                         "white_threshold": int(style.get("white_threshold", DEFAULT_WHITE_THRESHOLD))}
        display_result, display_receipt = self._invoke_tool(gateway, DISPLAY_CAPABILITY, display_input)
        window = display_result["display_window"]
        source_size = deepcopy(projection["source_size"])

        # --- Physical page and layout ---------------------------------------
        canvas = decisions["canvas"]
        dpi = int(canvas["dpi"])
        resolved_layout = LayoutResolver(self.registry).resolve(
            contracts["scenario"]["embedded"]["layout"], dpi)
        frame = LayoutResolver.map_frame(resolved_layout)
        frame_box = {key: value for key, value in zip(("x", "y", "width", "height"), frame["bounds_px"])}
        placement = contain_layout({"width_px": window["width"], "height_px": window["height"]}, frame_box)
        page = resolved_layout["page"]

        # --- Grouped style -> graphics --------------------------------------
        fields: dict[str, dict[str, str]] = {}
        for binding in request.get("source_bindings", []):
            role = binding.get("role")
            fields[role] = {item["semantic_role"]: item["source_field"]
                            for item in binding.get("field_bindings", [])}
        itinerary = {"projection": projection, "sources": {"route-stops": stops_document,
                                                           "route-line": route_document or {}},
                     "fields": fields}
        styled = apply_grouped_style(style, {"basemap": {"source_size": source_size,
                                                         "display_window": window}}, itinerary)
        graphics = styled["graphics"]

        # --- Optional annotation solver (greedy + annealing, fixed seed) ------
        annotation_receipt = None
        annotation = request.get("annotation_layout")
        if annotation:
            graphics, annotation_receipt = self._solve_annotations(
                gateway, graphics, window, annotation)

        # --- Freeze the image page request ----------------------------------
        font_digest = file_digest(font_path)
        font_family = self._font_family(font_path)
        title = decisions.get("title") or request.get("map_title") or request.get("goal", "领导调研行程路线图")
        from ...scenario_registry import ScenarioRegistry
        profile = ScenarioRegistry(self.registry).for_generate(request)
        # Page furniture (style contract's page_furniture): freeze the nominal
        # fonts onto the texts and the frame border into the furniture node —
        # absent means the renderers' historical derivations apply unchanged.
        furniture_style = style.get("page_furniture") or {}
        title_text = {"content_id": "title", "text": title}
        if "title_font_pt" in furniture_style:
            title_text["font_pt"] = furniture_style["title_font_pt"]
        source_text = {"content_id": "source", "text": profile.notice}
        if "body_font_pt" in furniture_style:
            source_text["font_pt"] = furniture_style["body_font_pt"]
        page_request = {
            "schema_version": 4, "geometry": "image",
            "font": {"path": str(font_path), "digest": font_digest, "size_bytes": font_path.stat().st_size},
            "grid_north": None, "scale_bar": None,
            "resolved_layout": resolved_layout,
            "texts": [title_text, source_text],
            "legends": [{"content_id": "legend", "title": "图例",
                         "items": [{"id": f"legend-item-{index + 1}", "label": item["label"],
                                    "color": item["color"], "shape": item["shape"]}
                                    for index, item in enumerate(styled["legend_items"])]}],
            "document": {"category": "leadership_visit", "name": title},
            "basemap": {"image": {"path": str(image_path), "digest": image_ref["digest"],
                                  "size_bytes": len(image_bytes)},
                        "source_size": source_size, "display_window": window,
                        "white_threshold": style.get("white_threshold", DEFAULT_WHITE_THRESHOLD)},
        }
        if furniture_style.get("frame_border"):
            page_request["furniture"] = {"frame_border": deepcopy(furniture_style["frame_border"])}
        self.registry.validate("page-request", page_request)
        page_path = self.project_root / ".carto" / "image" / "page-requests" / (
            sha256_digest(page_request)[7:23] + ".yaml")
        atomic_yaml(self.guard.resolve(page_path), page_request)
        page_ref = artifact_ref("page-request", page_request, page_path)

        # --- RenderScene -----------------------------------------------------
        prepared_refs = [deepcopy(binding["prepared_ref"]) for binding in bundle.get("role_bindings", [])]
        prepared_bundle_ref = {"id": "prepared-data-bundle", "version": "1.0.0",
                               "digest": sha256_digest(bundle), "uri": bundle_uri}
        resources = [
            {"id": "basemap-image", "kind": "data", "digest_mode": "bytes",
             "ref": {"id": image_ref.get("id", "basemap-image"), "version": "1.0.0",
                     "digest": image_ref["digest"], "uri": image_ref["uri"]}},
            {"id": "registration-parameters", "kind": "contract", "digest_mode": "canonical-json",
             "ref": deepcopy(basemap_request["parameters_ref"])},
            {"id": "map-font", "kind": "font", "digest_mode": "bytes",
             "ref": {"id": "map-font", "version": "1.0.0", "digest": font_digest,
                     "uri": str(font_path)}},
        ]
        # ToolGateway evidence follows the scene: the immutable tool artifacts are
        # referenced as frozen contracts, so render/check re-verification can
        # re-check the compile-time capability receipts.
        tool_receipts = [receipt for receipt in
                         (projection_receipt, display_receipt, annotation_receipt)
                         if receipt is not None]
        resources.extend(self._evidence_resource(receipt) for receipt in tool_receipts)
        if annotation:
            seed = int(annotation["seed"]) % 4294967296
        else:
            # Mechanical derivation from the run identity; no silent default seed.
            seed = int(sha256_digest(request["run_id"])[7:19], 16) % 4294967296
        scene = {
            "schema_version": 1, "scene_id": "scene-" + request["run_id"], "revision": 1,
            "viewport": {"width_px": page["width_px"], "height_px": page["height_px"],
                         "device_pixel_ratio": 1},
            "resolved_layout": resolved_layout,
            "export": {"targets": ["pdf", "png"], "dpi": dpi},
            "random_seed": seed,
            "renderer_id": renderer_id,
            "context": {"run_id": context.run_id, "tenant_id": context.tenant_id,
                        "project_id": context.project_id, "subject_id": context.subject_id},
            "prepared_bundle_ref": prepared_bundle_ref,
            "page_request_ref": page_ref,
            "resources": resources,
            "image_graphics": graphics,
        }
        self.registry.validate("render-scene", scene)

        # --- Execution + candidate -------------------------------------------
        targets = {}
        for suffix, fmt in (("pdf", "pdf"), ("png", "png")):
            targets[f"{_TARGET_PREFIX}-{suffix}"] = {"format": fmt, "display_crs": deepcopy(_DISPLAY_CRS),
                                                     "dpi": dpi, "width_mm": page["width_mm"],
                                                     "height_mm": page["height_mm"]}
        execution = {
            "intent_ref": artifact_ref("map-intent", intent),
            "profile_refs": [deepcopy(intent["evidence_refs"][0]), deepcopy(intent["evidence_refs"][-1])],
            "business_scene": intent["business_scene"],
            "map_tasks": list(intent["tasks"]),
            "template_refs": [deepcopy(installation["template_ref"])],
            "dataset_refs": [deepcopy(ref) for ref in prepared_refs],
            "prepared_data_refs": [deepcopy(ref) for ref in prepared_refs],
            "ownership": {"scenario": "map-scenario"},
            "shared_semantics": {"theme_tags": list(intent["theme_tags"]),
                                 "data_nature": profile.definition["data_nature"]},
            "views": [{"id": _MAIN_VIEW, "extent": list(decisions["extent"]),
                       "layer_ids": [_ROUTE_LAYER],
                       "target_ids": [f"{_TARGET_PREFIX}-pdf", f"{_TARGET_PREFIX}-png"]}],
            "targets": targets,
            "resolved_layout": resolved_layout,
            "render_scene_ref": artifact_ref("render-scene", scene),
            "environment": environment_snapshot(renderer_id),
            "page_inputs": {"prepared_bundle_ref": deepcopy(prepared_bundle_ref),
                            "page_request_ref": deepcopy(page_ref)},
            "resolved_assets": [deepcopy(item["ref"]) for item in resources],
        }
        candidate = {
            "schema_version": 1, "candidate_id": "candidate-" + request["run_id"],
            "project_id": request["project_id"], "run_id": request["run_id"],
            "execution_digest": sha256_digest(execution), "execution": execution,
            "open_issues": [], "created_at": utc_now(),
        }
        self.registry.validate("resolved-map", candidate)
        self.verify_request(request, scene, None)
        # --- Frontend map_json (成果本体): same graphics, mm coordinates -----
        # Compile-time pure-data product; never part of the formal delivery set
        # (the delivery manifest admits pdf/png only).
        # The filename carries the request digest so a design revision (which
        # keeps the run_id but changes the request bytes) writes a distinct
        # immutable document instead of colliding with the create-once store.
        document = FrontendDocumentBuilder(self.registry).build(
            scene, page_request, identifier=f"map-{request['run_id']}", name=title)
        document_path = self.project_root / ".carto" / "image" / "map-documents" / (
            f"map-{request['run_id']}-{sha256_digest(request)[7:23]}.json")
        atomic_json(self.guard.resolve(document_path), document)
        frontend_ref = {"id": "frontend-map-document", "version": "1.0.0",
                        "digest": sha256_digest(document), "uri": str(document_path)}
        return {"candidate": candidate, "scene": scene, "preflight": None,
                "frontend_document": document, "frontend_document_ref": frontend_ref,
                "tool_receipts": [receipt.to_dict() for receipt in tool_receipts],
                "projection": {"method": PROJECTION_METHOD, "version": PROJECTION_VERSION,
                               "display_window": window, "placement": placement,
                               "normalized_extent": normalize_extent(parameters),
                               "annotation_algorithm": ANNOTATION_ALGORITHM if annotation else None}}

    # ------------------------------------------------------------------
    # verify_request — render re-verification (I-4a)
    # ------------------------------------------------------------------

    def verify_request(self, request: dict[str, Any], scene: dict[str, Any],
                       inputs: Any) -> None:
        if scene["renderer_id"] != IMAGE_ITINERARY_PAGE.renderer_id:
            raise ProtocolError("IMAGE_SCENE_RENDERER_MISMATCH", "Scene was not compiled for the image backend")
        basemap = request.get("basemap", {})
        expected = (basemap.get("image_ref", {}).get("digest")
                    or scene["resources"][0]["ref"]["digest"])
        resource = next((item for item in scene["resources"] if item["id"] == "basemap-image"), None)
        if resource is None or resource["ref"]["digest"] != expected:
            raise ProtocolError("IMAGE_SCENE_BASEMAP_DRIFT", "Scene basemap differs from the request")
        # I-4a: the frozen ToolGateway evidence must be present and re-verifiable —
        # the compile-time capability receipts (projection/display, and the
        # annotation solver when annotations were requested) are scene contracts.
        required = (PROJECTION_CAPABILITY, DISPLAY_CAPABILITY,
                    ANNOTATION_CAPABILITY if request.get("annotation_layout") else None)
        for capability in (item for item in required if item):
            evidence = next((item for item in scene["resources"]
                             if item["id"] == f"tool-{capability}"), None)
            if evidence is None or evidence["kind"] != "contract":
                raise ProtocolError("IMAGE_SCENE_TOOL_EVIDENCE_MISSING", capability)
            path = self.guard.resolve(evidence["ref"]["uri"], must_exist=True)
            document = load_document(path)
            if sha256_digest(document) != evidence["ref"]["digest"]:
                raise ProtocolError("IMAGE_SCENE_TOOL_EVIDENCE_DRIFT", capability)

    # ------------------------------------------------------------------
    # ToolGateway helpers
    # ------------------------------------------------------------------

    def _invoke_tool(self, gateway: Any, capability_id: str,
                     typed_input: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        """Invoke an authorized capability and load its verified output document.

        The receipt is bound to this exact typed input (input/output digests,
        single artifact); the output is loaded from the immutable evidence store
        and re-checked against the receipt digest.
        """
        receipt = gateway.invoke(capability_id, typed_input, self.context)
        if (receipt.status != "succeeded"
                or receipt.input_digest != sha256_digest(typed_input)
                or receipt.capability_id != capability_id
                or len(receipt.artifact_refs) != 1
                or receipt.artifact_refs[0]["digest"] != receipt.output_digest):
            raise ProtocolError("IMAGE_TOOL_EVIDENCE_INVALID",
                                f"{capability_id} gateway evidence is not bound to this request")
        ref = receipt.artifact_refs[0]
        path = self.guard.resolve(ref["uri"], must_exist=True)
        document = load_document(path)
        if not isinstance(document, dict) or sha256_digest(document) != ref["digest"]:
            raise ProtocolError("IMAGE_TOOL_EVIDENCE_CORRUPT", str(ref["uri"]))
        return document, receipt

    @staticmethod
    def _evidence_resource(receipt: Any) -> dict[str, Any]:
        ref = receipt.artifact_refs[0]
        return {"id": ref["id"], "kind": "contract", "digest_mode": "canonical-json",
                "ref": {"id": ref["id"], "version": ref["version"],
                        "digest": ref["digest"], "uri": ref["uri"]}}

    # ------------------------------------------------------------------
    # annotation solver (greedy + simulated annealing, fixed seed)
    # ------------------------------------------------------------------

    def _solve_annotations(self, gateway: Any, graphics: list[dict[str, Any]],
                           window: dict[str, int],
                           annotation: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
        """Replace greedy callout placement with the bounded solver result.

        The solver runs as the authorized annotation-layout capability; the
        handler re-verifies the result (check_layout, no re-optimization) before
        it can become evidence, and this compiler only consumes the frozen
        assignment offsets.
        """
        def windowed(points: list[dict[str, float]]) -> list[dict[str, float]]:
            return [{"x": p["x"] - window["x"], "y": p["y"] - window["y"]} for p in points]

        hard_lines = [{"points": windowed(graphic["points"]),
                       "width_px": graphic.get("width_px", 4)}
                      for graphic in graphics if graphic["type"] == "line"]
        hard_boxes: list[dict[str, float]] = []
        items = []
        for graphic in graphics:
            if graphic["type"] == "point":
                radius = graphic.get("radius_px", 12)
                anchor = graphic["position"]
                hard_boxes.append({"x": anchor["x"] - window["x"] - radius,
                                   "y": anchor["y"] - window["y"] - radius,
                                   "w": 2 * radius, "h": 3 * radius})
            elif graphic["type"] == "callout":
                item = {"id": graphic["id"],
                        "anchor_x": graphic["position"]["x"] - window["x"],
                        "anchor_y": graphic["position"]["y"] - window["y"],
                        "w": graphic["width_px"], "h": graphic["height_px"]}
                items.append(item)
        if not items:
            return graphics, None
        typed = {"schema_version": 1, "items": items, "hard_lines": hard_lines,
                 "hard_boxes": hard_boxes,
                 "canvas": {"width": window["width"], "height": window["height"]},
                 "gap_px": float(annotation["gap_px"]),
                 "seed": int(annotation["seed"]),
                 "iterations": int(annotation["iterations"])}
        result, receipt = self._invoke_tool(gateway, ANNOTATION_CAPABILITY, typed)
        if result["status"] != "placed":
            raise ProtocolError("ITINERARY_CALLOUT_PLACEMENT_FAILED",
                                ",".join(a["id"] for a in result["assignments"] if a["status"] == "unplaced"))
        by_id = {a["id"]: a for a in result["assignments"]}
        solved = []
        for graphic in graphics:
            if graphic["type"] == "callout" and graphic["id"] in by_id:
                assignment = by_id[graphic["id"]]
                graphic = {**graphic, "offset_x_px": assignment["dx"], "offset_y_px": assignment["dy"]}
            solved.append(graphic)
        return solved, receipt

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _bundle_uri(self, bundle: dict[str, Any]) -> str:
        refs = [binding["prepared_ref"]["uri"] for binding in bundle.get("role_bindings", []) if
                "uri" in binding.get("prepared_ref", {})]
        if not refs:
            raise ProtocolError("IMAGE_BUNDLE_URI_UNRESOLVED", "Bundle carries no prepared references")
        parent = posixpath.dirname(posixpath.dirname(refs[0]))
        return posixpath.join(parent, "prepared-data-bundle.yaml")

    @staticmethod
    def _font_family(path: Path) -> str:
        try:
            from fontTools.ttLib import TTFont
            with TTFont(str(path), lazy=True) as font:
                family = font["name"].getDebugName(1)
            if family:
                return family
        except Exception:
            pass
        return "sans-serif"
