"""ADR-001 stage 2/3: deterministic vector portrayal resolution on the encoding IR.

Geometry-agnostic IR primitives (validate_ir/ir_to_kind/radius/_size_symbol) now live in
portrayal_resolver.py (ADR-001 §9.5 item 1, removing the "vector_portrayal" naming
misunderstanding). This module keeps the vector-specific feature resolution, compiler and
shared-legend assembly, and re-exports the shared primitives so existing import sites keep
working during the stage-3 migration.

Explicit categories, explicit class intervals and area-proportional circles only.
No inferred units, joins, quantiles, density computation, clipping or recoloring.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
from pathlib import Path
from ..canonical import sha256_digest
from ..errors import ProtocolError
# ADR-001 stage 3: geometry-agnostic IR primitives live in portrayal_resolver (§9.5 item 1).
# metric_value joined them in Tier-2 去环 Step4 (it was reached up from workflow.thematic).
from .portrayal_resolver import validate_ir, radius, _size_symbol, _number, _key, metric_value


def compiler_digest():
    root = Path(__file__).resolve().parents[3]
    return sha256_digest({'version': '2.0.0', 'files': {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
        [Path(__file__), Path(__file__).resolve().parent / 'portrayal_resolver.py', Path(__file__).resolve().parent / 'thematic_design.py', Path(__file__).resolve().parents[1] / 'workflow/thematic.py', root / 'schemas/encoding-ir.schema.json', root / 'schemas/resolved-portrayal.schema.json']}})


def resolve_labels(report, label_source):
    # Select feature labels from the declared property field, with draw-ready anchors.
    # Point anchors are the coordinates; polygon anchors use shapely's
    # representative_point (a label-anchor query, not a derived geometry layer).
    # Missing/non-string/blank values are skipped, never invented.
    if not label_source:
        return None
    field = label_source["field"]
    from shapely.geometry import shape
    out = []
    for feature in report["features"]:
        text = feature["properties"].get(field)
        if not isinstance(text, str) or not text.strip():
            continue
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            anchor = [float(geometry["coordinates"][0]), float(geometry["coordinates"][1])]
        elif geometry["type"] in ("LineString", "MultiLineString"):
            mid = shape(geometry).interpolate(0.5, normalized=True)
            anchor = [float(mid.x), float(mid.y)]
        else:
            point = shape(geometry).representative_point()
            anchor = [float(point.x), float(point.y)]
        out.append({"feature_id": feature["id"], "text": text.strip(), "anchor": anchor})
        if label_source.get("max_labels") is not None and len(out) >= label_source["max_labels"]:
            break
    return out


def resolve_features(prepared, ir, registry=None):
    validate_ir(ir, registry)
    if prepared['geometry'] != ir['geometry_role']:
        raise ProtocolError('VECTOR_EXPRESSION_GEOMETRY', 'Expression geometry differs from the source')
    key_mode = ir['key_mode']
    symbols = ir['channels']['symbols']
    unit = ir['domain']['unit']
    field = ir['domain']['field']
    single = key_mode == 'discrete' and field is None
    definitions = []
    if single:definitions = [{'id': 'single', 'label': ir['legend']['uniform_label'], 'symbol': symbols[0]}]
    elif key_mode == 'discrete':definitions = [{'id': f'class-{i}', 'label': c['label'], 'symbol': symbols[i]}
                                               for i, c in enumerate(ir['scale']['categories'])]
    elif key_mode == 'interval':
        edges = ir['scale']['edges']
        definitions = [{'id': f'class-{i}', 'label': f"{label}: [{edges[i]:g}, {edges[i+1]:g}{']' if i == len(edges)-2 else ')'} {unit}", 'symbol': symbols[i]}
                       for i, label in enumerate(ir['scale']['labels'])]
    else:definitions = [{'id': f'size-{i}', 'label': f"{value:g} {unit}",
                         'symbol': _size_symbol(ir, value)} for i, value in enumerate(ir['scale']['legend_values'])]
    missing = {'id': 'missing', 'label': ir['missing']['label'], 'symbol': ir['missing'].get('symbol')}
    styles, observed = [], set()
    counts = dict.fromkeys(('feature_count', 'visible_count', 'missing_count', 'zero_count'), 0)
    keys = {_key(c['value']): i for i, c in enumerate(ir['scale']['categories'])} if (key_mode == 'discrete' and not single) else {}
    for feature in prepared['features']:
        counts['feature_count'] += 1
        value = metric_value(feature['properties'], ir['domain'])
        legend_id, symbol = None, None
        if not single and value is None:
            counts['missing_count'] += 1
            if ir['missing']['policy'] == 'reject':
                raise ProtocolError('VECTOR_VALUE_MISSING', 'The required value is absent; no imputation')
            legend_id, symbol = 'missing', missing['symbol']
        elif single:legend_id, symbol = 'single', symbols[0]
        elif key_mode == 'discrete':
            key = _key(value)
            if key not in keys:
                raise ProtocolError('VECTOR_CATEGORY_UNKNOWN', 'A value has no explicit category definition')
            index = keys[key]; legend_id, symbol = f'class-{index}', symbols[index]
        elif key_mode == 'interval':
            edges = ir['scale']['edges']
            if not _number(value) or not edges[0] <= value <= edges[-1]:
                raise ProtocolError('VECTOR_BREAK_DOMAIN', 'Value is nonnumeric or outside explicit class edges')
            index = next(i for i in range(len(edges) - 1) if value < edges[i + 1] or i == len(edges) - 2)
            legend_id, symbol = f'class-{index}', symbols[index]
        else:
            size = radius(ir, value)
            if size == 0:counts['zero_count'] += 1
            else:symbol = _size_symbol(ir, value)
        if symbol is not None:
            counts['visible_count'] += 1
            if legend_id:observed.add(legend_id)
            style = {'symbol': deepcopy(symbol), 'legend_id': legend_id}
        else:style = None
        styles.append({'feature_id': feature['id'], 'style': style})
    if not counts['visible_count']:
        raise ProtocolError('VECTOR_EMPTY_MAP', 'No feature would be drawn')
    if key_mode == 'discrete' and not single and ir['legend']['policy'] == 'observed':
        definitions = [entry for entry in definitions if entry['id'] in observed]
    if 'missing' in observed:definitions.append(missing)
    if len({item['label'] for item in definitions}) != len(definitions):
        raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Missing-value legend duplicates a class label')
    for entry in definitions:
        entry['shape'] = ('circle' if ir['geometry_role'] == 'point'
                     else 'line' if ir['geometry_role'] == 'line' else 'square')
    return {'feature_styles': styles, 'legend_items': deepcopy(definitions), 'counts': counts}


class VectorPortrayalCompiler:
    def __init__(self, preparation):self.preparation = preparation

    def compile(self, prepared_ref, ir, context, label_source=None):
        report = self.preparation.load_verified(prepared_ref, context)
        # Colour redlines: ordered class colours (discrete/interval) must stay
        # distinguishable before freezing; scaling encodes size, not colour order.
        if ir['key_mode'] in ('discrete', 'interval') and len(ir['channels']['symbols']) >= 2:
            from .color_checks import ColorRedlinesPolicy, check_color_sequence, enforce
            colors = [symbol['color'] for symbol in ir['channels']['symbols']]
            enforce(check_color_sequence(colors, ColorRedlinesPolicy.load(registry=self.preparation.registry)))
        body = {'schema_version': 1, 'kind': 'resolved-portrayal', 'geometry': 'vector',
                'key_mode': ir['key_mode'], 'compiler_version': '1.0.0',
                'prepared_ref': deepcopy(prepared_ref),
                'encoding': deepcopy(ir), **resolve_features(report, ir, self.preparation.registry),
                'compiler_digest': compiler_digest()}
        labels = resolve_labels(report, label_source)
        if labels is not None:
            body['label_source'] = deepcopy(label_source)
            body['labels'] = labels
        return self.preparation.save('resolved-portrayal', body)

    def load_verified(self, ref, context):
        value = self.preparation.document(ref, 'resolved-portrayal')
        report = self.preparation.load_verified(value['prepared_ref'], context)
        expected = {**value, **resolve_features(report, value['encoding'], self.preparation.registry),
                    'compiler_digest': compiler_digest()}
        if value.get('label_source'):
            expected['labels'] = resolve_labels(report, value['label_source'])
        if expected != value:
            raise ProtocolError('VECTOR_PORTRAYAL_CHANGED', 'Resolved encoding differs from frozen inputs')
        return value, report


def shared_legend(portrayals):
    if not portrayals:raise ProtocolError('VECTOR_SHARED_LEGEND', 'At least one portrayal is required')
    # The declared contract is identical units/categories/edges/scales (domain+scale+
    # key_mode). geometry_role and channel colors are layer-specific; per-entry
    # symbol consistency is enforced by the id-collision check below, so a
    # multi-geometry stack sharing one legend stays semantically verifiable.
    def _legend_key(ir):
        return {key: deepcopy(ir[key]) for key in ('key_mode', 'domain', 'scale') if key in ir}
    key = _legend_key(portrayals[0]['encoding'])
    if any(_legend_key(item['encoding']) != key for item in portrayals):
        raise ProtocolError('VECTOR_SHARED_ENCODING_MISMATCH', 'Shared legends require identical units, categories, edges and scales')
    entries = {}
    for portrayal in portrayals:
        for entry in portrayal['legend_items']:
            # Shape is derived from the layer's geometry family (square ground vs
            # circle figure); label/symbol/color must stay identical across layers.
            previous = entries.get(entry['id'])
            if previous is not None and ({k: v for k, v in previous.items() if k != 'shape'}
                                          != {k: v for k, v in entry.items() if k != 'shape'}):
                raise ProtocolError('VECTOR_SHARED_ENCODING_MISMATCH', 'Legend symbols differ')
            if previous is None:
                entries[entry['id']] = deepcopy(entry)
    def order(key):
        if key == 'missing':return 999
        if key == 'single':return 0
        return int(key.rsplit('-', 1)[1])
    return [entries[key] for key in sorted(entries, key=order)]
