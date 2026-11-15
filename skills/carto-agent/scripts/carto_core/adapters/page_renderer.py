"""Unified page renderer with geometry branching for raster and vector painting.

Raster geometry pre-renders map bodies and embeds them as images; vector geometry
draws features directly as matplotlib patches. Both share the MeasuredPageRenderer
typography/fitting/export base.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import io
import math
from pathlib import Path
from threading import RLock
from typing import Any

from ..backend_registry import RASTER_PAGE, VECTOR_PAGE
from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..errors import ProtocolError
from ..repository.immutable_store import StoredArtifact
from ..contracts.execution import ExecutionContext
from .static_page_renderer import MeasuredPageRenderer, FONT_LIMIT

RASTER_RENDERER_ID = RASTER_PAGE.renderer_id
RASTER_VERSION = "3.0.0"
VECTOR_RENDERER_ID = VECTOR_PAGE.renderer_id
VECTOR_VERSION = "1.0.0"


def page_renderer_digest(geometry: str = "raster") -> str:
    """Code digest covering all files that affect page output for the given geometry."""
    from .raster_renderer import renderer_digest as raster_body_digest

    path = Path(__file__).resolve()
    root = path.parents[3]
    common = [
        path,
        path.with_name("static_page_renderer.py"),
        path.parents[1] / "artifacts.py",
        path.parents[1] / "workflow" / "static_assets.py",
        path.parents[1] / "compiler" / "appearance.py",
        path.parents[1] / "compiler" / "page_bindings.py",
        path.parents[1] / "compiler" / "grid_layout.py",
        # P0-2 coverage: LayoutResolver decides frame/viewport geometry for BOTH
        # geometries; it was only fingerprinted on the raster side, and only
        # indirectly through the embedded body-renderer digest.
        path.parents[1] / "compiler" / "layout.py",
        # P0-2 coverage: chart slots are bound by chart_core.bind_chart_slots while
        # freezing a page (compiler.vector_page) and re-validated by
        # static_page_renderer while painting one, so both geometries depend on it.
        path.parents[1] / "compiler" / "chart_core.py",
        root / "schemas" / "cartography.schema.json",
        root / "schemas" / "layout.schema.json",
        root / "schemas" / "resolved-appearance.schema.json",
        root / "schemas" / "page-bindings.schema.json",
        root / "schemas" / "page-request.schema.json",
        root / "schemas" / "page-output.schema.json",
    ]
    if geometry == "raster":
        extra = [
            path.parents[1] / "workflow" / "raster_preparation.py",
            path.parents[1] / "compiler" / "raster_page_contract.py",
            path.parents[1] / "compiler" / "raster_legends.py",
            path.parents[1] / "compiler" / "raster_portrayal.py",
        ]
        version = RASTER_VERSION
    else:
        extra = [
            path.parents[1] / "compiler" / "vector_page.py",
            path.parents[1] / "compiler" / "vector_portrayal.py",
            path.parents[1] / "compiler" / "portrayal_resolver.py",
            path.parents[1] / "workflow" / "vector_preparation.py",
            root / "schemas" / "vector-input.schema.json",
            root / "schemas" / "encoding-ir.schema.json",
            root / "schemas" / "vector-prepared-data.schema.json",
            root / "schemas" / "resolved-portrayal.schema.json",
        ]
        version = VECTOR_VERSION
    all_paths = common + extra
    payload: dict[str, Any] = {"version": version, "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in all_paths}}
    if geometry == "raster":
        payload["body_renderer"] = raster_body_digest()
    return sha256_digest(payload)


class PageRenderer(MeasuredPageRenderer):
    """Unified page renderer. Geometry field on the request selects raster or vector strategy."""

    def __init__(self, preparation: Any) -> None:
        self.preparation = preparation
        self._geometry: str | None = None

    # -- geometry helpers -------------------------------------------------

    @property
    def renderer_id(self) -> str:
        g = self._geometry
        if g == "vector":
            return VECTOR_RENDERER_ID
        return RASTER_RENDERER_ID

    @property
    def renderer_version(self) -> str:
        return VECTOR_VERSION if self._geometry == "vector" else RASTER_VERSION

    # -- validation -------------------------------------------------------

    def validate_request(self, request: dict[str, Any], context: ExecutionContext) -> Any:
        g = request.get("geometry", "raster")
        self._geometry = g
        if g == "vector":
            return self._validate_vector(request, context)
        return self._validate_raster(request, context)

    def _validate_raster(self, request: dict[str, Any], context: ExecutionContext) -> Any:
        from ..compiler.raster_page_contract import validate_page_request
        from ..workflow.preparation_bundle import BundlePreparer
        from .raster_renderer import RasterMapBodyRenderer

        if not hasattr(self, "_body_renderer"):
            self._body_renderer = RasterMapBodyRenderer(self.preparation)
        if not hasattr(self, "_layout"):
            self._layout = self._body_renderer.layout

        inputs = validate_page_request(self.preparation, request, context, BundlePreparer)
        resolved = request["resolved_layout"]
        self._layout.validate(resolved)
        frames = {f["content_id"]: f for f in resolved["frames"] if f["type"] != "map"}
        assigned: dict[str, str] = {}
        items = [(x, {"title", "marginalia"}) for x in request["texts"]]
        items += [(x, {"legend"}) for x in request["legends"]]
        items += [(request["scale_bar"], {"scale-bar"}), (request["grid_north"], {"north-arrow"})]
        for item, kinds in items:
            if item is None:
                continue
            key = item["content_id"]
            frame = frames.get(key)
            if key in assigned or frame is None or frame["type"] not in kinds:
                raise ProtocolError("RASTER_PAGE_FRAME_BINDING", "Missing, duplicate or incompatible content binding")
            assigned[key] = frame["type"]
        if set(assigned) != set(frames) or list(assigned.values()).count("title") != 1:
            raise ProtocolError("RASTER_PAGE_FRAME_BINDING", "Every frame must be bound exactly once")
        if len(inputs["layers"]) > 1 and any(request[k] is not None for k in ("scale_bar", "grid_north")):
            raise ProtocolError("PAGE_BINDING_UNSUPPORTED", "Multi-panel adornments are not enabled")
        if not all(math.isfinite(v) for v in request["appearance"]["typography"].values()):
            raise ProtocolError("RASTER_PAGE_NUMBER_INVALID", "Typography must be finite")
        if request["scale_bar"] is not None and not math.isfinite(request["scale_bar"]["distance_m"]):
            raise ProtocolError("RASTER_PAGE_NUMBER_INVALID", "Scale distance must be finite")
        for item in request["texts"]:
            if assigned[item["content_id"]] == "title" and len(item["text"]) > resolved["contract"]["capacity"]["title_characters"]:
                raise ProtocolError("RASTER_PAGE_TITLE_CAPACITY", "Title exceeds template capacity")
        return inputs

    def _validate_vector(self, request: dict[str, Any], context: ExecutionContext) -> Any:
        from ..compiler.vector_page import validate_page

        if not hasattr(self, "_layout"):
            self._layout = LayoutResolver(self.preparation.registry)
        return validate_page(self.preparation, request, context)

    # -- freeze / render / verify -----------------------------------------

    def freeze_request(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        self.validate_request(request, context)
        request = deepcopy(request)
        font, _, _ = self._font(request, self._strings(request))
        request["font"] = {"path": font["artifact_ref"]["uri"], "digest": font["artifact_ref"]["digest"], "size_bytes": font["size_bytes"]}
        return self.preparation.save_document(request, "page-request")

    def render(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        g = request.get("geometry", "raster")
        self._geometry = g
        if g == "vector":
            return self._render_vector(request, context)
        return self._render_raster(request, context)

    def _render_raster(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        from .raster_renderer import RasterMapBodyRenderer

        self.validate_request(request, context)
        request = deepcopy(request)
        if not hasattr(self, "_body_renderer"):
            self._body_renderer = RasterMapBodyRenderer(self.preparation)
        refs = {x["view_id"]: x["ref"] for x in request["portrayals"]}
        bodies: dict[str, Any] = {}
        body_refs: list[dict[str, Any]] = []
        for panel in request["bindings"]["panels"]:
            body_artifact = self._body_renderer.render(
                refs[panel["view_id"]], request["resolved_layout"], context, frame_id=panel["frame_id"])
            body = self.preparation.document(body_artifact.ref(), "raster-map-body")
            bodies[panel["view_id"]] = body
            body_refs.append({"view_id": panel["view_id"], "frame_id": panel["frame_id"], "ref": body_artifact.ref()})
        if len({sha256_digest(b["environment"]) for b in bodies.values()}) != 1:
            raise ProtocolError("RASTER_ENVIRONMENT_MISMATCH", "Panel environments differ")
        font_asset, family, flags = self._font(request, self._strings(request))
        request["font"] = {"path": font_asset["artifact_ref"]["uri"], "digest": font_asset["artifact_ref"]["digest"], "size_bytes": font_asset["size_bytes"]}
        frozen_request = self.preparation.save_document(request, "page-request")
        payloads, measurements, environment = self._draw(request, bodies, font_asset)
        self.preparation.snapshot_bytes(font_asset, "font", ".ttf")
        outputs = {kind: self.preparation.store_asset(data, f"page-{kind}", f".{kind}") for kind, data in payloads.items()}
        result = {
            "schema_version": 4, "geometry": "raster", "kind": "page-output",
            "renderer_id": RASTER_RENDERER_ID, "renderer_version": RASTER_VERSION,
            "renderer_code_digest": page_renderer_digest("raster"),
            "request_ref": frozen_request.ref(), "body_refs": body_refs,
            "font_snapshot": font_asset, "font_family": family, "font_embedding_flags": flags,
            "environment": environment, "outputs": outputs, "measurements": measurements,
            "checks": {k: "passed" for k in ["frame-binding", "glyph-coverage", "font-embedding", "content-fit", "png-dimensions"]},
            "capability_boundary": "internal-page-output-not-formal-render-receipt",
        }
        return self.preparation.save_document(result, "page-output")

    def _render_vector(self, request: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        layers = self._validate_vector(request, context)
        request = deepcopy(request)
        font, family, flags = self._font(request, self._strings(request))
        frozen = self.freeze_request(request, context)
        request = self.preparation.document(frozen.ref(), "page-request")
        if not hasattr(self, "_layout"):
            self._layout = LayoutResolver(self.preparation.registry)
        bodies = {}
        for p in request["panels"]:
            stack = layers[p["view_id"]]
            bodies[p["view_id"]] = {"stack": stack,
                                    "portrayal": stack[0]["portrayal"], "report": stack[0]["report"],
                                    "panel": p,
                                    "frame": self._layout.map_frame(request["resolved_layout"], p["frame_id"]),
                                    "basemap": request.get("basemap")}

        import platform as _platform
        import zlib as _zlib
        from .raster_renderer import _dependencies as _deps
        try:
            import fontTools as _fontTools
            from matplotlib import ft2font as _ft2font
        except ImportError:
            raise ProtocolError("VECTOR_RENDER_DEPENDENCY_MISSING", "fonttools is required") from None
        from ..geospatial_deps import dependencies as _vec_deps
        _np, _rio, _mpl, _, _, _pil, _ = _deps()
        _fiona, _shapely, *_ = _vec_deps()
        runtime = {"python": _platform.python_version(), "rasterio": _rio.__version__,
                   "gdal": _rio.__gdal_version__, "numpy": _np.__version__,
                   "matplotlib": _mpl.__version__, "pillow": _pil.__version__,
                   "freetype": _ft2font.__freetype_version__, "fonttools": _fontTools.__version__,
                   "zlib": _zlib.ZLIB_RUNTIME_VERSION,
                   "fiona": _fiona.__version__, "shapely": _shapely.__version__,
                   "vector_gdal": _fiona.__gdal_version__}

        for body in bodies.values():
            body["environment"] = runtime
        payloads, measurements, runtime = self._draw(request, bodies, font)
        result = {
            "schema_version": 4, "geometry": "vector", "kind": "page-output",
            "renderer_id": VECTOR_RENDERER_ID, "renderer_version": VECTOR_VERSION,
            "renderer_code_digest": page_renderer_digest("vector"),
            "request_ref": frozen.ref(),
            "panel_evidence": [
                {**p, "feature_count": sum(item["portrayal"]["counts"]["feature_count"]
                                           for item in layers[p["view_id"]]),
                 "drawn_count": sum(item["portrayal"]["counts"]["visible_count"]
                                    for item in layers[p["view_id"]])}
                for p in request["panels"]
            ],
            "font_snapshot": font, "font_family": family, "font_embedding_flags": flags,
            "environment": runtime,
            "outputs": {kind: self.preparation.store_asset(data, "page-" + kind, "." + kind)
                       for kind, data in payloads.items()},
            "measurements": measurements,
            "checks": {key: "passed" for key in ("frame-binding", "glyph-coverage", "font-embedding", "content-fit", "png-dimensions")},
            "capability_boundary": "internal-page-output-not-formal-render-receipt",
        }
        return self.preparation.save("page-output", result)

    def load_verified(self, reference: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        g = self._geometry or "raster"
        if g == "vector":
            output = self.preparation.document(reference, "page-output")
            page = self.preparation.document(output["request_ref"], "page-request")
            for kind, asset in output["outputs"].items():
                self.preparation.snapshot_bytes(asset, "page-" + kind, "." + kind)
            if self.render(page, context).digest != reference["digest"]:
                raise ProtocolError("VECTOR_PAGE_CHANGED", "Page evidence does not match deterministic frozen inputs")
            return output
        output = self.preparation.document(reference, "page-output")
        request = self.preparation.document(output["request_ref"], "page-request")
        self.validate_request(request, context)
        for kind, asset in output["outputs"].items():
            self.preparation.snapshot_bytes(asset, f"page-{kind}", f".{kind}")
        current = self.render(request, context)
        if current.digest != reference["digest"]:
            raise ProtocolError("RASTER_PAGE_CHANGED", "Page provenance differs from its frozen result")
        return output

    # -- drawing ----------------------------------------------------------

    def _draw_map_bodies(self, fig: Any, bodies: dict[str, Any], width: float, height: float, dpi: float) -> None:
        g = self._geometry or "raster"
        if g == "vector":
            self._draw_vector_map_bodies(fig, bodies, width, height, dpi)
        else:
            self._draw_raster_map_bodies(fig, bodies, width, height, dpi)

    def _draw_raster_map_bodies(self, fig: Any, bodies: dict[str, Any], width: float, height: float, dpi: float) -> None:
        from .raster_renderer import _dependencies

        np, _, _, _, _, _, Image = _dependencies()
        for body in bodies.values():
            pixels = self.preparation.snapshot_bytes(body["image"], "map-body", ".png")
            with Image.open(io.BytesIO(pixels)) as image:
                rgba = np.array(image.convert("RGBA"))
            x, y, w, h = body["image_rect"]
            axis = fig.add_axes([x / width, 1 - (y + h) / height, w / width, h / height])
            axis.imshow(rgba, origin="upper", interpolation="none", resample=False, aspect="auto")
            axis.set_axis_off()

    def _draw_vector_map_bodies(self, fig: Any, bodies: dict[str, Any], width: float, height: float, dpi: float) -> None:
        from matplotlib.path import Path as MplPath
        from matplotlib.patches import PathPatch, Ellipse

        for body in bodies.values():
            x, y, fw, fh = body["frame"]["bounds_px"]
            left, bottom, right, top = body["panel"]["extent"]
            flat_styles = [s for item in body["stack"] for s in item["portrayal"]["feature_styles"] if s["style"]]
            max_radius = max((s["style"]["symbol"]["radius_mm"] for s in flat_styles), default=0)
            max_stroke = max((s["style"]["symbol"]["stroke_width_pt"] for s in flat_styles), default=0)
            padding = (max_radius * dpi / 25.4 if any(item["report"]["geometry"] == "point" for item in body["stack"]) else 0) + max_stroke * dpi / 144 + 1
            if fw <= 2 * padding or fh <= 2 * padding:
                raise ProtocolError("VECTOR_MARK_OVERFLOW", "Map frame cannot contain the declared symbol size")
            scale = min((fw - 2 * padding) / (right - left), (fh - 2 * padding) / (top - bottom))
            ox = x + (fw - scale * (right - left)) / 2
            oy = y + (fh - scale * (top - bottom)) / 2

            def position(point):
                return ((ox + (point[0] - left) * scale) / width,
                        1 - (oy + (top - point[1]) * scale) / height)

            basemap = body.get("basemap")
            if basemap:
                self._draw_basemap(fig, basemap, x, y, fw, fh, left, top, scale, ox, oy, width, height)
            # Paint each stacked layer in declared order; later layers cover earlier ones.
            for item in body["stack"]:
                self._draw_stacked_layer(fig, item, position, width, height, dpi, body)

    def _draw_stacked_layer(self, fig: Any, item: dict[str, Any], position: Any,
                            width: float, height: float, dpi: float, body: dict[str, Any]) -> None:
        from matplotlib.path import Path as MplPath
        from matplotlib.patches import PathPatch, Ellipse
        styles = {s["feature_id"]: s["style"] for s in item["portrayal"]["feature_styles"]}
        for feature in item["report"]["features"]:
                style = styles[feature["id"]]
                if style is None:
                    continue
                symbol = style["symbol"]
                geometry = feature["geometry"]
                kwargs = {"facecolor": symbol["color"], "edgecolor": symbol["stroke"],
                          "linewidth": symbol["stroke_width_pt"], "transform": fig.transFigure, "clip_on": False}
                if geometry["type"] == "Point":
                    radius = symbol["radius_mm"] * dpi / 25.4
                    artist = Ellipse(position(geometry["coordinates"]), 2 * radius / width, 2 * radius / height, **kwargs)
                    fig.add_artist(artist)
                elif geometry["type"] in ("LineString", "MultiLineString"):
                    # W3: draw lines using the symbol color as the line color and
                    # stroke_width_pt as the line width; radius_mm is unused for lines.
                    from matplotlib.lines import Line2D
                    lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
                    for coordinates in lines:
                        points = [position(pt) for pt in coordinates]
                        if len(points) >= 2:
                            xs = [pt[0] * width for pt in points]
                            ys = [pt[1] * height for pt in points]
                            artist = Line2D(xs, ys, color=symbol["color"],
                                            linewidth=symbol["stroke_width_pt"],
                                            transform=fig.transFigure, clip_on=False)
                            fig.add_artist(artist)
                else:
                    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
                    for polygon in polygons:
                        vertices, codes = [], []
                        for ring in polygon:
                            vertices.extend(position(point) for point in ring)
                            codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 2) + [MplPath.CLOSEPOLY])
                        fig.add_artist(PathPatch(MplPath(vertices, codes), **kwargs))
        self._draw_feature_labels(fig, {"portrayal": item["portrayal"], "frame": body["frame"]},
                                  position, width, height, dpi)

    def _draw_basemap(self, fig: Any, basemap: dict[str, Any], x: float, y: float, fw: float, fh: float,
                      left: float, top: float, scale: float, ox: float, oy: float,
                      width: float, height: float) -> None:
        # Ground layer: the basemap image is georeferenced by its declared extent
        # and painted through the SAME affine transform as the thematic features
        # (no separate placement decision). Figure-ground is enforced via the
        # frozen style constraints (desaturate/lighten), applied deterministically.
        import io as _io
        from pathlib import Path as _Path
        import numpy as _np
        from PIL import Image as _Image
        image = basemap["image"]
        data = _Path(image["path"]).read_bytes()
        if self.preparation.digest_bytes(data) != image["digest"]:
            raise ProtocolError("BASEMAP_DRIFT", "Basemap image differs from its frozen digest")
        with _Image.open(_io.BytesIO(data)) as opened:
            rgba = _np.array(opened.convert("RGBA"))
        style = basemap.get("style") or {}
        desaturate = float(style.get("desaturate", 0.0))
        lighten = float(style.get("lighten", 0.0))
        if desaturate or lighten:
            rgb = rgba[..., :3].astype(float) / 255.0
            if desaturate:
                luminance = rgb @ _np.array([0.2126, 0.7152, 0.0722])
                rgb = rgb * (1.0 - desaturate) + luminance[..., None] * desaturate
            if lighten:
                rgb = _np.clip(rgb + lighten * (1.0 - rgb) if lighten > 0 else rgb * (1.0 + lighten), 0.0, 1.0)
            rgba = _np.dstack([(rgb * 255.0).round().astype("uint8"), rgba[..., 3]])
        # The axes occupies the frame; the data window mirrors position()'s affine.
        axis = fig.add_axes([x / width, 1 - (y + fh) / height, fw / width, fh / height])
        axis.set_axis_off()
        bx0, by0, bx1, by1 = basemap["extent"]
        axis.imshow(rgba, extent=(bx0, bx1, by0, by1), origin="upper",
                    interpolation="none", resample=False, aspect="auto", zorder=-5)
        axis.set_xlim(left + (x - ox) / scale, left + (x + fw - ox) / scale)
        axis.set_ylim(top - (y + fh - oy) / scale, top - (y - oy) / scale)

    def _draw_feature_labels(self, fig: Any, body: dict[str, Any], position: Any,
                             width: float, height: float, dpi: float) -> None:
        # W2: draw frozen feature labels with a halo, then greedily drop any label
        # that overlaps an earlier one (collision_policy=avoid) or leaves the map
        # frame. The program never moves or rewrites labels.
        from matplotlib.patheffects import withStroke
        from matplotlib.font_manager import FontProperties
        labels = (body.get("portrayal") or {}).get("labels") or []
        if not labels:
            return
        annotation = getattr(self, "_annotation", None) or {}
        labeling = annotation.get("labeling") or {}
        halo = labeling.get("halo") or {"color": "#FFFFFF", "width_mm": 0.5}
        stroke = max(halo["width_mm"] * dpi / 25.4 * 2, 0.5)
        size = annotation.get("typography", {}).get("body_pt", 9)
        font_path = getattr(self, "_font_path", None)
        props = FontProperties(fname=font_path, size=size) if font_path else FontProperties(size=size)
        effects = [withStroke(linewidth=stroke, foreground=halo["color"])]
        frame = body["frame"]["bounds_px"]
        renderer = fig.canvas.get_renderer()
        placed: list[Any] = []
        for label in labels:
            anchor = position(label["anchor"])
            artist = fig.text(anchor[0], 1 - anchor[1], label["text"],
                              fontproperties=props, ha="center", va="center",
                              color="#17212B", path_effects=effects,
                              transform=fig.transFigure, parse_math=False, usetex=False)
            box = artist.get_window_extent(renderer)
            overlap = any(box.overlaps(other) for other in placed)
            outside = (box.x0 < frame[0] or box.y0 < frame[1]
                       or box.x1 > frame[0] + frame[2] or box.y1 > frame[1] + frame[3])
            if overlap or outside:
                artist.remove()
            else:
                placed.append(box)

    @staticmethod
    def _legend_swatch_mm(legend: dict[str, Any]) -> float:
        if not legend.get("items"):
            return 3
        first = legend["items"][0]
        if "symbol" in first and first.get("shape") == "circle":
            return max(3, max(2 * row["symbol"]["radius_mm"] if row["shape"] == "circle" else 3 for row in legend["items"]))
        return 3

    @staticmethod
    def _draw_legend_symbol(fig: Any, artists: list, row: dict[str, Any], element: str,
                            content: str, x: float, y: float, swatch: float,
                            width: float, height: float, dpi: float) -> None:
        from matplotlib.patches import Ellipse, Rectangle

        if "symbol" in row:
            symbol = row["symbol"]
            radius = symbol["radius_mm"] * dpi / 25.4
            artist = Ellipse(((x + swatch / 2) / width, 1 - (y + swatch / 2) / height),
                             2 * radius / width, 2 * radius / height,
                             facecolor=symbol["color"], edgecolor=symbol["stroke"],
                             linewidth=symbol["stroke_width_pt"], transform=fig.transFigure)
            if row["shape"] == "square":
                size = 3 * dpi / 25.4
                artist = Rectangle(((x + (swatch - size) / 2) / width, 1 - (y + (swatch + size) / 2) / height),
                                 size / width, size / height,
                                 facecolor=symbol["color"], edgecolor=symbol["stroke"],
                                 linewidth=symbol["stroke_width_pt"], transform=fig.transFigure)
            fig.add_artist(artist)
            artists.append((element, content, artist, symbol["stroke_width_pt"] * dpi / 144))
        else:
            # fallback to raster-style rectangle swatch
            artist = Rectangle((x / width, 1 - (y + swatch) / height), swatch / width, swatch / height,
                             facecolor=row["color"], edgecolor="#444444", linewidth=0.4, transform=fig.transFigure)
            fig.add_artist(artist)
            artists.append((element, content, artist, 0.2 * dpi / 72))