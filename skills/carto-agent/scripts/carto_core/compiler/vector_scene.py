"""Frozen vector scenes reuse the formal layout, execution and approval pipeline."""
from copy import deepcopy
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..backend_registry import VECTOR_PAGE
from ..contracts.bundle import context_snapshot
from ..contracts.protocols import (BundlePreparerFactory, EnvironmentSnapshotProvider,
                                   PageContractFactory, VectorPreparationProtocol)
from .vector_page import validate_page
from .layout import LayoutResolver

RENDERER_ID = VECTOR_PAGE.renderer_id  # derived; single authority = carto_core.backend_registry


class VectorSceneCompiler:
    def __init__(self, preparation: VectorPreparationProtocol, *, bundles: BundlePreparerFactory,
                 pages: PageContractFactory, environment: EnvironmentSnapshotProvider):
        # All three collaborators are injected ports (Tier-2 去环 Step8 for ``bundles``,
        # P1 Step D2 for ``pages`` / ``environment``); keyword-only so three callables
        # cannot be silently mis-ordered.
        self.preparation = preparation
        self.bundles = bundles
        self.registry = preparation.registry
        self.pages = pages
        self.environment = environment

    def _inputs(self, bundle_ref, page_ref, context):
        bundle = self.bundles(self.preparation, "vector").load_verified(bundle_ref, context)
        page = self.preparation.document(page_ref, 'page-request')
        layers = validate_page(self.preparation, page, context)
        rebuilt = self.bundles(self.preparation, "vector").build_many([item['portrayal']['prepared_ref'] for stack in layers.values() for item in stack], context)
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
        page_ref = self.pages(self.preparation).freeze_request(page_request, context).ref()
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
        if not VECTOR_PAGE.export_formats <= set(scene['export']['targets']):
            raise ProtocolError('VECTOR_TARGETS_REQUIRED', 'PDF and PNG must both be requested')
        return inputs

    def bind_execution(self, execution, scene, context):
        inputs = self.validate_scene(scene, context); result = deepcopy(execution)
        page = scene['resolved_layout']['page']; crs = inputs['page']['bindings']['views'][0]['crs']
        result.update(page_inputs={k: deepcopy(scene[k]) for k in ('prepared_bundle_ref', 'page_request_ref')},
                      resolved_layout=deepcopy(scene['resolved_layout']),
                      render_scene_ref={'id': scene['scene_id'], 'version': '1.0.0', 'digest': sha256_digest(scene)},
                      dataset_refs=deepcopy(inputs['bundle']['datasets']), prepared_data_refs=[deepcopy(scene['prepared_bundle_ref'])],
                      resolved_assets=[deepcopy(inputs['font']['artifact_ref'])], environment=self.environment(RENDERER_ID),
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
