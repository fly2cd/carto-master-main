"""Normalize declared appearance without choosing business colors or geometry."""
from __future__ import annotations
from copy import deepcopy
from ..artifacts import artifact_ref
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def resolve_appearance(cartography, layout, color_sources, registry=None):
    registry = registry or SchemaRegistry()
    registry.validate("cartography", cartography)
    registry.validate("layout", layout)
    if "content_padding_mm" not in layout:
        raise ProtocolError("PAGE_PADDING_REQUIRED", "The layout must declare content padding")
    typography = deepcopy(cartography["typography"])
    typography["padding_mm"] = layout["content_padding_mm"]
    result = {"schema_version": 2, "cartography": deepcopy(cartography),
              "style_ref": artifact_ref("cartography", cartography),
              "color_sources": deepcopy(color_sources), "typography": typography}
    registry.validate("resolved-appearance", result)
    return result


def require_appearance(appearance, layout, color_sources, registry=None):
    registry = registry or SchemaRegistry()
    registry.validate("resolved-appearance", appearance)
    if appearance != resolve_appearance(appearance["cartography"], layout, color_sources, registry):
        raise ProtocolError("APPEARANCE_BINDING_MISMATCH", "Appearance differs from declared sources")
