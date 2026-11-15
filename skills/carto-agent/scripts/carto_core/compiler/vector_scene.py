"""Frozen vector scenes reuse the formal layout, execution and approval pipeline."""
from copy import deepcopy
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..workflow.vector_preparation import context_snapshot
from ..workflow.preparation_bundle import BundlePreparer
from .vector_page import validate_page
from .layout import LayoutResolver

RENDERER_ID = 'matplotlib-vector-page'


class VectorSceneCompiler:
    def __init__(self, preparation):
        self.preparation = preparation
        self.registry = preparation.registry

    def _inputs(self, bundle_ref, page_ref, context):
        bundle = BundlePreparer(self.preparation, "vector").load_verified(bundle_ref, context)
        page = self.preparation.document(page_ref, 'page-request')
        layers = validate_page(self.preparation, page, context)
        rebuilt = BundlePreparer(self.preparation, "vector").build_many([item['portrayal']['prepared_ref'] for stack in layers.values() for item in stack], context)
        if rebuilt != bundle:raise ProtocolError('VECTOR_BUNDLE_MISMATCH', 'Page sources differ from the prepared bundle')
        font = {'artifact_ref': {'id': 'font', 'version': '1.0.0', 'digest': page['font']['digest'], 'uri': page['font']['path']},
                'size_bytes': page['font']['size_bytes']}
        self.preparation.snapshot_bytes(font, 'font', '.ttf')
        resources = {}
        def add(ref, kind, mode):
            key = 'font' if kind == 'font' else kind + '-' + sha256_digest(ref)[7:31]
            resources[key] = {'id': key, 'kind': kind, 'digest_mode': mode, 'ref': deepcopy(ref)}
        add(bundle_ref, 'contract', 'canonical-json');add(bundle['task_ref'], 'contract', 'canonical-json');add(page_ref, 'contract', 'canonical-json')
        add(font['artifact_ref'], 'font', 'bytes')
        for panel in page['panels']:
            stack = layers[panel['view_id']]
            for ref in (panel.get('layers') or [{'portrayal_ref': panel['portrayal_ref']}]):
                add(ref['portrayal_ref'], 'contract', 'canonical-json')
            for layer in stack:
                add(layer['portrayal']['prepared_ref'], 'contract', 'canonical-json')
                for asset in layer['report']['source_assets']:add(asset['ref'], 'data', 'bytes')
                if layer['report'].get('attribute_evidence'):
                    add(layer['report']['attribute_evidence']['asset']['artifact_ref'], 'data', 'bytes')
        return {'page': page, 'layers': layers, 'bundle': bundle, 'font': font,
                'resources': [resources[key] for key in sorted(resources)]}

    def compile(self, *, bundle_ref, page_request, context, scene_id, revision=1, targets=('pdf', 'png'), random_seed=0):
        from ..adapters.page_renderer import PageRenderer
        page_ref = PageRenderer(self.preparation).freeze_request(page_request, context).ref()
        inputs = self._inputs(bundle_ref, page_ref, context); page = inputs['page']['resolved_layout']['page']
        scene = {'schema_version': 1, 'scene_id': scene_id, 'revision': revision, 'renderer_id': RENDERER_ID,
                 'context': context_snapshot(context), 'prepared_bundle_ref': deepcopy(bundle_ref), 'page_request_ref': page_ref,
                 'resolved_layout': deepcopy(inputs['page']['resolved_layout']),
                 'viewport': {k: page[k] for k in ('width_px', 'height_px', 'device_pixel_ratio')},
                 'export': {'targets': sorted(targets), 'dpi': page['dpi']}, 'random_seed': random_seed, 'resources': inputs['resources']}
        self.validate_scene(scene, context)
        return scene

    def validate_scene(self, scene, context):
        self.registry.validate('render-scene', scene)
        if scene['renderer_id'] != RENDERER_ID or scene['context'] != context_snapshot(context):
            raise SecurityError('VECTOR_SCENE_SCOPE', 'Wrong backend or execution scope')
        inputs = self._inputs(scene['prepared_bundle_ref'], scene['page_request_ref'], context)
        if inputs['resources'] != scene['resources'] or inputs['page']['resolved_layout'] != scene['resolved_layout']:
            raise ProtocolError('VECTOR_SCENE_CHANGED', 'Frozen scene sources or layout differ')
        LayoutResolver(self.registry).validate_scene(scene)
        if not {'pdf', 'png'} <= set(scene['export']['targets']):
            raise ProtocolError('VECTOR_TARGETS_REQUIRED', 'PDF and PNG must both be requested')
        return inputs

    def bind_execution(self, execution, scene, context):
        from ..adapters.formal_renderer import RendererProfile
        inputs = self.validate_scene(scene, context); result = deepcopy(execution)
        page = scene['resolved_layout']['page']; crs = inputs['page']['bindings']['views'][0]['crs']
        result.update(page_inputs={k: deepcopy(scene[k]) for k in ('prepared_bundle_ref', 'page_request_ref')},
                      resolved_layout=deepcopy(scene['resolved_layout']),
                      render_scene_ref={'id': scene['scene_id'], 'version': '1.0.0', 'digest': sha256_digest(scene)},
                      dataset_refs=deepcopy(inputs['bundle']['datasets']), prepared_data_refs=[deepcopy(scene['prepared_bundle_ref'])],
                      resolved_assets=[deepcopy(inputs['font']['artifact_ref'])], environment=RendererProfile.current(RENDERER_ID).environment_snapshot(),
                      views=[{'id': v['id'], 'extent': v['extent'], 'layer_ids': v['layer_ids'], 'target_ids': scene['export']['targets']}
                             for v in inputs['page']['bindings']['views']],
                      targets={kind: {'format': kind, 'display_crs': crs, **{k: page[k] for k in ('width_mm', 'height_mm', 'dpi')}}
                               for kind in scene['export']['targets']})
        return result

    def validate_execution(self, scene, execution, context):
        inputs = self.validate_scene(scene, context)
        LayoutResolver(self.registry).validate_execution(scene, execution)
        expected = self.bind_execution(execution, scene, context)
        if expected != execution or execution['shared_semantics']['data_nature'] != inputs['bundle']['summary']['data_nature']:
            raise ProtocolError('VECTOR_EXECUTION_CHANGED', 'Execution views, inputs or environment differ')
        return inputs

    def validate_generation(self, scene, execution, request, context):
        inputs = self.validate_execution(scene, execution, context)
        BundlePreparer(self.preparation, "vector").validate_request(request, inputs['bundle'], context)
        requested = {p['id']: p for p in request['vector_panels']}
        if set(requested) != set(inputs['layers']) or request['layout_parameters'] != scene['resolved_layout']['parameters']:
            raise ProtocolError('VECTOR_GENERATION_CHANGED', 'Panel selection differs')
        for panel in inputs['page']['panels']:
            source = requested[panel['view_id']]; stack = inputs['layers'][panel['view_id']]
            from ..workflow.thematic import resolve_design
            # First version: the generate workflow binds one source per panel;
            # stacked panels are composed at compile_page level (request-level
            # multi-layer declaration is a later orchestration step).
            layer = stack[0]
            expected_encoding,_=resolve_design(source['design'],layer['report'],self.registry)
            if (source['source_id'] != layer['report']['source']['source_id'] or expected_encoding != layer['portrayal']['encoding']
                    or source['extent'] != panel['extent']):
                raise ProtocolError('VECTOR_GENERATION_CHANGED', 'Panel source, encoding or extent differs')
        from ..scenario_registry import ScenarioRegistry
        notice = ScenarioRegistry(self.registry).for_generate(request).notice
        expected_texts = {'title': request['map_title'], 'source': notice}
        if len(requested) > 1:
            expected_texts.update({p['id'].replace('view-', 'caption-', 1): p['title'] for p in request['vector_panels']})
        if {p['content_id']: p['text'] for p in inputs['page']['texts']} != expected_texts:
            raise ProtocolError('VECTOR_GENERATION_CHANGED', 'Frozen titles or notice differ from the request')
        if sorted(request['requested_outputs']) != scene['export']['targets']:
            raise ProtocolError('VECTOR_GENERATION_CHANGED', 'Requested outputs differ')
        return inputs
