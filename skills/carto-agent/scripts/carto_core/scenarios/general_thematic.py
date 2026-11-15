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
* the validation fixture renders through the registered raster backend: it derives
  a deterministic synthetic raster from the packaged legend sample, measures it
  through the authorized MCP gateway, and freezes the scene so publication can
  re-verify the exact rendering evidence;
* no business data rows, secrets or sensitive coordinates are written into
  template packages, fixtures or reports.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..adapters.tool_gateway import ToolGateway
from ..canonical import sha256_digest
from ..compiler.dependencies import DependencyResolver
from ..compiler.layout import LayoutResolver
from ..compiler.page_bindings import build_page_bindings, index_by
from ..compiler.raster_page_contract import compile_page_request
from ..compiler.raster_portrayal import RasterPortrayalCompiler
from ..compiler.raster_scene import RASTER_RENDERER_ID, RasterSceneCompiler
from ..errors import ProtocolError, SecurityError
from ..repository.immutable_store import ImmutableArtifactStore
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..repository.staging_package import StagingPackageWriter
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from ..artifacts import artifact_ref
from ..workflow.models import ExecutionContext
from ..workflow.preparation_bundle import BundlePreparer
from ..workflow.raster_preparation import RasterPreparationService

SCENARIO_ID = "general-thematic-map"
VERSION = "3.0.0"
BUSINESS_SCENE = "general_thematic_mapping"
AUTHORING_PROFILE = "general-thematic-authoring"
TASK = "thematic-map"
DATA_ROLE = "classified-surface"
ROLE_BINDING_KEY = "classified_surface"
LAYER_ID = "raster-layer"
EXPRESSION_ID = "categorical"
EXPRESSION_VERSION = "2.0.0"
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
VALIDATION_TITLE = "分类栅格模板样张"
FIXTURE_SIZE = 64
FIXTURE_ORIGIN_X = 500000.0
FIXTURE_ORIGIN_Y = 4000000.0
FIXTURE_PIXEL = 30.0
FIXTURE_TIFF = "validation-fixture.tif"
FIXTURE_LEGEND = "validation-legend.csv"
FIXTURE_SOURCE_ID = "validation-fixture-raster"
FIXTURE_DATASET_ID = "validation-fixture"


def _catalog_reference(registry: SchemaRegistry) -> dict[str, str]:
    return MapExpressionCatalog(registry).reference(EXPRESSION_ID, EXPRESSION_VERSION)


# --------------------------------------------------------------------------
# generate-map line: data preparation, planning, candidate compilation
# --------------------------------------------------------------------------


class GeneralThematicDataPreparer:
    """Bind explicitly selected ready classification reports to the generation request.

    No new GIS work happens here: ``BundlePreparer.prepare_request``
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
        prepared = BundlePreparer(preparation, "raster").prepare_request(request, context)
        return {"bundle": prepared["bundle"], "bundle_ref": prepared["bundle_ref"],
                "request_ref": deepcopy(request_ref)}


class GeneralThematicPlanner:
    """Derive plan decisions from the template portrayal contract; never invent classification or backend."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self,request,intent,brief,bundle,installation,contracts):
        from ..workflow.thematic import raster_views
        if not bundle.get("role_bindings"):
            raise ProtocolError("RASTER_BUNDLE_UNSUPPORTED","No bound data")
        profile=ScenarioRegistry(self.registry).for_template(request['template'])
        layout=LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'],
            profile.definition['output_profile']['dpi'],
            parameters=request['layout_parameters'])
        bindings=build_page_bindings(layout['contract'],contracts['portrayal'],bundle,request['panels'],self.registry)
        return {'schema_version':4,'plan_id':f"plan-{request['run_id']}",'revision':brief['revision'],'project_id':request['project_id'],
            'intent_ref':artifact_ref('map-intent',intent),'brief_ref':artifact_ref('map-brief',brief),
            'business_scene':intent['business_scene'],'tasks':list(intent['tasks']),
            'template_refs':[deepcopy(installation['template_ref'])],
            'data_bindings':[{'role':b['role'],'dataset_ref':deepcopy(b['dataset_ref'])} for b in bundle['role_bindings']],
            'decisions':{'title':request['map_title'], 'legend_source':'actual-encoding',
                         'renderer_id':profile.definition['renderer_id'],
                         'legend_capacity':layout['contract']['capacity']['legend_items'],
                         'thematic_views':raster_views(request,bundle,self.registry)},
            'bindings':bindings,'layout_parameters':deepcopy(request['layout_parameters']),'open_issues':[],
            'theme_tags':list(intent['theme_tags'])}


class GeneralThematicCandidateCompiler:
    """Assemble frozen scene/execution/candidate artifacts for the raster page backend."""

    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None, *,
                 project_root: Path | None = None, context: ExecutionContext | None = None) -> None:
        self.path_guard = path_guard
        self.registry = registry or SchemaRegistry()
        self.project_root = project_root
        self.context = context

    def compile(self,request,intent,plan,bundle,installation,contracts,font_path):
        from ..adapters.static_page_renderer import FONT_LIMIT
        from ..workflow.thematic import raster_views
        if self.project_root is None or self.context is None:
            raise SecurityError('RASTER_EXECUTION_CONTEXT_REQUIRED','Trusted project context required')
        context=ExecutionContext.from_generate_request(request)
        if any(getattr(context,k)!=getattr(self.context,k) for k in ('run_id','tenant_id','project_id','subject_id')):
            raise SecurityError('CLASSIFICATION_SCOPE_MISMATCH','Execution scope differs')
        self.registry.validate('map-plan',plan)
        preparation=RasterPreparationService(project_root=self.project_root,allowed_roots=list(self.path_guard.allowed_roots),registry=self.registry)
        prepared=BundlePreparer(preparation, "raster").prepare_request(request,context)
        from ..workflow.map_data_preparation import bundle_core
        if bundle_core(bundle)!=bundle_core(prepared['bundle']):raise ProtocolError('RASTER_CANDIDATE_BUNDLE_MISMATCH','Bundle differs from exact inputs')
        profile=ScenarioRegistry(self.registry).for_template(request['template']);output=profile.definition['output_profile']
        if any(b['crs']!=contracts['spatial_behavior']['display_crs'] for b in bundle['role_bindings']):
            raise ProtocolError('RASTER_DISPLAY_CRS_MISMATCH','No implicit reprojection')
        resolved=LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'],output['dpi'],parameters=request['layout_parameters'])
        sources=index_by(bundle['role_bindings'],'source_id');panels=index_by(request['panels'],'id');refs={}
        for sid,b in sources.items():
            refs[sid]=RasterPortrayalCompiler(preparation).compile(deepcopy(contracts['portrayal']),LAYER_ID,b['prepared_ref'],context).ref()
        font_bytes=preparation.read_bytes(Path(font_path),FONT_LIMIT)
        texts=[{'content_id':'title','text':request['map_title']},{'content_id':'source','text':profile.notice}]
        if len(panels)>1:
            for vid,panel in sorted(panels.items()):texts.append({'content_id':vid.replace('view-','caption-',1),'text':panel['title']})
        raw={'schema_version':4,'portrayals':[{'view_id':vid,'ref':refs[panel['source_id']]} for vid,panel in sorted(panels.items())],
             'resolved_layout':resolved,'font':{'path':str(font_path),'digest':preparation.digest_bytes(font_bytes),'size_bytes':len(font_bytes)},
             'texts':texts,'legends':[{'content_id':f['content_id'],'title':resolved['contract'].get('legend_title',LEGEND_TITLE)} for f in resolved['frames'] if f['type']=='legend'],
             'scale_bar':None,'grid_north':None}
        page=compile_page_request(preparation,raw,contracts['scenario']['embedded']['cartography'],context,BundlePreparer)
        stats=[{'source_id':b['source_id'],'counts':b['category_counts']} for b in bundle['role_bindings']]
        if (plan['bindings']!=page['bindings'] or plan['layout_parameters']!=request['layout_parameters']
            or plan['decisions']['thematic_views'] != raster_views(request,bundle,self.registry)
            or plan['decisions']['title'] != request['map_title']
            or plan['decisions']['legend_capacity']!=resolved['contract']['capacity']['legend_items']):
            raise ProtocolError('PLAN_BINDING_MISMATCH','Plan differs from verified template and data')
        compiler=RasterSceneCompiler(preparation,BundlePreparer)
        scene=compiler.compile(bundle_ref=prepared['bundle_ref'],page_request=page,context=context,scene_id=f"scene-{request['run_id']}",targets=tuple(sorted(request['requested_outputs'])))
        base=self._execution_base(intent,installation,bundle,profile,contracts)
        base['thematic_plan_ref']=artifact_ref('map-plan',plan)
        execution=compiler.bind_execution(base,scene,context)
        candidate={'schema_version':1,'candidate_id':f"candidate-{request['run_id']}",'project_id':request['project_id'],'run_id':request['run_id'],
                   'execution_digest':sha256_digest(execution),'execution':execution,'open_issues':[],'created_at':request['requested_at']}
        return {'candidate':candidate,'scene':scene}

    def _execution_base(self, intent: dict[str, Any], installation: dict[str, Any],
                        bundle: dict[str, Any], profile: Any, contracts: dict[str, Any]) -> dict[str, Any]:
        return {
            "intent_ref": {"id": "map-intent", "version": "1.0.0", "digest": sha256_digest(intent)},
            "profile_refs": [deepcopy(intent["evidence_refs"][0]), deepcopy(intent["evidence_refs"][-1])],
            "business_scene": intent["business_scene"],
            "map_tasks": list(intent["tasks"]),
            "template_refs": [deepcopy(installation["template_ref"])],
            "dependency_refs": [deepcopy(contracts['portrayal']['layers'][0]['map_expression_ref'])],
            "policy_refs": [profile.ref],
            "ownership": {"scenario": "map-scenario"},
            "shared_semantics": {"theme_tags": list(intent["theme_tags"]),
                                 "data_nature": bundle["summary"]["data_nature"]},
            "material_facts_refs": [deepcopy(bundle["data_facts"])] if bundle.get("data_facts") else [],
        }


def legend_checker(context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
    """Business semantics of the frozen legend: unambiguous, complete, ordered."""
    raster=context.get('raster')
    if not isinstance(raster,dict) or 'page' not in raster:
        raise ProtocolError('RASTER_EXECUTION_CONTEXT_REQUIRED','Verified page context required')
    results=[_check_legend_items(legend['items']) for legend in raster['page']['legends']]
    return all(ok for ok,_ in results), {'legend_item_count':sum(d['legend_item_count'] for _,d in results), 'problems':sorted({p for _,d in results for p in d['problems']}), 'legends':[details for _,details in results]}, None


def _check_legend_items(items):
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
    return not problems, details


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


# --------------------------------------------------------------------------
# Template contract declarations: one geometry-free source for both authors
# --------------------------------------------------------------------------
# ADR-001 §9.5 项②: business semantics, layout and expression declarations are
# single-sourced here. The raster and vector authors differ only through the
# explicit geometry-adaptation parameters (version, data_role, geometry_types,
# fields, portrayal layer, delivery composition, quality-gate set), so neither
# author inherits the other's payloads. Key order is part of the package digest
# — ``staging_package._serialize`` dumps YAML with ``sort_keys=False`` — and is
# therefore frozen here for both geometries.

GATE_PROTOCOL = {"id": "protocol.schema-valid", "version": "1.0.0", "params": {}}
GATE_LEGEND = {"id": "cartography.legend-consistency", "version": "1.0.0", "params": {}}
GATE_RASTER_CLASSIFICATION = {"id": "raster.classification-clarified", "version": "1.0.0",
                              "params": {}}
RASTER_DATA_FIELDS = (
    {"name": "category_value", "type": "integer", "nullable": False,
     "semantic_role": "category-value"},
    {"name": "category_label", "type": "string", "nullable": True,
     "semantic_role": "category-label"},
)
RASTER_LIMITATIONS = (
    "样张渲染使用合成栅格与固定调色板，仅验证模板协议、渲染链路与版式，不代表真实业务数据。",
)
# Scale-band identity is part of the authored contract, so each geometry names its own
# band instead of the vector template inheriting a raster-flavoured identifier.
RASTER_SCALE_BAND_ID = "native-raster"


def package_identity(version: str = VERSION) -> dict[str, Any]:
    """Package identity shared by both geometries; only the version differs."""
    return {"namespace": NAMESPACE, "kind": KIND, "id": SCENARIO_ID, "version": version}


def require_admitted(request: dict[str, Any], brief: dict[str, Any], *,
                     version: str = VERSION, profile: str = AUTHORING_PROFILE) -> None:
    """Four fail-closed authoring gates: identity, targets, preserve-CRS, brief."""
    if (request.get("kind") != KIND or request.get("namespace") != NAMESPACE
            or request.get("template_id") != SCENARIO_ID or request.get("version") != version
            or request.get("profile") != profile):
        raise ProtocolError("CAPABILITY_NOT_AVAILABLE",
                            "Only the registered authoring profile may use this author")
    if sorted(request.get("targets", [])) != ["pdf", "png"]:
        raise ProtocolError("RENDER_TARGET_UNSUPPORTED", "Admitted targets are exactly pdf and png")
    if request["source_crs"] != request["display_crs"]:
        raise ProtocolError("SOURCE_CRS_UNSUPPORTED",
                            "The preserve policy requires display_crs to equal source_crs")
    if (brief.get("kind") != KIND or brief.get("namespace") != NAMESPACE
            or brief.get("template_id") != SCENARIO_ID or brief.get("version") != version):
        raise ProtocolError("TEMPLATE_BRIEF_MISMATCH", "Brief does not describe this template")


def identity_contract(*, version: str = VERSION) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "identity_id": IDENTITY_ID,
        "version": version,
        "organization": ORGANIZATION,
        "colors": [{
            "role": "primary",
            "hex": "#1F4E79",
            "provenance": {"source_type": "internal",
                           "source_ref": f"template:{SCENARIO_ID}@{version}",
                           "classification": "internal"},
        }],
        "typography": [{"role": "title", "family": FONT_FAMILY, "weight": 700},
                       {"role": "body", "family": FONT_FAMILY, "weight": 400}],
        "attribution": {"organization_format": "制图：{organization}",
                        "data_source_format": "数据来源：{source}"},
        "rules": [],
    }


def cartography_contract(*, version: str = VERSION) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "style_id": STYLE_ID,
        "version": version,
        "visual_language": "technical",
        "symbolization": {"color_system": "qualitative",
                          "symbol_catalogs": ["ramps/categorical-raster@1.0.0"],
                          "default_opacity": 1.0},
        "labeling": {"density": "low", "collision_policy": "avoid", "font_role": "body"},
        "generalization": {"scale_dependent": False, "strategy": "none"},
        "defaults": {"opacity": 1.0},
        "typography": {"title_pt": 18, "body_pt": 9, "legend_pt": 10,
                       "legend_heading_pt": 11, "line_spacing": 1.25},
        "rules": [],
    }


def layout_contract(*, version: str = VERSION) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "layout_id": LAYOUT_ID,
        "version": version,
        "content_padding_mm": 2,
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
        "grid": {"allowed_shapes": [[1,1],[1,2],[2,2]], "legend_modes": ["independent","shared"],
                 "panel_area": [10,27,277,160], "shared_panel_area": [10,27,277,126],
                 "shared_legend_bounds": [10,159,277,30], "source_bounds": [10,190,277,10],
                 "column_gap_mm": 8, "row_gap_mm": 8, "caption_height_mm": 9, "caption_gap_mm": 2,
                 "legend_width_mm": 41, "legend_gap_mm": 3, "shared_legend_columns": 4},
        "capacity": {"legend_items": 12, "title_characters": 60},
        "rules": [],
    }


def scenario_contract(request: dict[str, Any], *, version: str = VERSION,
                      data_role: str = DATA_ROLE) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scenario_id": SCENARIO_ID,
        "version": version,
        "business_scene": BUSINESS_SCENE,
        "tasks": [TASK],
        "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal",
                           "delivery", "quality-gates"],
        "embedded": {"identity": identity_contract(version=version),
                     "cartography": cartography_contract(version=version),
                     "layout": layout_contract(version=version)},
        "replaceable_segments": [],
        "data_role_refs": [data_role],
        "target_ids": list(TARGET_IDS),
        "application": {"supported_uses": sorted(request["supported_uses"]),
                        "excluded_uses": sorted(request["excluded_uses"])},
        "compatibility": {"target_profiles": [LAYOUT_ID],
                          "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"]},
        "rules": [],
    }


def data_schema_contract(*, data_role: str = DATA_ROLE, geometry_types=("raster",),
                         fields=RASTER_DATA_FIELDS) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "roles": [{
            "id": data_role,
            "required": True,
            "geometry_types": list(geometry_types),
            "fields": [deepcopy(field) for field in fields],
            "license_policy": "project-approved",
        }],
    }


def spatial_behavior_contract(request: dict[str, Any], *,
                              scale_band_id: str = RASTER_SCALE_BAND_ID) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_crs_policy": "preserve",
        "display_crs": deepcopy(request["display_crs"]),
        "extent_policy": "data",
        "scale_bands": [{"id": scale_band_id, "min_denominator": 1,
                         "max_denominator": 100000000, "generalization": "none"}],
        "topology": {"preserve_adjacency": True, "preserve_route_order": False},
        "rules": [],
    }


def raster_portrayal_contract(registry: SchemaRegistry) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "layers": [{
            "id": LAYER_ID,
            "data_role": DATA_ROLE,
            "geometry": "raster",
            "z_order": 10,
            "map_expression_ref": _catalog_reference(registry),
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


def delivery_contract(*, composition: str = "raster-map-vector-overlay",
                      vector_claim: str = "overlay-only") -> dict[str, Any]:
    page = {"width_mm": 297, "height_mm": 210, "orientation": "landscape",
            "dpi": 300, "safe_margin_mm": 10}
    return {
        "schema_version": 1,
        "targets": [
            {"id": TARGET_IDS[0], "delivery_class": "engineering-preview", "format": "pdf",
             "composition": composition, "vector_claim": vector_claim,
             "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
             "production_ready": False},
            {"id": TARGET_IDS[1], "delivery_class": "engineering-preview", "format": "png",
             "composition": "flattened-raster", "vector_claim": "none",
             "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
             "production_ready": False},
        ],
        "rules": [],
    }


def quality_gates_contract(*, version: str = VERSION, checks=None,
                           baseline_digest: str | None = None) -> dict[str, Any]:
    if checks is None:
        checks = (GATE_PROTOCOL, GATE_LEGEND, GATE_RASTER_CLASSIFICATION)
    if baseline_digest is None:
        baseline_digest = sha256_digest({"scenario_id": SCENARIO_ID, "version": version,
                                         "business_scene": BUSINESS_SCENE})
    return {
        "schema_version": 1,
        "baseline": {"id": BASELINE_ID, "version": version, "digest": baseline_digest},
        "checks": [deepcopy(check) for check in checks],
    }


def fixture_csv(header=FIXTURE_HEADER, rows=FIXTURE_ROWS) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def prototype_contract(*, prototype_id: str, layout_id: str, layer_ids, limitations,
                       fixture_ref: str = FIXTURE_PATH) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "prototype_id": prototype_id,
        "status": "pending-validation",
        "render_required": True,
        "renderer_execution": "not-run",
        "layout_id": layout_id,
        "target_ids": list(TARGET_IDS),
        "layer_ids": list(layer_ids),
        "fixture_ref": fixture_ref,
        "limitations": list(limitations),
    }


def dependency_lock(identity: dict[str, Any], request: dict[str, Any],
                    registry: SchemaRegistry, *, lock_id: str = LOCK_ID,
                    resources=None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "lock_id": lock_id,
        "package": {**identity, "digest": sha256_digest(identity)},
        "dependencies": [],
        "resources": [_catalog_reference(registry)] if resources is None else list(resources),
        "resolver_version": "1.0.0",
        "generated_at": request["requested_at"],
    }


def package_manifest(identity: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package": {**identity, "status": "draft", "summary": request["purpose"][:500]},
        "business_contracts": dict(DependencyResolver.MAP_SCENARIO_CONTRACTS),
        "dependencies": [],
        "dependency_lock": "dependencies.lock.yaml",
        "targets": sorted(request["targets"]),
    }


def author_context(path_guard: PathGuard, work_root: Path,
                   registry: SchemaRegistry | None = None) -> tuple[PathGuard, Path, SchemaRegistry]:
    """Resolve the trusted work root once; shared by both geometry authors."""
    return path_guard, path_guard.resolve(work_root, must_exist=True), registry or SchemaRegistry()


def write_package(path_guard: PathGuard, work_root: Path, registry: SchemaRegistry,
                  manifest: dict[str, Any], documents: dict[str, Any]) -> dict[str, str]:
    return StagingPackageWriter(path_guard, work_root, registry).write(manifest, documents)


def verify_package(path_guard: PathGuard, work_root: Path, registry: SchemaRegistry,
                   manifest: dict[str, Any], documents: dict[str, Any]) -> dict[str, str]:
    return StagingPackageWriter(path_guard, work_root, registry).verify_existing(
        manifest, documents)


class GeneralThematicAuthor:
    """Deterministically author the closed staging package for this scenario.

    Every declaration comes from the geometry-free ``*_contract`` functions above;
    this class only pins the raster geometry-adaptation parameters.
    """

    def __init__(self, path_guard: PathGuard, work_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard, self.work_root, self.registry = author_context(
            path_guard, work_root, registry)

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._payloads(request, brief)
        return write_package(self.path_guard, self.work_root, self.registry,
                             manifest_base, documents)

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._payloads(request, brief)
        return verify_package(self.path_guard, self.work_root, self.registry,
                              manifest_base, documents)

    def _payloads(self, request: dict[str, Any], brief: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        require_admitted(request, brief)
        identity = package_identity()
        documents = {
            "contracts/scenario.yaml": scenario_contract(request),
            "contracts/data.schema.yaml": data_schema_contract(),
            "contracts/spatial-behavior.yaml": spatial_behavior_contract(request),
            "contracts/portrayal.yaml": raster_portrayal_contract(self.registry),
            "contracts/delivery.yaml": delivery_contract(),
            "contracts/quality-gates.yaml": quality_gates_contract(),
            "dependencies.lock.yaml": dependency_lock(identity, request, self.registry),
            "prototypes/general-thematic.yaml": prototype_contract(
                prototype_id=PROTOTYPE_ID, layout_id=LAYOUT_ID, layer_ids=(LAYER_ID,),
                limitations=RASTER_LIMITATIONS),
            FIXTURE_PATH: fixture_csv(),
        }
        return package_manifest(identity, request), documents


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
    _fixture_rows(package_root, snapshot)


def _fixture_rows(package_root: Path, snapshot: dict[str, Any]) -> list[tuple[int, str]]:
    """Parse the single packaged legend sample into bounded (code, label) rows."""
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
    rows: list[tuple[int, str]] = []
    seen: set[int] = set()
    for record in reader:
        if len(rows) >= MAX_CLASSES or None in record or any(value is None for value in record.values()):
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
        rows.append((int(code), label))
    if not rows:
        raise ProtocolError("CLASSIFICATION_CSV_EMPTY", fixture_paths[0])
    return rows


def _fixture_dtype(codes: list[int]) -> str:
    for dtype, low, high in (("uint8", 0, 255), ("int16", -32768, 32767),
                             ("uint16", 0, 65535), ("int32", -2147483648, 2147483647)):
        if all(low <= code <= high for code in codes):
            return dtype
    return "uint32"


def _raster_info(dataset: Any) -> dict[str, Any]:
    """Measure the wire metadata of the synthetic fixture raster; nothing is hardcoded."""
    crs = dataset.crs
    transform = dataset.transform
    pixel = [abs(float(transform.a)), abs(float(transform.e))]
    if crs is None:
        crs_text, crs_type, units, meters = None, "undefined", [], None
    elif crs.is_projected:
        unit, factor = crs.linear_units_factor
        epsg = crs.to_epsg()
        crs_text = f"EPSG:{epsg}" if epsg is not None else crs.to_string()
        crs_type, units = "projected", [unit, unit]
        meters = [pixel[0] * float(factor), pixel[1] * float(factor)]
    elif crs.is_geographic:
        epsg = crs.to_epsg()
        crs_text = f"EPSG:{epsg}" if epsg is not None else crs.to_string()
        crs_type, units, meters = "geographic", ["degree", "degree"], None
    else:
        crs_type, units, meters = "other", [], None
        crs_text = crs.to_string()
    bounds = dataset.bounds
    return {
        "kind": "raster", "driver": dataset.driver,
        "width": int(dataset.width), "height": int(dataset.height),
        "band_count": int(dataset.count),
        "crs": crs_text, "crs_type": crs_type, "coordinate_units": units,
        "bounds": [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)],
        "transform": [float(transform.a), float(transform.b), float(transform.c),
                      float(transform.d), float(transform.e), float(transform.f)],
        "pixel_size": pixel, "pixel_size_meters": meters,
        "bands": [{"band": int(band), "dtype": dataset.dtypes[index],
                   "nodata": dataset.nodata, "description": dataset.descriptions[index],
                   "unit": dataset.units[index]}
                  for index, band in enumerate(dataset.indexes)],
        "warnings": [],
    }


def _fixture_gateway(preparation: RasterPreparationService, workspace: Path) -> SimpleNamespace:
    """Local in-process capability binding that measures the synthetic fixture raster.

    Statistics still flow through the authorized MCP gateway contract with typed
    input/output schemas and immutable evidence; no second GIS reader is admitted
    and no evidence value is hardcoded.
    """
    policy_path = Path(__file__).resolve().parents[3] / "policies/tool-bindings.yaml"
    config_digest = "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest()
    store = ImmutableArtifactStore(workspace / ".carto/geospatial/evidence", path_guard=PathGuard([workspace]))
    gateway = ToolGateway(policy_path, store, preparation.registry)

    def statistics(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        import numpy as np
        import rasterio
        source = request["source"]
        path = preparation.guard.resolve(source["path"], base_root=preparation.project, must_exist=True)
        try:
            with rasterio.open(path) as dataset:
                data = dataset.read(1, masked=True)
                info = _raster_info(dataset)
        except ProtocolError:
            raise
        except Exception as exc:
            raise ProtocolError("RASTER_FIXTURE_PROFILE_UNSUPPORTED",
                                "Synthetic fixture raster could not be measured") from exc
        total = int(data.size)
        dtype = info["bands"][0]["dtype"]
        if dtype in ("float32", "float64"):
            # ADR-001 阶段2.3：float 栅格 → continuous 统计（min/max/mean/stddev + histogram）。
            valid_arr = data.compressed().astype("float64")
            valid = int(valid_arr.size)
            vmin, vmax = float(valid_arr.min()), float(valid_arr.max())
            bucket_count = max(1, min(256, valid))
            hist = np.histogram(valid_arr, bins=bucket_count, range=(vmin, vmax))[0]
            statistic = {"total_pixels": total, "valid_pixels": valid, "masked_pixels": total - valid,
                         "continuous": {"min": vmin, "max": vmax, "mean": float(valid_arr.mean()),
                                        "stddev": float(valid_arr.std()),
                                        "histogram": {"min": vmin, "max": vmax, "bucket_count": bucket_count,
                                                      "counts": [int(c) for c in hist]}}}
        else:
            values, counts = np.unique(data.compressed(), return_counts=True)
            valid = int(data.count())
            statistic = {"total_pixels": total, "valid_pixels": valid, "masked_pixels": total - valid,
                         "classes": [{"value": int(value), "count": int(count)}
                                     for value, count in zip(values, counts)]}
        return {
            "schema_version": 1, "operation": "statistics",
            "source_ref": deepcopy(source["source_ref"]),
            "dataset_id": source["dataset_id"], "source_size_bytes": source["size_bytes"],
            "server": {"id": "geospatial-mcp", "version": "0.3.0",
                       "config_digest": config_digest,
                       "catalog_digest": sha256_digest({"dataset_id": source["dataset_id"],
                                                        "kind": "raster", "path": source["path"]}),
                       "tool_catalog_digest": sha256_digest({"capability": "gis-raster-statistics",
                                                             "operation": "statistics"})},
            "raster_info": info,
            "statistics": statistic,
            "warnings": [],
        }

    gateway.register("gis-raster-statistics", statistics,
                     input_schema="geospatial-request", output_schema="geospatial-result")
    return SimpleNamespace(make_gateway=lambda: gateway)


def validation_scene(package_root: Path, snapshot: dict[str, Any], targets: list[str],
                     font: Path, validator_version: str, *,
                     context: ExecutionContext | None = None,
                     workspace: Path | None = None,
                     registry: SchemaRegistry | None = None, layout_parameters=None) -> dict[str, Any]:
    """Freeze the deterministic synthetic raster scene for controlled fixture rendering.

    The fixture raster derives only from the packaged synthetic legend sample and
    the frozen package contracts; its statistics are measured through the
    authorized gateway and the frozen page/scene can be re-verified at publish
    time without the authoring host's font. No business data, no production
    claim, no fabricated evidence.
    """
    from ..adapters.static_page_renderer import FONT_LIMIT
    if context is None or workspace is None:
        raise SecurityError("RASTER_EXECUTION_CONTEXT_REQUIRED",
                            "Fixture rendering requires the trusted validation context and workspace")
    try:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
    except ImportError:
        raise ProtocolError("RASTER_RENDER_DEPENDENCY_MISSING",
                            "The raster fixture render branch requires the raster-rendering extra") from None
    context.require_project_scope()
    registry = registry or SchemaRegistry()
    documents = snapshot.get("documents")
    if (not isinstance(documents, dict)
            or not {"scenario", "spatial_behavior", "portrayal"} <= set(documents)):
        raise ProtocolError("CAPABILITY_NOT_AVAILABLE",
                            "Static validation must pass before fixture rendering")
    if sorted(targets) != ["pdf", "png"]:
        raise ProtocolError("RENDER_TARGET_UNSUPPORTED", "The raster fixture render requires exactly pdf and png")
    manifest = snapshot["manifest"]
    rows = _fixture_rows(package_root, snapshot)
    codes = [row[0] for row in rows]
    profile = ScenarioRegistry(registry).for_template(manifest["package"])
    display_crs = documents["spatial_behavior"]["display_crs"]

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    raster_path = workspace / FIXTURE_TIFF
    legend_path = workspace / FIXTURE_LEGEND
    dtype = _fixture_dtype(codes)
    pattern = np.add.outer(np.arange(FIXTURE_SIZE), np.arange(FIXTURE_SIZE)) % len(codes)
    fixture = np.asarray(codes, dtype=getattr(np, dtype))[pattern]
    try:
        with rasterio.open(
            raster_path, "w", driver="GTiff", width=FIXTURE_SIZE, height=FIXTURE_SIZE, count=1,
            dtype=dtype, crs="EPSG:" + str(display_crs["code"]),
            transform=from_origin(FIXTURE_ORIGIN_X, FIXTURE_ORIGIN_Y, FIXTURE_PIXEL, FIXTURE_PIXEL),
        ) as dataset:
            dataset.write(fixture, 1)
    except Exception as exc:
        raise ProtocolError("RASTER_FIXTURE_PROFILE_UNSUPPORTED",
                            "The template display CRS cannot back a synthetic fixture raster") from exc
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["value", "label"])
    writer.writerows([[code, label] for code, label in rows])
    legend_path.write_bytes(buffer.getvalue().encode("utf-8-sig"))

    font = Path(font)
    preparation = RasterPreparationService(
        project_root=workspace, allowed_roots=[str(workspace), str(font.parent)], registry=registry)
    tiff_bytes = preparation.read_bytes(raster_path, 268435456)
    legend_bytes = preparation.read_bytes(legend_path, 1048576)
    request = {
        "schema_version": 1,
        "source": {
            "schema_version": 1, "role": DATA_ROLE,
            "source_ref": {"id": FIXTURE_SOURCE_ID, "version": "1.0.0",
                           "digest": preparation.digest_bytes(tiff_bytes)},
            "path": FIXTURE_TIFF, "format": "geotiff", "dataset_id": FIXTURE_DATASET_ID,
            "size_bytes": len(tiff_bytes), "crs": deepcopy(display_crs), "band": 1,
            "value_semantics": "categorical-integer", "mask_policy": "embedded",
            "license": "project-approved", "data_nature": "synthetic",
            "contains_sensitive_coordinates": False,
        },
        "legend": {"path": FIXTURE_LEGEND, "digest": preparation.digest_bytes(legend_bytes),
                   "size_bytes": len(legend_bytes), "encoding": "utf-8-sig",
                   "value_column": "value", "label_column": "label", "color_column": None},
        "palette": "carto-categorical-v1", "legend_policy": "observed",
    }
    prepared = preparation.analyze(request, context, _fixture_gateway(preparation, workspace))
    report, _ = preparation.load_verified(prepared.ref())
    if report["status"] != "ready":
        raise ProtocolError("CLASSIFICATION_CLARIFICATION_REQUIRED",
                            "Fixture categories did not resolve into a ready classification")

    bundle = BundlePreparer(preparation, "raster").build(prepared.ref(), context)
    bundle_ref = preparation.save_document(bundle, "prepared-data-bundle").ref()
    portrayal_ref = RasterPortrayalCompiler(preparation).compile(
        deepcopy(documents["portrayal"]), LAYER_ID, prepared.ref(), context).ref()
    resolved_portrayal = preparation.document(portrayal_ref, "resolved-portrayal")
    legend = resolved_portrayal["legend_items"]
    scenario = documents["scenario"]
    limit = int(scenario["embedded"]["layout"]["capacity"]["legend_items"])
    if not legend or len(legend) > limit:
        raise ProtocolError("RASTER_LEGEND_CAPACITY",
                            "Legend must be nonempty and fit the layout capacity")
    output = profile.definition["output_profile"]
    resolved_layout = LayoutResolver(registry).resolve(
        scenario["embedded"]["layout"], output["dpi"], parameters=layout_parameters or {"rows":1,"columns":1,"legend_mode":"independent"})
    if any(resolved_layout["page"][key] != output[key]
           for key in ("width_mm", "height_mm", "dpi", "width_px", "height_px")):
        raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                            "Layout differs from the enabled output profile")
    font_bytes = preparation.read_bytes(font, FONT_LIMIT)
    page_request = {
        "schema_version": 4,
        "portrayals": [{"view_id":f["content_id"], "ref":deepcopy(portrayal_ref)} for f in resolved_layout["frames"] if f["type"]=="map"],
        "resolved_layout": deepcopy(resolved_layout),
        "font": {"path": str(font), "digest": preparation.digest_bytes(font_bytes),
                 "size_bytes": len(font_bytes)},
        "texts": [
            {"content_id": "title", "text": VALIDATION_TITLE},
            {"content_id": "source", "text": profile.notice},
        ],
        "legends": [{"content_id":f["content_id"], "title":scenario["embedded"]["layout"].get("legend_title", LEGEND_TITLE)} for f in resolved_layout["frames"] if f["type"]=="legend"],
        "scale_bar": None,
        "grid_north": None,
    }
    for frame in resolved_layout['frames']:
        if frame['content_id'].startswith('caption-'):
            page_request['texts'].append({'content_id':frame['content_id'],'text':'Panel '+frame['content_id'].removeprefix('caption-')})
    page_request = compile_page_request(preparation, page_request, scenario["embedded"]["cartography"], context, BundlePreparer)
    scene_id = "validation-scene-" + sha256_digest({
        "package_digest": snapshot["package_digest"],
        "fixture_set_digest": snapshot["fixture_set_digest"],
        "validator_version": validator_version,
        "layout_parameters": resolved_layout["parameters"],
    })[7:23]
    return RasterSceneCompiler(preparation, BundlePreparer).compile(
        bundle_ref=deepcopy(bundle_ref), page_request=page_request, context=context,
        scene_id=scene_id, targets=tuple(sorted(targets)))
