# -*- coding: utf-8 -*-
"""Path A colour authority tests (plan 裁决1).

resolve_classes consumes an explicit category_colors authority resolved from a confirmed
Style before preparation. These unit tests isolate the resolution contract: single
authority, conflict rejection, answer colour-override rejection, missing-colour
clarification, preparation-time redlines, and zero regression of the legacy CSV/palette
path when category_colors is absent.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.raster_portrayal import PALETTE, resolve_classes
from carto_core.errors import ProtocolError


def _request(category_colors=None, palette=None, color_column=None):
    request = {
        "schema_version": 1,
        "legend": {"color_column": color_column},
        "palette": palette,
        "legend_policy": "observed",
    }
    if category_colors is not None:
        request["category_colors"] = category_colors
    return request


def _legend():
    return [
        {"value": 1, "label": "Forest", "color": None, "order": 0},
        {"value": 2, "label": "Water", "color": None, "order": 1},
    ]


def _statistics():
    return {"classes": [{"value": 1, "count": 5}, {"value": 2, "count": 3}]}


def _answers(color="#00FF00"):
    return {
        "schema_version": 1,
        "based_on_digest": "sha256:" + "a" * 64,
        "entries": [{"value": 1, "semantic": "class", "display": "color",
                     "label": "Forest", "color": color, "order": 0, "include_in_legend": True}],
    }


class PathAColorAuthorityTests(unittest.TestCase):
    def test_style_mode_colors_are_the_authority(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"},
                                            {"value": 2, "color": "#0000FF"}])
        rows, questions = resolve_classes(request, _legend(), _statistics())
        self.assertEqual([], questions)
        self.assertEqual("#FF0000", rows[0]["color"])
        self.assertEqual("#0000FF", rows[1]["color"])

    def test_conflicting_palette_is_rejected(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"}],
                           palette="carto-categorical-v1")
        with self.assertRaisesRegex(ProtocolError, "CLASSIFICATION_COLOR_AUTHORITY_CONFLICT"):
            resolve_classes(request, _legend(), _statistics())

    def test_conflicting_csv_color_column_is_rejected(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"}],
                           color_column="color")
        with self.assertRaisesRegex(ProtocolError, "CLASSIFICATION_COLOR_AUTHORITY_CONFLICT"):
            resolve_classes(request, _legend(), _statistics())

    def test_answers_must_not_replace_bound_colors(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"},
                                            {"value": 2, "color": "#0000FF"}])
        with self.assertRaisesRegex(ProtocolError, "CLASSIFICATION_ANSWER_COLOR_OVERRIDE"):
            resolve_classes(request, _legend(), _statistics(), _answers(color="#00FF00"))

    def test_missing_category_color_clarifies_not_autofill(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"}])
        rows, questions = resolve_classes(request, _legend(), _statistics())
        self.assertEqual("#FF0000", rows[0]["color"])
        self.assertIsNone(rows[1]["color"])
        self.assertIn("missing-color", {q["kind"] for q in questions})

    def test_legacy_palette_path_unchanged_without_category_colors(self):
        request = _request(palette="carto-categorical-v1")
        rows, questions = resolve_classes(request, _legend(), _statistics())
        self.assertEqual([], questions)
        self.assertEqual(PALETTE[0], rows[0]["color"])
        self.assertEqual(PALETTE[1], rows[1]["color"])

    def test_redline_blocker_enforced_at_preparation(self):
        request = _request(category_colors=[{"value": 1, "color": "#FF0000"},
                                            {"value": 2, "color": "#FE0000"}])
        with self.assertRaises(ProtocolError) as ctx:
            resolve_classes(request, _legend(), _statistics())
        self.assertIn("COLOR_", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()