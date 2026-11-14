"""ADR-001 stage 2.3 continuous raster end-to-end (synthetic float32 surface only).

Exercises the continuous chain that categorical fixtures never reach:
  analyze(continuous request) -> _analyze_continuous -> _continuous_encoding (interval IR)
  -> raster-continuous-preparation -> RasterPortrayalCompiler._build_continuous
  -> resolved-portrayal(key_mode=interval).

No GIS service, no renderer, no repository policy or user approval is created or consumed.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.tool_gateway import ToolGateway
from carto_core.compiler.raster_portrayal import RasterPortrayalCompiler
from carto_core.errors import CartoError
from carto_core.repository.immutable_store import ImmutableArtifactStore
from carto_core.repository.map_expression_catalog import MapExpressionCatalog
from carto_core.workflow.models import ExecutionContext
from carto_core.workflow.raster_preparation import RasterPreparationService
from tests.fixtures.schema_cases import VALID_CASES
from tests.helpers import set_raster

ROLE = "classified-surface"
RAMP = ["#08306B", "#2171B5", "#4292C6", "#6BAED6", "#9ECAE1"]


class ContinuousFixture(unittest.TestCase):
    """A float32 surface (4x3, two masked cells -> 10 valid, values 0.5..11.5) + continuous request."""

    def setUp(self):
        try:
            from carto_core.adapters.raster_renderer import _dependencies
            deps = _dependencies()
            self.np, self.rio = deps[0], deps[1]
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source_path = self.root / "surface.tif"
        self.request = {
            "schema_version": 1,
            "source": deepcopy(VALID_CASES["raster-input"]),
            "measurement": "density",
            "unit": "kg/ha",
            "classification": {"method": "equal-interval", "class_count": 5},
            "color_ramp": {"scheme": "sequential", "colors": deepcopy(RAMP)},
        }
        self.request["source"]["path"] = "surface.tif"
        self.request["source"]["role"] = ROLE
        self.service = RasterPreparationService(project_root=self.root, allowed_roots=[str(self.root)])
        self.context = ExecutionContext("test-run", "test-tenant", "test-project", "test-subject",
                                        frozenset({"operator"}), frozenset({"test-project"}),
                                        frozenset({"gis-raster-statistics"}))
        self.evidence = deepcopy(VALID_CASES["geospatial-result"])
        self.evidence.update(operation="statistics")
        values = self.np.array([[0.5, 1.5, 2.5, 3.5], [4.5, 5.5, 6.5, 7.5], [8.5, 9.5, 10.5, 11.5]], dtype="float32")
        mask = self.np.ones(values.shape, dtype="uint8") * 255
        mask[1, 3] = 0
        mask[2, 0] = 0
        set_raster(self, values, mask=mask)  # writes the TIFF, builds continuous evidence, syncs digests
        self.calls = []
        store = ImmutableArtifactStore(self.root / ".carto/geospatial/evidence", path_guard=self.service.project_guard)
        gateway = ToolGateway(SCRIPTS_ROOT.parent / "policies/tool-bindings.yaml", store)

        def statistics(request, context):
            self.calls.append(deepcopy(request))
            return deepcopy(self.evidence)

        gateway.register("gis-raster-statistics", statistics, input_schema="geospatial-request",
                         output_schema="geospatial-result")
        self.adapter = SimpleNamespace(make_gateway=lambda: gateway)
        self.compiler = RasterPortrayalCompiler(self.service)

    def sync_inputs(self):
        # Continuous requests carry no legend, unlike the categorical PreparationFixture.
        self.request["source"].update(size_bytes=self.source_path.stat().st_size)
        self.request["source"]["source_ref"]["digest"] = self.service.digest_bytes(self.source_path.read_bytes())
        self.evidence.update(source_ref=deepcopy(self.request["source"]["source_ref"]),
                             source_size_bytes=self.request["source"]["size_bytes"])

    def analyze(self):
        return self.service.analyze(self.request, self.context, self.adapter)

    def contract(self, *, class_count=5, method="equal-interval"):
        return {
            "schema_version": 1,
            "layers": [{
                "id": "raster-layer", "data_role": ROLE, "geometry": "raster", "z_order": 0,
                "map_expression_ref": MapExpressionCatalog().reference("graduated-color", "2.0.0"),
                "classification": {"method": method},
                "source_mask_policy": "preserve", "resampling": "nearest", "no_data": "transparent",
            }],
            "legend": {"generated_from_layers": True, "show_no_data": False, "overflow_policy": "reject"},
            "rules": [],
        }


class ContinuousPreparationTests(ContinuousFixture):
    def test_analyze_produces_interval_encoding_ir(self):
        report, result = self.service.load_verified(self.analyze().ref())
        self.assertEqual("raster-continuous-preparation", report["kind"])
        self.assertEqual("ready", report["status"])
        self.assertEqual(1, len(self.calls))  # statistics came through the gateway once
        self.assertIn("continuous", result["statistics"])
        self.assertNotIn("classes", result["statistics"])
        encoding = report["encoding"]
        self.assertEqual("interval", encoding["key_mode"])
        self.assertEqual("raster-cell", encoding["geometry_role"])
        self.assertEqual("density", encoding["domain"]["measurement"])
        self.assertEqual(6, len(encoding["scale"]["edges"]))       # class_count 5 -> 6 edges
        self.assertEqual(5, len(encoding["scale"]["labels"]))
        self.assertEqual(5, len(encoding["channels"]["symbols"]))
        self.assertAlmostEqual(0.5, encoding["scale"]["edges"][0])
        self.assertAlmostEqual(11.5, encoding["scale"]["edges"][-1])

    def test_ramp_class_count_mismatch_is_rejected(self):
        self.request["color_ramp"]["colors"] = RAMP[:4]  # 4 colors but class_count 5
        with self.assertRaisesRegex(CartoError, "RASTER_RAMP_CLASS_MISMATCH"):
            self.analyze()

    def test_integer_band_cannot_use_continuous_request(self):
        # A categorical (integer) surface driven through the continuous request must fail closed.
        values = self.np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]], dtype="uint8")
        set_raster(self, values)  # rewrites the TIFF + evidence as integer/classes
        with self.assertRaisesRegex(CartoError, "RASTER_CONTINUOUS_PROFILE_UNSUPPORTED"):
            self.analyze()


class ContinuousPortrayalTests(ContinuousFixture):
    def test_compile_to_interval_resolved_portrayal(self):
        prepared = self.analyze()
        artifact = self.compiler.compile(self.contract(), "raster-layer", prepared.ref(), self.context)
        result = self.compiler.load_verified(artifact.ref(), self.context)
        self.assertEqual("interval", result["key_mode"])
        self.assertEqual("raster", result["geometry"])
        self.assertEqual(5, len(result["legend_items"]))
        self.assertEqual(["Class 1", "Class 5"], [result["legend_items"][0]["label"], result["legend_items"][-1]["label"]])
        self.assertEqual(RAMP[0], result["legend_items"][0]["color"])
        self.assertEqual("interval", result["encoding"]["key_mode"])
        self.assertNotIn("lookup_table", result)
        self.assertNotIn("backend", result)

    def test_continuous_compile_is_deterministic_and_scope_bound(self):
        prepared = self.analyze()
        first = self.compiler.compile(self.contract(), "raster-layer", prepared.ref(), self.context)
        second = self.compiler.compile(self.contract(), "raster-layer", prepared.ref(), self.context)
        self.assertEqual(first.ref(), second.ref())
        self.context.run_id = "other-run"
        with self.assertRaises(CartoError):
            self.compiler.compile(self.contract(), "raster-layer", prepared.ref(), self.context)


if __name__ == "__main__":
    unittest.main()
