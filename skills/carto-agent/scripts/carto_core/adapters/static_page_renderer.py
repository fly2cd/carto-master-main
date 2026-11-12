"""Shared physical-page typography, fitting and export. No business or data rules."""
from __future__ import annotations
from copy import deepcopy
import io
import math
from pathlib import Path
from threading import RLock
from typing import Any
import zlib
from ..canonical import sha256_digest
from ..errors import ProtocolError
from .raster_renderer import _dependencies

FONT_LIMIT = 32 * 1024 * 1024
_PAGE_RENDER_LOCK = RLock()

class MeasuredPageRenderer:
    def _strings(self, request):
        strings=[x['text'] for x in request['texts']]
        for legend in request['legends']:
            strings.append(legend['title']);strings.extend(x['label'] for x in legend['items'])
        if request['scale_bar'] is not None:strings.append(self._scale_label(request['scale_bar']))
        if request['grid_north'] is not None:strings.append(request['grid_north']['label'])
        return strings


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


    def _draw(self, request: dict[str, Any], bodies: dict[str, Any], font_asset: dict[str, Any]
              ) -> tuple[dict[str, bytes], list[dict[str, Any]], dict[str, str]]:
        np, rasterio, mpl, _, _, _, Image = _dependencies()
        import fontTools
        from matplotlib import ft2font
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties
        from matplotlib.patches import Rectangle, FancyArrowPatch
        layout = request["resolved_layout"]
        page, typography = layout["page"], request["appearance"]["typography"]
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

            self._draw_map_bodies(fig, bodies, width, height, dpi)
            for item in request["texts"]:
                frame = frames[item["content_id"]]
                x, y, w, h = frame["bounds_px"]
                size = typography["title_pt" if frame["type"] == "title" else "body_pt"]
                text(item["content_id"], item["content_id"], item["text"], x + padding, y + padding,
                     size, w - 2 * padding)
            declared_frames={f['content_id']:f for f in layout['contract']['frames']}
            for legend in request['legends']:
                key=legend['content_id'];x,y,w,h=frames[key]['bounds_px'];cursor=y+padding
                cursor+=text(key+'-heading',key,legend['title'],x+padding,cursor,typography['legend_heading_pt'],w-2*padding)+3*mm
                swatch,gap=self._legend_swatch_mm(legend)*mm,2*mm;cols=declared_frames[key].get('legend_columns',1)
                col_width=(w-2*padding)/cols
                for start in range(0,len(legend['items']),cols):
                    row_height=0
                    for column,row in enumerate(legend['items'][start:start+cols]):
                        index=start+column;left=x+padding+column*col_width
                        ih=text(f'{key}-label-{index}',key,row['label'],left+swatch+gap,cursor,
                                typography['legend_pt'],col_width-swatch-gap)
                        self._draw_legend_symbol(fig, artists, row, f'{key}-swatch-{index}', key, left, cursor, swatch, width, height, dpi)
                        row_height=max(row_height,swatch,ih)
                    cursor+=row_height+2*mm
            body=next(iter(bodies.values()))
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
                        metadata={"Software": "Carto " + self.renderer_id + " " + self.renderer_version})
            payloads["png"] = png.getvalue()
            with Image.open(io.BytesIO(payloads["png"])) as image:
                if image.size != (width, height):
                    raise ProtocolError("RASTER_PAGE_DIMENSIONS_INVALID", "PNG must match the rounded layout canvas")
            fig.set_size_inches(page["width_mm"] / 25.4, page["height_mm"] / 25.4, forward=False)
            for kind, metadata in [("pdf", {"Creator": "Carto " + self.renderer_id + " " + self.renderer_version,
                                            "CreationDate": None, "ModDate": None}),
                                   ("svg", {"Creator": "Carto " + self.renderer_id + " " + self.renderer_version, "Date": None})]:
                stream = io.BytesIO()
                fig.savefig(stream, format=kind, dpi=dpi, facecolor="white", bbox_inches=None, metadata=metadata)
                payloads[kind] = stream.getvalue()
            fig.clear()
        environment = {**body["environment"], "freetype": ft2font.__freetype_version__,
                       "fonttools": fontTools.__version__, "zlib": zlib.ZLIB_RUNTIME_VERSION}
        return payloads, measurements, environment


    def _draw_map_bodies(self, fig, bodies, width, height, dpi):
        raise NotImplementedError

    @staticmethod
    def _legend_swatch_mm(legend):
        return 3

    @staticmethod
    def _draw_legend_symbol(fig, artists, row, element, content, x, y, swatch, width, height, dpi):
        from matplotlib.patches import Rectangle
        artist = Rectangle((x / width, 1 - (y + swatch) / height), swatch / width, swatch / height,
                           facecolor=row['color'], edgecolor='#444444', linewidth=0.4, transform=fig.transFigure)
        fig.add_artist(artist)
        artists.append((element, content, artist, 0.2 * dpi / 72))

