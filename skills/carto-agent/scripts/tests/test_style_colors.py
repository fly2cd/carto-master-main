# -*- coding: utf-8 -*-
"""裁决5 style role-color lift tests + Path A integration.

The resolver lifts a reusable Style's discrete role colors through an instance role↔value
binding into the value→color category_colors authority. These tests isolate the lift
contract and prove the lifted colors drive Path A preparation resolution end to end.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.style_colors import resolve_style_category_colors, style_discrete_colors
from carto_core.compiler.raster_portrayal import resolve_classes
from carto_core.errors import ProtocolError


def _style():
    return {
        "symbol_roles": [
            {"role_id": "forest", "geometry_role": "raster-cell", "key_mode": "discrete",
             "symbol": {"color": "#1F611F"}},
            {"role_id": "water", "geometry_role": "raster-cell", "key_mode": "discrete",
             "symbol": {"color": "#3C2FD5"}},
            {"role_id": "continuous-ramp", "geometry_role": "raster-cell", "key_mode": "interval",
             "symbol": {"color": "#FFFFFF"}},
        ]
    }


class StyleColorLiftTests(unittest.TestCase):
    def test_lift_is_value_keyed_and_ordered(self):
        result = resolve_style_category_colors(_style(), {"water": 2, "forest": 1})
        self.assertEqual([{"value": 1, "color": "#1F611F"},
                          {"value": 2, "color": "#3C2FD5"}], result)

    def test_non_discrete_roles_are_ignored(self):
        self.assertEqual({"forest": "#1F611F", "water": "#3C2FD5"},
                         style_discrete_colors(_style()))

    def test_lowercase_color_is_normalized(self):
        style = {"symbol_roles": [{"role_id": "forest", "geometry_role": "raster-cell",
                                   "key_mode": "discrete", "symbol": {"color": "#1f611f"}}]}
        self.assertEqual([{"value": 1, "color": "#1F611F"}],
                         resolve_style_category_colors(style, {"forest": 1}))

    def test_bound_role_without_color_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "STYLE_ROLE_COLOR_MISSING"):
            resolve_style_category_colors(_style(), {"unknown-role": 1})

    def test_two_roles_binding_same_value_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "STYLE_ROLE_BINDING_CONFLICT"):
            resolve_style_category_colors(_style(), {"forest": 1, "water": 1})

    def test_empty_binding_yields_empty(self):
        self.assertEqual([], resolve_style_category_colors(_style(), {}))

    def test_lifted_colors_drive_path_a_preparation(self):
        category_colors = resolve_style_category_colors(_style(), {"forest": 1, "water": 2})
        request = {"schema_version": 1, "legend": {"color_column": None},
                   "palette": None, "legend_policy": "observed",
                   "category_colors": category_colors}
        legend = [{"value": 1, "label": "Forest", "color": None, "order": 0},
                  {"value": 2, "label": "Water", "color": None, "order": 1}]
        statistics = {"classes": [{"value": 1, "count": 5}, {"value": 2, "count": 3}]}
        rows, questions = resolve_classes(request, legend, statistics)
        self.assertEqual([], questions)
        self.assertEqual("#1F611F", rows[0]["color"])
        self.assertEqual("#3C2FD5", rows[1]["color"])


if __name__ == "__main__":
    unittest.main()