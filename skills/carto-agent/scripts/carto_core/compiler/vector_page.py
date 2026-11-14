"""Assemble/recheck a native-coordinate vector page using S1 layout contracts."""
from copy import deepcopy
import math
from ..errors import ProtocolError
from .layout import LayoutResolver
from .appearance import resolve_appearance, require_appearance
from .page_bindings import index_by
from .vector_portrayal import VectorPortrayalCompiler, shared_legend
from .portrayal_resolver import ir_to_kind


def compile_page(service, *, layout, cartography, panels, font, texts, legend_titles, context):
    resolver = LayoutResolver(service.registry)
    resolver.validate(layout)
    maps = {f['content_id']: f for f in layout['frames'] if f['type'] == 'map'}
    supplied = index_by(panels, 'view_id')
    if set(supplied) != set(maps):
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Every map view must have exactly one panel')
    compiler = VectorPortrayalCompiler(service)
    layers, resolved_panels = {}, []
    for vid, panel in sorted(supplied.items()):
        if set(panel) != {'view_id', 'portrayal_ref', 'extent'}:
            raise ProtocolError('VECTOR_PAGE_BINDING', 'Unsupported panel members')
        portrayal, report = compiler.load_verified(panel['portrayal_ref'], context)
        bounds = panel['extent']
        if len(bounds) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds):
            raise ProtocolError('VECTOR_PAGE_EXTENT', 'Each view requires an explicit finite extent')
        left, bottom, right, top = bounds
        actual = report['bounds']
        if left >= right or bottom >= top or not (left <= actual[0] <= actual[2] <= right and bottom <= actual[1] <= actual[3] <= top):
            raise ProtocolError('VECTOR_PAGE_EXTENT', 'Extent must contain the source; silent feature clipping is forbidden')
        layers[vid] = {'portrayal': portrayal, 'report': report}
        resolved_panels.append({**deepcopy(panel), 'frame_id': maps[vid]['id']})
    if len({item['report']['crs_wkt'] for item in layers.values()}) != 1:
        raise ProtocolError('VECTOR_CRS_MISMATCH', 'Page sources must use the same CRS; no implicit reprojection')
    legends = []
    slots = [f for f in layout['contract']['frames'] if f['type'] == 'legend']
    if set(legend_titles) != {f['content_id'] for f in slots}:
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Legend titles must match all declared slots')
    for frame in slots:
        views = frame.get('view_ids', list(maps) if len(maps) == 1 else [])
        if not views or len(set(views)) != len(views) or not set(views) <= set(maps):
            raise ProtocolError('VECTOR_PAGE_BINDING', 'Every legend must explicitly identify its served views')
        items = shared_legend([layers[vid]['portrayal'] for vid in views])
        if len(items) > layout['contract']['capacity']['legend_items']:
            raise ProtocolError('VECTOR_LEGEND_CAPACITY', 'Legend exceeds declared capacity')
        legends.append({'content_id': frame['content_id'], 'title': legend_titles[frame['content_id']],
                        'view_ids': sorted(views), 'items': items})
    colors = [{'view_id': p['view_id'], 'ref': p['portrayal_ref']} for p in resolved_panels]
    page = {'schema_version': 4, 'geometry': 'vector', 'resolved_layout': deepcopy(layout), 'cartography': deepcopy(cartography),
            'panels': resolved_panels, 'font': deepcopy(font), 'texts': deepcopy(texts), 'legends': legends,
            'appearance': resolve_appearance(cartography, layout['contract'], colors, service.registry),
            'coordinate_mode': 'native-no-reprojection', 'scale_bar': None, 'grid_north': None}
    from ..workflow.preparation_bundle import crs_contract
    from ..workflow.thematic import expression_reference
    from .page_bindings import validate_bindings
    data = {}
    for layer in layers.values():
        report = layer['report']; sid = report['source']['source_id']; ref = layer['portrayal']['prepared_ref']
        data[sid] = {'id': sid, 'source_id': sid, 'role': report['source']['role'], 'dataset_ref': ref, 'prepared_ref': ref}
    binding_layers = [{'id': 'layer-' + vid, 'data_binding_id': layers[vid]['report']['source']['source_id'],
                       'expression_ref': expression_reference(ir_to_kind(layers[vid]['portrayal']['encoding']),service.registry)} for vid in sorted(layers)]
    page['bindings'] = {'schema_version': 2, 'data_bindings': [data[key] for key in sorted(data)], 'layers': binding_layers,
        'views': [{'id': p['view_id'], 'extent': p['extent'], 'crs': crs_contract(layers[p['view_id']]['report']),
                   'layer_ids': ['layer-' + p['view_id']]} for p in resolved_panels],
        'panels': [{'id': p['frame_id'], 'frame_id': p['frame_id'], 'view_id': p['view_id']} for p in resolved_panels],
        'legends': [{'id': l['content_id'], 'frame_id': next(f['id'] for f in slots if f['content_id'] == l['content_id']),
                     'view_ids': l['view_ids'], 'layer_ids': ['layer-' + vid for vid in l['view_ids']]} for l in legends],
        'elements': [{'id': f['content_id'], 'frame_id': f['id'], 'kind': f['type'], 'view_id': None}
                     for f in layout['contract']['frames'] if f['type'] not in {'map', 'legend'}],
        'sharing': {'view_groups': [], 'legend_groups': [], 'encoding_groups':
                    [{'id': 'shared-encoding', 'members': [l['id'] for l in binding_layers]}] if len(legends) == 1 and len(layers) > 1 else []}}
    validate_bindings(page['bindings'], service.registry, executable=True)
    service.registry.validate('page-request', page)
    return page


def validate_page(service, page, context):
    service.registry.validate('page-request', page)
    expected = compile_page(service, layout=page['resolved_layout'], cartography=page['cartography'],
                            panels=[{k: v for k, v in p.items() if k != 'frame_id'} for p in page['panels']],
                            font=page['font'], texts=page['texts'],
                            legend_titles={l['content_id']: l['title'] for l in page['legends']}, context=context)
    if page != expected:
        raise ProtocolError('VECTOR_PAGE_CHANGED', 'Page mappings or appearance differ from verified inputs')
    frames = {f['content_id']: f for f in page['resolved_layout']['frames'] if f['type'] != 'map'}
    assigned = {}
    for items, kinds in ((page['texts'], {'title', 'marginalia'}), (page['legends'], {'legend'})):
        for item in items:
            key = item['content_id']
            if key in assigned or key not in frames or frames[key]['type'] not in kinds:
                raise ProtocolError('VECTOR_PAGE_BINDING', 'Duplicate or incompatible page element')
            assigned[key] = frames[key]['type']
            if frames[key]['type'] == 'title' and len(item['text']) > page['resolved_layout']['contract']['capacity']['title_characters']:
                raise ProtocolError('VECTOR_TITLE_CAPACITY', 'Title exceeds template capacity')
    if set(assigned) != set(frames) or list(assigned.values()).count('title') != 1:
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Every non-map frame must be populated')
    compiler = VectorPortrayalCompiler(service)
    return {p['view_id']: dict(zip(('portrayal', 'report'), compiler.load_verified(p['portrayal_ref'], context))) for p in page['panels']}
