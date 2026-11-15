"""Assemble/recheck a native-coordinate vector page using S1 layout contracts."""
from copy import deepcopy
import math
from ..errors import ProtocolError
from .layout import LayoutResolver
from .appearance import resolve_appearance, require_appearance
from .page_bindings import index_by
from .vector_portrayal import VectorPortrayalCompiler, shared_legend
from .portrayal_resolver import expression_reference, ir_to_kind


def _panel_refs(panel):
    # OneOf panel shape: legacy single layer ({view_id, portrayal_ref, extent}) or
    # ordered layer stack ({view_id, layers: [{portrayal_ref}...], extent}). The
    # internal structure is unified to a list so every consumer iterates the same way.
    if set(panel) == {'view_id', 'portrayal_ref', 'extent'}:
        return [{'portrayal_ref': panel['portrayal_ref']}]
    if set(panel) == {'view_id', 'layers', 'extent'}:
        refs = panel['layers']
        if not 1 <= len(refs) <= 4:
            raise ProtocolError('VECTOR_PAGE_BINDING', 'A panel may stack 1 to 4 layers')
        if any(set(item) - {'portrayal_ref'} or not item.get('portrayal_ref') for item in refs):
            raise ProtocolError('VECTOR_PAGE_BINDING', 'Each stacked layer requires exactly one portrayal_ref')
        return [dict(item) for item in refs]
    raise ProtocolError('VECTOR_PAGE_BINDING', 'Unsupported panel members')


def _layer_ids(view_id, stack):
    # Stable binding ids: single-layer views keep the legacy 'layer-<vid>' identity.
    if len(stack) == 1:
        return ['layer-' + view_id]
    return ['layer-%s-%d' % (view_id, index) for index in range(len(stack))]


def compile_page(service, *, layout, cartography, panels, font, texts, legend_titles, context, charts=None, basemap=None):
    resolver = LayoutResolver(service.registry)
    resolver.validate(layout)
    maps = {f['content_id']: f for f in layout['frames'] if f['type'] == 'map'}
    supplied = index_by(panels, 'view_id')
    if set(supplied) != set(maps):
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Every map view must have exactly one panel')
    compiler = VectorPortrayalCompiler(service)
    layers, resolved_panels = {}, []
    for vid, panel in sorted(supplied.items()):
        refs = _panel_refs(panel)
        stack = []
        for item in refs:
            portrayal, report = compiler.load_verified(item['portrayal_ref'], context)
            stack.append({'portrayal': portrayal, 'report': report})
        bounds = panel['extent']
        if len(bounds) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds):
            raise ProtocolError('VECTOR_PAGE_EXTENT', 'Each view requires an explicit finite extent')
        left, bottom, right, top = bounds
        for item in stack:
            actual = item['report']['bounds']
            if left >= right or bottom >= top or not (left <= actual[0] <= actual[2] <= right and bottom <= actual[1] <= actual[3] <= top):
                raise ProtocolError('VECTOR_PAGE_EXTENT', 'Extent must contain the source; silent feature clipping is forbidden')
        layers[vid] = stack
        resolved_panels.append({**deepcopy(panel), 'frame_id': maps[vid]['id']})
    if len({item['report']['crs_wkt'] for stack in layers.values() for item in stack}) != 1:
        raise ProtocolError('VECTOR_CRS_MISMATCH', 'Page sources must use the same CRS; no implicit reprojection')
    legends = []
    slots = [f for f in layout['contract']['frames'] if f['type'] == 'legend']
    if set(legend_titles) != {f['content_id'] for f in slots}:
        raise ProtocolError('VECTOR_PAGE_BINDING', 'Legend titles must match all declared slots')
    for frame in slots:
        views = frame.get('view_ids', list(maps) if len(maps) == 1 else [])
        if not views or len(set(views)) != len(views) or not set(views) <= set(maps):
            raise ProtocolError('VECTOR_PAGE_BINDING', 'Every legend must explicitly identify its served views')
        items = shared_legend([item['portrayal'] for vid in views for item in layers[vid]])
        if len(items) > layout['contract']['capacity']['legend_items']:
            raise ProtocolError('VECTOR_LEGEND_CAPACITY', 'Legend exceeds declared capacity')
        legends.append({'content_id': frame['content_id'], 'title': legend_titles[frame['content_id']],
                        'view_ids': sorted(views), 'items': items})
    # E6 chart core: bind each declared chart to a layout chart slot and
    # validate its scale semantics before freezing into the page request.
    from .chart_core import bind_chart_slots, validate_chart
    resolved_charts = bind_chart_slots(layout, list(charts or []))
    for chart in resolved_charts:
        validate_chart(chart, service.registry)
    # Basemap: a reference resource painted beneath the thematic layers. The
    # ground must cover every figure -- thematic bounds must fall inside the
    # declared basemap extent (dangling figures break figure-ground).
    if basemap is not None:
        bx0, by0, bx1, by1 = basemap['extent']
        if bx0 >= bx1 or by0 >= by1:
            raise ProtocolError('BASEMAP_EXTENT_INVALID', 'Basemap extent must have positive area')
        for stack in layers.values():
            for item in stack:
                bounds = item['report']['bounds']
                if not (bx0 <= bounds[0] and bounds[2] <= bx1 and by0 <= bounds[1] and bounds[3] <= by1):
                    raise ProtocolError('BASEMAP_EXTENT_INSUFFICIENT',
                                        'Thematic bounds exceed the basemap extent; no silent clipping')
    colors = []
    for panel in resolved_panels:
        stripped = {k: v for k, v in panel.items() if k != 'frame_id'}
        for item in _panel_refs(stripped):
            colors.append({'view_id': panel['view_id'], 'ref': item['portrayal_ref']})
    # Layer stack: the frozen paint order (figure-ground is a declared contract).
    layer_stack = (['basemap'] if basemap is not None else []) + ['thematic', 'legends', 'charts', 'furniture']
    page = {'schema_version': 4, 'geometry': 'vector', 'resolved_layout': deepcopy(layout), 'cartography': deepcopy(cartography),
            'panels': resolved_panels, 'font': deepcopy(font), 'texts': deepcopy(texts), 'legends': legends,
            'charts': deepcopy(resolved_charts), 'layer_stack': layer_stack,
            **({'basemap': deepcopy(basemap)} if basemap is not None else {}),
            'appearance': resolve_appearance(cartography, layout['contract'], colors, service.registry),
            'coordinate_mode': 'native-no-reprojection', 'scale_bar': None, 'grid_north': None}
    from .page_bindings import validate_bindings
    data = {}
    for vid in sorted(layers):
        for item in layers[vid]:
            report = item['report']
            sid = report['source']['source_id']
            ref = item['portrayal']['prepared_ref']
            data[sid] = {'id': sid, 'source_id': sid, 'role': report['source']['role'], 'dataset_ref': ref, 'prepared_ref': ref}
    binding_layers = []
    view_layer_ids = {}
    for vid in sorted(layers):
        ids = _layer_ids(vid, layers[vid])
        view_layer_ids[vid] = ids
        for index, item in enumerate(layers[vid]):
            binding_layers.append({'id': ids[index],
                                   'data_binding_id': item['report']['source']['source_id'],
                                   'expression_ref': expression_reference(ir_to_kind(item['portrayal']['encoding']), service.registry)})
    page['bindings'] = {'schema_version': 2, 'data_bindings': [data[key] for key in sorted(data)], 'layers': binding_layers,
        'views': [{'id': p['view_id'], 'extent': p['extent'], 'crs': service.crs_contract(layers[p['view_id']][0]['report']),
                   'layer_ids': view_layer_ids[p['view_id']]} for p in resolved_panels],
        'panels': [{'id': p['frame_id'], 'frame_id': p['frame_id'], 'view_id': p['view_id']} for p in resolved_panels],
        'legends': [{'id': l['content_id'], 'frame_id': next(f['id'] for f in slots if f['content_id'] == l['content_id']),
                     'view_ids': l['view_ids'], 'layer_ids': [lid for vid in l['view_ids'] for lid in view_layer_ids[vid]]} for l in legends],
        'elements': [{'id': f['content_id'], 'frame_id': f['id'], 'kind': f['type'], 'view_id': None}
                     for f in layout['contract']['frames'] if f['type'] not in {'map', 'legend'}],
        'sharing': {'view_groups': [], 'legend_groups': [], 'encoding_groups':
                    [{'id': 'shared-encoding', 'members': [l['id'] for l in binding_layers]}] if len(legends) == 1 and len(binding_layers) > 1 else []}}
    validate_bindings(page['bindings'], service.registry, executable=True)
    require_appearance(page['appearance'], layout['contract'], colors, service.registry)
    service.registry.validate('page-request', page)
    return page


def validate_page(service, page, context):
    service.registry.validate('page-request', page)
    expected = compile_page(service, layout=page['resolved_layout'], cartography=page['cartography'],
                            panels=[{k: v for k, v in p.items() if k != 'frame_id'} for p in page['panels']],
                            font=page['font'], texts=page['texts'],
                            legend_titles={l['content_id']: l['title'] for l in page['legends']}, context=context,
                            charts=page.get('charts'), basemap=page.get('basemap'))
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
    result = {}
    for p in page['panels']:
        refs = [item['portrayal_ref'] for item in p['layers']] if 'layers' in p else [p['portrayal_ref']]
        result[p['view_id']] = [dict(zip(('portrayal', 'report'), compiler.load_verified(ref, context))) for ref in refs]
    return result
