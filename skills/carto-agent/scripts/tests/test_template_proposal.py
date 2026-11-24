# -*- coding: utf-8 -*-
"""Acceptance for the two create-template entry primitives (bounded, non-authoritative)."""
import io
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PIL import Image

from carto_core import color_science
from carto_core.canonical import sha256_digest
from carto_core.compiler import reference_extraction as rx
from carto_core.compiler.template_derivation import derive
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES

KNOWN = ["#FFF7BC", "#FEC44F", "#FE9929", "#CC4C02"]


def _reference_png() -> bytes:
    img = Image.new("RGB", (64, 64))
    for i, hexv in enumerate(KNOWN):
        r, g, b = (int(hexv[j:j + 2], 16) for j in (1, 3, 5))
        for y in range(16 * i, 16 * (i + 1)):
            for x in range(64):
                img.putpixel((x, y), (r, g, b))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class DeltaE2000Tests(unittest.TestCase):
    def test_sharma_2005_reference_pairs(self):
        pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                 ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
                 ((50, 2.8361, -74.0200), (50, 0, -82.7485), 3.4412),
                 ((50, -1.3802, -84.2814), (50, 0, -82.7485), 1.0000),
                 ((50, 0, 0), (50, -1, 2), 2.3669)]
        for a, b, expect in pairs:
            self.assertAlmostEqual(color_science.delta_e2000_lab(a, b), expect, delta=1e-3)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.png = _reference_png()
        self.registry = SchemaRegistry()

    def test_palette_round_trip_recovers_known_colors(self):
        got = rx.extract_palette(self.png, k=4)
        self.assertEqual(len(got), 4)
        self.assertLess(rx.round_trip_palette(self.png, got), 2.0)

    def test_extraction_is_deterministic(self):
        a = rx.extract_palette(self.png, k=4)
        b = rx.extract_palette(self.png, k=4)
        self.assertEqual(a, b)
        self.assertEqual(sha256_digest(a), sha256_digest(b))

    def test_proposal_validates_and_lists_unrecoverable(self):
        p = rx.extract_proposal(self.png, proposal_id="prop-1", license="CC-BY-4.0",
                                k=4, selected_segments=["style"])
        self.registry.validate("template-proposal", p)  # validation at boundary, not inside module
        self.assertEqual(p["kind"], "extract")
        fields = {u["field"] for u in p["unrecoverable"]}
        self.assertTrue({"crs", "data_role_refs", "layout.frames.bounds", "typography"} <= fields)
        self.assertTrue(all(u["requires_user"] for u in p["unrecoverable"]))
        self.assertEqual(p["confidence"]["layout"], 0.0)
        self.assertEqual(p["selected_segments"], ["style"])

    def test_proposal_requires_license_for_extract(self):
        p = rx.extract_proposal(self.png, proposal_id="prop-2", license="CC-BY-4.0",
                                k=4, selected_segments=["style"])
        bad = dict(p); bad.pop("license")
        with self.assertRaises(ProtocolError):
            self.registry.validate("template-proposal", bad)

    def test_module_is_independent_of_workflow_and_schema(self):
        # MCP-ready: the unit must not pull in registry/workflow/repository.
        self.assertFalse(hasattr(rx, "SchemaRegistry"))
        p = rx.extract_proposal(self.png, proposal_id="prop-3", license="CC-BY-4.0",
                                k=4, selected_segments=["style"])
        self.assertIsInstance(p, dict)  # pure dict, no validation side-effect

    def test_user_supplied_layout_and_typography_resolve_unrecoverable(self):
        layout = {"canvas": {"width": 420, "height": 297}, "frames": []}
        typo = {"title_pt": 18, "body_pt": 9}
        p = rx.extract_proposal(self.png, proposal_id="prop-4", license="CC-BY-4.0",
                                k=4, selected_segments=["style", "layout"],
                                user_layout=layout, user_typography=typo)
        self.assertEqual(p["recovered"]["layout"], layout)
        self.assertEqual(p["recovered"]["typography"], typo)
        # P2-2: user supply is a responsibility transfer, not a measurement -> confidence 0.
        self.assertEqual(p["confidence"]["layout"], 0.0)
        self.assertEqual(p["confidence"]["typography"], 0.0)
        self.assertEqual(p["field_sources"]["layout"], "user")
        self.assertEqual(p["field_sources"]["typography"], "user")
        fields = {u["field"] for u in p["unrecoverable"]}
        self.assertNotIn("layout.frames.bounds", fields)
        self.assertNotIn("typography", fields)
        self.registry.validate("template-proposal", p)

    def test_pluggable_backend_used_when_no_user_supply(self):
        p = rx.extract_proposal(self.png, proposal_id="prop-5", license="CC-BY-4.0",
                                k=4, selected_segments=["layout"],
                                layout_backend=lambda b: {"frames": ["detected"]})
        self.assertEqual(p["recovered"]["layout"], {"frames": ["detected"]})
        self.assertEqual(p["confidence"]["layout"], 0.6)
        self.assertEqual(p["field_sources"]["layout"], "backend")


class DerivationTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.base = VALID_CASES["style"]

    def test_derive_restricted_bumps_version_and_pins_base(self):
        new, base_ref = derive(self.base, {"typography": {**self.base["typography"], "title_pt": 20}},
                               schema="style", id_field="style_id", kind="map-style",
                               allowed_keys=("typography",), registry=self.registry)
        self.assertEqual(new["typography"]["title_pt"], 20)
        self.assertNotEqual(new["version"], self.base["version"])
        self.assertEqual(base_ref["digest"], sha256_digest(self.base))
        self.registry.validate("style", new)

    def test_derive_rejects_disallowed_key(self):
        with self.assertRaisesRegex(ProtocolError, "DERIVATION_KEY_FORBIDDEN"):
            derive(self.base, {"visual_language": "editorial"}, schema="style",
                   id_field="style_id", kind="map-style", allowed_keys=("typography",),
                   registry=self.registry)


if __name__ == "__main__":
    unittest.main()