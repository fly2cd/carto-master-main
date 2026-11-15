"""Frozen multi-panel scenes; every resource is revalidated before rendering."""
from __future__ import annotations
from copy import deepcopy
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..contracts.execution import ExecutionContext
from ..contracts.bundle import context_snapshot
from ..workflow.preparation_bundle import BundlePreparer
from ..workflow.raster_preparation import RasterPreparationService
from .layout import LayoutResolver
from .raster_page_contract import validate_page_request

RASTER_RENDERER_ID='rasterio-matplotlib-page'

# context_snapshot: imported from the neutral leaf contracts.bundle (single
# authoritative definition). The former local duplicate was removed to prevent drift.

class RasterSceneCompiler:
    def __init__(self,preparation:RasterPreparationService):
        self.preparation=preparation;self.registry=preparation.registry

    def _inputs(self,bundle_ref,page_ref,context):
        bundle=BundlePreparer(self.preparation, "raster").load_verified(bundle_ref,context)
        page=self.preparation._json_ref(page_ref,'page-request')
        inputs=validate_page_request(self.preparation,page,context)
        if bundle!=inputs['bundle']:
            raise ProtocolError('RASTER_BUNDLE_PORTRAYAL_MISMATCH','Page sources differ from bundle')
        from ..adapters.page_renderer import PageRenderer
        PageRenderer(self.preparation)._validate(page,context)
        font={'artifact_ref':{'id':'font','version':'1.0.0','digest':page['font']['digest'],'uri':page['font']['path']},'size_bytes':page['font']['size_bytes']}
        self.preparation.snapshot_bytes(font,'font','.ttf')
        resources={}
        def add(ref,kind,mode):
            key=ref['id'] if kind=='font' else kind+'-'+sha256_digest(ref)[7:31]
            value={'id':key,'kind':kind,'digest_mode':mode,'ref':deepcopy(ref)}
            if key in resources and resources[key]!=value:raise ProtocolError('RASTER_RESOURCE_DUPLICATE','Conflicting resource identity')
            resources[key]=value
        add(bundle_ref,'contract','canonical-json');add(bundle['task_ref'],'contract','canonical-json');add(page_ref,'contract','canonical-json')
        for layer in inputs['layers'].values():
            port,report=layer['portrayal'],layer['report']
            task=self.preparation.save_document(report['request'],'raster-classification-request')
            for ref in (task.ref(),port['prepared_ref'],report['gis_result_ref'],layer['portrayal_ref']):add(ref,'contract','canonical-json')
            for key in ('source_snapshot','legend_snapshot'):add(report[key]['artifact_ref'],'data','bytes')
        add(font['artifact_ref'],'font','bytes')
        return {**inputs,'page':page,'font':font,'resources':[resources[k] for k in sorted(resources)]}

    def compile(self,*,bundle_ref,page_request,context,scene_id,revision=1,targets=('pdf','png'),random_seed=0):
        from ..adapters.page_renderer import PageRenderer
        page_ref=PageRenderer(self.preparation).freeze_request(page_request,context).ref()
        inputs=self._inputs(bundle_ref,page_ref,context);page=inputs['page']['resolved_layout']['page']
        scene={'schema_version':1,'scene_id':scene_id,'revision':revision,'renderer_id':RASTER_RENDERER_ID,
               'context':context_snapshot(context),'prepared_bundle_ref':deepcopy(bundle_ref),'page_request_ref':page_ref,
               'resolved_layout':deepcopy(inputs['page']['resolved_layout']),
               'viewport':{k:page[k] for k in ('width_px','height_px','device_pixel_ratio')},
               'export':{'targets':sorted(targets),'dpi':page['dpi']},'random_seed':random_seed,'resources':inputs['resources']}
        self.validate_scene(scene,context);return scene

    def validate_scene(self,scene,context):
        self.registry.validate('render-scene',scene)
        if scene['renderer_id']!=RASTER_RENDERER_ID:raise ProtocolError('RENDER_BACKEND_MISMATCH','Expected static page backend')
        if scene['context']!=context_snapshot(context):raise SecurityError('RASTER_SCENE_SCOPE_MISMATCH','Wrong execution scope')
        inputs=self._inputs(scene['prepared_bundle_ref'],scene['page_request_ref'],context)
        if scene['resources']!=inputs['resources'] or scene['resolved_layout']!=inputs['page']['resolved_layout']:
            raise ProtocolError('RASTER_SCENE_INPUT_DRIFT','Frozen resources or layout differ')
        LayoutResolver(self.registry).validate_scene(scene)
        if not {'pdf','png'}<=set(scene['export']['targets']):raise ProtocolError('RASTER_REQUIRED_TARGETS_MISSING','PDF and PNG required')
        return inputs

    @staticmethod
    def _views(inputs,targets):
        return [{'id':v['id'],'extent':deepcopy(v['extent']),'layer_ids':deepcopy(v['layer_ids']),'target_ids':sorted(targets)} for v in inputs['page']['bindings']['views']]

    def bind_execution(self,execution,scene,context):
        from ..adapters.formal_renderer import RendererProfile
        inputs=self.validate_scene(scene,context);result=deepcopy(execution)
        for key in ('camera','overlay_coordinate_policy','interaction_policy'):result.pop(key,None)
        page=scene['resolved_layout']['page'];views=inputs['page']['bindings']['views'];crs=views[0]['crs']
        if any(v['crs']!=crs for v in views):raise ProtocolError('RASTER_BUNDLE_PROFILE_MISMATCH','No implicit reprojection')
        result.update(page_inputs={k:deepcopy(scene[k]) for k in ('prepared_bundle_ref','page_request_ref')},
            resolved_layout=deepcopy(scene['resolved_layout']),render_scene_ref={'id':scene['scene_id'],'version':'1.0.0','digest':sha256_digest(scene)},
            dataset_refs=deepcopy(inputs['bundle']['datasets']),prepared_data_refs=[deepcopy(scene['prepared_bundle_ref'])],
            resolved_assets=[deepcopy(inputs['font']['artifact_ref'])],environment=RendererProfile.current().environment_snapshot(),
            views=self._views(inputs,scene['export']['targets']),
            targets={kind:{'format':kind,'display_crs':deepcopy(crs),**{k:page[k] for k in ('width_mm','height_mm','dpi')}} for kind in scene['export']['targets']})
        self.validate_execution(scene,result,context);return result

    def validate_execution(self,scene,execution,context):
        inputs=self.validate_scene(scene,context);LayoutResolver(self.registry).validate_execution(scene,execution)
        expected={'dataset_refs':inputs['bundle']['datasets'],'prepared_data_refs':[scene['prepared_bundle_ref']],
                  'resolved_assets':[inputs['font']['artifact_ref']],'views':self._views(inputs,scene['export']['targets'])}
        if any(execution.get(k)!=v for k,v in expected.items()):raise ProtocolError('RASTER_EXECUTION_INPUT_DRIFT','Execution bindings differ')
        crs=inputs['page']['bindings']['views'][0]['crs']
        if (sorted(t['format'] for t in execution['targets'].values())!=scene['export']['targets']
            or execution['shared_semantics']['data_nature']!=inputs['bundle']['summary']['data_nature']
            or any(t['display_crs']!=crs for t in execution['targets'].values())):
            raise ProtocolError('RASTER_EXECUTION_SEMANTICS_DRIFT','CRS, nature or outputs differ')
        return inputs

    def validate_generation(self,scene,execution,request,context):
        inputs=self.validate_execution(scene,execution,context)
        BundlePreparer(self.preparation, "raster").validate_request(request,inputs['bundle'],context)
        actual={v['id']:v['source_id'] for v in request['panels']}
        data={v['id']:v['source_id'] for v in inputs['page']['bindings']['data_bindings']}
        layers={v['id']:data[v['data_binding_id']] for v in inputs['page']['bindings']['layers']}
        expected={v['id']:layers[v['layer_ids'][0]] for v in inputs['page']['bindings']['views']}
        if actual!=expected or request['layout_parameters']!=scene['resolved_layout']['parameters']:
            raise ProtocolError('RASTER_GENERATE_BINDING_MISMATCH','Panel assignment or layout selection differs')
        if sorted(request['requested_outputs'])!=scene['export']['targets']:raise ProtocolError('RASTER_GENERATE_TARGET_MISMATCH','Requested outputs differ')
        return inputs
