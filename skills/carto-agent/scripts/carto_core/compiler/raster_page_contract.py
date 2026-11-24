"""Compile and revalidate v4 raster pages, including strict shared legends.

``bundles`` is the injected BundlePreparer factory
(``contracts.protocols.BundlePreparerFactory``): the concrete preparer stays in the
execution layer and is handed in by the composition root, so this module never
imports ``workflow`` (Tier-2 去环 Step7).
"""
from __future__ import annotations
from copy import deepcopy
from ..errors import ProtocolError
from .appearance import resolve_appearance, require_appearance
from .page_bindings import build_page_bindings, index_by, validate_bindings
from .raster_legends import resolve_shared_legend


def load_layers(service, references, context, bundles):
    from .raster_portrayal import RasterPortrayalCompiler
    if not 1 <= len(references) <= 4:
        raise ProtocolError('PAGE_BINDING_UNSUPPORTED','One to four explicit map references required')
    indexed=index_by(references,'view_id');layers={};prototype=None
    for vid,item in sorted(indexed.items()):
        portrayal=RasterPortrayalCompiler(service).load_verified(item['ref'],context)
        report,gis=service.load_verified(portrayal['prepared_ref'])
        if prototype is None:prototype=portrayal['portrayal']
        elif prototype!=portrayal['portrayal']:
            raise ProtocolError('PAGE_EXPRESSION_CONTRACT_MISMATCH','All panels must use the template expression contract')
        layers[vid]={'portrayal_ref':deepcopy(item['ref']),'portrayal':portrayal,'report':report,'gis':gis}
    bundle=bundles(service, "raster").build_many([v['portrayal']['prepared_ref'] for v in layers.values()],context)
    assignments=[{'id':vid,'source_id':v['report']['request']['source']['source_ref']['id']} for vid,v in layers.items()]
    return layers,bundle,prototype,assignments


def resolve_legends(service, bindings, legends, layers, context, color_scheme=None):
    from .style_colors import overlay_legend_colors
    titles=index_by(legends,'content_id');result=[]
    if set(titles)!={x['id'] for x in bindings['legends']}:
        raise ProtocolError('PAGE_BINDING_LEGEND','Legend titles must match template slots')
    for binding in bindings['legends']:
        refs=[layers[vid]['portrayal_ref'] for vid in binding['view_ids']]
        if len(refs)>1:
            items=resolve_shared_legend(service,refs,context)
            if color_scheme is not None:
                items=overlay_legend_colors(items,color_scheme)
        else:items=deepcopy(layers[binding['view_ids'][0]]['portrayal']['legend_items'])
        if not items:raise ProtocolError('RASTER_LEGEND_CAPACITY','Every legend must be nonempty')
        result.append({'content_id':binding['id'],'title':titles[binding['id']]['title'],'items':items})
    return result


def compile_page_request(service, request, cartography, context, bundles, color_scheme=None):
    if request.get('schema_version')!=4:
        raise ProtocolError('PAGE_CONTRACT_VERSION','An explicit v4 page design is required')
    if any(k in request for k in ('typography','appearance','bindings','portrayal_ref','legend')):
        raise ProtocolError('PAGE_DESIGN_ALREADY_RESOLVED','Do not supply legacy or already resolved inputs')
    if any('items' in item for item in request['legends']):
        raise ProtocolError('PAGE_DESIGN_ALREADY_RESOLVED','Legend entries come only from verified sources')
    result=deepcopy(request);result['portrayals']=sorted(result['portrayals'],key=lambda x:x['view_id'])
    layers,bundle,prototype,assignments=load_layers(service,result['portrayals'],context,bundles)
    if color_scheme is not None:
        # 裁决4: apply the compile-time effective-color overlay to the frozen portrayal rows
        # and legend items; the prepared report/bundle stays frozen and reusable.
        from .style_colors import apply_color_scheme
        from .raster_portrayal import legend_items
        for layer in layers.values():
            effective,_=apply_color_scheme(layer['portrayal']['lookup_table'],color_scheme,registry=service.registry)
            layer['portrayal']['lookup_table']=effective
            layer['portrayal']['legend_items']=legend_items(effective)
    layout=result['resolved_layout']['contract']
    result['bindings']=build_page_bindings(layout,prototype,bundle,assignments,service.registry)
    result['appearance']=resolve_appearance(cartography,layout,result['portrayals'],service.registry)
    result['legends']=resolve_legends(service,result['bindings'],result['legends'],layers,context,color_scheme)
    result['schema_version'] = 4; result['geometry'] = 'raster'
    service.registry.validate('page-request', result)
    return result


def validate_page_request(service,request,context,bundles):
    service.registry.validate('page-request', request)
    require_appearance(request['appearance'],request['resolved_layout']['contract'],request['portrayals'],service.registry)
    validate_bindings(request['bindings'],service.registry,executable=True)
    layers,bundle,prototype,assignments=load_layers(service,request['portrayals'],context,bundles)
    expected=build_page_bindings(request['resolved_layout']['contract'],prototype,bundle,assignments,service.registry)
    if request['bindings']!=expected:
        raise ProtocolError('PAGE_BINDING_DRIFT','Page does not match source and layout bindings')
    if request['legends']!=resolve_legends(service,expected,request['legends'],layers,context):
        raise ProtocolError('SHARED_LEGEND_SOURCE_MISMATCH','Legend differs from verified sources')
    limit=request['resolved_layout']['contract']['capacity']['legend_items']
    if any(len(x['items'])>limit for x in request['legends']):
        raise ProtocolError('RASTER_PAGE_LEGEND_CAPACITY','Legend exceeds template capacity')
    return {'layers':layers,'bundle':bundle}
