"""General S2 vector adapter; shared layout, rendering and workflow remain reusable.

This implementation is not an admission grant. The registered profile/strict
request overlays and normal T1/TP/G1/G2/G3 gates are still required.
"""
from copy import deepcopy
import json
from pathlib import Path
from ..canonical import sha256_digest
from ..artifacts import artifact_ref, file_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..scenario_registry import ScenarioRegistry
from ..compiler.layout import LayoutResolver
from ..compiler.page_bindings import index_by, validate_bindings
from ..compiler.vector_portrayal import VectorPortrayalCompiler
from ..compiler.portrayal_resolver import ir_to_kind
from ..compiler.vector_page import compile_page
from ..compiler.vector_scene import VectorSceneCompiler, RENDERER_ID
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..workflow.vector_preparation import VectorPreparationService
from ..workflow.preparation_bundle import BundlePreparer
from ..workflow.models import ExecutionContext
from .general_thematic import (
    FIXTURE_PATH, GATE_LEGEND, GATE_PROTOCOL, LAYOUT_ID, author_context,
    data_schema_contract, delivery_contract, dependency_lock, fixture_csv,
    package_identity, package_manifest, prototype_contract, quality_gates_contract,
    require_admitted, scenario_contract, spatial_behavior_contract, verify_package,
    write_package,
)

VERSION = '4.0.0'
ROLE = 'thematic-features'
AUTHORING_PROFILE = 'general-vector-authoring'
LAYER_ID = 'vector-layer'
LOCK_ID = 'general-vector-lock'
PROTOTYPE_ID = 'general-vector-prototype'
PROTOTYPE_PATH = 'prototypes/general-vector.yaml'
LIMITATIONS = ('Synthetic vector validation only; not user data or production approval.',)
SCALE_BAND_ID = 'native-vector'
EXPRESSION_KINDS = ('categorical', 'choropleth', 'proportional')
class GeneralVectorSourceContract:
    """Source contract for vector geometry; standalone (no longer a subclass of GeneralThematicSourceContract).

    The two formerly inherited methods are copied inline with vector-appropriate
    semantics.  validate_role_bindings checks that the legend-sample CSV used for
    template authoring is present and well-formed, same as the raster path.
    """
    REQUIRED_FIELDS = frozenset(("category_value", "category_label"))

    def suggestions(self, profile_definition):
        return [{"path": "/portrayal/map-expressions", "value_origin": "system_suggestion",
                 "value": ["categorical@2.0.0", "graduated-color@2.0.0", "proportional-symbol@2.0.0"], "rationale": "Explicit vector encodings; project values and units are never inferred."}]

    def brief_roles(self, request):
        return [{"role_id": ROLE, "source_id": request["role_bindings"]["thematic_features"],
                 "geometry_types": ["none"], "value_field": "category_value", "semantic_role": "thematic-value"}]

    def validate_source_profile(self, source, request):
        """Validate a template-authoring source profile (legend sample CSV)."""
        from ..errors import SecurityError  # noqa: F811  — re-import for standalone use
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

    def validate_role_bindings(self, request, summaries):
        """Validate that exactly one thematic_features role is bound to a CSV source."""
        bindings = request.get("role_bindings", {})
        if set(bindings) != {"thematic_features"}:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED",
                                "Exactly one thematic_features role binding is admitted")
        if len(summaries) != 1:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED", "Exactly one legend-sample source is admitted")
        summary = summaries[0]
        if bindings["thematic_features"] != summary["source_id"]:
            raise ProtocolError("ROLE_BINDING_SOURCE_MISMATCH", summary["source_id"])
        if summary["kind"] != "csv":
            raise ProtocolError("SOURCE_TYPE_UNSUPPORTED", summary["source_id"])
        missing = sorted(self.REQUIRED_FIELDS - set(summary["field_names"]))
        if missing:
            raise ProtocolError("ROLE_BINDING_FIELD_MISSING", ",".join(missing))

SOURCE_CONTRACT = GeneralVectorSourceContract()


def expression_ref(registry):return MapExpressionCatalog(registry).reference('categorical', '2.0.0')


def make_bindings(request, layout, bundle, contracts, registry):
    from ..workflow.thematic import expression_reference
    sources = index_by(bundle['role_bindings'], 'source_id')
    panels = index_by(request['vector_panels'], 'id')
    maps = {f['content_id']: f for f in layout['contract']['frames'] if f['type'] == 'map'}
    if set(maps) != set(panels) or {p['source_id'] for p in panels.values()} != set(sources):
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Exact source/view/frame assignments required')
    layers = [{'id': 'layer-' + vid, 'data_binding_id': panel['source_id'],
                'expression_ref': expression_reference(ir_to_kind(panel['encoding']),registry)}
              for vid, panel in sorted(panels.items())]
    legends = []
    for frame in layout['contract']['frames']:
        if frame['type'] == 'legend':
            served = frame.get('view_ids', list(maps) if len(maps) == 1 else [])
            legends.append({'id': frame['content_id'], 'frame_id': frame['id'], 'view_ids': sorted(served),
                            'layer_ids': ['layer-' + vid for vid in sorted(served)]})
    result = {'schema_version': 2,
        'data_bindings': [{'id': sid, 'source_id': sid, 'role': b['role'], 'dataset_ref': b['dataset_ref'], 'prepared_ref': b['prepared_ref']} for sid, b in sorted(sources.items())],
        'layers': layers,
        'views': [{'id': vid, 'extent': p['extent'], 'crs': sources[p['source_id']]['crs'], 'layer_ids': ['layer-' + vid]} for vid, p in sorted(panels.items())],
        'panels': [{'id': maps[vid]['id'], 'view_id': vid, 'frame_id': maps[vid]['id']} for vid in sorted(panels)],
        'legends': legends,
        'elements': [{'id': f['content_id'], 'frame_id': f['id'], 'kind': f['type'], 'view_id': None} for f in layout['contract']['frames'] if f['type'] not in {'map', 'legend'}],
        'sharing': {'view_groups': [], 'legend_groups': [], 'encoding_groups': [{'id': 'shared-encoding', 'members': [l['id'] for l in layers]}] if len(legends) == 1 and len(panels) > 1 else []}}
    return validate_bindings(result, registry, executable=True)


class GeneralVectorDataPreparer:
    def __init__(self, path_guard, project_root, output_root, registry=None):
        self.service = VectorPreparationService(project_root=project_root, allowed_roots=list(path_guard.allowed_roots), registry=registry)

    def prepare(self, request, request_ref):
        if request_ref['digest'] != sha256_digest(request):raise ProtocolError('VECTOR_REQUEST_CHANGED', 'Request digest differs')
        result = BundlePreparer(self.service, "vector").prepare_request(request, ExecutionContext.from_generate_request(request))
        return {**result, 'request_ref': request_ref}


class GeneralVectorPlanner:
    def __init__(self, registry=None, *, project_root=None):
        self.registry = registry or SchemaRegistry()
        self.project_root = project_root

    def build(self, request, intent, brief, bundle, installation, contracts):
        from ..workflow.thematic import vector_views
        # Preparation refs are immutable and identify the approved project root.
        from ..security.paths import PathGuard
        project = self.project_root
        if project is None:
            raise ProtocolError('THEMATIC_CONTEXT_REQUIRED', 'Planner needs trusted project context')
        service=VectorPreparationService(project_root=project,allowed_roots=[str(project)],registry=self.registry)
        context=ExecutionContext.from_generate_request(request)
        views=vector_views(request,bundle,service,context)
        profile=ScenarioRegistry(self.registry).for_template(request['template'])
        layout=LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'],profile.definition['output_profile']['dpi'],parameters=request['layout_parameters'])
        proxy=deepcopy(request)
        encodings={v['view_id']:v['encoding'] for v in views}
        for p in proxy['vector_panels']:p['encoding']=encodings[p['id']]
        return {'schema_version':4,'plan_id':'plan-'+request['run_id'],'revision':brief['revision'],'project_id':request['project_id'],
                'intent_ref':artifact_ref('map-intent',intent),'brief_ref':artifact_ref('map-brief',brief),
                'business_scene':intent['business_scene'],'tasks':list(intent['tasks']),'theme_tags':list(intent['theme_tags']),
                'template_refs':[deepcopy(installation['template_ref'])],
                'data_bindings':[{'role':v['role'],'dataset_ref':deepcopy(v['dataset_ref'])} for v in bundle['role_bindings']],
                'decisions':{'title':request['map_title'],'legend_source':'actual-encoding','renderer_id':profile.definition['renderer_id'],
                             'legend_capacity':layout['contract']['capacity']['legend_items'],'thematic_views':views},
                'bindings':make_bindings(proxy,layout,bundle,contracts,self.registry),
                'layout_parameters':deepcopy(request['layout_parameters']),'open_issues':[]}


class GeneralVectorCandidateCompiler:
    def __init__(self, path_guard, registry=None, *, project_root=None, context=None):
        self.guard, self.registry, self.project, self.context = path_guard, registry or SchemaRegistry(), project_root, context

    def compile(self, request, intent, plan, bundle, installation, contracts, font_path):
        profile = ScenarioRegistry(self.registry).for_generate(request)
        context = ExecutionContext.from_generate_request(request)
        if self.context is None or any(getattr(self.context, k) != getattr(context, k) for k in ('run_id', 'project_id', 'tenant_id', 'subject_id')):
            raise ProtocolError('VECTOR_SCOPE_MISMATCH', 'Compiler requires the trusted execution context')
        service = VectorPreparationService(project_root=self.project, allowed_roots=list(self.guard.allowed_roots), registry=self.registry)
        preparer = BundlePreparer(service, "vector")
        preparer.validate_request(request, bundle, context)
        if any(b['crs'] != contracts['spatial_behavior']['display_crs'] for b in bundle['role_bindings']):
            raise ProtocolError('VECTOR_CRS_MISMATCH', 'Native source CRS must match template display CRS')
        from ..workflow.thematic import vector_views
        expected_views=vector_views(request,bundle,service,context)
        if plan['decisions']['thematic_views']!=expected_views:
            raise ProtocolError('THEMATIC_PLAN_DRIFT','Plan differs from the selected data and design')
        allowed=contracts['portrayal']['layers'][0].get('expression_options',[])
        if any(v['expression_ref'] not in allowed for v in expected_views):
            raise ProtocolError('THEMATIC_METHOD_UNSUPPORTED','Template does not support the selected expression')
        encodings={v['view_id']:v['encoding'] for v in expected_views}
        refs = {b['source_id']: b['prepared_ref'] for b in bundle['role_bindings']}
        inputs = [{'view_id': p['id'], 'extent': p['extent'],
                   'portrayal_ref': VectorPortrayalCompiler(service).compile(
                       refs[p['source_id']], encodings[p['id']], context, label_source=p.get('labels')).ref()}
                  for p in sorted(request['vector_panels'], key=lambda p: p['id'])]
        output_dpi = ScenarioRegistry(self.registry).for_template(request['template']).definition['output_profile']['dpi']
        layout = LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'], output_dpi, parameters=request['layout_parameters'])
        font = service.read_bytes(font_path, 32 * 1024 * 1024)
        texts = [{'content_id': 'title', 'text': request['map_title']}, {'content_id': 'source', 'text': profile.notice}]
        if len(inputs) > 1:texts += [{'content_id': p['id'].replace('view-', 'caption-', 1), 'text': p['title']} for p in request['vector_panels']]

        frozen_basemap = None
        declared_basemap = request.get('basemap')
        if declared_basemap is not None:
            # A basemap is a reference resource (font-like admission): digest-bound,
            # never thematic data. CRS must match the template display CRS exactly;
            # reprojection is an explicit data-preparation operation, never implicit.
            if declared_basemap['crs'] != contracts['spatial_behavior']['display_crs']:
                raise ProtocolError('BASEMAP_CRS_MISMATCH', 'Basemap CRS must equal the display CRS; no implicit reprojection')
            image_path = Path(declared_basemap['image']['path'])
            image_bytes = service.read_bytes(image_path, 64 * 1024 * 1024)
            frozen_basemap = {'image': {'path': str(image_path), 'digest': service.digest_bytes(image_bytes),
                                        'size_bytes': len(image_bytes)},
                              'crs': deepcopy(declared_basemap['crs']),
                              'extent': list(declared_basemap['extent'])}
            if declared_basemap.get('style'):
                frozen_basemap['style'] = deepcopy(declared_basemap['style'])
        page = compile_page(service, layout=layout, cartography=contracts['scenario']['embedded']['cartography'],
                            panels=inputs, font={'path': str(font_path), 'digest': service.digest_bytes(font), 'size_bytes': len(font)},
                            texts=texts, legend_titles={f['content_id']: 'Legend' for f in layout['contract']['frames'] if f['type'] == 'legend'}, context=context,
                            charts=request.get('charts'), basemap=frozen_basemap)
        if plan['bindings'] != page['bindings'] or plan['layout_parameters'] != request['layout_parameters'] or plan['decisions']['title'] != request['map_title']:
            raise ProtocolError('VECTOR_PLAN_MISMATCH', 'Plan does not describe the compiled page')
        compiler = VectorSceneCompiler(service, BundlePreparer)
        from ..workflow.map_data_preparation import bundle_core
        # The scene verifies the GIS core; adopted material facts are separately bound
        # into execution and verified by the shared generation workflow.
        scene = compiler.compile(bundle_ref=service.save('prepared-data-bundle', bundle_core(bundle)).ref(), page_request=page, context=context,
                                 scene_id='scene-' + request['run_id'], targets=tuple(request['requested_outputs']))
        base = {'intent_ref': artifact_ref('map-intent', intent), 'profile_refs': [intent['evidence_refs'][0], intent['evidence_refs'][-1]],
                'business_scene': intent['business_scene'], 'map_tasks': intent['tasks'], 'template_refs': [installation['template_ref']],
                'dependency_refs': list({v['expression_ref']['id']:v['expression_ref'] for v in expected_views}.values()), 'policy_refs': [profile.ref], 'ownership': {'scenario': 'map-scenario'},
                'shared_semantics': {'theme_tags': intent['theme_tags'], 'data_nature': bundle['summary']['data_nature']},
                'material_facts_refs': [deepcopy(bundle['data_facts'])] if bundle.get('data_facts') else []}
        base['thematic_plan_ref'] = artifact_ref('map-plan', plan)
        execution = compiler.bind_execution(base, scene, context)
        return {'scene': scene, 'candidate': {'schema_version': 1, 'candidate_id': 'candidate-' + request['run_id'],
                    'project_id': request['project_id'], 'run_id': request['run_id'], 'execution_digest': sha256_digest(execution),
                    'execution': execution, 'open_issues': [], 'created_at': request['requested_at']}}


def legend_checker(context):
    inputs = context.get('vector')
    if inputs is None:raise ProtocolError('VECTOR_CHECK_CONTEXT', 'Verified vector context required')
    valid = all(l['items'] and len({r['label'] for r in l['items']}) == len(l['items']) for l in inputs['page']['legends'])
    return valid, {'panel_count': len(inputs['layers']), 'legend_item_count': sum(len(l['items']) for l in inputs['page']['legends'])}, None


class GeneralVectorAuthor:
    """Author the vector variant of the one general-thematic template contract.

    Standalone since ADR-001 §9.5 项②: every declaration comes from the shared
    geometry-free ``*_contract`` functions in ``general_thematic``; this class only
    pins the vector geometry-adaptation parameters (version, data role, geometry
    types, portrayal layer, delivery composition, quality-gate set) and subjects the
    request to the same four fail-closed authoring gates as the raster author.
    """

    def __init__(self, path_guard, work_root, registry=None):
        self.path_guard, self.work_root, self.registry = author_context(path_guard, work_root, registry)

    def author(self, request, brief):
        manifest_base, documents = self._payloads(request, brief)
        return write_package(self.path_guard, self.work_root, self.registry, manifest_base, documents)

    def verify_existing(self, request, brief):
        manifest_base, documents = self._payloads(request, brief)
        return verify_package(self.path_guard, self.work_root, self.registry, manifest_base, documents)

    def _payloads(self, request, brief):
        require_admitted(request, brief, version=VERSION, profile=AUTHORING_PROFILE)
        self.registry.validate('general-template-create-request', request)
        from ..workflow.thematic import expression_reference
        options=[expression_reference(kind,self.registry) for kind in EXPRESSION_KINDS]
        identity = package_identity(VERSION)
        portrayal = {'schema_version': 1, 'layers': [{'id': LAYER_ID, 'data_role': ROLE, 'geometry': 'vector', 'z_order': 0,
                      'map_expression_ref': expression_ref(self.registry), 'encoding_policy': 'explicit-per-panel', 'expression_options':options, 'validation_expressions': ['single', 'categorical', 'choropleth', 'proportional']}],
                     'legend': {'generated_from_layers': True, 'show_no_data': True, 'overflow_policy': 'reject'}, 'rules': []}
        # No all-vector production claim; text is embedded and the actual vector
        # composition is attested by the renderer, not by changing delivery policy.
        documents = {'contracts/scenario.yaml': scenario_contract(request, version=VERSION, data_role=ROLE),
                     'contracts/data.schema.yaml': data_schema_contract(data_role=ROLE, geometry_types=('point', 'polygon'), fields=()),
                     'contracts/spatial-behavior.yaml': spatial_behavior_contract(request, scale_band_id=SCALE_BAND_ID),
                     'contracts/portrayal.yaml': portrayal,
                     'contracts/delivery.yaml': delivery_contract(composition='vector-map', vector_claim='whole-map'),
                     'contracts/quality-gates.yaml': quality_gates_contract(version=VERSION, checks=(GATE_PROTOCOL, GATE_LEGEND),
                                                                            baseline_digest=sha256_digest(identity)),
                     'dependencies.lock.yaml': dependency_lock(identity, request, self.registry, lock_id=LOCK_ID, resources=options),
                     PROTOTYPE_PATH: prototype_contract(prototype_id=PROTOTYPE_ID, layout_id=LAYOUT_ID,
                                                        layer_ids=(LAYER_ID,), limitations=LIMITATIONS),
                     FIXTURE_PATH: fixture_csv()}
        return package_manifest(identity, request), documents


def validation_scene(package_root, snapshot, targets, font, validator_version, *, context, workspace, registry,
                     layout_parameters=None, validation_expression='single'):
    """Synthetic sample, never a template copy of user geometry or attribute rows."""
    from ..workflow.vector_preparation import dependencies
    from ..compiler.grid_layout import grid_cases
    from ..security.paths import PathGuard
    fiona, _, _, _, _, CRS = dependencies()
    workspace = Path(workspace); workspace.mkdir(parents=True, exist_ok=True)
    docs = snapshot['documents']; template = docs['scenario']
    crs = docs['spatial_behavior']['display_crs']
    if crs['authority'] != 'EPSG':raise ProtocolError('VECTOR_FIXTURE_CRS', 'Validation needs an explicit EPSG CRS')
    name = 'fixture-' + validation_expression
    directory = PathGuard([workspace]).resolve(workspace / name)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'dataset.shp'
    geometry = 'Point' if validation_expression == 'proportional' else 'Polygon'
    with fiona.open(str(path), 'w', driver='ESRI Shapefile', crs=CRS.from_epsg(int(crs['code'])),
                    schema={'geometry': geometry, 'properties': {'value': 'float', 'category': 'int'}}, encoding='UTF-8') as dst:
        for i in range(3):
            coordinates = [float(i), 0.0] if geometry == 'Point' else [[[i, 0], [i + .8, 0], [i + .8, .8], [i, .8], [i, 0]]]
            dst.write({'geometry': {'type': geometry, 'coordinates': coordinates}, 'properties': {'value': float(i + 1), 'category': i + 1}})
    source = {'schema_version': 1, 'source_id': name, 'role': ROLE, 'format': 'shapefile', 'crs': 'EPSG:' + crs['code'],
              'encoding': 'utf-8', 'files': [{'extension': p.suffix, 'path': str(p), 'digest': file_digest(p), 'size_bytes': p.stat().st_size}
                for p in sorted(directory.iterdir()) if p.suffix in {'.shp', '.shx', '.dbf', '.prj', '.cpg'}],
              'data_nature': 'synthetic', 'contains_sensitive_coordinates': False, 'contains_production_data': False, 'license': 'project-approved'}
    service = VectorPreparationService(project_root=workspace, allowed_roots=[str(workspace), str(Path(font).parent)], registry=registry)
    prepared = service.prepare(source, context)
    symbol = {'color': '#2277AA', 'stroke': '#222222', 'stroke_width_pt': .4, 'radius_mm': 2}
    geometry_role = 'point' if geometry == 'Point' else 'polygon'
    missing = {'policy': 'reject', 'label': 'Missing', 'symbol': {**symbol, 'color': '#BBBBBB'}}
    if validation_expression == 'single':
        encoding = {'schema_version': 1, 'key_mode': 'discrete', 'geometry_role': geometry_role,
                    'domain': {'field': None, 'measurement': 'nominal', 'unit': None, 'normalization': None},
                    'scale': {'categories': []}, 'channels': {'symbols': [symbol], 'shape': 'auto'},
                    'missing': missing, 'legend': {'policy': 'all', 'uniform_label': 'Features'}}
    elif validation_expression == 'categorical':
        encoding = {'schema_version': 1, 'key_mode': 'discrete', 'geometry_role': geometry_role,
                    'domain': {'field': 'category', 'measurement': 'nominal', 'unit': None, 'normalization': None},
                    'scale': {'categories': [{'value': i + 1, 'label': 'Class ' + str(i + 1)} for i in range(3)]},
                    'channels': {'symbols': [{**symbol, 'color': color} for color in ['#226688', '#66AA99', '#EEAA44']], 'shape': 'auto'},
                    'missing': missing, 'legend': {'policy': 'observed'}}
    elif validation_expression == 'choropleth':
        encoding = {'schema_version': 1, 'key_mode': 'interval', 'geometry_role': geometry_role,
                    'domain': {'field': 'value', 'measurement': 'normalized-index', 'unit': 'index', 'normalization': None},
                    'scale': {'edges': [0, 2, 4], 'labels': ['[0,2)', '[2,4]'], 'interval_policy': 'left-closed-last-both', 'out_of_range': 'reject'},
                    'channels': {'symbols': [symbol, {**symbol, 'color': '#AADDEE'}], 'shape': 'auto'},
                    'missing': missing, 'legend': {'policy': 'all'}}
    else:
        encoding = {'schema_version': 1, 'key_mode': 'scaling', 'geometry_role': geometry_role,
                    'domain': {'field': 'value', 'measurement': 'count', 'unit': 'index', 'normalization': None},
                    'scale': {'domain_max': 4, 'range_mm': [0, 3], 'size_scale': 'sqrt', 'zero_policy': 'omit',
                              'negative_policy': 'reject', 'out_of_range': 'reject', 'legend_values': [1, 4]},
                    'channels': {'symbols': [symbol], 'shape': 'auto'},
                    'missing': missing, 'legend': {'policy': 'all'}}
    portrayal = VectorPortrayalCompiler(service).compile(prepared.ref(), encoding, context)
    params = layout_parameters or grid_cases(template['embedded']['layout'])[0]
    layout = LayoutResolver(registry).resolve(template['embedded']['layout'], 300, parameters=params)
    panels = [{'view_id': f['content_id'], 'portrayal_ref': portrayal.ref(), 'extent': [-1, -1, 4, 2]}
              for f in layout['contract']['frames'] if f['type'] == 'map']
    profile = ScenarioRegistry(registry).for_template(snapshot['manifest']['package'])
    texts = [{'content_id': f['content_id'], 'text': 'Vector validation' if f['type'] == 'title' else (profile.notice if f['content_id'] == 'source' else 'Panel')}
             for f in layout['contract']['frames'] if f['type'] not in {'map', 'legend'}]
    font_bytes = service.read_bytes(Path(font), 32 * 1024 * 1024)
    page = compile_page(service, layout=layout, cartography=template['embedded']['cartography'], panels=panels,
        font={'path': str(font), 'digest': service.digest_bytes(font_bytes), 'size_bytes': len(font_bytes)}, texts=texts,
        legend_titles={f['content_id']: 'Legend' for f in layout['contract']['frames'] if f['type'] == 'legend'}, context=context)
    bundle = BundlePreparer(service, "vector").build_many([prepared.ref()], context)
    return VectorSceneCompiler(service, BundlePreparer).compile(bundle_ref=service.save('prepared-data-bundle', bundle).ref(), page_request=page,
        context=context, scene_id='validation-' + sha256_digest({'package': snapshot['package_digest'], 'params': params, 'expression': validation_expression})[7:31], targets=tuple(targets))
