"""ADR-001 stage 3: geometry-agnostic encoding-IR resolution primitives.

These operate purely on the backend-independent encoding IR (schemas/encoding-ir.schema.json):
key_mode drives resolution (discrete lookup / interval breaks / continuous scaling) and is
decoupled from geometry_role. They previously lived in vector_portrayal.py despite being
geometry-agnostic -- the "vector_portrayal naming misunderstanding" that ADR-001 §9.5 item 1
removes. This module is the single portrayal resolver both the raster and vector compilers
depend on for IR-level resolution; geometry-specific data resolution (raster CSV class tables,
vector feature styles) stays in the execution layer per §9.3.

Values never come from layout or renderer. No inferred units, joins, quantiles, density
computation, clipping or recoloring.
"""
from __future__ import annotations

from copy import deepcopy
import math

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def ir_to_kind(ir):
    """Recover the legacy expression kind from an IR (for catalog reference & validation samples)."""
    key_mode = ir['key_mode']
    if key_mode == 'interval':
        return 'choropleth'
    if key_mode == 'scaling':
        return 'proportional'
    return 'single' if ir['domain']['field'] is None else 'categorical'


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _key(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ProtocolError('VECTOR_CATEGORY_TYPE', 'Categories require exact strings or integers')
    return type(value).__name__, value


def validate_ir(ir, registry=None):
    (registry or SchemaRegistry()).validate('encoding-ir', ir)
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ProtocolError('VECTOR_ENCODING_INVALID', 'Encoding contains a nonfinite number')
        if isinstance(value, dict):
            for item in value.values():finite(item)
        elif isinstance(value, list):
            for item in value:finite(item)
    finite(ir)
    key_mode = ir['key_mode']
    symbols = ir['channels']['symbols']
    if key_mode == 'discrete':
        if ir['domain']['field'] is None:
            if len(symbols) != 1:
                raise ProtocolError('VECTOR_ENCODING_INVALID', 'Single-symbol encoding requires exactly one symbol')
        else:
            categories = ir['scale']['categories']
            if len({_key(c['value']) for c in categories}) != len(categories):
                raise ProtocolError('VECTOR_CATEGORY_DUPLICATE', 'Category codes must be unique')
            if len({c['label'] for c in categories}) != len(categories):
                raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Category labels must be unique')
            if len(symbols) != len(categories):
                raise ProtocolError('VECTOR_ENCODING_INVALID', 'Each category requires exactly one symbol')
            if len({s['color'] for s in symbols}) != len(symbols):
                raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Category fill colors must be distinct')
    elif key_mode == 'interval':
        edges = ir['scale']['edges']
        if any(a >= b for a, b in zip(edges, edges[1:])):
            raise ProtocolError('VECTOR_BREAKS_INVALID', 'Class edges must be strictly increasing')
        if len(symbols) != len(edges) - 1 or len(ir['scale']['labels']) != len(edges) - 1:
            raise ProtocolError('VECTOR_BREAKS_INVALID', 'Each interval requires one symbol and label')
        if len(set(ir['scale']['labels'])) != len(ir['scale']['labels']) or len({s['color'] for s in symbols}) != len(symbols):
            raise ProtocolError('VECTOR_LEGEND_AMBIGUOUS', 'Class labels and colors must be distinct')
    else:
        scale = ir['scale']
        values = scale['legend_values']
        if values != sorted(set(values)) or values[-1] > scale['domain_max']:
            raise ProtocolError('VECTOR_SIZE_LEGEND_INVALID', 'Representative values must be increasing and in domain')
        if scale['range_mm'][0] >= scale['range_mm'][1]:
            raise ProtocolError('VECTOR_SIZE_RANGE_INVALID', 'Minimum visible radius must be below maximum')
        for value in values: radius(ir, value)
    return ir


def radius(ir, value):
    scale = ir['scale']
    domain_max = scale['domain_max']; max_r = scale['range_mm'][1]; min_r = scale['range_mm'][0]
    if not _number(value) or value < 0 or value > domain_max:
        raise ProtocolError('VECTOR_SIZE_DOMAIN', 'Value must be finite, nonnegative and within declared domain')
    if value == 0:return 0.0
    ratio = value / domain_max
    result = max_r * (ratio if scale.get('size_scale', 'sqrt') == 'linear' else math.sqrt(ratio))
    if result <= 0 or result < max(0.000001, min_r):
        raise ProtocolError('VECTOR_SIZE_UNREADABLE', 'Positive symbol is below the declared minimum; no clamping')
    return result


def _size_symbol(ir, value):
    result = deepcopy(ir['channels']['symbols'][0])
    result['radius_mm'] = radius(ir, value)
    return result
