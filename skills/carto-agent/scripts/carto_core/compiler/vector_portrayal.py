"""S2 deterministic vector encodings. Values never come from layout or renderer.

Explicit categories, explicit class intervals and area-proportional circles only.
No inferred units, joins, quantiles, density computation, clipping or recoloring.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def compiler_digest():
    root = Path(__file__).resolve().parents[3]
    return sha256_digest({'version': '1.0.0', 'files': {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
        [Path(__file__), root / 'schemas/vector-encoding.schema.json', root / 'schemas/resolved-portrayal.schema.json']}})


_KEY_MODE = {'single': 'discrete', 'categorical': 'discrete',
             'choropleth': 'interval', 'proportional': 'scaling'}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _key(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ProtocolError('VECTOR_CATEGORY_TYPE', 'Categories require exact strings or integers')
    return type(value).__name__, value


def validate_encoding(encoding, registry=None):
    (registry or SchemaRegistry()).validate('vector-encoding', encoding)
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ProtocolError('VECTOR_ENCODING_INVALID', 'Encoding contains a nonfinite number')
        if isinstance(value, dict):
            for item in value.values():finite(item)
        elif isinstance(value, list):
            for item in value:finite(item)
    finite(encoding)
    kind = encoding['kind']
    if kind == 'categorical':
        categories = encoding['categories']
        if len({_key(c['value']) for c in categories}) != len(categories):
            raise ProtocolError('VECTOR_CATEGORY_DUPLICATE', 'Category codes must be unique')
        if len({c['label'] for c in categories}) != len(categories):
            raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Category labels must be unique')
        if len({c['symbol']['color'] for c in categories}) != len(categories):
            raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Category fill colors must be distinct')
    if kind == 'choropleth':
        edges = encoding['edges']
        if any(a >= b for a, b in zip(edges, edges[1:])):
            raise ProtocolError('VECTOR_BREAKS_INVALID', 'Class edges must be strictly increasing')
        if len(encoding['symbols']) != len(edges) - 1 or len(encoding['labels']) != len(edges) - 1:
            raise ProtocolError('VECTOR_BREAKS_INVALID', 'Each interval requires one symbol and label')
        if len(set(encoding['labels'])) != len(encoding['labels']) or len({s['color'] for s in encoding['symbols']}) != len(encoding['symbols']):
            raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Class labels and colors must be distinct')
    if kind == 'proportional':
        values = encoding['legend_values']
        if values != sorted(set(values)) or values[-1] > encoding['maximum_value']:
            raise ProtocolError('VECTOR_SIZE_LEGEND_INVALID', 'Representative values must be increasing and in domain')
        if encoding['minimum_radius_mm'] >= encoding['maximum_radius_mm']:
            raise ProtocolError('VECTOR_SIZE_RANGE_INVALID', 'Minimum visible radius must be below maximum')
        for value in values: radius(encoding, value)
    return encoding


def radius(encoding, value):
    if not _number(value) or value < 0 or value > encoding['maximum_value']:
        raise ProtocolError('VECTOR_SIZE_DOMAIN', 'Value must be finite, nonnegative and within declared domain')
    if value == 0:return 0.0
    result = encoding['maximum_radius_mm'] * math.sqrt(value / encoding['maximum_value'])
    if result <= 0 or result < max(0.000001, encoding['minimum_radius_mm']):
        raise ProtocolError('VECTOR_SIZE_UNREADABLE', 'Positive symbol is below the declared minimum; no clamping')
    return result


def _size_symbol(encoding, value):
    result = deepcopy(encoding['symbol'])
    result['radius_mm'] = radius(encoding, value)
    return result


def resolve_features(prepared, encoding, registry=None):
    validate_encoding(encoding, registry)
    if prepared['geometry'] != encoding['geometry']:
        raise ProtocolError('VECTOR_EXPRESSION_GEOMETRY', 'Expression geometry differs from the source')
    kind = encoding['kind']
    definitions = []
    if kind == 'single':definitions = [{'id': 'single', 'label': encoding['label'], 'symbol': encoding['symbol']}]
    if kind == 'categorical':definitions = [{'id': f'class-{i}', 'label': row['label'], 'symbol': row['symbol']}
                                           for i, row in enumerate(encoding['categories'])]
    if kind == 'choropleth':definitions = [{'id': f'class-{i}', 'label': f"{label}: [{encoding['edges'][i]:g}, {encoding['edges'][i+1]:g}{']' if i == len(encoding['edges'])-2 else ')'} {encoding['unit']}", 'symbol': sym}
                                          for i, (label, sym) in enumerate(zip(encoding['labels'], encoding['symbols']))]
    if kind == 'proportional':definitions = [{'id': f'size-{i}', 'label': f"{value:g} {encoding['unit']}",
                                            'symbol': _size_symbol(encoding, value)} for i, value in enumerate(encoding['legend_values'])]
    missing = {'id': 'missing', 'label': encoding['missing']['label'], 'symbol': encoding['missing']['symbol']}
    styles, observed = [], set()
    counts = dict.fromkeys(('feature_count', 'visible_count', 'missing_count', 'zero_count'), 0)
    keys = {_key(row['value']): index for index, row in enumerate(encoding.get('categories', []))}
    for feature in prepared['features']:
        counts['feature_count'] += 1
        value = feature['properties'].get(encoding['field']) if encoding['field'] else None
        legend_id, symbol = None, None
        if kind != 'single' and value is None:
            counts['missing_count'] += 1
            if encoding['missing']['policy'] == 'reject':
                raise ProtocolError('VECTOR_VALUE_MISSING', 'The required value is absent; no imputation')
            legend_id, symbol = 'missing', missing['symbol']
        elif kind == 'single':legend_id, symbol = 'single', encoding['symbol']
        elif kind == 'categorical':
            key = _key(value)
            if key not in keys:
                raise ProtocolError('VECTOR_CATEGORY_UNKNOWN', 'A value has no explicit category definition')
            index = keys[key]; legend_id, symbol = f'class-{index}', encoding['categories'][index]['symbol']
        elif kind == 'choropleth':
            edges = encoding['edges']
            if not _number(value) or not edges[0] <= value <= edges[-1]:
                raise ProtocolError('VECTOR_BREAK_DOMAIN', 'Value is nonnumeric or outside explicit class edges')
            index = next(i for i in range(len(edges) - 1) if value < edges[i + 1] or i == len(edges) - 2)
            legend_id, symbol = f'class-{index}', encoding['symbols'][index]
        else:
            size = radius(encoding, value)
            if size == 0:counts['zero_count'] += 1
            else:symbol = _size_symbol(encoding, value)
        if symbol is not None:
            counts['visible_count'] += 1
            if legend_id:observed.add(legend_id)
            style = {'symbol': deepcopy(symbol), 'legend_id': legend_id}
        else:style = None
        styles.append({'feature_id': feature['id'], 'style': style})
    if not counts['visible_count']:
        raise ProtocolError('VECTOR_EMPTY_MAP', 'No feature would be drawn')
    if kind == 'categorical' and encoding['legend_policy'] == 'observed':
        definitions = [entry for entry in definitions if entry['id'] in observed]
    if 'missing' in observed:definitions.append(missing)
    if len({item['label'] for item in definitions}) != len(definitions):
        raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Missing-value legend duplicates a class label')
    for entry in definitions:
        entry['shape'] = 'circle' if encoding['geometry'] == 'point' else 'square'
    return {'feature_styles': styles, 'legend_items': deepcopy(definitions), 'counts': counts}


class VectorPortrayalCompiler:
    def __init__(self, preparation):self.preparation = preparation

    def compile(self, prepared_ref, encoding, context):
        report = self.preparation.load_verified(prepared_ref, context)
        body = {'schema_version': 1, 'kind': 'resolved-portrayal', 'geometry': 'vector',
                'key_mode': _KEY_MODE[encoding['kind']], 'compiler_version': '1.0.0',
                'prepared_ref': deepcopy(prepared_ref),
                'encoding': deepcopy(encoding), **resolve_features(report, encoding, self.preparation.registry),
                'compiler_digest': compiler_digest()}
        return self.preparation.save('resolved-portrayal', body)

    def load_verified(self, ref, context):
        value = self.preparation.document(ref, 'resolved-portrayal')
        report = self.preparation.load_verified(value['prepared_ref'], context)
        expected = {**value, **resolve_features(report, value['encoding'], self.preparation.registry),
                    'compiler_digest': compiler_digest()}
        if expected != value:
            raise ProtocolError('VECTOR_PORTRAYAL_CHANGED', 'Resolved encoding differs from frozen inputs')
        return value, report


def shared_legend(portrayals):
    if not portrayals:raise ProtocolError('VECTOR_SHARED_LEGEND', 'At least one portrayal is required')
    encoding = portrayals[0]['encoding']
    if any(item['encoding'] != encoding for item in portrayals):
        raise ProtocolError('VECTOR_SHARED_ENCODING_MISMATCH', 'Shared legends require identical units, categories, edges and scales')
    entries = {}
    for portrayal in portrayals:
        for entry in portrayal['legend_items']:
            if entry['id'] in entries and entry != entries[entry['id']]:
                raise ProtocolError('VECTOR_SHARED_ENCODING_MISMATCH', 'Legend symbols differ')
            entries[entry['id']] = deepcopy(entry)
    def order(key):
        if key == 'missing':return 999
        if key == 'single':return 0
        return int(key.rsplit('-', 1)[1])
    return [entries[key] for key in sorted(entries, key=order)]
