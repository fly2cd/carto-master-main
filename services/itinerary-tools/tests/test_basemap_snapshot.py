"""basemap_snapshot tests.

All tile fetching is mocked (fixed synthetic tile PNGs) — no network, no
Tianditu key. Determinism: same extent + dpi + tile bytes => byte-identical
PNG and a deterministic registration; the provenance timestamp is injectable.
"""
import io
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PIL import Image, ImageDraw

import basemap_snapshot as snapshot_module
from _service_utils import ServiceError
from basemap_snapshot import _select_zoom, basemap_snapshot

EXTENT = {"west": 119.97, "south": 29.97, "east": 120.03, "north": 30.03}


def _tile_bytes(color=(120, 160, 200)) -> bytes:
    image = Image.new("RGB", (256, 256), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _merc(x, y):
    r = 6378137.0
    return (x * math.pi * r / 180.0, r * math.log(math.tan(math.pi / 4 + math.radians(y) / 2)))


class SnapshotZoomTests(unittest.TestCase):
    def test_zoom_selection_is_deterministic_and_bounded(self):
        first = _select_zoom(EXTENT, 4096)
        self.assertEqual(first, _select_zoom(EXTENT, 4096))
        self.assertGreaterEqual(first, 0)
        self.assertLessEqual(first, 18)
        # A finer pixel-width target demands a finer (>=) zoom.
        self.assertGreaterEqual(_select_zoom(EXTENT, 8192), first)
        # Real-material regression (2026-11-21): a 248km-wide extent at a
        # frame-relative width must stay far below the tile budget (the old
        # print-native formula clamped to z18 and exploded to ~2M tiles).
        wide = {"west": 118.285933, "south": 29.13093, "east": 120.765109, "north": 30.62371}
        zoom = _select_zoom(wide, 4096)
        self.assertLess(zoom, 14)


class SnapshotToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        os.environ["CARTO_TIANDITU_KEY"] = "synthetic-key"
        self.addCleanup(os.environ.pop, "CARTO_TIANDITU_KEY", None)

    def _call(self, **overrides):
        arguments = {"extent": EXTENT, "output_path": "data/basemap-online.png",
                     "layer": "vec_w", "width_px": 4096,
                     "fetched_at": "2026-11-21T00:00:00+00:00"}
        arguments.update(overrides)
        return basemap_snapshot(arguments, {"allowed_root": self.root})

    def test_snapshot_is_deterministic(self):
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            first = self._call()
            second = self._call(output_path="data/basemap-online-2.png")
        self.assertEqual(first["status"], "complete")
        self.assertEqual((self.root / "data/basemap-online.png").read_bytes(),
                         (self.root / "data/basemap-online-2.png").read_bytes())
        self.assertEqual(first["registration"], second["registration"])
        self.assertEqual(first["provenance"]["tile_count"], second["provenance"]["tile_count"])
        self.assertEqual("Tianditu", first["provenance"]["provider"])
        self.assertEqual("vec_w", first["provenance"]["layer"])

    def test_registration_maps_extent_corners_to_pixel_corners(self):
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            result = self._call()
        registration = result["registration"]
        width, height = registration["source_size"]
        matrix = registration["local_km_y_down_to_pixel"]
        # top-left (0,0) <-> (west, north); bottom-right (w,h) <-> (east, south)
        for pixel, (lon, lat) in (((0, 0), (EXTENT["west"], EXTENT["north"])),
                                  ((width, height), (EXTENT["east"], EXTENT["south"]))):
            local_x_km = (pixel[0] - matrix[0][2]) / matrix[0][0]
            local_y_km = (pixel[1] - matrix[1][2]) / matrix[1][1]
            mx, my = _merc(lon, lat)
            merc_w = _merc(EXTENT["east"], 0)[0] - _merc(EXTENT["west"], 0)[0]
            tolerance = merc_w / registration["source_size"][0] + 0.5
            self.assertAlmostEqual(local_x_km * 1000 + registration["origin_m"][0], mx,
                                    delta=tolerance)
            self.assertAlmostEqual(registration["origin_m"][1] - local_y_km * 1000, my,
                                    delta=tolerance)

    def test_snapshot_tool_accepts_explicit_zoom(self):
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            result = self._call(zoom=6)
        self.assertEqual("complete", result["status"])
        self.assertEqual(6, result["provenance"]["zoom"])

    def test_missing_key_fails_closed(self):
        os.environ.pop("CARTO_TIANDITU_KEY", None)
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            with self.assertRaises(ServiceError) as raised:
                self._call()
        self.assertEqual("TIANDITU_KEY_MISSING", raised.exception.code)

    def test_output_path_confined_to_allowed_root(self):
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            with self.assertRaises(ServiceError) as raised:
                self._call(output_path=str(Path(self.root).parent / "outside.png"))
        self.assertEqual("PATH_OUTSIDE_ROOT", raised.exception.code)

    def test_extent_validation_rejects_unordered_bounds(self):
        with self.assertRaises(ServiceError) as raised:
            self._call(extent={"west": 120.03, "south": 29.97, "east": 119.97, "north": 30.03})
        self.assertEqual("EXTENT_INVALID", raised.exception.code)


class DeriveCameraExtentTests(unittest.TestCase):
    """Mid-run switch loop: the tool derives the display-window extent from a
    registration + basemap pair, mirroring the kernel's window_extent math.

    Golden values were computed WITH the kernel implementation
    (carto_core.adapters.frontend_geo.window_extent) on this exact fixture on
    2026-11-21 — they lock the service-side replica to the kernel formula.
    """

    # Kernel window_extent output for this fixture (2026-11-21):
    GOLDEN_EXTENT = {"west": 119.8984903728945, "south": 29.93937811847414,
                     "east": 120.1015994586339, "north": 30.06081811854307}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # Mirror of the kernel fixture: white 2381x1684 + black border rect.
        image = Image.new("RGB", (2381, 1684), "white")
        ImageDraw.Draw(image).rectangle([60, 60, 2320, 1620], outline="black", width=6)
        self.basemap_path = self.root / "basemap.png"
        image.save(self.basemap_path, format="PNG")
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        x0, y0 = transformer.transform(120.0, 30.0)
        self.registration = {"work_crs": "EPSG:3857", "origin_m": [x0, y0],
                             "local_km_y_down_to_pixel": [[100.0, 0.0, 1190.0],
                                                          [0.0, 100.0, 842.0]],
                             "source_size": [2381, 1684]}
        self.registration_path = self.root / "registration.yaml"
        self.registration_path.write_text(
            yaml.safe_dump(self.registration, sort_keys=True), encoding="utf-8")

    def _derived(self):
        from basemap_snapshot import derive_camera_extent
        return derive_camera_extent(self.registration, self.basemap_path.read_bytes())

    def test_derived_extent_matches_kernel_golden(self):
        extent = self._derived()
        for key, expected in self.GOLDEN_EXTENT.items():
            self.assertAlmostEqual(expected, extent[key], places=6, msg=key)
        self._derived()  # deterministic on repeat

    def test_derivation_rejects_size_mismatch(self):
        bad = dict(self.registration)
        bad["source_size"] = [1000, 1000]
        with self.assertRaises(ServiceError) as raised:
            from basemap_snapshot import derive_camera_extent
            derive_camera_extent(bad, self.basemap_path.read_bytes())
        self.assertEqual("REGISTRATION_IMAGE_MISMATCH", raised.exception.code)

    def test_derivation_rejects_geographic_crs(self):
        bad = dict(self.registration)
        bad["work_crs"] = "EPSG:4326"
        with self.assertRaises(ServiceError) as raised:
            from basemap_snapshot import derive_camera_extent
            derive_camera_extent(bad, self.basemap_path.read_bytes())
        self.assertEqual("REGISTRATION_CRS_INVALID", raised.exception.code)

    def test_tool_conflicts_and_requirements(self):
        os.environ["CARTO_TIANDITU_KEY"] = "synthetic-key"
        self.addCleanup(os.environ.pop, "CARTO_TIANDITU_KEY", None)
        with patch.object(snapshot_module, "_fetch_tile_sync", return_value=_tile_bytes()):
            with self.assertRaises(ServiceError) as raised:
                self._call_with(extent=EXTENT, derive_registration_path="registration.yaml",
                                derive_basemap_path="basemap.png")
            self.assertEqual("EXTENT_INPUT_CONFLICT", raised.exception.code)
            with self.assertRaises(ServiceError) as raised:
                self._call_with()
            self.assertEqual("EXTENT_INPUT_REQUIRED", raised.exception.code)
            # The full mid-run switch loop in one call: derive + snapshot.
            result = self._call_with(derive_registration_path="registration.yaml",
                                     derive_basemap_path="basemap.png",
                                     output_path="data/snapshot-derived.png")
        self.assertEqual("complete", result["status"])
        self.assertEqual("derived-registration", result["extent_source"])
        for key, expected in self.GOLDEN_EXTENT.items():
            self.assertAlmostEqual(expected, result["provenance"]["extent"][key], places=6,
                                   msg=key)

    def _call_with(self, output_path="data/basemap-online.png", **overrides):
        arguments = {"output_path": output_path, "layer": "vec_w", "width_px": 4096,
                     "fetched_at": "2026-11-21T00:00:00+00:00"}
        arguments.update(overrides)
        return basemap_snapshot(arguments, {"allowed_root": self.root})


if __name__ == "__main__":
    unittest.main()
