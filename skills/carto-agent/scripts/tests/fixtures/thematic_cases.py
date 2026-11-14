"""Canonical A3.1 test designs (not production compatibility defaults)."""
from copy import deepcopy
RASTER_DESIGN={"geometry":"raster","kind":"categorical","measurement":"nominal","palette_source":"prepared"}

def design_from_encoding(encoding):
    d=deepcopy(encoding)
    kind=d['kind']
    d['measurement']='nominal' if kind in ('single','categorical') else 'count' if kind=='proportional' else d['quantity_kind']
    if kind in ('choropleth','proportional'):d['normalization']=None
    if kind=='choropleth':
        d['classification']={'method':'manual','edges':d.pop('edges'),'labels':d.pop('labels')}
        for k in ('quantity_kind','interval_policy','out_of_range'):d.pop(k)
    return d

def canonical_request(request):
    request['map_title']=request['goal']
    for p in request.get('panels',[]):p['design']=deepcopy(RASTER_DESIGN)
    for p in request.get('vector_panels',[]):
        if 'encoding' in p:p['design']=design_from_encoding(p.pop('encoding'))
    return request
