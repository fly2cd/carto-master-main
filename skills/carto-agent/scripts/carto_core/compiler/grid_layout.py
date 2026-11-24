"""Finite, template-owned grid rules. No template search or arbitrary solver."""
from __future__ import annotations
from copy import deepcopy
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def grid_cases(contract):
    grid = contract.get('grid')
    if grid is None:
        return []
    if 'allowed_cases' in grid:
        # Reviewed finite domain is the single authority when present (plan phase 3 §6.2).
        return [{'rows':c['rows'], 'columns':c['columns'], 'legend_mode':c['legend_mode'],
                 'legend_placement':c.get('legend_placement', 'outside')} for c in grid['allowed_cases']]
    return [{'rows':shape[0], 'columns':shape[1], 'legend_mode':mode, 'legend_placement':'outside'}
            for shape in grid['allowed_shapes'] for mode in grid['legend_modes']]


def case_key(case):
    """Full-tuple identity of a grid case (placement defaults to outside for legacy tuples)."""
    return (case['rows'], case['columns'], case['legend_mode'], case.get('legend_placement', 'outside'))


def _inside_legend_bounds(map_bounds, decl):
    """Mechanically derive an inside legend's bounds from the author declaration (design §2.3).

    Anchor selects the map corner; offset_mm + padding_mm inset the legend from that corner.
    Full enclosure by the map frame is verified here — a legend that does not fit fails closed
    (GRID_CAPACITY_INVALID), never silently shrunk or moved outside.
    """
    mx, my, mw, mh = map_bounds
    p, o = decl['padding_mm'], decl['offset_mm']
    lw, lh = decl['width_mm'], decl['height_mm']
    right = decl['anchor'] in ('top-right', 'bottom-right')
    bottom = decl['anchor'] in ('bottom-left', 'bottom-right')
    lx = mx + mw - p - o - lw if right else mx + p + o
    ly = my + mh - p - o - lh if bottom else my + p + o
    if not (lx >= mx - 1e-9 and ly >= my - 1e-9
            and lx + lw <= mx + mw + 1e-9 and ly + lh <= my + mh + 1e-9):
        raise ProtocolError('GRID_CAPACITY_INVALID', 'Inside legend does not fit fully within the map frame')
    return [lx, ly, lw, lh]


def instantiate_grid(contract, parameters, registry=None):
    registry = registry or SchemaRegistry()
    registry.validate('layout', contract)
    if parameters is None:
        if 'grid' in contract:
            raise ProtocolError('GRID_PARAMETERS_REQUIRED', 'Choose explicit template parameters')
        return deepcopy(contract)
    registry.validate('grid-parameters', parameters)
    if 'grid' not in contract or case_key(parameters) not in {case_key(c) for c in grid_cases(contract)}:
        raise ProtocolError('GRID_PARAMETERS_UNSUPPORTED', 'Parameters are outside the template contract')
    grid = contract['grid']
    rows, cols = parameters['rows'], parameters['columns']
    placement = parameters.get('legend_placement', 'outside')
    result = deepcopy(contract)
    result.pop('grid')
    if rows == cols == 1:
        maps = [f for f in result['frames'] if f['type']=='map']
        if len(maps)!=1:
            raise ProtocolError('GRID_BASE_INVALID', 'The base must declare one map')
        for frame in result['frames']:
            if frame['type']=='legend':frame['view_ids']=[maps[0]['content_id']]
        return result
    if any(f['type'] not in {'map','title','legend','marginalia'} for f in result['frames']):
        raise ProtocolError('GRID_BASE_INVALID', 'Grid does not support undeclared adornments')
    # The grid regenerates every map frame, so a base containment declaration would dangle.
    if any('inside_frame' in f for f in result['frames']):
        raise ProtocolError('GRID_BASE_INVALID', 'Declared containment requires a single-map base; the grid regenerates map frames')
    shared = parameters['legend_mode']=='shared'
    if placement == 'inside':
        # Phase 3 opens independent+inside only; shared+inside stays unopened (plan §6.1).
        if shared:
            raise ProtocolError('GRID_PARAMETERS_UNSUPPORTED', 'shared+inside legend is not opened')
        if 'inside_legend' not in grid:
            raise ProtocolError('GRID_PARAMETERS_UNSUPPORTED', 'inside placement requires an inside_legend declaration')
    area = grid['shared_panel_area'] if shared else grid['panel_area']
    x,y,w,h = area
    cw = (w-(cols-1)*grid['column_gap_mm'])/cols
    ch = (h-(rows-1)*grid['row_gap_mm'])/rows
    frames = [f for f in result['frames'] if f['type'] not in {'map','legend'}]
    for frame in frames:
        if frame['type']=='marginalia':frame['bounds']=deepcopy(grid['source_bounds'])
    def add(identifier, content, kind, bounds, **extra):
        if bounds[2] <= 0 or bounds[3] <= 0:
            raise ProtocolError('GRID_CAPACITY_INVALID', 'Grid leaves no usable content area')
        frames.append({'id':identifier,'content_id':content,'type':kind,'bounds':bounds,
                       'coordinate_space':'page','overflow_policy':'clip' if kind=='map' else 'reject',**extra})
    view_ids=[]
    for r in range(rows):
        for c in range(cols):
            key=f'r{r}-c{c}';view=f'view-{key}';view_ids.append(view)
            left=x+c*(cw+grid['column_gap_mm']);top=y+r*(ch+grid['row_gap_mm'])
            add('caption-'+key,'caption-'+key,'marginalia',[left,top,cw,grid['caption_height_mm']])
            mt=top+grid['caption_height_mm']+grid['caption_gap_mm'];mh=ch-grid['caption_height_mm']-grid['caption_gap_mm']
            # inside legend lives within the map, so the map keeps the full cell width (no outer column).
            mw=cw if (shared or placement=='inside') else cw-grid['legend_width_mm']-grid['legend_gap_mm']
            map_bounds=[left,mt,mw,mh]
            add('map-'+key,view,'map',map_bounds,content_role='main-map')
            if not shared:
                if placement=='inside':
                    lb=_inside_legend_bounds(map_bounds, grid['inside_legend'])
                    add('legend-'+key,'legend-'+key,'legend',lb,view_ids=[view],legend_columns=1,
                        content_role='legend-group',inside_frame='map-'+key)
                else:
                    add('legend-'+key,'legend-'+key,'legend',
                        [left+mw+grid['legend_gap_mm'],mt,grid['legend_width_mm'],mh],view_ids=[view],legend_columns=1,content_role='legend-group')
    if shared:
        add('legend','legend','legend',deepcopy(grid['shared_legend_bounds']),
            view_ids=view_ids,legend_columns=grid['shared_legend_columns'],content_role='legend-group')
    result['frames']=frames
    registry.validate('layout',result)
    return result
