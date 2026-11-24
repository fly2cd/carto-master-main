# -*- coding: utf-8 -*-
"""Phase 2 reference intake + proposal->segment-design assembly tests."""
from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from PIL import Image

from carto_core.errors import ProtocolError, SecurityError
from carto_core.security.paths import PathGuard
from carto_core.schema_registry import SchemaRegistry
from carto_core.scenarios.general_thematic.raster import layout_contract, style_contract
from carto_core.workflow.reference_intake import assemble_segment_design, intake_reference


def _png(width=32, height=32, fmt="PNG"):
    img = Image.new("RGB", (width, height), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="carto-intake-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "reference.png"
        self.image.write_bytes(_png())
        self.guard = PathGuard([self.root])
        self.registry = SchemaRegistry()

    def test_intake_freezes_source_evidence(self):
        record, raw = intake_reference(self.guard, self.image, intake_id="intake-1",
                                       license="CC-BY-4.0", registry=self.registry)
        self.assertEqual("PNG", record["format"])
        self.assertEqual((32, 32), (record["width_px"], record["height_px"]))
        self.assertEqual(len(raw), record["byte_size"])
        self.assertEqual("CC-BY-4.0", record["license"])
        self.assertTrue(record["source_image"]["digest"].startswith("sha256:"))
        self.registry.validate("reference-intake", record)

    def test_intake_rejects_oversized_bytes(self):
        with self.assertRaisesRegex(SecurityError, "REFERENCE_SIZE_INVALID"):
            intake_reference(self.guard, self.image, intake_id="i", license="x", max_bytes=1)

    def test_intake_rejects_pixel_limit(self):
        with self.assertRaisesRegex(SecurityError, "REFERENCE_PIXEL_LIMIT_EXCEEDED"):
            intake_reference(self.guard, self.image, intake_id="i", license="x", max_pixels=1)

    def test_intake_rejects_unsupported_format(self):
        gif = self.root / "reference.gif"
        gif.write_bytes(_png(fmt="GIF"))
        with self.assertRaisesRegex(ProtocolError, "REFERENCE_FORMAT_UNSUPPORTED"):
            intake_reference(self.guard, gif, intake_id="i", license="x")

    def test_intake_rejects_path_outside_allowed_roots(self):
        outside = Path(self.temp.name).parent / "outside-reference.png"
        outside.write_bytes(_png())
        self.addCleanup(outside.unlink)
        with self.assertRaises(SecurityError):
            intake_reference(self.guard, outside, intake_id="i", license="x")

    def test_intake_digest_matches_frozen_bytes(self):
        import hashlib
        record, raw = intake_reference(self.guard, self.image, intake_id="intake-digest",
                                       license="CC-BY-4.0", registry=self.registry)
        self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(),
                         record["source_image"]["digest"])


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.base_style = style_contract()
        self.base_layout = layout_contract()

    def test_style_assembly_applies_recovered_typography(self):
        typo = {"title_pt": 20, "body_pt": 9, "legend_pt": 10,
                "legend_heading_pt": 11, "line_spacing": 1.25}
        proposal = {"recovered": {"typography": typo}}
        design = assemble_segment_design(proposal, kind="map-style",
                                         base_design=self.base_style, registry=self.registry)
        self.assertEqual(typo, design["typography"])
        self.registry.validate("style", design)

    def test_style_assembly_rejects_incomplete_typography(self):
        proposal = {"recovered": {"typography": {"title_pt": 20}}}
        with self.assertRaises(ProtocolError):
            assemble_segment_design(proposal, kind="map-style",
                                    base_design=self.base_style, registry=self.registry)

    def test_layout_assembly_uses_recovered_layout(self):
        layout = self.base_layout
        proposal = {"recovered": {"layout": layout}}
        design = assemble_segment_design(proposal, kind="map-layout",
                                         base_design=self.base_layout, registry=self.registry)
        self.assertEqual(layout, design)
        self.registry.validate("layout", design)

    def test_assembly_rejects_unknown_kind(self):
        with self.assertRaisesRegex(ProtocolError, "SEGMENT_KIND_UNSUPPORTED"):
            assemble_segment_design({"recovered": {}}, kind="map-scenario",
                                    base_design=self.base_style, registry=self.registry)


if __name__ == "__main__":
    unittest.main()