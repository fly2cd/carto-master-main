"""Opt-in integration against an independently installed geospatial-mcp 0.3.0.

Set CARTO_GEOSPATIAL_TEST_PYTHON to its real interpreter. No server installation,
external repository mutation, or user-data fixture is performed by these tests.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.geospatial_mcp import CAPABILITIES, GeospatialMcpAdapter
from carto_core.canonical import sha256_digest
from carto_core.cli import main
from carto_core.workflow.models import ExecutionContext
from tests.fixtures.schema_cases import VALID_CASES


@unittest.skipUnless(os.environ.get("CARTO_GEOSPATIAL_TEST_PYTHON"), "Explicit independent GIS service interpreter required")
class GeospatialStdioTests(unittest.TestCase):
    def setUp(self):
        try:
            import rasterio
            import numpy
            import mcp
        except ImportError:
            self.skipTest("Optional MCP client and synthetic TIFF fixture dependencies are unavailable")
        self.rasterio, self.np = rasterio, numpy
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / "project"; self.project.mkdir()
        self.data_root = self.root / "data"; self.data_root.mkdir()
        self.path = self.data_root / "classified.tif"
        self.values = numpy.array([[0, 1, 255, 2], [0, 1, 255, 2], [0, 1, 255, 2]], dtype="uint8")
        self.mask = numpy.ones(self.values.shape, dtype="uint8") * 255
        self.mask[0, 1] = 0
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(self.path, "w", driver="GTiff", width=4, height=3, count=1,
                               dtype="uint8", crs="EPSG:26911", transform=rasterio.transform.from_origin(500000, 4000000, 30, 30)) as dst:
                dst.write(self.values, 1); dst.write_mask(self.mask)
        self.python = Path(os.environ["CARTO_GEOSPATIAL_TEST_PYTHON"]).resolve(strict=True)
        self.allowed_roots = [str(self.root), str(self.python.parent)]
        catalog = self.project / "datasets.json"
        catalog.write_text(json.dumps({"version": 1, "datasets": {"classified": {"kind": "raster", "path": "classified.tif"}}}), encoding="utf-8")
        config = deepcopy(VALID_CASES["geospatial-mcp-config"])
        config.update(server_python=str(self.python), data_root=str(self.data_root), catalog_path=str(catalog))
        self.config_path = self.project / "mcp.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.source = deepcopy(VALID_CASES["raster-input"])
        self.source.update(path=str(self.path), size_bytes=self.path.stat().st_size)
        self.source["source_ref"]["digest"] = "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest()

    def adapter(self):
        return GeospatialMcpAdapter(config_path=self.config_path, project_root=self.project, allowed_roots=self.allowed_roots)

    def request(self, operation):
        result = {"schema_version": 1, "operation": operation, "source": self.source}
        if operation == "reproject":
            result["parameters"] = {"target_crs": "EPSG:4326", "resolution": None, "resampling": "nearest"}
        return result

    def invoke(self, operation, request=None):
        context = ExecutionContext("integration-run", "test-tenant", "test-project", "test-subject",
                                   frozenset({"test-operator"}), frozenset({"test-project"}),
                                   frozenset({CAPABILITIES[operation]}))
        receipt = self.adapter().make_gateway().invoke(CAPABILITIES[operation], request or self.request(operation), context)
        output = json.loads(Path(receipt.artifact_refs[0]["uri"]).read_text(encoding="utf-8"))
        self.assertEqual(sha256_digest(output), receipt.output_digest)
        return output

    def test_official_stdio_information_and_exact_statistics(self):
        # Prove the real SDK session uses Carto's pinned local validation hook.
        remote_validator = AsyncMock(side_effect=AssertionError("Remote tool schemas must not execute"))
        with patch("mcp.ClientSession.validate_tool_result", remote_validator):
            info = self.invoke("info")
        remote_validator.assert_not_called()
        self.assertEqual("EPSG:26911", info["raster_info"]["crs"])
        self.assertEqual((4, 3), (info["raster_info"]["width"], info["raster_info"]["height"]))
        stats = self.invoke("statistics")["statistics"]
        self.assertEqual((12, 11, 1), (stats["total_pixels"], stats["valid_pixels"], stats["masked_pixels"]))
        self.assertEqual({0: 3, 1: 2, 2: 3, 255: 3}, {row["value"]: row["count"] for row in stats["classes"]})

    def test_official_stdio_reprojection_and_binary_resource_download(self):
        output = self.invoke("reproject")
        info = output["artifact"]
        path = Path(info["artifact_ref"]["uri"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), info["artifact_ref"]["digest"][7:])
        with self.rasterio.open(path) as dst:
            self.assertEqual("EPSG:4326", dst.crs.to_string())
            self.assertEqual(("uint8",), dst.dtypes)
            self.assertEqual(output["raster_info"]["width"], dst.width)
            self.assertEqual(output["raster_info"]["height"], dst.height)
            self.assertTrue(set(self.np.unique(dst.read(1, masked=True).compressed())) <= {0, 1, 2, 255})
        self.assertFalse(Path(str(path) + ".msk").exists())
        self.assertEqual(self.source["source_ref"]["digest"], "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_same_grid_preserves_embedded_mask_and_valid_extreme_values(self):
        request = self.request("reproject")
        request["parameters"].update(target_crs="EPSG:26911", resolution=30)
        output = self.invoke("reproject", request)
        with self.rasterio.open(output["artifact"]["artifact_ref"]["uri"]) as dst:
            self.np.testing.assert_array_equal(self.mask, dst.read_masks(1))
            self.np.testing.assert_array_equal(self.values[self.mask != 0], dst.read(1)[self.mask != 0])

    def test_read_only_cli_emits_receipt_not_dataset_content(self):
        request_path = self.project / "request.json"
        request_path.write_text(json.dumps(self.request("statistics")), encoding="utf-8")
        args = ["data", "inspect-raster", str(request_path), "--mcp-config", str(self.config_path),
                "--project-root", str(self.project), "--run-id", "test-run", "--tenant-id", "test-tenant",
                "--project-id", "test-project", "--subject-id", "test-subject"]
        for root in self.allowed_roots: args.extend(["--allowed-root", root])
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            status = main(args)
        self.assertEqual(0, status, err.getvalue())
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        self.assertNotIn("classes", out.getvalue())
        self.assertEqual("gis-raster-statistics", result["tool_result"]["capability_id"])
        self.assertTrue(Path(result["tool_result"]["artifact_refs"][0]["uri"]).is_file())


if __name__ == "__main__":
    unittest.main()
