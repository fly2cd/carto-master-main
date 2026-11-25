"""Shared reference-design image symbol scaling (P6 §13.2, Option 1).

Reusable expression infrastructure for image-coordinate symbol domains. Symbol
sizes are declared in *reference-design pixels* at a fixed reference canvas; the
effective symbol scale is floored at 1.0 and derived from the display window
relative to that reference. Physical page furniture (pt / mm) does NOT participate
in this scale — it travels through the separate physical-unit conversion point
(image_layout / image_page_renderer).

This module owns the mechanism, not any business scenario's grouping, numbering or
stop semantics. A scenario consumes ``symbol_scale`` / ``scale_symbol_px`` and
supplies its own business bindings; the shared kernel never imports a scenario.

Domain discipline (plan §13.5):
  reference-design px  --symbol_scale-->  effective symbol px (floored at 1.0)
  physical pt / mm     --NOT scaled here-->  image_layout single conversion point
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProtocolError

# A3 landscape reference design at 144 DPI. The reference canvas is a fixed design
# fact, not a per-request parameter; symbol sizes are authored against it.
REFERENCE_WIDTH_PX = 2381
REFERENCE_HEIGHT_PX = 1684

# P6 field-mapping §2.2 / X03: the baseline measurement rule (U) is an EXPLICIT
# adopted preset, not an implicit universal constant. It reproduces the historical
# reference-design pixel behavior (2381x1684, scale floor 1.0, min-ratio function).
# A consumer adopts a rule by precise reference; this dict is the registered baseline
# preset value, validated against the measurement-rule schema.
BASELINE_MEASUREMENT_RULE: dict[str, Any] = {
    "schema_version": 1,
    "rule_id": "reference-design-a3-144dpi",
    "version": "1.0.0",
    "reference_width_px": REFERENCE_WIDTH_PX,
    "reference_height_px": REFERENCE_HEIGHT_PX,
    "scale_floor": 1.0,
    "scale_function": "min-ratio-floor",
}


def scale_for_rule(window: dict[str, Any], rule: dict[str, Any]) -> float:
    """Effective symbol scale for a display window under an explicit measurement rule.

    The rule declares the reference canvas, scale function and floor. Only the
    registered ``min-ratio-floor`` function is admitted: max(floor, min(w/ref_w,
    h/ref_h)). Unknown functions or invalid rules are refused — the backend never
    substitutes its own reference canvas (field-mapping §8.4).
    """
    if not isinstance(rule, dict) or rule.get("scale_function") != "min-ratio-floor":
        raise ProtocolError("MEASUREMENT_RULE_UNSUPPORTED", "only min-ratio-floor is admitted")
    ref_w = rule.get("reference_width_px")
    ref_h = rule.get("reference_height_px")
    floor = rule.get("scale_floor")
    if (not isinstance(ref_w, (int, float)) or isinstance(ref_w, bool)
            or not isinstance(ref_h, (int, float)) or isinstance(ref_h, bool)
            or not isinstance(floor, (int, float)) or isinstance(floor, bool)
            or not math.isfinite(ref_w) or not math.isfinite(ref_h) or not math.isfinite(floor)
            or ref_w <= 0 or ref_h <= 0 or floor < 0):
        raise ProtocolError("MEASUREMENT_RULE_INVALID", "positive finite reference and nonnegative floor required")
    width, height = window.get("width"), window.get("height")
    if (isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, (int, float)) or not isinstance(height, (int, float))
            or not math.isfinite(width) or not math.isfinite(height)
            or width <= 0 or height <= 0):
        raise ProtocolError("IMAGE_SYMBOL_WINDOW_INVALID", "positive finite window required")
    return max(floor, min(width / ref_w, height / ref_h))


def symbol_scale(window: dict[str, Any], *,
                 rule: dict[str, Any] | None = None) -> float:
    """Effective symbol scale, floored per the adopted measurement rule.

    Defaults to the registered baseline preset (explicit, documented). A consumer
    that adopts a different precise rule passes it; the floor means symbols never
    shrink below their reference-design size for smaller windows.
    """
    return scale_for_rule(window, BASELINE_MEASUREMENT_RULE if rule is None else rule)


def scale_symbol_px(value: float, scale: float) -> float:
    """Scale one reference-design pixel symbol value to effective pixels."""
    return value * scale


def scale_symbol_dict(values: dict[str, Any], scale: float, *,
                      exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Scale the numeric reference-design pixel fields of a symbol config.

    Fields named in ``exclude`` (e.g. nested ``arrows`` handled separately, or
    non-pixel metadata) pass through unchanged. Only numeric values are scaled;
    the caller decides which keys belong to the reference-pixel symbol domain.
    """
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in exclude:
            result[key] = value
        elif isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float)):
            result[key] = value * scale
        else:
            result[key] = value
    return result