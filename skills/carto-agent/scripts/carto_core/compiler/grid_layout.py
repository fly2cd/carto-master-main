"""Finite, template-owned grid rules. No template search or arbitrary solver."""
from __future__ import annotations
from copy import deepcopy
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def grid_cases(contract):
    grid = contract.get('grid')
    if grid is None:
        return []
    return [{'rows':shape[0], 'columns':shape[1], 'legend_mode':mode}
            for shape in grid['allowed_shapes'] for mode in grid['legend_modes']]


def instantiate_grid(contract, parameters, registry=None):
    registry = registry or SchemaRegistry()
    registry.validate('layout', contract)
    if parameters is None:
        if 'grid' in contract:
            raise ProtocolError('GRID_PARAMETERS_REQUIRED', 'Choose explicit template parameters')
        return deepcopy(contract)
    registry.validate('grid-parameters', parameters)
    if 'grid' not in contract or parameters not in grid_cases(contract):
        raise ProtocolError('GRID_PARAMETERS_UNSUPPORTED', 'Parameters are outside the template contract')
    grid = contract['grid']
    rows, cols = parameters['rows'], parameters['columns']
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
            mw=cw if shared else cw-grid['legend_width_mm']-grid['legend_gap_mm']
            add('map-'+key,view,'map',[left,mt,mw,mh])
            if not shared:
                add('legend-'+key,'legend-'+key,'legend',
                    [left+mw+grid['legend_gap_mm'],mt,grid['legend_width_mm'],mh],view_ids=[view],legend_columns=1)
    if shared:
        add('legend','legend','legend',deepcopy(grid['shared_legend_bounds']),
            view_ids=view_ids,legend_columns=grid['shared_legend_columns'])
    result['frames']=frames
    registry.validate('layout',result)
    return result
