"""Explicit page references shared by scenarios, with finite single/grid execution."""
from __future__ import annotations
from copy import deepcopy
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def index_by(items, key):
    result = {}
    for item in items:
        value = item[key]
        if value in result:
            raise ProtocolError("PAGE_BINDING_DUPLICATE", f"Duplicate {key}: {value}")
        result[value] = item
    return result


def one_item(items, key):
    indexed = index_by(items, key)
    if len(indexed) != 1:
        raise ProtocolError("PAGE_BINDING_UNSUPPORTED", "This template component requires exactly one item")
    return next(iter(indexed.values()))


def category_counts(report):
    rows = report["rows"]
    return {
        "observed_value_count": sum(row["count"] > 0 for row in rows),
        "defined_class_count": sum(row["semantic"] == "class" for row in rows),
        "observed_class_count": sum(row["semantic"] == "class" and row["count"] > 0 for row in rows),
        "displayed_class_count": sum(row["semantic"] == "class" and row["count"] > 0
                                     and row["display"] == "color" for row in rows),
        "legend_item_count": sum(row["include_in_legend"] and row["display"] == "color" for row in rows),
    }


def validate_bindings(value, registry=None, *, executable=False):
    registry = registry or SchemaRegistry()
    registry.validate("page-bindings", value)
    data = index_by(value["data_bindings"], "id")
    layers = index_by(value["layers"], "id")
    views = index_by(value["views"], "id")
    panels = index_by(value["panels"], "id")
    legends = index_by(value["legends"], "id")
    elements = index_by(value["elements"], "id")
    def require(members, available):
        if not set(members) <= set(available):
            raise ProtocolError("PAGE_BINDING_REFERENCE", "An explicit binding target does not exist")
    for layer in layers.values():
        require([layer["data_binding_id"]], data)
    for view in views.values():
        require(view["layer_ids"], layers)
    for panel in panels.values():
        require([panel["view_id"]], views)
    for legend in legends.values():
        require(legend["view_ids"], views)
        require(legend["layer_ids"], layers)
        visible = {layer for view in legend["view_ids"] for layer in views[view]["layer_ids"]}
        if not set(legend["layer_ids"]) <= visible:
            raise ProtocolError("PAGE_BINDING_LEGEND", "Legend layers must belong to its bound views")
    for element in elements.values():
        if element["view_id"] is not None:
            require([element["view_id"]], views)
    frames = [item["frame_id"] for items in (panels, legends, elements) for item in items.values()]
    if len(frames) != len(set(frames)):
        raise ProtocolError("PAGE_BINDING_DUPLICATE", "A frame has multiple content bindings")
    for name, available in (("view_groups", views), ("encoding_groups", layers), ("legend_groups", legends)):
        groups = index_by(value["sharing"][name], "id")
        used = set()
        for group in groups.values():
            require(group["members"], available)
            if used.intersection(group["members"]):
                raise ProtocolError("PAGE_BINDING_SHARING", "Overlapping sharing groups")
            used.update(group["members"])
    if executable and (len(views) != len(panels)
                       or len(layers) != len(panels)
                       or value['sharing']['view_groups'] or value['sharing']['legend_groups']):
        raise ProtocolError('PAGE_BINDING_UNSUPPORTED','Unsupported grid binding')
    if executable and len(legends) not in {1, len(panels)}:
        raise ProtocolError('PAGE_BINDING_UNSUPPORTED', 'Legends must be one shared or one per panel')
    return value


def build_page_bindings(layout, portrayal, bundle, panels, registry=None):
    registry=registry or SchemaRegistry()
    registry.validate('layout',layout);registry.validate('portrayal',portrayal)
    frames=index_by(layout['frames'],'id')
    maps={f['content_id']:f for f in frames.values() if f['type']=='map'}
    assignments=index_by(panels,'id');sources=index_by(bundle['role_bindings'],'source_id')
    if set(assignments)!=set(maps) or {p['source_id'] for p in panels}!=set(sources):
        raise ProtocolError('PAGE_BINDING_DATA','Every source and map slot must be bound explicitly')
    prototype=one_item(portrayal['layers'],'id')
    data=[]
    for sid,b in sorted(sources.items()):
        if b['role']!=prototype['data_role']:
            raise ProtocolError('PAGE_BINDING_DATA','Template data role differs')
        data.append({'id':sid,'source_id':sid,'role':b['role'],'dataset_ref':deepcopy(b['dataset_ref']),'prepared_ref':deepcopy(b['prepared_ref'])})
    layers=[];views=[];placed=[]
    for view_id,frame in sorted(maps.items()):
        source=assignments[view_id]['source_id'];b=sources[source]
        layer_id=prototype['id'] if len(maps)==1 else 'layer-'+view_id
        layers.append({'id':layer_id,'data_binding_id':source,'expression_ref':deepcopy(prototype['map_expression_ref'])})
        views.append({'id':view_id,'layer_ids':[layer_id],'extent':deepcopy(b['bbox']),'crs':deepcopy(b['crs'])})
        placed.append({'id':frame['id'],'view_id':view_id,'frame_id':frame['id']})
    by_view=index_by(views,'id');legends=[]
    for frame in sorted(frames.values(),key=lambda f:f['id']):
        if frame['type']!='legend':continue
        served=frame.get('view_ids',list(maps) if len(maps)==1 else [])
        if not served or not set(served)<=set(maps):raise ProtocolError('PAGE_BINDING_LEGEND','Explicit legend views required')
        legends.append({'id':frame['content_id'],'frame_id':frame['id'],'view_ids':sorted(served),
                        'layer_ids':sorted({lid for vid in served for lid in by_view[vid]['layer_ids']})})
    elements=[]
    for f in sorted(frames.values(),key=lambda f:f['id']):
        if f['type'] in {'map','legend'}:continue
        view_id=None
        if f['type'] in {'scale-bar','north-arrow'}:
            if len(maps)!=1:raise ProtocolError('PAGE_BINDING_UNSUPPORTED','Grid adornments require a later explicit contract')
            view_id=next(iter(maps))
        elements.append({'id':f['content_id'],'frame_id':f['id'],'kind':f['type'],'view_id':view_id})
    shared=[{'id':'shared-encoding','members':[x['id'] for x in layers]}] if len(legends)==1 and len(maps)>1 else []
    result={'schema_version':2,'data_bindings':data,'layers':layers,'views':views,'panels':placed,'legends':legends,
            'elements':elements,'sharing':{'view_groups':[],'encoding_groups':shared,'legend_groups':[]}}
    return validate_bindings(result,registry,executable=True)


def build_single_bindings(layout,portrayal,bundle,registry=None):
    frame=one_item([f for f in layout['frames'] if f['type']=='map'],'id')
    source=one_item(bundle['role_bindings'],'source_id')
    return build_page_bindings(layout,portrayal,bundle,[{'id':frame['content_id'],'source_id':source['source_id']}],registry)
