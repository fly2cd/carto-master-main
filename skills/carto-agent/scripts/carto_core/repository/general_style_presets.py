"""General-purpose Style presets (reusable map-style segments).

Appearance contracts (typography hierarchy, color system, labeling, defaults) that
pair with the general single-map layouts. Scenario-agnostic: they carry no business
vocabulary or data semantics — only visual-role appearance (field-mapping Style
authority). Reusable across business scenarios via segment_refs / replaceable style.

Each preset pins a registered symbol catalog (ramp) so the appearance is executable,
not merely schema-legal. visual_language / color_system / typography vary to give a
small coherent starting set (not an exhaustive taxonomy).
"""
from __future__ import annotations

from typing import Any

_TYPO = {
    "technical": {"title_pt": 18, "body_pt": 9, "legend_pt": 10, "legend_heading_pt": 11, "line_spacing": 1.25},
    "statistical": {"title_pt": 20, "body_pt": 10, "legend_pt": 10, "legend_heading_pt": 12, "line_spacing": 1.3},
    "minimal": {"title_pt": 16, "body_pt": 8, "legend_pt": 9, "legend_heading_pt": 10, "line_spacing": 1.2},
    "editorial": {"title_pt": 22, "body_pt": 11, "legend_pt": 11, "legend_heading_pt": 12, "line_spacing": 1.35},
}


def general_style(language: str = "technical", *, version: str = "1.0.0") -> dict[str, Any]:
    """Build one general Style preset for a visual language."""
    if language not in _TYPO:
        raise ValueError(f"unsupported visual language {language}")
    color_system = "sequential" if language == "statistical" else "qualitative"
    ramp = "ramps/test-theme@1.0.0" if color_system == "sequential" else "ramps/categorical-raster@1.0.0"
    return {
        "schema_version": 2,
        "style_id": f"general-style-{language}",
        "version": version,
        "visual_language": language,
        "symbolization": {"color_system": color_system, "symbol_catalogs": [ramp],
                          "default_opacity": 1.0},
        "labeling": {"density": "low" if language == "minimal" else "medium",
                     "collision_policy": "avoid", "font_role": "body"},
        "generalization": {"scale_dependent": False, "strategy": "none"},
        "defaults": {"opacity": 1.0, "line_width_mm": 0.2, "point_size_mm": 3},
        "typography": dict(_TYPO[language]),
        "rules": [],
    }


def all_general_styles() -> dict[str, dict[str, Any]]:
    return {f"general-style-{lang}": general_style(lang)
            for lang in ("technical", "statistical", "minimal", "editorial")}