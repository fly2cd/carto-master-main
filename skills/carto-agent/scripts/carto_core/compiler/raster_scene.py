"""Frozen scene/execution assembly shared by admitted raster-capable scenarios.

No business purpose is selected here. Callers supply their intent/template snapshot;
this compiler binds only data, portrayal, physical page and renderer environment.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..workflow.models import ExecutionContext
from ..workflow.raster_bundle import RasterBundlePreparer
from ..workflow.raster_preparation import RasterPreparationService
from .layout import LayoutResolver
from .raster_portrayal import RasterPortrayalCompiler

RASTER_RENDERER_ID = "rasterio-matplotlib-page"


def context_snapshot(context: ExecutionContext) -> dict[str, str]:
    context.require_project_scope()
    return {key: getattr(context, key) for key in ("run_id", "tenant_id", "project_id", "subject_id")}


class RasterSceneCompiler:
    def __init__(self, preparation: RasterPreparationService) -> None:
        self.preparation = preparation
        self.registry = preparation.registry

    def _inputs(self, bundle_ref, page_ref, context):
        bundle = RasterBundlePreparer(self.preparation).load_verified(bundle_ref, context)
        page = self.preparation._json_ref(page_ref, "raster-page-request")
        portrayal = RasterPortrayalCompiler(self.preparation).load_verified(page["portrayal_ref"], context)
        if portrayal["prepared_ref"] != bundle["role_bindings"][0]["prepared_ref"]:
            raise ProtocolError("RASTER_BUNDLE_PORTRAYAL_MISMATCH", "Page and bundle must use the same preparation")
        from ..adapters.raster_page_renderer import RasterPageRenderer
        RasterPageRenderer(self.preparation)._validate(page, context)
        report, evidence = self.preparation.load_verified(portrayal["prepared_ref"])
        font = {"artifact_ref": {"id": "font", "version": "1.0.0", "digest": page["font"]["digest"],
                                  "uri": page["font"]["path"]}, "size_bytes": page["font"]["size_bytes"]}
        self.preparation.snapshot_bytes(font, "font", ".ttf")
        resources = []
        for ref, kind, mode in [(bundle_ref, "contract", "canonical-json"),
                (bundle["task_ref"], "contract", "canonical-json"),
                (portrayal["prepared_ref"], "contract", "canonical-json"),
                (report["gis_result_ref"], "contract", "canonical-json"),
                (page["portrayal_ref"], "contract", "canonical-json"), (page_ref, "contract", "canonical-json"),
                (report["source_snapshot"]["artifact_ref"], "data", "bytes"),
                (report["legend_snapshot"]["artifact_ref"], "data", "bytes"), (font["artifact_ref"], "font", "bytes")]:
            resources.append({"id": ref["id"], "kind": kind, "digest_mode": mode, "ref": deepcopy(ref)})
        resources.sort(key=lambda item: item["id"])
        if len({item["id"] for item in resources}) != len(resources):
            raise ProtocolError("RASTER_RESOURCE_DUPLICATE", "Resource identities must be unique")
        return {"bundle": bundle, "page": page, "portrayal": portrayal, "report": report,
                "gis": evidence, "font": font, "resources": resources}

    def compile(self, *, bundle_ref, page_request, context: ExecutionContext,
                scene_id: str, revision: int = 1, targets=("pdf", "png"), random_seed: int = 0):
        from ..adapters.raster_page_renderer import RasterPageRenderer
        page_ref = RasterPageRenderer(self.preparation).freeze_request(page_request, context).ref()
        inputs = self._inputs(bundle_ref, page_ref, context)
        page = inputs["page"]["resolved_layout"]["page"]
        scene = {"schema_version": 1, "scene_id": scene_id, "revision": revision,
                 "renderer_id": RASTER_RENDERER_ID, "context": context_snapshot(context),
                 "prepared_bundle_ref": deepcopy(bundle_ref), "page_request_ref": page_ref,
                 "resolved_layout": deepcopy(inputs["page"]["resolved_layout"]),
                 "viewport": {k: page[k] for k in ("width_px", "height_px", "device_pixel_ratio")},
                 "export": {"targets": sorted(targets), "dpi": page["dpi"]}, "random_seed": random_seed,
                 "resources": inputs["resources"]}
        self.validate_scene(scene, context)
        return scene

    def validate_scene(self, scene: dict[str, Any], context: ExecutionContext):
        self.registry.validate("render-scene", scene)
        if scene["renderer_id"] != RASTER_RENDERER_ID:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", "Expected the raster page backend")
        if scene["context"] != context_snapshot(context):
            raise SecurityError("RASTER_SCENE_SCOPE_MISMATCH", "Scene belongs to another execution context")
        inputs = self._inputs(scene["prepared_bundle_ref"], scene["page_request_ref"], context)
        if scene["resources"] != inputs["resources"] or scene["resolved_layout"] != inputs["page"]["resolved_layout"]:
            raise ProtocolError("RASTER_SCENE_INPUT_DRIFT", "Scene resources/layout differ from the frozen page")
        LayoutResolver(self.registry).validate_scene(scene)
        if not {"pdf", "png"}.issubset(scene["export"]["targets"]):
            raise ProtocolError("RASTER_REQUIRED_TARGETS_MISSING", "Formal page scenes require PDF and PNG")
        return inputs

    def bind_execution(self, execution, scene, context):
        """Bind an existing business execution snapshot; no new scenario or implicit GIS transform."""
        from ..adapters.raster_formal_renderer import RasterRendererProfile
        inputs = self.validate_scene(scene, context)
        result = deepcopy(execution)
        for key in ("camera", "overlay_coordinate_policy", "interaction_policy"):
            result.pop(key, None)
        profile = RasterRendererProfile.current()
        page = scene["resolved_layout"]["page"]
        crs = inputs["bundle"]["role_bindings"][0]["crs"]
        result.update(raster_inputs={k: deepcopy(scene[k]) for k in ("prepared_bundle_ref", "page_request_ref")},
                      resolved_layout=deepcopy(scene["resolved_layout"]),
                      render_scene_ref={"id": scene["scene_id"], "version": "1.0.0", "digest": sha256_digest(scene)},
                      dataset_refs=deepcopy(inputs["bundle"]["datasets"]),
                      prepared_data_refs=[deepcopy(scene["prepared_bundle_ref"])],
                      resolved_assets=[deepcopy(inputs["font"]["artifact_ref"])],
                      environment=profile.environment_snapshot(),
                      views=[{"id": LayoutResolver.map_frame(scene["resolved_layout"])["content_id"],
                              "extent": inputs["bundle"]["summary"]["combined_bbox"],
                              "layer_ids": [inputs["portrayal"]["layer_id"]],
                              "target_ids": sorted(scene["export"]["targets"])}],
                      targets={kind: {"format": kind, "display_crs": deepcopy(crs),
                                      **{k: page[k] for k in ("width_mm", "height_mm", "dpi")}}
                               for kind in scene["export"]["targets"]})
        self.validate_execution(scene, result, context)
        return result

    def validate_execution(self, scene, execution, context):
        inputs = self.validate_scene(scene, context)
        LayoutResolver(self.registry).validate_execution(scene, execution)
        expected = {"dataset_refs": inputs["bundle"]["datasets"],
                    "prepared_data_refs": [scene["prepared_bundle_ref"]],
                    "resolved_assets": [inputs["font"]["artifact_ref"]]}
        if any(execution.get(key) != value for key, value in expected.items()):
            raise ProtocolError("RASTER_EXECUTION_INPUT_DRIFT", "Execution must bind exactly the verified frozen assets")
        view = execution["views"][0]
        if (view["extent"] != inputs["bundle"]["summary"]["combined_bbox"]
                or view["layer_ids"] != [inputs["portrayal"]["layer_id"]]
                or sorted(view["target_ids"]) != sorted(execution["targets"])
                or sorted(t["format"] for t in execution["targets"].values()) != scene["export"]["targets"]
                or execution["shared_semantics"]["data_nature"] != inputs["bundle"]["summary"]["data_nature"]
                or any(t["display_crs"] != inputs["bundle"]["role_bindings"][0]["crs"] for t in execution["targets"].values())):
            raise ProtocolError("RASTER_EXECUTION_SEMANTICS_DRIFT", "Extent, layer, data nature, CRS and targets must match")
        return inputs

    def validate_generation(self, scene, execution, request, context):
        """Preserve explicitly requested sources and exports at the generation boundary."""
        inputs = self.validate_execution(scene, execution, context)
        RasterBundlePreparer(self.preparation).validate_request(request, inputs["bundle"], context)
        if sorted(request["requested_outputs"]) != scene["export"]["targets"]:
            raise ProtocolError("RASTER_GENERATE_TARGET_MISMATCH", "Scene outputs must match the generation request")
        return inputs
