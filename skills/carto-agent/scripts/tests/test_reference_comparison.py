# -*- coding: utf-8 -*-
"""Phase 2 round-trip three-way decomposition + redline deviation tests."""
from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from PIL import Image

from carto_core.compiler import reference_comparison as rc
from carto_core.compiler.reference_extraction import extract_palette


def _two_color_png() -> bytes:
    img = Image.new("RGB", (32, 32))
    for y in range(32):
        for x in range(32):
            img.putpixel((x, y), (31, 97, 31) if y < 16 else (60, 47, 213))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class RoundTripReportTests(unittest.TestCase):
    def setUp(self):
        self.png = _two_color_png()
        self.proposed = extract_palette(self.png, k=2)

    def test_faithful_render_has_low_recovery_and_implementation_error(self):
        report = rc.round_trip_report(self.png, self.png, proposed_colors=self.proposed)
        self.assertLess(report["recovery_error_delta_e2000"], 2.0)
        self.assertLess(report["implementation_error_delta_e2000"], 2.0)
        self.assertEqual(0.0, report["authorized_deviation_delta_e2000"])

    def test_authorized_recolor_is_attributed_to_deviation(self):
        effective = ["#FF0000", "#00FF00"]
        report = rc.round_trip_report(self.png, self.png, proposed_colors=self.proposed,
                                      effective_colors=effective)
        self.assertGreater(report["authorized_deviation_delta_e2000"], 0.0)

    def test_module_is_independent_of_schema_registry(self):
        self.assertFalse(hasattr(rc, "SchemaRegistry"))


class RedlineDeviationTests(unittest.TestCase):
    def test_safe_colors_need_no_authorization(self):
        result = rc.redline_deviation(["#1F611F", "#3C2FD5"])
        self.assertFalse(result["requires_authorization"])
        self.assertEqual([], result["blockers"])

    def test_blocker_colors_require_authorized_deviation(self):
        result = rc.redline_deviation(["#FF0000", "#FE0000"])
        self.assertTrue(result["requires_authorization"])
        self.assertTrue(result["blockers"])
        self.assertTrue(all(b["severity"] == "blocker" for b in result["blockers"]))


if __name__ == "__main__":
    unittest.main()