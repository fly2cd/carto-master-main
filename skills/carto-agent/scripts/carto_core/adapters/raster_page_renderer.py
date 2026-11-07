"""Internal print-page backend for a frozen categorical raster.

Uses the shared LayoutResolver frame contract, not the SVG compositor's fixed-pixel
text placement. Matplotlib owns text metrics, glyph paths and PDF font embedding.
This component does NOT create a RenderReceipt, consume gates or publish a delivery.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import math
from threading import RLock
from pathlib import Path
from typing import Any
import zlib

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..repository.immutable_store import StoredArtifact
from ..workflow.models import ExecutionContext
from ..workflow.raster_preparation import RasterPreparationService
from .raster_renderer import RasterMapBodyRenderer, _dependencies, renderer_digest

VERSION = "1.0.0"
FONT_LIMIT = 32 * 1024 * 1024
_PAGE_RENDER_LOCK = RLock()


def page_renderer_digest() -> str:
    path = Path(__file__).resolve()
    root = path.parents[3]
    paths = [path, path.parents[1] / "workflow/raster_preparation.py",
             path.parents[1] / "compiler/raster_portrayal.py",
             root / "schemas/raster-page-request.schema.json", root / "schemas/raster-page-output.schema.json"]
    return sha256_digest({"version": VERSION, "body_renderer": renderer_digest(),
                          "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


class RasterPageRenderer:
    """Produce immutable internal PDF/PNG/SVG assets; no output path supplied by users."""

    def __init__(self, preparation: RasterPreparationService) -> None:
        self.preparation = preparation
        self.body_renderer = RasterMapBodyRenderer(preparation)
        self.layout = self.body_renderer.layout

    def _validate(self, request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        self.preparation.registry.validate("raster-page-request", request)
        self.body_renderer.portrayal_compiler.load_verified(request["portrayal_ref"], context)
        resolved = request["resolved_layout"]
        self.layout.validate(resolved)
        frames = resolved["frames"]
        by_content = {f["content_id"]: f for f in frames if f["type"] != "map"}
        assigned: dict[str, str] = {}
        for item, kinds in [(t, {"title", "marginalia"}) for t in request["texts"]] + [
                (request["legend"], {"legend"}), (request["scale_bar"], {"scale-bar"}),
                (request["grid_north"], {"north-arrow"})]:
            if item is None:
                continue
            key = item["content_id"]
            if key in assigned or key not in by_content or by_content[key]["type"] not in kinds:
                raise ProtocolError("RASTER_PAGE_FRAME_BINDING", "Every page element must bind one frame of the correct type")
            assigned[key] = by_content[key]["type"]
        if set(assigned) != set(by_content) or list(assigned.values()).count("title") != 1:
            raise ProtocolError("RASTER_PAGE_FRAME_BINDING", "Require one title, one legend and no unused or unsupported frame")
        # Reject NaN/infinity before importing libraries, including callers bypassing JSON encoding.
        if not all(math.isfinite(v) for v in request["typography"].values()):
            raise ProtocolError("RASTER_PAGE_NUMBER_INVALID", "Typography must be finite")
        scale = request["scale_bar"]
        if scale is not None and not math.isfinite(scale["distance_m"]):
            raise ProtocolError("RASTER_PAGE_NUMBER_INVALID", "Scale distance must be finite")
        for text in request["texts"]:
            if assigned[text["content_id"]] == "title" and len(text["text"]) > resolved["contract"]["capacity"]["title_characters"]:
                raise ProtocolError("RASTER_PAGE_TITLE_CAPACITY", "Title exceeds the layout contract capacity")
        return by_content

    def _font(self, request: dict[str, Any], texts: list[str]) -> tuple[dict[str, Any], str, int]:
        source = request["font"]
        data = self.preparation.read_bytes(Path(source["path"]), FONT_LIMIT)
        if len(data) != source["size_bytes"] or self.preparation.digest_bytes(data) != source["digest"]:
            raise ProtocolError("RASTER_FONT_CHANGED", "Selected font differs from its declared digest or length")
        # A single-face TrueType font only. Collections/OTF/WOFF and silent fallback are not supported.
        if data[:4] != b"\x00\x01\x00\x00":
            raise ProtocolError("RASTER_FONT_FORMAT_UNSUPPORTED", "Select a single TrueType .ttf font, not a collection")
        try:
            from fontTools.ttLib import TTFont
            with TTFont(io.BytesIO(data), lazy=False) as font:
                if "OS/2" not in font or "glyf" not in font:
                    raise ProtocolError("RASTER_FONT_FORMAT_UNSUPPORTED", "TrueType outlines and embedding flags are required")
                flags = font["OS/2"].fsType
                # Restricted embedding, no subsetting or bitmap-only embedding cannot use this PDF path.
                if flags & (0x2 | 0x100 | 0x200):
                    raise ProtocolError("RASTER_FONT_EMBEDDING_FORBIDDEN", "Font does not permit this subset/outline embedding mode")
                cmap = font.getBestCmap() or {}
                missing = {ord(c) for text in texts for c in text if not c.isspace() and ord(c) not in cmap}
                if missing:
                    raise ProtocolError("RASTER_FONT_GLYPH_MISSING", f"Selected font misses {len(missing)} required codepoints")
                family = font["name"].getDebugName(1)
                if not family:
                    raise ProtocolError("RASTER_FONT_FORMAT_UNSUPPORTED", "Font family metadata is required")
        except ImportError:
            raise ProtocolError("RASTER_RENDER_DEPENDENCY_MISSING", "The raster-rendering extra requires fonttools") from None
        except ProtocolError:
            raise
        except Exception:
            raise ProtocolError("RASTER_FONT_INVALID", "Cannot decode the selected TrueType font") from None
        return self.preparation._asset(data, "font", ".ttf"), family, flags

    @staticmethod
    def _scale_label(scale: dict[str, Any]) -> str:
        meters = scale["distance_m"]
        distance = f"{meters / 1000:g} km" if meters >= 1000 else f"{meters:g} m"
        prefix = "投影距离" if scale["label_language"] == "zh" else "Grid distance:"
        return f"{prefix} {distance}"

    @staticmethod
    def grid_scale_length(body: dict[str, Any], distance_m: float) -> float:
        import rasterio
        crs = rasterio.crs.CRS.from_string(body["crs"])
        if not crs.is_projected:
            raise ProtocolError("RASTER_SCALE_CRS_UNSUPPORTED", "A projected linear CRS is required")
        _, meters_per_unit = crs.linear_units_factor
        if not math.isfinite(meters_per_unit) or meters_per_unit <= 0:
            raise ProtocolError("RASTER_SCALE_CRS_UNSUPPORTED", "CRS linear units must be known")
        return distance_m * body["ground_to_image"][0] / meters_per_unit

    def freeze_request(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        """Snapshot the approved font/input contract without drawing or issuing approvals."""
        self._validate(request, context)
        request = deepcopy(request)
        portrayal = self.body_renderer.portrayal_compiler.load_verified(request["portrayal_ref"], context)
        strings = ([item["text"] for item in request["texts"]] + [request["legend"]["title"]]
                   + [row["label"] for row in portrayal["legend_items"]])
        if request["scale_bar"] is not None:
            strings.append(self._scale_label(request["scale_bar"]))
        if request["grid_north"] is not None:
            strings.append(request["grid_north"]["label"])
        font, _, _ = self._font(request, strings)
        request["font"] = {"path": font["artifact_ref"]["uri"], "digest": font["artifact_ref"]["digest"],
                           "size_bytes": font["size_bytes"]}
        return self.preparation.save_document(request, "raster-page-request")

    def render(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        """Freeze an explicit font and render only a ready classification in the same scope."""
        self._validate(request, context)
        request = deepcopy(request)
        body_artifact = self.body_renderer.render(request["portrayal_ref"], request["resolved_layout"], context)
        body = self.preparation._json_ref(body_artifact.ref(), "raster-map-body")
        rows = body["legend_items"]
        if not rows or len(rows) > request["resolved_layout"]["contract"]["capacity"]["legend_items"]:
            raise ProtocolError("RASTER_PAGE_LEGEND_CAPACITY", "The page requires a nonempty legend within layout capacity")
        strings = [item["text"] for item in request["texts"]] + [request["legend"]["title"]] + [row["label"] for row in rows]
        if request["scale_bar"] is not None:
            strings.append(self._scale_label(request["scale_bar"]))
        if request["grid_north"] is not None:
            strings.append(request["grid_north"]["label"])
        font_asset, family, flags = self._font(request, strings)
        request["font"] = {"path": font_asset["artifact_ref"]["uri"], "digest": font_asset["artifact_ref"]["digest"],
                           "size_bytes": font_asset["size_bytes"]}
        frozen_request = self.preparation.save_document(request, "raster-page-request")
        payloads, measurements, environment = self._draw(request, body, font_asset)
        self.preparation.snapshot_bytes(font_asset, "font", ".ttf")
        outputs = {kind: self.preparation._asset(data, f"page-{kind}", f".{kind}") for kind, data in payloads.items()}
        result = {
            "schema_version": 1, "kind": "raster-page-output", "renderer_id": "rasterio-matplotlib-page",
            "renderer_version": VERSION, "renderer_code_digest": page_renderer_digest(),
            "request_ref": frozen_request.ref(), "body_ref": body_artifact.ref(),
            "font_snapshot": font_asset, "font_family": family, "font_embedding_flags": flags,
            "environment": environment, "outputs": outputs, "measurements": measurements,
            "checks": {key: "passed" for key in ["frame-binding", "glyph-coverage", "font-embedding", "content-fit", "png-dimensions"]},
            "capability_boundary": "internal-page-output-not-formal-render-receipt",
        }
        return self.preparation.save_document(result, "raster-page-output")

    def load_verified(self, reference: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        """Verify outputs AND re-render frozen inputs; changed fonts/code/layout/environment fail closed."""
        output = self.preparation._json_ref(reference, "raster-page-output")
        request = self.preparation._json_ref(output["request_ref"], "raster-page-request")
        self._validate(request, context)
        for kind, asset in output["outputs"].items():
            self.preparation.snapshot_bytes(asset, f"page-{kind}", f".{kind}")
        current = self.render(request, context)
        if current.digest != reference["digest"]:
            raise ProtocolError("RASTER_PAGE_CHANGED", "Page provenance differs from its frozen result")
        return output

    def _draw(self, request: dict[str, Any], body: dict[str, Any], font_asset: dict[str, Any]
              ) -> tuple[dict[str, bytes], list[dict[str, Any]], dict[str, str]]:
        np, rasterio, mpl, _, _, _, Image = _dependencies()
        import fontTools
        from matplotlib import ft2font
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties
        from matplotlib.patches import Rectangle, FancyArrowPatch
        layout = request["resolved_layout"]
        page, typography = layout["page"], request["typography"]
        width, height, dpi = page["width_px"], page["height_px"], page["dpi"]
        mm = dpi / 25.4
        padding = typography["padding_mm"] * mm
        frames = {f["content_id"]: f for f in layout["frames"]}
        font_path = font_asset["artifact_ref"]["uri"]
        # Explicit rc context: no TeX/math parsing, tight crop, system font fallback or random SVG IDs.
        rc = {"text.usetex": False, "text.parse_math": False, "pdf.fonttype": 42, "pdf.use14corefonts": False,
              "pdf.compression": 6, "svg.fonttype": "path", "svg.hashsalt": sha256_digest(request),
              "savefig.bbox": None, "savefig.pad_inches": 0, "savefig.transparent": False,
              "image.composite_image": False, "path.simplify": False, "text.hinting": "none",
              "text.antialiased": True}
        if "font.enable_last_resort" in mpl.rcParams:
            rc["font.enable_last_resort"] = False
        if tuple(int(v) for v in mpl.__version__.split(".")[:2]) < (3, 11):
            rc["text.hinting_factor"] = 8
            rc["text.kerning_factor"] = 0
        with _PAGE_RENDER_LOCK, mpl.rc_context(rc):
            # Rounded integer PNG canvas; physical PDF/SVG sizes are set separately below.
            fig = Figure(figsize=((width + 1e-7) / dpi, (height + 1e-7) / dpi), dpi=dpi,
                         facecolor="white", layout="none")
            canvas = FigureCanvasAgg(fig)
            metrics = canvas.get_renderer()
            artists: list[tuple[str, str, Any, float]] = []

            def props(size: float) -> Any:
                return FontProperties(fname=font_path, size=size)

            def wrap(text: str, available: float, size: float) -> str:
                if available <= 0:
                    raise ProtocolError("RASTER_PAGE_CONTENT_OVERFLOW", "Frame has no content width after padding")
                prop = props(size)
                def measure(value: str) -> float:
                    return metrics.get_text_width_height_descent(value, prop, ismath=False)[0]
                lines: list[str] = []
                for paragraph in text.split("\n"):
                    if not paragraph:
                        lines.append("")
                    while paragraph:
                        lo, hi = 0, len(paragraph)
                        while lo < hi:
                            mid = (lo + hi + 1) // 2
                            if measure(paragraph[:mid]) <= available:
                                lo = mid
                            else:
                                hi = mid - 1
                        if lo == 0:
                            raise ProtocolError("RASTER_PAGE_CONTENT_OVERFLOW", "A glyph cannot fit the selected frame and point size")
                        cut = lo
                        if cut < len(paragraph):
                            space = paragraph.rfind(" ", 0, cut + 1)
                            if space > 0:
                                cut = space
                        lines.append(paragraph[:cut])
                        paragraph = paragraph[cut:].lstrip(" ")
                return "\n".join(lines)

            def text(element: str, content: str, value: str, x: float, y: float, size: float,
                     available: float, align: str = "left") -> float:
                wrapped = wrap(value, available, size)
                anchor_x = x + available / 2 if align == "center" else x
                artist = fig.text(anchor_x / width, 1 - y / height, wrapped, transform=fig.transFigure,
                                  fontproperties=props(size), ha=align, va="top", color="#17212B",
                                  linespacing=typography["line_spacing"], parse_math=False, usetex=False)
                artists.append((element, content, artist, 0))
                return artist.get_window_extent(metrics).height

            def patch(element: str, content: str, x: float, y: float, w: float, h: float, color: str) -> None:
                artist = Rectangle((x / width, 1 - (y + h) / height), w / width, h / height,
                                   facecolor=color, edgecolor="#444444", linewidth=0.4, transform=fig.transFigure)
                fig.add_artist(artist)
                artists.append((element, content, artist, 0.2 * dpi / 72))

            pixels = self.preparation.snapshot_bytes(body["image"], "map-body", ".png")
            with Image.open(io.BytesIO(pixels)) as image:
                rgba = np.array(image.convert("RGBA"))
            x, y, w, h = body["image_rect"]
            axis = fig.add_axes([x / width, 1 - (y + h) / height, w / width, h / height])
            axis.imshow(rgba, origin="upper", interpolation="none", resample=False, aspect="auto")
            axis.set_axis_off()
            for item in request["texts"]:
                frame = frames[item["content_id"]]
                x, y, w, h = frame["bounds_px"]
                size = typography["title_pt" if frame["type"] == "title" else "body_pt"]
                text(item["content_id"], item["content_id"], item["text"], x + padding, y + padding,
                     size, w - 2 * padding)
            legend = request["legend"]
            key = legend["content_id"]
            x, y, w, h = frames[key]["bounds_px"]
            cursor = y + padding
            cursor += text("legend-heading", key, legend["title"], x + padding, cursor,
                           typography["legend_heading_pt"], w - 2 * padding) + 3 * mm
            swatch, gap = 3 * mm, 2 * mm
            for index, row in enumerate(body["legend_items"]):
                item_height = text(f"legend-label-{index}", key, row["label"], x + padding + swatch + gap,
                                   cursor, typography["legend_pt"], w - 2 * padding - swatch - gap)
                patch(f"legend-swatch-{index}", key, x + padding, cursor, swatch, swatch, row["color"])
                cursor += max(swatch, item_height) + 2 * mm
            scale = request["scale_bar"]
            if scale is not None:
                key = scale["content_id"]
                x, y, w, h = frames[key]["bounds_px"]
                # Horizontal grid distance, not geodesic distance or a uniform true-ground scale.
                length = self.grid_scale_length(body, scale["distance_m"])
                if length < 2 or length > w - 2 * padding:
                    raise ProtocolError("RASTER_SCALE_LENGTH_INVALID", "Requested distance is too small or exceeds the scale frame")
                label_height = text("scale-label", key, self._scale_label(scale), x + padding, y + padding,
                                    typography["body_pt"], w - 2 * padding)
                for i in range(2):
                    patch(f"scale-segment-{i}", key, x + padding + length * i / 2,
                          y + padding + label_height + 2 * mm, length / 2, 2 * mm, "#222222" if i == 0 else "#FFFFFF")
            north = request["grid_north"]
            if north is not None:
                key = north["content_id"]
                x, y, w, h = frames[key]["bounds_px"]
                center = x + w / 2
                arrow = FancyArrowPatch((center / width, 1 - (y + padding + 14 * mm) / height),
                                        (center / width, 1 - (y + padding + 2 * mm) / height),
                                        arrowstyle="-|>", mutation_scale=12, color="#17212B", linewidth=1,
                                        transform=fig.transFigure)
                fig.add_artist(arrow)
                artists.append(("grid-north-arrow", key, arrow, dpi / 144))
                text("grid-north-label", key, north["label"], x + padding, y + padding + 17 * mm,
                     typography["body_pt"], w - 2 * padding, align="center")
            canvas.draw()
            measurements = []
            for element, content, artist, stroke in artists:
                box = artist.get_window_extent(canvas.get_renderer())
                bounds = [box.x0 - stroke, height - box.y1 - stroke, box.width + 2 * stroke, box.height + 2 * stroke]
                fx, fy, fw, fh = frames[content]["bounds_px"]
                bx, by, bw, bh = bounds
                if (not all(math.isfinite(v) for v in bounds) or bx < fx or by < fy
                        or bx + bw > fx + fw or by + bh > fy + fh):
                    raise ProtocolError("RASTER_PAGE_CONTENT_OVERFLOW", f"Measured content exceeds frame {frames[content]['id']}")
                measurements.append({"element_id": element, "frame_id": frames[content]["id"],
                                     "bounds_px": [round(v, 6) for v in bounds]})
            payloads: dict[str, bytes] = {}
            png = io.BytesIO()
            fig.savefig(png, format="png", dpi=dpi, facecolor="white", bbox_inches=None,
                        metadata={"Software": "Carto rasterio-matplotlib-page " + VERSION})
            payloads["png"] = png.getvalue()
            with Image.open(io.BytesIO(payloads["png"])) as image:
                if image.size != (width, height):
                    raise ProtocolError("RASTER_PAGE_DIMENSIONS_INVALID", "PNG must match the rounded layout canvas")
            fig.set_size_inches(page["width_mm"] / 25.4, page["height_mm"] / 25.4, forward=False)
            for kind, metadata in [("pdf", {"Creator": "Carto rasterio-matplotlib-page " + VERSION,
                                            "CreationDate": None, "ModDate": None}),
                                   ("svg", {"Creator": "Carto rasterio-matplotlib-page " + VERSION, "Date": None})]:
                stream = io.BytesIO()
                fig.savefig(stream, format=kind, dpi=dpi, facecolor="white", bbox_inches=None, metadata=metadata)
                payloads[kind] = stream.getvalue()
            fig.clear()
        environment = {**body["environment"], "freetype": ft2font.__freetype_version__,
                       "fonttools": fontTools.__version__, "zlib": zlib.ZLIB_RUNTIME_VERSION}
        return payloads, measurements, environment
