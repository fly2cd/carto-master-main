"""Registered components of the ``general_thematic_mapping`` business scenario.

This module implements exactly one statable cartographic purpose — standard
thematic map compilation from user-provided, already-classified raster data —
and nothing else. It is admitted through the closed ``_COMPONENTS`` allowlist in
``scenario_registry`` and the versioned ``policies/scenario-capabilities.yaml``;
it never selects itself from request data, issues approvals, or widens a
capability policy.

Determinism rules enforced here:

* every artifact is a pure function of the approved request/intent/contracts and
  the verified preparation evidence — timestamps come from the request, never
  from the clock;
* the fixture-render branch of template validation is NOT implemented yet, so
  ``validation_scene`` fails closed and this template line cannot be published
  until that framework evolution lands;
* no business data rows, secrets or sensitive coordinates are written into
  template packages, fixtures or reports.
"""
from __future__ import annotations

import csv
import io
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..compiler.dependencies import DependencyResolver
from ..compiler.layout import LayoutResolver
from ..compiler.raster_portrayal import RasterPortrayalCompiler
from ..compiler.raster_scene import RASTER_RENDERER_ID, RasterSceneCompiler
from ..errors import ProtocolError, SecurityError
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..repository.staging_package import StagingPackageWriter
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from ..artifacts import artifact_ref
from ..workflow.models import ExecutionContext
from ..workflow.raster_bundle import RasterBundlePreparer
from ..workflow.raster_preparation import RasterPreparationService

SCENARIO_ID = "general-thematic-map"
VERSION = "1.0.0"
BUSINESS_SCENE = "general_thematic_mapping"
AUTHORING_PROFILE = "general-thematic-authoring"
TASK = "thematic-map"
DATA_ROLE = "classified-surface"
ROLE_BINDING_KEY = "classified_surface"
LAYER_ID = "raster-layer"
EXPRESSION_ID = "raster/categorical"
EXPRESSION_VERSION = "1.0.0"
LAYOUT_ID = "general-thematic-a4-landscape"
IDENTITY_ID = "general-thematic-identity"
STYLE_ID = "general-thematic-style"
PROTOTYPE_ID = "general-thematic-prototype"
LOCK_ID = "general-thematic-map-lock"
BASELINE_ID = "general-thematic-map-baseline"
TARGET_IDS = ("a4-pdf", "a4-png")
NAMESPACE = "local"
KIND = "map-scenario"
FONT_FAMILY = "Noto Sans SC"
LEGEND_TITLE = "图例"
ORGANIZATION = "carto-general-thematic"
FIXTURE_PATH = "fixtures/validation-input.csv"
FIXTURE_HEADER = ("category_value", "category_label")
FIXTURE_ROWS = (
    ("1", "示例类别一"),
    ("2", "示例类别二"),
    ("3", "示例类别三"),
)
FIXTURE_LIMIT_BYTES = 65536
MAX_CLASSES = 256
_CODE = re.compile(r"-?(?:0|[1-9][0-9]{0,9})\Z")
TYPOGRAPHY = {"title_pt": 18, "body_pt": 9, "legend_pt": 10,
              "legend_heading_pt": 11, "padding_mm": 2, "line_spacing": 1.25}


def _catalog_reference(registry: SchemaRegistry) -> dict[str, str]:
    return MapExpressionCatalog(registry).reference(EXPRESSION_ID, EXPRESSION_VERSION)


# --------------------------------------------------------------------------
# generate-map line: data preparation, planning, candidate compilation
# --------------------------------------------------------------------------


class GeneralThematicDataPreparer:
    """Bind one already-ready classification report to the generation request.

    No new GIS work happens here: ``RasterBundlePreparer.prepare_request``
    re-verifies the immutable preparation evidence, its execution scope and the
    exact request bindings before a bundle may exist.
    """

    def __init__(self, path_guard: PathGuard, project_root: Path, output_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = Path(project_root)
        self.output_root = Path(output_root)
        self.registry = registry or SchemaRegistry()

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        if request_ref.get("digest") != sha256_digest(request):
            raise ProtocolError("RASTER_REQUEST_REF_MISMATCH", "Preparation must bind the exact generation request")
        context = ExecutionContext.from_generate_request(request)
        preparation = RasterPreparationService(
            project_root=self.project_root,
            allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
        prepared = RasterBundlePreparer(preparation).prepare_request(request, context)
        return {"bundle": prepared["bundle"], "bundle_ref": prepared["bundle_ref"],
                "request_ref": deepcopy(request_ref)}


class GeneralThematicPlanner:
    """Plan the single admitted expression: unique-value categorical raster page."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self, request: dict[str, Any], intent: dict[str, Any], brief: dict[str, Any],
              bundle: dict[str, Any], installation: dict[str, Any],
              contracts: dict[str, Any]) -> dict[str, Any]:
        bindings = bundle.get("role_bindings", [])
        if len(bindings) != 1 or bindings[0].get("role") != DATA_ROLE:
            raise ProtocolError("RASTER_BUNDLE_UNSUPPORTED", f"Plan requires exactly one {DATA_ROLE} raster binding")
        capacity = contracts["scenario"]["embedded"]["layout"]["capacity"]["legend_items"]
        return {
            "schema_version": 1,
            "plan_id": f"plan-{request['run_id']}",
            "revision": 1,
            "project_id": request["project_id"],
            "intent_ref": artifact_ref("map-intent", intent),
            "brief_ref": artifact_ref("map-brief", brief),
            "business_scene": intent["business_scene"],
            "tasks": list(intent["tasks"]),
            "template_refs": [deepcopy(installation["template_ref"])],
            "data_bindings": [{"role": bindings[0]["role"],
                               "dataset_ref": deepcopy(bindings[0]["dataset_ref"])}],
            "decisions": {
                "classification": "unique-values",
                "class_count": int(capacity),
                "extent": deepcopy(bundle["summary"]["combined_bbox"]),
                "title": request["goal"],
                "legend_source": "actual-encoding",
                "renderer_id": RASTER_RENDERER_ID,
            },
            "open_issues": [],
            "theme_tags": list(intent["theme_tags"]),
        }


class GeneralThematicCandidateCompiler:
    """Assemble frozen scene/execution/candidate artifacts for the raster page backend."""

    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None, *,
                 project_root: Path | None = None, context: ExecutionContext | None = None) -> None:
        self.path_guard = path_guard
        self.registry = registry or SchemaRegistry()
        self.project_root = project_root
        self.context = context

    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any],
                contracts: dict[str, Any], font_path: Path) -> dict[str, Any]:
        from ..adapters.raster_page_renderer import FONT_LIMIT
        if self.project_root is None or self.context is None:
            raise SecurityError("RASTER_EXECUTION_CONTEXT_REQUIRED",
                                "Raster candidates require the trusted project context")
        context = ExecutionContext.from_generate_request(request)
        if any(getattr(context, key) != getattr(self.context, key)
               for key in ("run_id", "tenant_id", "project_id", "subject_id")):
            raise SecurityError("CLASSIFICATION_SCOPE_MISMATCH",
                                "Injected execution context differs from the generation request")
        profile = ScenarioRegistry(self.registry).for_template(request["template"])
        prepared_ref = deepcopy(request["prepared_raster_bindings"][0]["prepared_ref"])
        preparation = RasterPreparationService(
            project_root=self.project_root,
            allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
        if bundle != RasterBundlePreparer(preparation).build(prepared_ref, context):
            raise ProtocolError("RASTER_CANDIDATE_BUNDLE_MISMATCH",
                                "Candidate input differs from the verified preparation")
        binding = bundle["role_bindings"][0]
        if binding["crs"] != contracts["spatial_behavior"]["display_crs"]:
            raise ProtocolError("RASTER_DISPLAY_CRS_MISMATCH",
                                "Prepared raster CRS differs from the frozen display CRS")
        bundle_ref = preparation.save_document(bundle, "prepared-data-bundle").ref()
        portrayal_ref = RasterPortrayalCompiler(preparation).compile(
            deepcopy(contracts["portrayal"]), LAYER_ID, prepared_ref, context).ref()
        resolved_portrayal = preparation._json_ref(portrayal_ref, "resolved-raster-portrayal")
        legend = resolved_portrayal["legend_items"]
        limit = min(int(contracts["scenario"]["embedded"]["layout"]["capacity"]["legend_items"]),
                    int(plan["decisions"]["class_count"]))
        if not legend or len(legend) > limit:
            raise ProtocolError("RASTER_LEGEND_CAPACITY",
                                "Legend must be nonempty and fit the layout capacity and the approved plan")
        output = profile.definition["output_profile"]
        resolved_layout = LayoutResolver(self.registry).resolve(
            contracts["scenario"]["embedded"]["layout"], output["dpi"])
        if any(resolved_layout["page"][key] != output[key]
               for key in ("width_mm", "height_mm", "dpi", "width_px", "height_px")):
            raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                                "Layout differs from the enabled output profile")
        font_bytes = preparation.read_bytes(Path(font_path), FONT_LIMIT)
        page_request = {
            "schema_version": 1,
            "portrayal_ref": deepcopy(portrayal_ref),
            "resolved_layout": deepcopy(resolved_layout),
            "font": {"path": str(font_path), "digest": preparation.digest_bytes(font_bytes),
                     "size_bytes": len(font_bytes)},
            "texts": [
                {"content_id": "title", "text": plan["decisions"]["title"]},
                {"content_id": "source", "text": profile.notice},
            ],
            "legend": {"content_id": "legend", "title": LEGEND_TITLE},
            "typography": dict(TYPOGRAPHY),
            "scale_bar": None,
            "grid_north": None,
        }
        compiler = RasterSceneCompiler(preparation)
        scene = compiler.compile(
            bundle_ref=deepcopy(bundle_ref), page_request=page_request, context=context,
            scene_id=f"scene-{request['run_id']}", targets=tuple(sorted(request["requested_outputs"])))
        execution = compiler.bind_execution(
            self._execution_base(intent, installation, bundle, profile), scene, context)
        candidate = {
            "schema_version": 1,
            "candidate_id": f"candidate-{request['run_id']}",
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "execution_digest": sha256_digest(execution),
            "execution": execution,
            "open_issues": [],
            "created_at": request["requested_at"],
        }
        return {"candidate": candidate, "scene": scene}

    def _execution_base(self, intent: dict[str, Any], installation: dict[str, Any],
                        bundle: dict[str, Any], profile: Any) -> dict[str, Any]:
        return {
            "intent_ref": {"id": "map-intent", "version": "1.0.0", "digest": sha256_digest(intent)},
            "profile_refs": [deepcopy(intent["evidence_refs"][0]), deepcopy(intent["evidence_refs"][-1])],
            "business_scene": intent["business_scene"],
            "map_tasks": list(intent["tasks"]),
            "template_refs": [deepcopy(installation["template_ref"])],
            "dependency_refs": [_catalog_reference(self.registry)],
            "policy_refs": [profile.ref],
            "ownership": {"scenario": "map-scenario"},
            "shared_semantics": {"theme_tags": list(intent["theme_tags"]),
                                 "data_nature": bundle["summary"]["data_nature"]},
        }


def legend_checker(context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
    """Business semantics of the frozen legend: unambiguous, complete, ordered."""
    raster = context.get("raster")
    if not isinstance(raster, dict) or "portrayal" not in raster:
        raise ProtocolError("RASTER_EXECUTION_CONTEXT_REQUIRED",
                            "legend_checker requires the verified raster context")
    items = raster["portrayal"]["legend_items"]
    problems: list[str] = []
    labels = [item.get("label") for item in items]
    colors = [item.get("color") for item in items]
    orders = [item.get("order") for item in items]
    if not items:
        problems.append("empty-legend")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        problems.append("missing-label")
    elif len(set(labels)) != len(labels):
        problems.append("duplicate-label")
    if any(not isinstance(color, str) or not color for color in colors):
        problems.append("missing-color")
    elif len(set(colors)) != len(colors):
        problems.append("duplicate-color")
    if any(not isinstance(order, int) or isinstance(order, bool) for order in orders):
        problems.append("order-invalid")
    elif orders != sorted(orders) or len(set(orders)) != len(orders):
        problems.append("order-invalid")
    details = {"legend_item_count": len(items), "problems": problems}
    return not problems, details, None


# --------------------------------------------------------------------------
# create-template line: source contract, author, validation components
# --------------------------------------------------------------------------


class GeneralThematicSourceContract:
    """Admit only a bounded, non-sensitive CSV legend sample for authoring."""

    REQUIRED_FIELDS = frozenset(FIXTURE_HEADER)

    def validate_source_profile(self, source: dict[str, Any], request: dict[str, Any]) -> None:
        profile = source.get("data_profile")
        if source.get("kind") != "csv":
            raise ProtocolError("SOURCE_TYPE_UNSUPPORTED",
                                "The authoring legend sample must be a bounded CSV")
        if not isinstance(profile, dict):
            raise SecurityError("SOURCE_PROFILE_REQUIRED", source.get("source_id", "unknown"))
        if profile.get("data_nature") != request["data_nature"]:
            raise ProtocolError("SOURCE_DATA_NATURE_MISMATCH", source["source_id"])
        if profile.get("contains_production_data") != request["contains_production_data"]:
            raise ProtocolError("SOURCE_PRODUCTION_FLAG_MISMATCH", source["source_id"])
        if profile.get("contains_sensitive_coordinates") or request["contains_sensitive_coordinates"]:
            raise SecurityError("SOURCE_SENSITIVE_COORDINATES_FORBIDDEN", source["source_id"])
        if source.get("license") not in {"public", "project-approved"}:
            raise SecurityError("SOURCE_LICENSE_RESTRICTED", source["source_id"])
        if profile.get("source_crs") != request["source_crs"]:
            raise ProtocolError("SOURCE_CRS_UNSUPPORTED",
                                "Legend sample must declare the template source CRS")

    def suggestions(self, profile_definition: dict[str, Any]) -> list[dict[str, Any]]:
        return [{
            "path": "/portrayal/map-expressions",
            "value_origin": "system_suggestion",
            "value": [f"{EXPRESSION_ID}@{EXPRESSION_VERSION}"],
            "rationale": "注册目录中唯一活动的分类栅格表达；模板仅引用目录条目，不内嵌颜色或类别行。",
        }]

    def validate_role_bindings(self, request: dict[str, Any], summaries: list[dict[str, Any]]) -> None:
        bindings = request.get("role_bindings", {})
        if set(bindings) != {ROLE_BINDING_KEY}:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED",
                                f"Exactly one {ROLE_BINDING_KEY} role binding is admitted")
        if len(summaries) != 1:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED", "Exactly one legend-sample source is admitted")
        summary = summaries[0]
        if bindings[ROLE_BINDING_KEY] != summary["source_id"]:
            raise ProtocolError("ROLE_BINDING_SOURCE_MISMATCH", summary["source_id"])
        if summary["kind"] != "csv":
            raise ProtocolError("SOURCE_TYPE_UNSUPPORTED", summary["source_id"])
        missing = sorted(self.REQUIRED_FIELDS - set(summary["field_names"]))
        if missing:
            raise ProtocolError("ROLE_BINDING_FIELD_MISSING", ",".join(missing))

    def brief_roles(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return [{
            "role_id": DATA_ROLE,
            "source_id": request["role_bindings"][ROLE_BINDING_KEY],
            "geometry_types": ["none"],
            "value_field": "category_value",
            "semantic_role": "category-value",
        }]


SOURCE_CONTRACT = GeneralThematicSourceContract()


class GeneralThematicAuthor:
    """Deterministically author the closed staging package for this scenario."""

    def __init__(self, path_guard: PathGuard, work_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.work_root = path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._payloads(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).write(
            manifest_base, documents)

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._payloads(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).verify_existing(
            manifest_base, documents)

    def _payloads(self, request: dict[str, Any], brief: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self._require_admitted(request, brief)
        identity = {"namespace": NAMESPACE, "kind": KIND, "id": SCENARIO_ID, "version": VERSION}
        documents = {
            "contracts/scenario.yaml": self._scenario(request),
            "contracts/data.schema.yaml": self._data_schema(),
            "contracts/spatial-behavior.yaml": self._spatial_behavior(request),
            "contracts/portrayal.yaml": self._portrayal(),
            "contracts/delivery.yaml": self._delivery(),
            "contracts/quality-gates.yaml": self._quality_gates(),
            "dependencies.lock.yaml": {
                "schema_version": 1,
                "lock_id": LOCK_ID,
                "package": {**identity, "digest": sha256_digest(identity)},
                "dependencies": [],
                "resources": [_catalog_reference(self.registry)],
                "resolver_version": "1.0.0",
                "generated_at": request["requested_at"],
            },
            "prototypes/general-thematic.yaml": {
                "schema_version": 1,
                "prototype_id": PROTOTYPE_ID,
                "status": "pending-validation",
                "render_required": True,
                "renderer_execution": "not-run",
                "layout_id": LAYOUT_ID,
                "target_ids": list(TARGET_IDS),
                "layer_ids": [LAYER_ID],
                "fixture_ref": FIXTURE_PATH,
                "limitations": [
                    "分类栅格模板的样张渲染分支尚未注册；发布前必须完成受控渲染验证。",
                ],
            },
            FIXTURE_PATH: self._fixture_csv(),
        }
        manifest_base = {
            "schema_version": 1,
            "package": {**identity, "status": "draft", "summary": request["purpose"][:500]},
            "business_contracts": dict(DependencyResolver.MAP_SCENARIO_CONTRACTS),
            "dependencies": [],
            "dependency_lock": "dependencies.lock.yaml",
            "targets": sorted(request["targets"]),
        }
        return manifest_base, documents

    @staticmethod
    def _require_admitted(request: dict[str, Any], brief: dict[str, Any]) -> None:
        if (request.get("kind") != KIND or request.get("namespace") != NAMESPACE
                or request.get("template_id") != SCENARIO_ID or request.get("version") != VERSION
                or request.get("profile") != AUTHORING_PROFILE):
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE",
                                "Only the registered general-thematic authoring profile may use this author")
        if sorted(request.get("targets", [])) != ["pdf", "png"]:
            raise ProtocolError("RENDER_TARGET_UNSUPPORTED", "Admitted targets are exactly pdf and png")
        if request["source_crs"] != request["display_crs"]:
            raise ProtocolError("SOURCE_CRS_UNSUPPORTED",
                                "The preserve policy requires display_crs to equal source_crs")
        if (brief.get("kind") != KIND or brief.get("namespace") != NAMESPACE
                or brief.get("template_id") != SCENARIO_ID or brief.get("version") != VERSION):
            raise ProtocolError("TEMPLATE_BRIEF_MISMATCH", "Brief does not describe this template")

    def _scenario(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "scenario_id": SCENARIO_ID,
            "version": VERSION,
            "business_scene": BUSINESS_SCENE,
            "tasks": [TASK],
            "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal",
                               "delivery", "quality-gates"],
            "embedded": {"identity": self._identity(), "cartography": self._cartography(),
                         "layout": self._layout()},
            "replaceable_segments": [],
            "data_role_refs": [DATA_ROLE],
            "target_ids": list(TARGET_IDS),
            "application": {"supported_uses": sorted(request["supported_uses"]),
                            "excluded_uses": sorted(request["excluded_uses"])},
            "compatibility": {"target_profiles": [LAYOUT_ID],
                              "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"]},
            "rules": [],
        }

    @staticmethod
    def _identity() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "identity_id": IDENTITY_ID,
            "version": VERSION,
            "organization": ORGANIZATION,
            "colors": [{
                "role": "primary",
                "hex": "#1F4E79",
                "provenance": {"source_type": "internal",
                               "source_ref": f"template:{SCENARIO_ID}@{VERSION}",
                               "classification": "internal"},
            }],
            "typography": [{"role": "title", "family": FONT_FAMILY, "weight": 700},
                           {"role": "body", "family": FONT_FAMILY, "weight": 400}],
            "attribution": {"organization_format": "制图：{organization}",
                            "data_source_format": "数据来源：{source}"},
            "rules": [],
        }

    @staticmethod
    def _cartography() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "style_id": STYLE_ID,
            "version": VERSION,
            "visual_language": "technical",
            "symbolization": {"color_system": "qualitative",
                              "symbol_catalogs": ["ramps/categorical-raster@1.0.0"],
                              "default_opacity": 1.0},
            "labeling": {"density": "low", "collision_policy": "avoid", "font_role": "body"},
            "generalization": {"scale_dependent": False, "strategy": "none"},
            "defaults": {"opacity": 1.0},
            "rules": [],
        }

    @staticmethod
    def _layout() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "layout_id": LAYOUT_ID,
            "version": VERSION,
            "category": "report",
            "canvas": {"width": 297, "height": 210, "unit": "mm",
                       "orientation": "landscape", "safe_margin": 10},
            "frames": [
                {"id": "map", "content_id": "main-view", "type": "map",
                 "bounds": [10, 25, 215, 175], "coordinate_space": "page",
                 "overflow_policy": "clip"},
                {"id": "title", "content_id": "title", "type": "title",
                 "bounds": [10, 10, 277, 10], "coordinate_space": "page",
                 "overflow_policy": "reject"},
                {"id": "legend", "content_id": "legend", "type": "legend",
                 "bounds": [230, 40, 57, 130], "coordinate_space": "page",
                 "overflow_policy": "reject"},
                {"id": "source", "content_id": "source", "type": "marginalia",
                 "bounds": [230, 180, 57, 15], "coordinate_space": "page",
                 "overflow_policy": "reject"},
            ],
            "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"],
            "capacity": {"legend_items": 12, "title_characters": 60},
            "rules": [],
        }

    @staticmethod
    def _data_schema() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "roles": [{
                "id": DATA_ROLE,
                "required": True,
                "geometry_types": ["raster"],
                "fields": [
                    {"name": "category_value", "type": "integer", "nullable": False,
                     "semantic_role": "category-value"},
                    {"name": "category_label", "type": "string", "nullable": True,
                     "semantic_role": "category-label"},
                ],
                "license_policy": "project-approved",
            }],
        }

    @staticmethod
    def _spatial_behavior(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_crs_policy": "preserve",
            "display_crs": deepcopy(request["display_crs"]),
            "extent_policy": "data",
            "scale_bands": [{"id": "native-raster", "min_denominator": 1,
                             "max_denominator": 100000000, "generalization": "none"}],
            "topology": {"preserve_adjacency": True, "preserve_route_order": False},
            "rules": [],
        }

    def _portrayal(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "layers": [{
                "id": LAYER_ID,
                "data_role": DATA_ROLE,
                "geometry": "raster",
                "z_order": 10,
                "map_expression_ref": _catalog_reference(self.registry),
                "value_role": "category-value",
                "category_mapping": {"method": "unique-values",
                                     "definition_source": "prepared-display-contract",
                                     "unknown_value_policy": "reject"},
                "source_mask_policy": "preserve",
                "resampling": "nearest",
                "no_data": "transparent",
            }],
            "legend": {"generated_from_layers": True, "show_no_data": False,
                       "overflow_policy": "reject"},
            "rules": [],
        }

    @staticmethod
    def _delivery() -> dict[str, Any]:
        page = {"width_mm": 297, "height_mm": 210, "orientation": "landscape",
                "dpi": 300, "safe_margin_mm": 10}
        return {
            "schema_version": 1,
            "targets": [
                {"id": TARGET_IDS[0], "delivery_class": "engineering-preview", "format": "pdf",
                 "composition": "raster-map-vector-overlay", "vector_claim": "overlay-only",
                 "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
                 "production_ready": False},
                {"id": TARGET_IDS[1], "delivery_class": "engineering-preview", "format": "png",
                 "composition": "flattened-raster", "vector_claim": "none",
                 "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
                 "production_ready": False},
            ],
            "rules": [],
        }

    @staticmethod
    def _quality_gates() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "baseline": {"id": BASELINE_ID, "version": VERSION,
                         "digest": sha256_digest({"scenario_id": SCENARIO_ID, "version": VERSION,
                                                  "business_scene": BUSINESS_SCENE})},
            "checks": [
                {"id": "protocol.schema-valid", "version": "1.0.0", "params": {}},
                {"id": "cartography.legend-consistency", "version": "1.0.0", "params": {}},
                {"id": "raster.classification-clarified", "version": "1.0.0", "params": {}},
            ],
        }

    @staticmethod
    def _fixture_csv() -> str:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(FIXTURE_HEADER)
        writer.writerows(FIXTURE_ROWS)
        return buffer.getvalue()


def validation_data_checker(package_root: Path, snapshot: dict[str, Any],
                            expected: dict[str, Any]) -> None:
    """Fail-closed content check of the authored package's synthetic legend sample."""
    manifest = snapshot["manifest"]
    identity = {key: manifest["package"][key] for key in ("namespace", "kind", "id", "version")}
    if identity != {key: expected[key] for key in identity}:
        raise ProtocolError("TEMPLATE_IDENTITY_MISMATCH", str(identity))
    if expected["source_crs"] != expected["display_crs"]:
        raise ProtocolError("SOURCE_CRS_UNSUPPORTED",
                            "The preserve policy requires display_crs to equal source_crs")
    fixture_paths = snapshot.get("fixture_paths") or []
    if len(fixture_paths) != 1:
        raise ProtocolError("FIXTURE_SET_INVALID", str(fixture_paths))
    fixture = Path(package_root) / fixture_paths[0]
    if not fixture.is_file() or not 0 < fixture.stat().st_size <= FIXTURE_LIMIT_BYTES:
        raise ProtocolError("SOURCE_TOO_LARGE", fixture_paths[0])
    try:
        content = fixture.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("SOURCE_ENCODING_INVALID", fixture_paths[0]) from exc
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    header = reader.fieldnames or []
    if sorted(header) != sorted(FIXTURE_HEADER) or len(set(header)) != len(header):
        raise ProtocolError("CSV_HEADER_INVALID", fixture_paths[0])
    rows = 0
    seen: set[int] = set()
    for record in reader:
        rows += 1
        if rows > MAX_CLASSES or None in record or any(value is None for value in record.values()):
            raise ProtocolError("CSV_ROW_INVALID", fixture_paths[0])
        code = record["category_value"].strip()
        if not _CODE.fullmatch(code) or not -2147483648 <= int(code) <= 4294967295:
            raise ProtocolError("CLASSIFICATION_CODE_INVALID", fixture_paths[0])
        if int(code) in seen:
            raise ProtocolError("CLASSIFICATION_CODE_DUPLICATE", fixture_paths[0])
        seen.add(int(code))
        label = record["category_label"].strip()
        if not label or len(label) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in label):
            raise ProtocolError("CLASSIFICATION_LABEL_INVALID", fixture_paths[0])
    if rows < 1:
        raise ProtocolError("CLASSIFICATION_CSV_EMPTY", fixture_paths[0])


def validation_scene(package_root: Path, snapshot: dict[str, Any], targets: list[str],
                     font: Path, validator_version: str) -> dict[str, Any]:
    """Raster fixture rendering is not registered yet; never fake render evidence."""
    raise ProtocolError(
        "RASTER_FIXTURE_RENDER_UNREGISTERED",
        "分类栅格模板的受控样张渲染分支尚未注册；在框架补齐之前不得发布该模板。",
    )
