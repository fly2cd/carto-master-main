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
from ..compiler.dependencies import DependencyResolver
from ..compiler.vector_portrayal import VectorPortrayalCompiler
from ..compiler.vector_page import compile_page
from ..compiler.vector_scene import VectorSceneCompiler, RENDERER_ID
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..workflow.vector_preparation import VectorPreparationService
from ..workflow.preparation_bundle import BundlePreparer
from ..workflow.models import ExecutionContext
from .general_thematic import GeneralThematicAuthor, TARGET_IDS

VERSION = '4.0.0'
ROLE = 'thematic-features'
class GeneralVectorSourceContract:
    """Source contract for vector geometry; standalone (no longer a subclass of GeneralThematicSourceContract).

    The two formerly inherited methods are copied inline with vector-appropriate
    semantics.  validate_role_bindings checks that the legend-sample CSV used for
    template authoring is present and well-formed, same as the raster path.
    """
    REQUIRED_FIELDS = frozenset(("category_value", "category_label"))

    def suggestions(self, profile_definition):
        return [{"path": "/portrayal/map-expressions", "value_origin": "system_suggestion",
                 "value": ["vector/explicit@1.0.0"], "rationale": "Explicit vector encodings; project values and units are never inferred."}]

    def brief_roles(self, request):
        return [{"role_id": ROLE, "source_id": request["role_bindings"]["classified_surface"],
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
        """Validate that exactly one classified_surface role is bound to a CSV source."""
        bindings = request.get("role_bindings", {})
        if set(bindings) != {"classified_surface"}:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED",
                                "Exactly one classified_surface role binding is admitted")
        if len(summaries) != 1:
            raise ProtocolError("ROLE_BINDING_UNSUPPORTED", "Exactly one legend-sample source is admitted")
        summary = summaries[0]
        if bindings["classified_surface"] != summary["source_id"]:
            raise ProtocolError("ROLE_BINDING_SOURCE_MISMATCH", summary["source_id"])
        if summary["kind"] != "csv":
            raise ProtocolError("SOURCE_TYPE_UNSUPPORTED", summary["source_id"])
        missing = sorted(self.REQUIRED_FIELDS - set(summary["field_names"]))
        if missing:
            raise ProtocolError("ROLE_BINDING_FIELD_MISSING", ",".join(missing))

SOURCE_CONTRACT = GeneralVectorSourceContract()


def expression_ref(registry):return MapExpressionCatalog(registry).reference('categorical', '2.0.0')


def make_bindings(request, layout, bundle, contracts, registry):
    sources = index_by(bundle['role_bindings'], 'source_id')
    panels = index_by(request['vector_panels'], 'id')
    maps = {f['content_id']: f for f in layout['contract']['frames'] if f['type'] == 'map'}
    if set(maps) != set(panels) or {p['source_id'] for p in panels.values()} != set(sources):
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Exact source/view/frame assignments required')
    layers = [{'id': 'layer-' + vid, 'data_binding_id': panel['source_id'],
                'expression_ref': deepcopy(contracts['portrayal']['layers'][0]['map_expression_ref'])}
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
    def __init__(self, registry=None):self.registry = registry or SchemaRegistry()

    def build(self, request, intent, brief, bundle, installation, contracts):
        profile = ScenarioRegistry(self.registry).for_template(request['template'])
        output_dpi = profile.definition['output_profile']['dpi']
        layout = LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'], output_dpi, parameters=request['layout_parameters'])
        return {'schema_version': 3, 'plan_id': 'plan-' + request['run_id'], 'revision': 1, 'project_id': request['project_id'],
                'intent_ref': artifact_ref('map-intent', intent), 'brief_ref': artifact_ref('map-brief', brief),
                'business_scene': intent['business_scene'], 'tasks': intent['tasks'], 'theme_tags': intent['theme_tags'],
                'template_refs': [installation['template_ref']], 'data_bindings': [{'role': b['role'], 'dataset_ref': b['dataset_ref']} for b in bundle['role_bindings']],
                'decisions': {'classification': contracts['portrayal']['layers'][0].get('encoding_policy', 'explicit-per-panel'),
                              'title': request['goal'], 'legend_source': 'actual-encoding',
                              'renderer_id': profile.definition.get('renderer_id', RENDERER_ID),
                              'legend_capacity': layout['contract']['capacity']['legend_items']},
                'bindings': make_bindings(request, layout, bundle, contracts, self.registry), 'layout_parameters': request['layout_parameters'], 'open_issues': []}


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
        refs = {b['source_id']: b['prepared_ref'] for b in bundle['role_bindings']}
        inputs = [{'view_id': p['id'], 'extent': p['extent'],
                   'portrayal_ref': VectorPortrayalCompiler(service).compile(refs[p['source_id']], p['encoding'], context).ref()}
                  for p in sorted(request['vector_panels'], key=lambda p: p['id'])]
        output_dpi = ScenarioRegistry(self.registry).for_template(request['template']).definition['output_profile']['dpi']
        layout = LayoutResolver(self.registry).resolve(contracts['scenario']['embedded']['layout'], output_dpi, parameters=request['layout_parameters'])
        font = service.read_bytes(font_path, 32 * 1024 * 1024)
        texts = [{'content_id': 'title', 'text': request['goal']}, {'content_id': 'source', 'text': profile.notice}]
        if len(inputs) > 1:texts += [{'content_id': p['id'].replace('view-', 'caption-', 1), 'text': p['title']} for p in request['vector_panels']]
        elif request['vector_panels'][0]['title'] != request['goal']:
            raise ProtocolError('VECTOR_TITLE_MISMATCH', 'Single panel title must equal the page title')
        page = compile_page(service, layout=layout, cartography=contracts['scenario']['embedded']['cartography'],
                            panels=inputs, font={'path': str(font_path), 'digest': service.digest_bytes(font), 'size_bytes': len(font)},
                            texts=texts, legend_titles={f['content_id']: 'Legend' for f in layout['contract']['frames'] if f['type'] == 'legend'}, context=context)
        if plan['bindings'] != page['bindings'] or plan['layout_parameters'] != request['layout_parameters'] or plan['decisions']['title'] != request['goal']:
            raise ProtocolError('VECTOR_PLAN_MISMATCH', 'Plan does not describe the compiled page')
        compiler = VectorSceneCompiler(service)
        scene = compiler.compile(bundle_ref=service.save('prepared-data-bundle', bundle).ref(), page_request=page, context=context,
                                 scene_id='scene-' + request['run_id'], targets=tuple(request['requested_outputs']))
        base = {'intent_ref': artifact_ref('map-intent', intent), 'profile_refs': [intent['evidence_refs'][0], intent['evidence_refs'][-1]],
                'business_scene': intent['business_scene'], 'map_tasks': intent['tasks'], 'template_refs': [installation['template_ref']],
                'dependency_refs': [deepcopy(contracts['portrayal']['layers'][0]['map_expression_ref'])], 'policy_refs': [profile.ref], 'ownership': {'scenario': 'map-scenario'},
                'shared_semantics': {'theme_tags': intent['theme_tags'], 'data_nature': bundle['summary']['data_nature']}}
        execution = compiler.bind_execution(base, scene, context)
        return {'scene': scene, 'candidate': {'schema_version': 1, 'candidate_id': 'candidate-' + request['run_id'],
                    'project_id': request['project_id'], 'run_id': request['run_id'], 'execution_digest': sha256_digest(execution),
                    'execution': execution, 'open_issues': [], 'created_at': request['requested_at']}}


def legend_checker(context):
    inputs = context.get('vector')
    if inputs is None:raise ProtocolError('VECTOR_CHECK_CONTEXT', 'Verified vector context required')
    valid = all(l['items'] and len({r['label'] for r in l['items']}) == len(l['items']) for l in inputs['page']['legends'])
    return valid, {'panel_count': len(inputs['layers']), 'legend_item_count': sum(len(l['items']) for l in inputs['page']['legends'])}, None


# TODO(R5-followup): Break the GeneralVectorAuthor(GeneralThematicAuthor) subclass.
# GeneralVectorAuthor overrides only _payloads() but inherits ~11 private helper
# methods (author, verify_existing, _scenario, _quality_gates, _delivery,
# _spatial_behavior, _fixture_csv, _require_admitted, _identity, _cartography,
# _layout, _data_schema, _portrayal).  To make it standalone:
#   1. Extract the inherited methods from GeneralThematicAuthor into module-level
#      functions in general_thematic.py.
#   2. Add author() and verify_existing() directly to GeneralVectorAuthor.
#   3. Have _payloads() call the extracted module-level helpers instead of self._*.
#   4. Remove the (GeneralThematicAuthor) parent and the import.
class GeneralVectorAuthor(GeneralThematicAuthor):
    def _payloads(self, request, brief):
        self.registry.validate('general-template-create-request', request)
        for key in ('kind', 'namespace', 'template_id', 'version'):
            if brief.get(key) != request[key]:raise ProtocolError('TEMPLATE_BRIEF_MISMATCH', 'Brief identity differs')
        identity = {'namespace': 'local', 'kind': 'map-scenario', 'id': 'general-thematic-map', 'version': VERSION}
        scenario = self._scenario(request)
        scenario['version'] = VERSION
        scenario['data_role_refs'] = [ROLE]
        for component in scenario['embedded'].values():component['version'] = VERSION
        portrayal = {'schema_version': 1, 'layers': [{'id': 'vector-layer', 'data_role': ROLE, 'geometry': 'vector', 'z_order': 0,
                      'map_expression_ref': expression_ref(self.registry), 'encoding_policy': 'explicit-per-panel', 'validation_expressions': ['single', 'categorical', 'choropleth', 'proportional']}],
                     'legend': {'generated_from_layers': True, 'show_no_data': True, 'overflow_policy': 'reject'}, 'rules': []}
        gates = self._quality_gates();gates['checks'] = [g for g in gates['checks'] if g['id'] != 'raster.classification-clarified']
        gates['baseline']['version'] = VERSION;gates['baseline']['digest'] = sha256_digest(identity)
        delivery = self._delivery()
        delivery['targets'][0]['composition'] = 'vector-map'
        delivery['targets'][0]['vector_claim'] = 'whole-map'
        # No all-vector production claim; text is embedded and the actual vector
        # composition is attested by the renderer, not by changing delivery policy.
        documents = {'contracts/scenario.yaml': scenario,
                     'contracts/data.schema.yaml': {'schema_version': 1, 'roles': [{'id': ROLE, 'required': True, 'geometry_types': ['point', 'polygon'], 'fields': [], 'license_policy': 'project-approved'}]},
                     'contracts/spatial-behavior.yaml': self._spatial_behavior(request), 'contracts/portrayal.yaml': portrayal,
                     'contracts/delivery.yaml': delivery, 'contracts/quality-gates.yaml': gates,
                     'dependencies.lock.yaml': {'schema_version': 1, 'lock_id': 'general-vector-lock', 'package': {**identity, 'digest': sha256_digest(identity)},
                        'dependencies': [], 'resources': [expression_ref(self.registry)], 'resolver_version': '1.0.0', 'generated_at': request['requested_at']},
                     'prototypes/general-vector.yaml': {
                         'schema_version': 1, 'prototype_id': 'general-vector-prototype',
                         'status': 'pending-validation', 'render_required': True, 'renderer_execution': 'not-run',
                         'layout_id': scenario['embedded']['layout']['layout_id'], 'target_ids': list(TARGET_IDS),
                         'layer_ids': ['vector-layer'], 'fixture_ref': 'fixtures/validation-input.csv',
                         'limitations': ['Synthetic vector validation only; not user data or production approval.']},
                     'fixtures/validation-input.csv': self._fixture_csv()}
        manifest = {'schema_version': 1, 'package': {**identity, 'status': 'draft', 'summary': request['purpose'][:500]},
                    'business_contracts': dict(DependencyResolver.MAP_SCENARIO_CONTRACTS), 'dependencies': [],
                    'dependency_lock': 'dependencies.lock.yaml', 'targets': sorted(request['targets'])}
        return manifest, documents


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
    encoding = {'schema_version': 1, 'kind': validation_expression, 'geometry': 'point' if geometry == 'Point' else 'polygon',
                'field': None if validation_expression == 'single' else ('category' if validation_expression == 'categorical' else 'value'),
                'unit': 'index' if validation_expression in {'choropleth', 'proportional'} else None,
                'missing': {'policy': 'reject', 'label': 'Missing', 'symbol': {**symbol, 'color': '#BBBBBB'}}}
    if validation_expression == 'single':encoding.update(label='Features', symbol=symbol)
    elif validation_expression == 'categorical':encoding.update(legend_policy='observed', categories=[
        {'value': i + 1, 'label': 'Class ' + str(i + 1), 'symbol': {**symbol, 'color': color}}
        for i, color in enumerate(['#226688', '#66AA99', '#EEAA44'])])
    elif validation_expression == 'choropleth':encoding.update(edges=[0, 2, 4], labels=['[0,2)', '[2,4]'],
        symbols=[symbol, {**symbol, 'color': '#AADDEE'}], quantity_kind='normalized-index', interval_policy='left-closed-last-both', out_of_range='reject')
    else:encoding.update(maximum_value=4, maximum_radius_mm=3, minimum_radius_mm=0,
        zero_policy='omit', negative_policy='reject', out_of_range='reject', legend_values=[1,4], symbol=symbol)
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
    return VectorSceneCompiler(service).compile(bundle_ref=service.save('prepared-data-bundle', bundle).ref(), page_request=page,
        context=context, scene_id='validation-' + sha256_digest({'package': snapshot['package_digest'], 'params': params, 'expression': validation_expression})[7:31], targets=tuple(targets))
