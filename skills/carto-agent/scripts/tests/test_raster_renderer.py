"""Optional real-library rendering tests plus a separately opt-in real MCP chain."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.raster_renderer import RasterMapBodyRenderer, _dependencies, fitted_rect
from carto_core.adapters.svg_compositor import SvgCompositor
from carto_core.compiler.layout import LayoutResolver
from carto_core.compiler.raster_portrayal import RasterPortrayalCompiler
from carto_core.repository.map_expression_catalog import MapExpressionCatalog
from carto_core.errors import CartoError
from carto_core.workflow.raster_preparation import RasterPreparationService
from carto_core.workflow.models import ExecutionContext
from tests.test_raster_classification import PreparationFixture
from tests.fixtures.schema_cases import VALID_CASES


def compile_portrayal(service, prepared, context):
    """Explicit synthetic template binding; not a runtime default expression."""
    contract = json.loads((Path(__file__).parent / "fixtures/portrayal-raster.valid.json").read_text(encoding="utf-8"))
    report, _ = service.load_verified(prepared.ref())
    contract["layers"][0]["data_role"] = report["request"]["source"]["role"]
    contract["layers"][0]["map_expression_ref"] = MapExpressionCatalog().reference("raster/categorical", "1.0.0")
    return RasterPortrayalCompiler(service).compile(contract, "raster-layer", prepared.ref(), context)


def pending_portrayal(service, ready_portrayal, pending):
    """Forge a schema-valid artifact to check consumers revalidate the whole chain."""
    document = service._json_ref(ready_portrayal, "resolved-raster-portrayal")
    document["prepared_ref"] = pending.ref()
    return service.save_document(document, "resolved-raster-portrayal")


def a4_layout(dpi=300):
    contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
    contract.update(layout_id="synthetic-a4-landscape")
    contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
    definitions = [("map", "main-view", "map", [10,25,215,175]),
                   ("title", "title", "title", [10,10,277,10]),
                   ("legend", "legend", "legend", [230,40,57,130]),
                   ("source", "source", "marginalia", [230,180,57,15])]
    contract["frames"] = [{"id":i,"content_id":c,"type":t,"bounds":b,"coordinate_space":"page",
                            "overflow_policy":"clip" if t == "map" else "reject"} for i,c,t,b in definitions]
    return LayoutResolver().resolve(contract, dpi)


def overlays():
    return [{"id":"title","type":"text","content":"Synthetic categorical map"},
            {"id":"legend","type":"legend"},
            {"id":"source","type":"attribution","content":"Synthetic data"}]


class RasterFittingTests(unittest.TestCase):
    def test_fit_geographic_aspect_not_pixel_counts(self):
        self.assertEqual([0,25,100,50], fitted_rect([0,0,100,100], [0,0,20,10]))
        self.assertEqual([25,0,50,100], fitted_rect([0,0,100,100], [0,0,10,20]))
        for frame, bounds in [([0,0,0,10],[0,0,1,1]), ([0,0,10,10],[1,0,0,1]),
                              ([0,0,float("nan"),10],[0,0,1,1]), ([0,0,99999,99999],[0,0,1,1])]:
            with self.assertRaises(CartoError):
                fitted_rect(frame,bounds)

    def test_missing_dependencies_fail_without_install_or_fallback(self):
        import builtins
        original = builtins.__import__
        def denied(name, *args, **kwargs):
            if name == "matplotlib":
                raise ImportError("simulated missing optional dependency")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=denied), self.assertRaisesRegex(CartoError, "DEPENDENCY_MISSING"):
            _dependencies()


class RasterRendererTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.np, self.rio, _, _, _, _, self.Image = _dependencies()
        except CartoError as exc:
            self.skipTest(str(exc))
        self.set_raster(self.np.array([[1,0,255],[255,1,0]],dtype="uint8"))
        self.renderer = RasterMapBodyRenderer(self.service)
        self.layout = a4_layout()

    def set_raster(self, array, *, mask=None, nodata=None, xsize=30, ysize=30):
        np, rio = self.np, self.rio
        transform = rio.transform.from_origin(500000,4000000,xsize,ysize)
        with rio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rio.open(self.source_path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                          count=1, dtype=str(array.dtype), crs="EPSG:26911", transform=transform, nodata=nodata) as dst:
                dst.write(array,1)
                if mask is not None:
                    dst.write_mask(mask)
        with rio.open(self.source_path) as src:
            data = src.read(1,masked=True)
            info = self.evidence["raster_info"]
            info.update(width=src.width,height=src.height,bounds=list(src.bounds),transform=list(src.transform)[:6],
                        pixel_size=[xsize,ysize],pixel_size_meters=[xsize,ysize])
            info["bands"][0].update(dtype=src.dtypes[0],nodata=src.nodata)
        values, counts = np.unique(data.compressed(),return_counts=True)
        self.evidence["statistics"]={"total_pixels":data.size,"valid_pixels":int(data.count()),
                                     "masked_pixels":int(np.ma.getmaskarray(data).sum()),
                                     "classes":[{"value":int(v),"count":int(c)} for v,c in zip(values,counts)]}
        self.sync_inputs()

    def portrayal(self, prepared=None):
        return compile_portrayal(self.service, prepared or self.ready(), self.context)

    def body(self, prepared=None):
        artifact = self.renderer.render(self.portrayal(prepared).ref(), self.layout, self.context)
        value = json.loads(artifact.path.read_text(encoding="utf-8"))
        content = self.service.snapshot_bytes(value["image"],"map-body",".png")
        image = self.Image.open(io.BytesIO(content)); image.load()
        return artifact,value,image

    def test_render_blocks_pending_clarifications_before_dependencies(self):
        pending = pending_portrayal(self.service, self.portrayal().ref(), self.analyze())
        with patch("carto_core.adapters.raster_renderer._dependencies", side_effect=AssertionError("must stop earlier")):
            with self.assertRaisesRegex(CartoError,"CLARIFICATION_REQUIRED"):
                self.renderer.render(pending.ref(),self.layout,self.context)

    def test_raw_preparation_cannot_bypass_portrayal_compilation(self):
        with self.assertRaises(CartoError):
            self.renderer.render(self.ready().ref(), self.layout, self.context)

    def test_exact_colors_alpha_orientation_and_a4_landscape(self):
        _, body, image = self.body()
        self.assertEqual((3508,2480),(self.layout["page"]["width_px"],self.layout["page"]["height_px"]))
        self.assertEqual((body["width_px"],body["height_px"]),image.size)
        self.assertAlmostEqual(1.5,image.width/image.height,delta=0.002)
        expected=[[(255,0,0,255),(0,0,0,0),(0,0,255,255)],[(0,0,255,255),(255,0,0,255),(0,0,0,0)]]
        for y in range(2):
            for x in range(3):
                self.assertEqual(expected[y][x],image.getpixel((int((x+.5)*image.width/3),int((y+.5)*image.height/2))))
        self.assertEqual(set(sum(expected,[])),{c for _,c in image.getcolors(image.width*image.height)})
        self.assertEqual([1,255],[r["value"] for r in body["legend_items"]])
        self.assertNotIn("prepared_ref", body)
        portrayal = self.renderer.portrayal_compiler.load_verified(body["portrayal_ref"], self.context)
        self.assertEqual(portrayal["legend_items"], body["legend_items"])
        a,b,c,d,e,f=body["ground_to_image"]; left,bottom,right,top=body["bounds"]
        self.assertAlmostEqual(0,a*left+c); self.assertAlmostEqual(0,e*top+f)
        self.assertAlmostEqual(image.width,a*right+c); self.assertAlmostEqual(image.height,e*bottom+f)
        self.assertEqual(0,b); self.assertEqual(0,d)

    def test_compose_uses_shared_legend_print_size_and_fitted_rect(self):
        artifact, body, _ = self.body()
        raw = overlays()
        path = self.renderer.compose(artifact.ref(), self.layout, raw, self.root/"map.svg", self.context)
        self.assertNotIn("legend_items", raw[1])
        tree = ElementTree.parse(path).getroot()
        ns={"s":"http://www.w3.org/2000/svg"}
        self.assertEqual("3508", tree.attrib["width"])
        self.assertEqual("2480", tree.attrib["height"])
        image = tree.find("s:image",ns)
        for key,value in zip(("x","y","width","height"),body["image_rect"]):
            self.assertAlmostEqual(value,float(image.attrib[key]),places=3)
        text=path.read_text(encoding="utf-8")
        self.assertIn("size:297mm 210mm",text)
        self.assertIn("Category A",text); self.assertIn("Category B",text)
        self.assertNotIn("Absent category",text)
        legend=tree.find("s:g[@id='legend']",ns)
        self.assertEqual(["#FF0000","#0000FF"],[r.attrib["fill"] for r in legend.findall("s:rect",ns)])

    def test_legend_conflict_and_image_rect_outside_frame_are_rejected(self):
        artifact, body, _=self.body()
        raw=overlays(); raw[1]["legend_items"]=[]
        with self.assertRaisesRegex(CartoError,"LEGEND_MISMATCH"):
            self.renderer.compose(artifact.ref(),self.layout,raw,self.root/"map.svg",self.context)
        raw=overlays(); raw[1]["legend_items"]=[{"label":"A","color":"#FF0000","symbol":"fill"}]
        placed=LayoutResolver().place_overlays(self.layout,raw)
        compositor=SvgCompositor(3508,2480,self.service.project_guard)
        for rect in ([0,0,10,10], [float("nan"),0,10,10], [130,300,20,20]):
            with self.assertRaises(CartoError):
                compositor.compose(Path(body["image"]["artifact_ref"]["uri"]),placed,self.root/"bad.svg",
                                   resolved_layout=self.layout,map_image_rect=rect)

    def test_immutable_source_render_and_repeatability(self):
        ready=self.ready()
        first, body, _=self.body(ready)
        self.source_path.write_bytes(b"changed original")
        self.legend_path.write_bytes(b"changed original")
        second, _, _=self.body(ready)
        self.assertEqual(first.ref(),second.ref())
        portrayal = self.portrayal(ready)
        self.context.subject_id="wrong-subject"
        with self.assertRaisesRegex(CartoError,"SCOPE_MISMATCH"):
            self.renderer.render(portrayal.ref(),self.layout,self.context)

    def test_sparse_negative_and_large_codes_use_discrete_indices(self):
        for dtype, values in (("int32",[-100,7,2000000000]),("uint32",[0,90000,4000000000])):
            with self.subTest(dtype=dtype):
                self.set_raster(self.np.array([values,values[::-1]],dtype=dtype))
                lines=["value,label,color"]+[f"{v},Category {i},{color}" for i,(v,color) in enumerate(zip(values,["#FF0000","#00FF00","#0000FF"]))]
                self.legend_path.write_text("\n".join(lines)+"\n",encoding="utf-8"); self.sync_inputs()
                _, _, image=self.body(self.analyze())
                self.assertEqual({(255,0,0,255),(0,255,0,255),(0,0,255,255)}, {c for _,c in image.getcolors(image.width*image.height)})

    def test_internal_mask_and_source_nodata_stay_transparent(self):
        for mode in ("mask","nodata"):
            with self.subTest(mode=mode):
                array=self.np.array([[1,1,255],[255,1,0]],dtype="uint8")
                kwargs={"mask":self.np.array([[0,255,255],[255,255,255]],dtype="uint8")} if mode=="mask" else {"nodata":1}
                self.set_raster(array,**kwargs)
                _, _, image=self.body()
                self.assertEqual(0,image.getpixel((int(image.width/6),int(image.height/4)))[3])
                self.assertEqual((0,0,255,255),image.getpixel((int(image.width*5/6),int(image.height/4))))

    def test_all_source_pixels_masked_is_rejected(self):
        self.set_raster(self.np.ones((2,3),dtype="uint8"),nodata=1)
        with self.assertRaises(CartoError):
            self.analyze()

    def test_all_explicitly_hidden_classes_cannot_generate_blank_map(self):
        baseline=self.analyze()
        report,_=self.service.load_verified(baseline.ref())
        answers={"schema_version":1,"based_on_digest":baseline.digest,"entries":[
            {"value":r["value"],"semantic":"background","display":"hidden","label":None,"color":None,
             "order":r["order"],"include_in_legend":False} for r in report["rows"]]}
        ready=self.service.clarify(baseline.ref(),answers,self.context)
        with self.assertRaisesRegex(CartoError,"NO_VISIBLE_CLASSES"):
            self.renderer.render(self.portrayal(ready).ref(),self.layout,self.context)

    def test_page_limit_and_png_tampering_fail_closed(self):
        ready=self.ready()
        with self.assertRaisesRegex(CartoError,"SIZE_LIMIT"):
            self.renderer.render(self.portrayal(ready).ref(),a4_layout(600),self.context)
        artifact,body,_=self.body(ready)
        Path(body["image"]["artifact_ref"]["uri"]).write_bytes(b"tampered PNG")
        with self.assertRaises(CartoError):
            self.renderer.compose(artifact.ref(),self.layout,overlays(),self.root/"bad.svg",self.context)

    def test_downsampling_to_all_transparent_is_rejected(self):
        array=self.np.zeros((1000,1000),dtype="uint8"); array[0,0]=1
        self.set_raster(array)
        baseline=self.analyze(); answers=self.answers(baseline); answers["entries"].pop()
        ready=self.service.clarify(baseline.ref(),answers,self.context)
        with self.assertRaisesRegex(CartoError,"NO_VISIBLE_PIXELS_AT_SCALE"):
            self.renderer.render(self.portrayal(ready).ref(),a4_layout(72),self.context)

    def test_non_square_ground_pixel_aspect_is_preserved(self):
        self.set_raster(self.np.array([[1,0,255],[255,1,0]],dtype="uint8"),xsize=60,ysize=30)
        _, _, image=self.body()
        self.assertAlmostEqual(3,image.width/image.height,delta=0.005)

    def test_decoder_rejects_forged_metadata_and_pixel_statistics(self):
        self.evidence["statistics"]["classes"][0]["count"]=1
        self.evidence["statistics"]["classes"][1]["count"]=3
        ready=self.ready()
        with self.assertRaisesRegex(CartoError,"DECODE_BINDING_MISMATCH"):
            self.renderer.render(self.portrayal(ready).ref(),self.layout,self.context)
        self.evidence["statistics"]["classes"][0]["count"]=2
        self.evidence["statistics"]["classes"][1]["count"]=2
        self.evidence["raster_info"]["transform"][2]+=1
        ready=self.ready()
        with self.assertRaisesRegex(CartoError,"DECODE_BINDING_MISMATCH"):
            self.renderer.render(self.portrayal(ready).ref(),self.layout,self.context)

    def test_body_layout_and_environment_tampering_cannot_be_composed(self):
        artifact, body, _=self.body()
        body["environment"]["matplotlib"]="forged"
        forged=self.service.save_document(body,"raster-map-body")
        with self.assertRaisesRegex(CartoError,"MAP_BODY_CHANGED"):
            self.renderer.compose(forged.ref(),self.layout,overlays(),self.root/"bad.svg",self.context)
        with self.assertRaisesRegex(CartoError,"MAP_BODY_CHANGED"):
            self.renderer.compose(artifact.ref(),a4_layout(144),overlays(),self.root/"bad.svg",self.context)


@unittest.skipUnless(os.environ.get("CARTO_GEOSPATIAL_TEST_PYTHON"), "Explicit independent GIS interpreter required")
class RasterRealMcpTests(unittest.TestCase):
    def test_real_mcp_freeze_clarify_render_compose_chain(self):
        from tests.test_geospatial_stdio import GeospatialStdioTests
        GeospatialStdioTests.setUp(self)
        try:
            _dependencies()
        except CartoError as exc:
            self.skipTest(str(exc))
        legend=self.project/"legend.csv"
        legend.write_text("value,label,color\n1,Category A,#FF0000\n2,Category C,#00FF00\n",encoding="utf-8")
        service=RasterPreparationService(project_root=self.project,allowed_roots=self.allowed_roots)
        request=deepcopy(VALID_CASES["raster-classification-request"])
        request.update(source=self.source)
        request["legend"].update(path=str(legend),digest=service.digest_bytes(legend.read_bytes()),size_bytes=legend.stat().st_size)
        context=ExecutionContext("integration-run","test-tenant","test-project","test-subject",
                                 frozenset({"operator"}),frozenset({"test-project"}),frozenset({"gis-raster-statistics"}))
        baseline=service.analyze(request,context,GeospatialStdioTests.adapter(self))
        calls_after_analysis=context.budget.tool_calls
        self.assertGreater(calls_after_analysis,0)
        report, _=service.load_verified(baseline.ref())
        self.assertEqual([0,255],[q["value"] for q in report["questions"]])
        ready=service.clarify(baseline.ref(),PreparationFixture.answers(baseline),context)
        renderer=RasterMapBodyRenderer(service); layout=a4_layout()
        portrayal=compile_portrayal(service,ready,context)
        body=renderer.render(portrayal.ref(),layout,context)
        output=renderer.compose(body.ref(),layout,overlays(),self.project/"map.svg",context)
        self.assertTrue(output.is_file())
        self.assertEqual(calls_after_analysis,context.budget.tool_calls)


if __name__ == "__main__":
    unittest.main()
