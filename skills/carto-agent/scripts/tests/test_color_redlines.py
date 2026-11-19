"""Colour redline tests: published-formula anchors, falsification anchors,
policy gate, and the continuous-path integration (no rendering extras needed).

Color math anchors come from published sources (CIE 15, WCAG 2.2, Machado 2009);
threshold calibration evidence: projects/.carto-dev/_cr_calibrate.py.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core import color_science
from carto_core.color_science import contrast_ratio, delta_e76, relative_luminance, simulate_cvd, srgb_to_lab
from carto_core.compiler.color_checks import (
    ColorRedlinesPolicy, check_color_sequence, check_ramp, default_policy_path, enforce,
)
from carto_core.errors import ProtocolError
from carto_core.repository import template_matching
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES

BLUES = ["#08306B", "#2171B5", "#4292C6", "#6BAED6", "#9ECAE1"]  # ColorBrewer Blues 5 (test RAMP)
RAINBOW = ["#FF0000", "#FFA500", "#FFFF00", "#008000", "#0000FF"]
RDBU = ["#B2182B", "#EF8A62", "#F7F7F7", "#67A9CF", "#2166AC"]  # ColorBrewer RdBu 5 (diverging)


def make_policy(**overrides) -> ColorRedlinesPolicy:
    policy = ColorRedlinesPolicy.load()
    return replace(policy, **overrides) if overrides else policy


class ColorScienceTests(unittest.TestCase):
    def test_known_values(self) -> None:
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0)
        self.assertAlmostEqual(contrast_ratio("#3296FA", "#3296FA"), 1.0)
        self.assertAlmostEqual(srgb_to_lab("#000000")[0], 0.0, places=4)
        self.assertAlmostEqual(srgb_to_lab("#FFFFFF")[0], 100.0, places=4)
        self.assertAlmostEqual(delta_e76("#000000", "#FFFFFF"), 100.0, places=4)

    def test_cvd_model_invariants(self) -> None:
        # Machado severity-1.0 matrices have unit row sums: white and neutral
        # grey are preserved exactly — a mechanical invariant of the model.
        for kind in ("protanopia", "deuteranopia"):
            self.assertEqual(simulate_cvd("#FFFFFF", kind), "#FFFFFF")
            self.assertEqual(simulate_cvd("#777777", kind), "#777777")
        # Protanopes see pure red as a dark olive (published behaviour):
        # luminance drops substantially and the hue moves toward yellow.
        sim = simulate_cvd("#FF0000", "protanopia")
        self.assertLess(relative_luminance(sim), 0.75 * relative_luminance("#FF0000"))
        r, g, b = (int(sim[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, g)
        self.assertGreater(g, b)

    def test_unknown_cvd_kind_rejected(self) -> None:
        with self.assertRaises(KeyError):
            simulate_cvd("#FF0000", "tritanomaly")

    def test_matching_reexport_is_single_source(self) -> None:
        self.assertIs(template_matching.delta_e76, color_science.delta_e76)
        self.assertIs(template_matching.hex_to_rgb, color_science.hex_to_rgb)


class RedlineCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = make_policy()

    def test_legitimate_ramps_pass_all_redlines(self) -> None:
        self.assertEqual(check_ramp(BLUES, "sequential", self.policy), [])
        self.assertEqual(check_ramp(list(reversed(BLUES)), "sequential", self.policy), [])
        self.assertEqual(check_ramp(RDBU, "diverging", self.policy), [])

    def test_rainbow_sequential_is_rejected(self) -> None:
        findings = check_ramp(RAINBOW, "sequential", self.policy)
        codes = [f["code"] for f in findings]
        self.assertIn("COLOR_RAMP_NOT_MONOTONIC", codes)
        with self.assertRaises(ProtocolError) as caught:
            enforce(findings)
        self.assertEqual(caught.exception.code, "COLOR_RAMP_NOT_MONOTONIC")

    def test_inverted_diverging_is_rejected(self) -> None:
        # A sequential ramp declared diverging has no light central critical point.
        findings = check_ramp(BLUES, "diverging", self.policy)
        self.assertIn("COLOR_RAMP_DIVERGING_INVALID", [f["code"] for f in findings])

    def test_unknown_scheme_rejected(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            check_ramp(BLUES, "qualitative", self.policy)
        self.assertEqual(caught.exception.code, "COLOR_RAMP_SCHEME_UNKNOWN")

    def test_adjacent_indistinguishable_is_rejected(self) -> None:
        findings = check_color_sequence(["#3296FA", "#3395F9"], self.policy)
        self.assertIn("COLOR_ADJACENT_INDISTINGUISHABLE", [f["code"] for f in findings])

    def test_red_green_pair_flagged_for_cvd_as_warning(self) -> None:
        # Normal-vision ΔE is huge (132.6) but deuteranopia collapses it to 10.92.
        findings = check_color_sequence(["#CC0000", "#00AA00"], self.policy)
        cvd = [f for f in findings if f["code"] == "COLOR_CVD_UNSAFE"]
        self.assertTrue(cvd)
        self.assertTrue(all(f["severity"] == "warning" for f in cvd))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            enforce(findings)  # warning must not block
        self.assertTrue(any("COLOR_CVD_UNSAFE" in str(w.message) for w in caught))

    def test_cvd_can_be_escalated_to_blocker_by_policy(self) -> None:
        strict = make_policy(cvd_safety="blocker")
        findings = check_color_sequence(["#CC0000", "#00AA00"], strict)
        with self.assertRaises(ProtocolError) as caught:
            enforce(findings)
        self.assertEqual(caught.exception.code, "COLOR_CVD_UNSAFE")

    def test_enforcement_off_and_thresholds_are_policy_driven(self) -> None:
        off = make_policy(ramp_semantics="off", adjacent_distinguishability="off", cvd_safety="off")
        self.assertEqual(check_ramp(RAINBOW, "sequential", off), [])
        loose = make_policy(adjacent_delta_e_min=0.1, cvd_delta_e_min=0.1)
        self.assertEqual(check_color_sequence(["#3296FA", "#3395F9"], loose), [])

    def test_short_sequences_are_noop(self) -> None:
        self.assertEqual(check_color_sequence([], self.policy), [])
        self.assertEqual(check_color_sequence(["#3296FA"], self.policy), [])
        self.assertEqual(check_ramp(["#3296FA"], "sequential", self.policy), [])


class RedlinesPolicyTests(unittest.TestCase):
    def test_packaged_policy_is_valid_and_pending(self) -> None:
        policy = ColorRedlinesPolicy.load()
        self.assertEqual(policy.confirmation_status, "pending-business-review")
        self.assertEqual(policy.ramp_semantics, "blocker")
        self.assertEqual(policy.cvd_safety, "warning")
        self.assertTrue(default_policy_path().is_file())

    def test_tampered_policy_rejected(self) -> None:
        registry = SchemaRegistry()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.yaml"
            mutations = ({"unknown_lever": True},
                         {"enforcement": {**VALID_CASES["color-redlines-policy"]["enforcement"],
                                           "cvd_safety": "sometimes"}},
                         {"adjacent_delta_e_min": 150.0},
                         {"confirmation_status": "approved"})
            for mutation in mutations:
                document = deepcopy(VALID_CASES["color-redlines-policy"])
                document.update(mutation)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                    ColorRedlinesPolicy.load(path, registry)


class ContinuousPathIntegrationTests(unittest.TestCase):
    """Exercises the real _continuous_encoding wiring without rendering extras."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        from carto_core.workflow.raster_preparation import RasterPreparationService
        self.service = RasterPreparationService(project_root=self.root,
                                                allowed_roots=[str(self.root)],
                                                registry=SchemaRegistry())

    def request_with(self, colors: list[str], scheme: str = "sequential") -> dict:
        return {"classification": {"method": "equal-interval", "class_count": 5},
                "color_ramp": {"scheme": scheme, "colors": colors},
                "measurement": "ratio", "unit": "m"}

    def test_blues_ramp_freezes_into_interval_encoding(self) -> None:
        encoding = self.service._continuous_encoding(self.request_with(BLUES), {"min": 0.0, "max": 10.0})
        self.assertEqual(encoding["key_mode"], "interval")
        self.assertEqual([s["color"] for s in encoding["channels"]["symbols"]], BLUES)

    def test_rainbow_ramp_fails_closed_before_freeze(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            self.service._continuous_encoding(self.request_with(RAINBOW), {"min": 0.0, "max": 10.0})
        self.assertEqual(caught.exception.code, "COLOR_RAMP_NOT_MONOTONIC")

    def test_class_count_mismatch_still_checked_first(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            self.service._continuous_encoding(self.request_with(BLUES[:4]), {"min": 0.0, "max": 10.0})
        self.assertEqual(caught.exception.code, "RASTER_RAMP_CLASS_MISMATCH")


if __name__ == "__main__":
    unittest.main()