# -*- coding: utf-8 -*-
"""Phase 3 mechanical scale-bar computation tests (data-independent core)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.scale_bar import compute_scale_bar
from carto_core.errors import ProtocolError


class ScaleBarComputationTests(unittest.TestCase):
    def test_nice_round_distance_and_km_label(self):
        bar = compute_scale_bar(100000.0, 1000.0, 200.0)
        self.assertEqual(20000.0, bar["distance_m"])
        self.assertEqual("20 km", bar["distance_label"])
        self.assertEqual(200.0, bar["length_px"])
        self.assertEqual("scale", bar["content_id"])

    def test_bar_exactly_represents_distance_at_map_scale(self):
        bar = compute_scale_bar(10000.0, 1000.0, 300.0)
        ground_per_px = 10000.0 / 1000.0
        self.assertAlmostEqual(bar["length_px"] * ground_per_px, bar["distance_m"], places=3)
        self.assertEqual("2 km", bar["distance_label"])

    def test_metre_label_for_small_ground_distance(self):
        bar = compute_scale_bar(500.0, 1000.0, 200.0)
        self.assertEqual(100.0, bar["distance_m"])
        self.assertEqual("100 m", bar["distance_label"])

    def test_bar_never_exceeds_frame_width(self):
        for frame in (50.0, 123.0, 400.0):
            bar = compute_scale_bar(98765.0, 1000.0, frame)
            self.assertLessEqual(bar["length_px"], frame + 1e-6)

    def test_max_fraction_caps_bar(self):
        bar = compute_scale_bar(100000.0, 1000.0, 200.0, max_fraction=0.5)
        self.assertLessEqual(bar["length_px"], 100.0 + 1e-6)
        self.assertEqual("10 km", bar["distance_label"])

    def test_deterministic(self):
        a = compute_scale_bar(123456.0, 800.0, 250.0)
        b = compute_scale_bar(123456.0, 800.0, 250.0)
        self.assertEqual(a, b)

    def test_invalid_inputs_rejected(self):
        for args in ((0.0, 1000.0, 200.0), (100000.0, -1.0, 200.0),
                     (100000.0, 1000.0, float("inf")), (100000.0, 1000.0, 0.0)):
            with self.assertRaisesRegex(ProtocolError, "SCALE_BAR_INPUT_INVALID"):
                compute_scale_bar(*args)

    def test_invalid_max_fraction_rejected(self):
        for fraction in (0.0, -0.5, 1.5, float("nan")):
            with self.assertRaisesRegex(ProtocolError, "SCALE_BAR_INPUT_INVALID"):
                compute_scale_bar(100000.0, 1000.0, 200.0, max_fraction=fraction)


if __name__ == "__main__":
    unittest.main()