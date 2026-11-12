"""Shared test helpers extracted from deleted test files.

These were previously spread across test_raster_renderer.py and test_raster_page_renderer.py
and are now consumed by the remaining test modules.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from carto_core.compiler.layout import LayoutResolver
from carto_core.compiler.raster_portrayal import RasterPortrayalCompiler
from carto_core.repository.map_expression_catalog import MapExpressionCatalog
from tests.fixtures.schema_cases import VALID_CASES


# ── From test_raster_renderer.py ────────────────────────────────────────────

def compile_portrayal(service, prepared, context):
    """Explicit synthetic template binding; not a runtime default expression."""
    contract = json.loads(
        (Path(__file__).parent / "fixtures/portrayal-raster.valid.json").read_text(encoding="utf-8"))
    report, _ = service.load_verified(prepared.ref())
    contract["layers"][0]["data_role"] = report["request"]["source"]["role"]
    contract["layers"][0]["map_expression_ref"] = MapExpressionCatalog().reference("raster/categorical", "1.0.0")
    return RasterPortrayalCompiler(service).compile(contract, "raster-layer", prepared.ref(), context)


def pending_portrayal(service, ready_portrayal, pending):
    """Forge a schema-valid artifact to check consumers revalidate the whole chain."""
    document = service._json_ref(ready_portrayal, "resolved-portrayal")
    document["prepared_ref"] = pending.ref()
    return service.save_document(document, "resolved-portrayal")


def a4_layout(dpi=300):
    contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
    contract.update(layout_id="synthetic-a4-landscape")
    contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
    definitions = [
        ("map", "main-view", "map", [10, 25, 215, 175]),
        ("title", "title", "title", [10, 10, 277, 10]),
        ("legend", "legend", "legend", [230, 40, 57, 130]),
        ("source", "source", "marginalia", [230, 180, 57, 15]),
    ]
    contract["frames"] = [
        {"id": i, "content_id": c, "type": t, "bounds": b, "coordinate_space": "page",
         "overflow_policy": "clip" if t == "map" else "reject"}
        for i, c, t, b in definitions
    ]
    return LayoutResolver().resolve(contract, dpi)


def overlays():
    return [
        {"id": "title", "type": "text", "content": "Synthetic categorical map"},
        {"id": "legend", "type": "legend"},
        {"id": "source", "type": "attribution", "content": "Synthetic data"},
    ]


def set_raster(test, array, *, mask=None, nodata=None, xsize=30, ysize=30):
    """Standalone extraction of RasterRendererTests.set_raster.

    Assumes *test* provides np, rio, source_path, evidence, and sync_inputs()
    (all supplied by PreparationFixture / RasterRendererTests.setUp).
    """
    np, rio = test.np, test.rio
    transform = rio.transform.from_origin(500000, 4000000, xsize, ysize)
    with rio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rio.open(test.source_path, "w", driver="GTiff", width=array.shape[1],
                       height=array.shape[0], count=1, dtype=str(array.dtype),
                       crs="EPSG:26911", transform=transform, nodata=nodata) as dst:
            dst.write(array, 1)
            if mask is not None:
                dst.write_mask(mask)
    with rio.open(test.source_path) as src:
        data = src.read(1, masked=True)
        info = test.evidence["raster_info"]
        info.update(width=src.width, height=src.height, bounds=list(src.bounds),
                    transform=list(src.transform)[:6], pixel_size=[xsize, ysize],
                    pixel_size_meters=[xsize, ysize])
        info["bands"][0].update(dtype=src.dtypes[0], nodata=src.nodata)
    values, counts = np.unique(data.compressed(), return_counts=True)
    test.evidence["statistics"] = {
        "total_pixels": data.size, "valid_pixels": int(data.count()),
        "masked_pixels": int(np.ma.getmaskarray(data).sum()),
        "classes": [{"value": int(v), "count": int(c)} for v, c in zip(values, counts)],
    }
    test.sync_inputs()


# ── From test_raster_page_renderer.py ───────────────────────────────────────

def release_test_font_handles():
    """Matplotlib caches FT2Font objects and holds file handles on Windows.

    Only tests delete font snapshots; production keeps its content-addressed fonts immutable.
    """
    import gc
    from matplotlib import font_manager
    font_manager._get_font.cache_clear()
    gc.collect()


def page_request(service, prepared, context, font_source=None, *, dpi=300):
    import matplotlib
    font_source = font_source or Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
    destination = service.project / "selected-font.ttf"
    destination.write_bytes(Path(font_source).read_bytes())
    result = deepcopy(VALID_CASES["page-request"])
    result.update(
        portrayals=[{"view_id": "main-view",
                      "ref": compile_portrayal(service, prepared, context).ref()}],
        resolved_layout=a4_layout(dpi),
    )
    result["font"] = {
        "path": str(destination),
        "digest": service.digest_bytes(destination.read_bytes()),
        "size_bytes": destination.stat().st_size,
    }
    result.pop("appearance", None)
    result.pop("bindings", None)
    result["legends"] = [{"content_id": x["content_id"], "title": x["title"]}
                          for x in result["legends"]]
    from carto_core.compiler.raster_page_contract import compile_page_request
    return compile_page_request(service, result, VALID_CASES["cartography"], context)


def rebind_page(service, page, context):
    style = page["appearance"]["cartography"]
    unresolved = {k: deepcopy(v) for k, v in page.items()
                   if k not in {"appearance", "bindings"}}
    unresolved["legends"] = [{"content_id": x["content_id"], "title": x["title"]}
                              for x in unresolved["legends"]]
    from carto_core.compiler.raster_page_contract import compile_page_request
    return compile_page_request(service, unresolved, style, context)


def adorned_layout(dpi=300):
    contract = deepcopy(a4_layout(dpi)["contract"])
    placements = {
        "map": [10, 25, 215, 160], "legend": [230, 30, 57, 125],
        "source": [10, 190, 100, 10],
    }
    for frame in contract["frames"]:
        if frame["id"] in placements:
            frame["bounds"] = placements[frame["id"]]
    for key, kind, bounds in [
        ("scale", "scale-bar", [115, 185, 110, 15]),
        ("north", "north-arrow", [230, 160, 57, 35]),
    ]:
        contract["frames"].append({
            "id": key, "content_id": key, "type": kind, "bounds": bounds,
            "coordinate_space": "page", "overflow_policy": "reject",
        })
    return LayoutResolver().resolve(contract, dpi)


# ── From test_s2_vector.py (vector fixture helpers) ─────────────────────────

def vector_encoding(kind, geometry=None):
    """Build a synthetic vector encoding fixture for the given kind."""
    base = deepcopy(VALID_CASES["vector-encoding"])
    sym = base.pop("symbol"); base.pop("label")
    base.update(
        kind=kind,
        geometry=geometry or ("point" if kind == "proportional" else "polygon"),
        field=None if kind == "single" else "value",
        unit="index" if kind in {"choropleth", "proportional"} else None,
    )
    if kind == "single":
        base.update(label="Features", symbol=sym)
    if kind == "categorical":
        base.update(legend_policy="observed", categories=[
            {"value": i, "label": f"Class {i}", "symbol": {**sym, "color": color}}
            for i, color in [(1, "#FF0000"), (2, "#00AA00"), (3, "#0000FF")]
        ])
    if kind == "choropleth":
        base.update(
            edges=[0, 2, 4], labels=["[0,2)", "[2,4]"],
            symbols=[sym, {**sym, "color": "#AADDEE"}],
            quantity_kind="normalized-index", interval_policy="left-closed-last-both",
            out_of_range="reject",
        )
    if kind == "proportional":
        base.update(
            maximum_value=4, maximum_radius_mm=4, minimum_radius_mm=0,
            zero_policy="omit", negative_policy="reject", out_of_range="reject",
            legend_values=[1, 4], symbol=sym,
        )
    return base


def vector_report(values, geometry="polygon"):
    return {
        "geometry": geometry,
        "features": [{"id": f"feature-{i}", "properties": {"value": v}}
                      for i, v in enumerate(values)],
    }


class VectorFixture:
    """Minimal synthetic vector setup shared by S2 workflow tests.

    All data is created in TemporaryDirectory; no real GIS files are referenced.
    """

    def setUp(self):
        import importlib.util
        if any(importlib.util.find_spec(n) is None for n in ("fiona", "shapely", "matplotlib")):
            self.skipTest("Explicit vector-rendering dependencies required")
        self.temp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(release_test_font_handles)
        from carto_core.workflow.models import ExecutionContext
        self.context = ExecutionContext(
            "vector-run", "test-tenant", "test-project", "test-subject",
            frozenset({"operator"}), frozenset({"test-project"}),
            frozenset({"read", "classify", "render-preview"}),
        )
        from carto_core.workflow.vector_preparation import VectorPreparationService
        self.service = VectorPreparationService(project_root=self.root, allowed_roots=[self.root])
        self.sources = []; self.prepared = []
        self.make_source("polygon", [1, 2, 3], "polygon-source")
        self.make_source("point", [0, 1, 4], "point-source")
        import matplotlib
        self.font = self.root / "font.ttf"
        self.font.write_bytes((Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf").read_bytes())

    def make_source(self, geometry, values, sid, fmt="geojson", crs="EPSG:4326"):
        import json as _json
        rows = []
        for i, value in enumerate(values):
            coords = (
                [i, 0] if geometry == "point"
                else [[[i, 0], [i + 0.8, 0], [i + 0.8, 0.8], [i, 0.8], [i, 0]]]
            )
            rows.append({
                "type": "Feature",
                "geometry": {"type": "Point" if geometry == "point" else "Polygon",
                             "coordinates": coords},
                "properties": {"value": value},
            })
        if fmt == "geojson":
            path = self.root / (sid + ".geojson")
            path.write_text(_json.dumps({"type": "FeatureCollection", "features": rows}),
                           encoding="utf-8")
            files = [path]
        else:
            import fiona  # noqa: PLC0415
            path = self.root / (sid + ".shp")
            with fiona.open(path, "w", driver="ESRI Shapefile", crs=crs,
                            schema={"geometry": rows[0]["geometry"]["type"],
                                    "properties": {"value": "float"}},
                            encoding="utf-8") as dst:
                for row in rows:
                    dst.write(row)
            files = sorted(self.root.glob(sid + ".*"))
        from carto_core.artifacts import file_digest
        source = {
            "schema_version": 1, "source_id": sid, "role": "thematic-features",
            "format": fmt, "crs": crs, "encoding": "utf-8",
            "files": [{"extension": p.suffix, "path": p.name, "digest": file_digest(p),
                       "size_bytes": p.stat().st_size} for p in files],
            "data_nature": "user-provided", "contains_sensitive_coordinates": False,
            "contains_production_data": False, "license": "project-approved",
        }
        self.sources.append(source)
        self.prepared.append(self.service.prepare(source, self.context))
        return source, self.prepared[-1]

    def page(self, modes=("single", "categorical", "choropleth", "proportional"), shared=False):
        from carto_core.compiler.layout import LayoutResolver
        from carto_core.scenarios.general_thematic import GeneralThematicAuthor
        from carto_core.compiler.vector_portrayal import VectorPortrayalCompiler
        from carto_core.compiler.vector_page import compile_page
        from carto_core.artifacts import file_digest
        layout = LayoutResolver().resolve(
            GeneralThematicAuthor._layout(), 72,
            parameters={
                "rows": 2 if len(modes) == 4 else 1,
                "columns": 2 if len(modes) > 1 else 1,
                "legend_mode": "shared" if shared else "independent",
            },
        )
        maps = [f for f in layout["contract"]["frames"] if f["type"] == "map"]
        panels = []
        for frame, kind in zip(maps, modes):
            prepared = self.prepared[1] if kind == "proportional" else self.prepared[0]
            portrayal = VectorPortrayalCompiler(self.service).compile(
                prepared.ref(), vector_encoding(kind), self.context)
            panels.append({
                "view_id": frame["content_id"], "portrayal_ref": portrayal.ref(),
                "extent": [-1, -1, 4, 2],
            })
        return compile_page(
            self.service, layout=layout,
            cartography=GeneralThematicAuthor._cartography(), panels=panels,
            font={"path": str(self.font), "digest": file_digest(self.font),
                  "size_bytes": self.font.stat().st_size},
            texts=[{"content_id": f["content_id"], "text": "Synthetic map"}
                   for f in layout["contract"]["frames"] if f["type"] not in {"map", "legend"}],
            legend_titles={f["content_id"]: "Legend"
                          for f in layout["contract"]["frames"] if f["type"] == "legend"},
            context=self.context,
        )