"""Synthetic print page tests. No business approvals or actual dataset rows."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.raster_page_renderer import RasterPageRenderer
from carto_core.adapters.raster_renderer import _dependencies
from carto_core.compiler.layout import LayoutResolver
from carto_core.errors import CartoError
from carto_core.workflow.models import ExecutionContext
from carto_core.workflow.raster_preparation import RasterPreparationService
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_raster_classification import PreparationFixture
from tests import test_raster_renderer as raster_helpers


def release_test_font_handles():
    # Matplotlib caches FT2Font objects and holds file handles on Windows. Only tests
    # delete font snapshots; production keeps its content-addressed fonts immutable.
    import gc
    from matplotlib import font_manager
    font_manager._get_font.cache_clear()
    gc.collect()


def page_request(service, prepared, context, font_source=None, *, dpi=300):
    import matplotlib
    font_source = font_source or Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
    # Explicit development fixture font; no font is redistributed in repository fixtures.
    destination = service.project / "selected-font.ttf"
    destination.write_bytes(Path(font_source).read_bytes())
    result = deepcopy(VALID_CASES["raster-page-request"])
    result.update(portrayal_ref=raster_helpers.compile_portrayal(service,prepared,context).ref(),
                  resolved_layout=raster_helpers.a4_layout(dpi))
    result["font"] = {"path": str(destination), "digest": service.digest_bytes(destination.read_bytes()),
                      "size_bytes": destination.stat().st_size}
    return result


def adorned_layout(dpi=300):
    contract = deepcopy(raster_helpers.a4_layout(dpi)["contract"])
    placements = {"map": [10,25,215,160], "legend": [230,30,57,125], "source": [10,190,100,10]}
    for frame in contract["frames"]:
        if frame["id"] in placements:
            frame["bounds"] = placements[frame["id"]]
    for key, kind, bounds in [("scale", "scale-bar", [115,185,110,15]), ("north", "north-arrow", [230,160,57,35])]:
        contract["frames"].append({"id":key,"content_id":key,"type":kind,"bounds":bounds,
                                   "coordinate_space":"page","overflow_policy":"reject"})
    return LayoutResolver().resolve(contract,dpi)


class RasterPageTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.np, self.rio, self.mpl, _, _, _, self.Image = _dependencies()
            import fontTools
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        raster_helpers.RasterRendererTests.set_raster(self, self.np.array([[1,0,255],[255,1,0]],dtype="uint8"))
        self.addCleanup(release_test_font_handles)
        self.page_renderer = RasterPageRenderer(self.service)
        self.prepared = self.ready()
        self.page = page_request(self.service,self.prepared,self.context)

    def render(self):
        artifact = self.page_renderer.render(self.page,self.context)
        return artifact, self.service._json_ref(artifact.ref(),"raster-page-output")

    def test_a4_png_pdf_svg_share_frozen_body_and_legend(self):
        _, output = self.render()
        self.assertEqual("internal-page-output-not-formal-render-receipt", output["capability_boundary"])
        png = Path(output["outputs"]["png"]["artifact_ref"]["uri"])
        body = self.service._json_ref(output["body_ref"],"raster-map-body")
        self.assertEqual(self.page["portrayal_ref"], body["portrayal_ref"])
        self.assertNotIn("prepared_ref", body)
        with self.Image.open(png) as image:
            self.assertEqual((3508,2480), image.size)
            self.assertAlmostEqual(300,image.info["dpi"][0],delta=0.01)
            x,y,w,h = body["image_rect"]
            row = [image.getpixel((int(x+w*(i+0.5)/3),int(y+h/4)))[:3] for i in range(3)]
            self.assertEqual([(255,0,0),(255,255,255),(0,0,255)], row)
            interior = self.np.array(image)[int(y)+3:int(y+h)-3,int(x)+3:int(x+w)-3,:3]
            self.assertEqual({(255,0,0),(0,0,255),(255,255,255)},set(map(tuple,self.np.unique(interior.reshape(-1,3),axis=0))))
        svg = ET.parse(output["outputs"]["svg"]["artifact_ref"]["uri"]).getroot()
        self.assertAlmostEqual(297/25.4*72,float(svg.attrib["width"][:-2]),places=5)
        self.assertAlmostEqual(210/25.4*72,float(svg.attrib["height"][:-2]),places=5)
        self.assertFalse(svg.findall(".//{http://www.w3.org/2000/svg}text")) # explicit glyph paths
        for image in svg.findall(".//{http://www.w3.org/2000/svg}image"):
            self.assertTrue(image.attrib["{http://www.w3.org/1999/xlink}href"].startswith("data:image/png;base64,"))
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("PDF structural QA requires optional pypdf")
        pdf = PdfReader(output["outputs"]["pdf"]["artifact_ref"]["uri"])
        self.assertEqual(1,len(pdf.pages))
        self.assertAlmostEqual(297/25.4*72,float(pdf.pages[0].mediabox.width),places=5)
        self.assertAlmostEqual(210/25.4*72,float(pdf.pages[0].mediabox.height),places=5)
        self.assertIn("Synthetic categorical map",pdf.pages[0].extract_text())
        self.assertIn("Category A",pdf.pages[0].extract_text())
        fonts=pdf.pages[0]["/Resources"]["/Font"].get_object()
        self.assertTrue(fonts)
        for font in fonts.values():
            self.assertEqual("/Type0",font.get_object()["/Subtype"])
            descendant=font.get_object()["/DescendantFonts"][0].get_object()
            self.assertIn("/FontFile2",descendant["/FontDescriptor"].get_object())

    def test_identical_rerender_and_original_file_removal(self):
        artifact, output = self.render()
        self.source_path.unlink(); self.legend_path.unlink(); Path(self.page["font"]["path"]).unlink()
        self.assertEqual(output,self.page_renderer.load_verified(artifact.ref(),self.context))
        self.assertFalse(any("approval" in str(p) for p in self.root.rglob("*")))

    def test_page_rejects_raw_preparation_or_legacy_prepared_ref(self):
        original = deepcopy(self.page)
        self.page["portrayal_ref"] = self.prepared.ref()
        with self.assertRaises(CartoError): self.render()
        self.page = deepcopy(original)
        self.page["prepared_ref"] = self.page.pop("portrayal_ref")
        with self.assertRaises(CartoError): self.render()

    def test_pending_answers_fail_before_page_dependencies(self):
        self.page["portrayal_ref"] = raster_helpers.pending_portrayal(
            self.service, self.page["portrayal_ref"], self.analyze()).ref()
        with patch("carto_core.adapters.raster_page_renderer._dependencies",side_effect=AssertionError("must not load")), \
                self.assertRaisesRegex(CartoError,"CLARIFICATION_REQUIRED"):
            self.render()

    def test_font_digest_glyph_embedding_format_and_path_guards(self):
        original = deepcopy(self.page)
        for kind in ("digest", "glyph", "format", "outside"):
            self.page = deepcopy(original)
            if kind == "digest": self.page["font"]["digest"] = "sha256:" + "0"*64
            if kind == "glyph": self.page["texts"][0]["text"] = "用地分类数据"
            if kind == "format":
                Path(self.page["font"]["path"]).write_bytes(b"ttcf"+b"synthetic")
                data=Path(self.page["font"]["path"]).read_bytes()
                self.page["font"].update(digest=self.service.digest_bytes(data),size_bytes=len(data))
            if kind == "outside": self.page["font"]["path"] = str(self.root.parent / "not-allowed.ttf")
            with self.subTest(kind=kind), self.assertRaises(CartoError): self.render()
        self.page=page_request(self.service,self.prepared,self.context)
        from fontTools.ttLib import TTFont
        for flags in (2,0x100,0x200):
            self.page=page_request(self.service,self.prepared,self.context)
            path=Path(self.page["font"]["path"])
            with TTFont(path) as font:
                font["OS/2"].fsType=flags
                stream=io.BytesIO(); font.save(stream)
            path.write_bytes(stream.getvalue())
            self.page["font"].update(digest=self.service.digest_bytes(path.read_bytes()),size_bytes=path.stat().st_size)
            with self.subTest(flags=flags), self.assertRaisesRegex(CartoError,"FONT_EMBEDDING_FORBIDDEN"): self.render()

    def test_binding_unknown_fields_capacity_and_text_overflow(self):
        for kind in ("duplicate", "missing", "wrong-kind", "unknown", "overflow", "capacity", "stale-layout"):
            page=deepcopy(self.page)
            if kind == "duplicate": page["texts"].append(deepcopy(page["texts"][0]))
            if kind == "missing": page["texts"].pop()
            if kind == "wrong-kind": page["texts"][0]["content_id"]="legend"
            if kind == "unknown": page["legend"]["colors"]=["#FF0000"]
            if kind == "overflow": page["texts"][1]["text"]="Long source text "*100
            if kind == "capacity": page["texts"][0]["text"]="a"*201
            if kind == "stale-layout": page["resolved_layout"]["page"]["width_mm"]=300
            with self.subTest(kind=kind),self.assertRaises(CartoError):
                self.page_renderer.render(page,self.context)

    def test_mutated_output_and_forged_provenance_are_rejected(self):
        artifact, output=self.render()
        forged=deepcopy(output); forged["environment"]["matplotlib"]="forged"
        bad=self.service.save_document(forged,"raster-page-output")
        with self.assertRaisesRegex(CartoError,"RASTER_PAGE_CHANGED"):
            self.page_renderer.load_verified(bad.ref(),self.context)
        self.context.subject_id="other-subject"
        with self.assertRaisesRegex(CartoError,"SCOPE_MISMATCH"):
            self.page_renderer.load_verified(artifact.ref(),self.context)
        self.context.subject_id="test-subject"
        Path(output["outputs"]["pdf"]["artifact_ref"]["uri"]).write_bytes(b"changed-pdf")
        with self.assertRaisesRegex(CartoError,"SNAPSHOT_CHANGED"):
            self.page_renderer.load_verified(artifact.ref(),self.context)

    def test_wrapping_literal_math_and_global_rc_do_not_change_contract(self):
        self.page["texts"][1]["text"]=r"$literal \notatex$ " + "source note "*6
        _, output=self.render()
        self.assertTrue(output["measurements"])
        with self.mpl.rc_context({"text.usetex":True,"savefig.bbox":"tight","pdf.fonttype":3,"svg.fonttype":"none"}):
            _, repeated=self.render()
        self.assertEqual(output,repeated)

    def test_grid_north_and_scale_are_explicit_not_true_north(self):
        self.page["resolved_layout"]=adorned_layout()
        self.page["grid_north"]={"content_id":"north","label":"Grid north"}
        self.page["scale_bar"]={"content_id":"scale","distance_m":30,"label_language":"en"}
        _, output=self.render()
        body=self.service._json_ref(output["body_ref"],"raster-map-body")
        segments=[m for m in output["measurements"] if m["element_id"].startswith("scale-segment")]
        # Measurements include a 0.4pt stroke on each rectangle.
        self.assertAlmostEqual(30*body["ground_to_image"][0],sum(s["bounds_px"][2]-0.4*300/72 for s in segments),places=4)
        self.page["scale_bar"]["distance_m"]=10000
        with self.assertRaisesRegex(CartoError,"SCALE_LENGTH_INVALID"): self.render()
        self.page["grid_north"]["label"]="True north"
        with self.assertRaises(CartoError): self.render()

    def test_scale_converts_projected_us_survey_feet_to_meters(self):
        body={"crs":"EPSG:2229","ground_to_image":[2,0,0,0,-2,0]}
        self.assertAlmostEqual(2*1000/(1200/3937),self.page_renderer.grid_scale_length(body,1000),places=6)
        body["crs"]="EPSG:4326"
        with self.assertRaisesRegex(CartoError,"SCALE_CRS_UNSUPPORTED"):
            self.page_renderer.grid_scale_length(body,1000)

    def test_render_failure_does_not_publish_page_outputs(self):
        self.page["texts"][1]["text"]="This cannot fit "*120
        with self.assertRaisesRegex(CartoError,"CONTENT_OVERFLOW"):
            self.render()
        for kind in ("page-pdf","page-png","page-svg","raster-page-output"):
            self.assertFalse((self.service.root/kind).exists())

    def test_physical_font_size_stays_fixed_when_dpi_changes(self):
        _, full=self.render()
        self.page["resolved_layout"]=raster_helpers.a4_layout(150)
        _, half=self.render()
        f=next(v for v in full["measurements"] if v["element_id"]=="title")
        h=next(v for v in half["measurements"] if v["element_id"]=="title")
        self.assertAlmostEqual(f["bounds_px"][3]/300,h["bounds_px"][3]/150,delta=0.01)

    @unittest.skipUnless(os.environ.get("CARTO_TEST_CJK_FONT"),"Explicit CJK font required")
    def test_chinese_pdf_text_and_pdf_page_rasterization(self):
        try:
            from pypdf import PdfReader
            import pypdfium2 as pdfium
        except ImportError:
            self.skipTest("PDF QA requires optional pypdf and pypdfium2")
        # Ten synthetic categories exercise a realistic legend density and Chinese wrapping.
        yy, xx = self.np.indices((80,120))
        raster_helpers.RasterRendererTests.set_raster(self, ((xx//10+yy//8)%10+1).astype("uint8"))
        palette=["#EECC66","#75AD78","#B9D77C","#E4AE92","#D65C5C","#7298CC","#AF8AB9","#74C4C7","#C6BEAF","#998B73"]
        labels=["合成类别"+letter for letter in "甲乙丙丁戊己庚辛壬癸"]
        labels[2] += "（较长名称用于自动换行测试）"
        self.legend_path.write_text("value,label,color\n"+"".join(f"{i},{label},{color}\n" for i,(label,color) in enumerate(zip(labels,palette),1)),encoding="utf-8")
        self.sync_inputs()
        self.prepared=self.analyze()
        self.page=page_request(self.service,self.prepared,self.context,Path(os.environ["CARTO_TEST_CJK_FONT"]))
        self.page["resolved_layout"]=adorned_layout()
        self.page["grid_north"]={"content_id":"north","label":"格网北"}
        self.page["scale_bar"]={"content_id":"scale","distance_m":1000,"label_language":"zh"}
        self.page["texts"][0]["text"]="用地分类数据"
        self.page["texts"][1]["text"]="合成测试数据；非用户成果"
        self.page["legend"]["title"]="分类图例"
        artifact, output=self.render()
        reader=PdfReader(output["outputs"]["pdf"]["artifact_ref"]["uri"])
        self.assertIn("用地分类数据",reader.pages[0].extract_text())
        self.assertIn("分类图例",reader.pages[0].extract_text())
        self.assertIn("格网北",reader.pages[0].extract_text())
        self.assertIn("投影距离",reader.pages[0].extract_text())
        self.assertEqual(10,len([m for m in output["measurements"] if m["element_id"].startswith("legend-swatch")]))
        self.assertEqual(output,self.page_renderer.load_verified(artifact.ref(),self.context))
        # Render the PDF independently; pixel size may be rounded up by PDFium.
        with pdfium.PdfDocument(output["outputs"]["pdf"]["artifact_ref"]["uri"]) as pdf:
            page=pdf[0]
            bitmap=page.render(scale=150/72)
            image=bitmap.to_pil().copy()
            self.assertTrue(abs(image.width-1754)<=1 and abs(image.height-1240)<=1)
            qa=os.environ.get("CARTO_RASTER_QA_DIR")
            if qa:
                folder=Path(qa).resolve()
                workspace=Path(__file__).resolve().parents[4]
                if not folder.is_relative_to(workspace/"projects/.carto-dev"):
                    self.fail("QA output must stay in the ignored project development directory")
                folder.mkdir(parents=True,exist_ok=True)
                image.save(folder/"synthetic-a4-chinese-pdf.png")
                for kind, asset in output["outputs"].items():
                    (folder/f"synthetic-a4-chinese.{kind}").write_bytes(Path(asset["artifact_ref"]["uri"]).read_bytes())
            bitmap.close();page.close()


@unittest.skipUnless(os.environ.get("CARTO_GEOSPATIAL_TEST_PYTHON"),"Explicit independent GIS interpreter required")
class RasterPageRealMcpTests(unittest.TestCase):
    def test_real_mcp_to_print_page(self):
        from tests.test_geospatial_stdio import GeospatialStdioTests
        GeospatialStdioTests.setUp(self)
        try: _dependencies()
        except CartoError as exc: self.skipTest(str(exc))
        self.addCleanup(release_test_font_handles)
        legend=self.project/"legend.csv"
        legend.write_text("value,label,color\n1,Category A,#FF0000\n2,Category C,#00FF00\n",encoding="utf-8")
        service=RasterPreparationService(project_root=self.project,allowed_roots=self.allowed_roots)
        request=deepcopy(VALID_CASES["raster-classification-request"])
        request["source"]=self.source
        request["legend"].update(path=str(legend),digest=service.digest_bytes(legend.read_bytes()),size_bytes=legend.stat().st_size)
        context=ExecutionContext("page-integration","test-tenant","test-project","test-subject",
            frozenset({"operator"}),frozenset({"test-project"}),frozenset({"gis-raster-statistics"}))
        baseline=service.analyze(request,context,GeospatialStdioTests.adapter(self))
        ready=service.clarify(baseline.ref(),PreparationFixture.answers(baseline),context)
        count=context.budget.tool_calls
        renderer=RasterPageRenderer(service)
        result=renderer.render(page_request(service,ready,context),context)
        output=renderer.load_verified(result.ref(),context)
        self.assertEqual({"pdf","png","svg"},set(output["outputs"]))
        self.assertEqual(count,context.budget.tool_calls)
        self.assertFalse(any("approval" in str(p) for p in self.root.rglob("*")))


if __name__ == "__main__":
    unittest.main()
