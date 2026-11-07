"""Internal static categorical map body. Not a formal RenderReceipt or gate bypass.

Rasterio decodes the frozen TIFF; NumPy indexes sparse codes; Matplotlib owns
color normalization/mapping. Pillow resizes category indices with NEAREST only.
The body feeds the existing SVG compositor or the Matplotlib print-page adapter.
No QGIS, browser, MapLibre or pyplot is used.
"""
from __future__ import annotations

import hashlib
import io
import math
import platform
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..compiler.raster_portrayal import RasterPortrayalCompiler, portrayal_compiler_digest
from ..errors import ProtocolError
from ..repository.immutable_store import StoredArtifact
from ..workflow.models import ExecutionContext
from ..workflow.raster_preparation import RasterPreparationService
from .svg_compositor import SvgCompositor

VERSION = "1.0.0"
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 4096


def _dependencies() -> tuple[Any, ...]:
    try:
        import numpy as np
        import rasterio
        import matplotlib
        from matplotlib import colors, image
        import PIL
        from PIL import Image
    except ImportError:
        raise ProtocolError("RASTER_RENDER_DEPENDENCY_MISSING", "Install the explicit raster-rendering extra; no fallback renderer") from None
    return np, rasterio, matplotlib, colors, image, PIL, Image


def renderer_digest() -> str:
    root = Path(__file__).resolve()
    files = [root, root.parents[1] / "compiler/layout.py", root.with_name("svg_compositor.py"),
             root.parents[3] / "schemas/raster-map-body.schema.json"]
    return sha256_digest({"version": VERSION, "portrayal_compiler": portrayal_compiler_digest(), "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})


def fitted_rect(frame: list[float], bounds: list[float]) -> list[float]:
    """Fit projected bounds without stretching; rounding is at most one output pixel."""
    if len(frame) != 4 or len(bounds) != 4 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in frame + bounds):
        raise ProtocolError("RASTER_FRAME_INVALID", "Expected finite frame and geographic bounds")
    x, y, w, h = frame
    left, bottom, right, top = bounds
    if min(w, h, right - left, top - bottom) <= 0 or min(x, y) < 0:
        raise ProtocolError("RASTER_FRAME_INVALID", "Frame and extent must have positive area")
    scale = min(w / (right - left), h / (top - bottom))
    iw, ih = max(1, math.floor((right - left) * scale)), max(1, math.floor((top - bottom) * scale))
    if iw > w or ih > h or max(iw, ih) > MAX_DIMENSION or iw * ih > MAX_PIXELS:
        raise ProtocolError("RASTER_RENDER_SIZE_LIMIT", "Map body exceeds the output pixel profile")
    return [x + (w - iw) / 2, y + (h - ih) / 2, iw, ih]


class RasterMapBodyRenderer:
    def __init__(self, preparation: RasterPreparationService) -> None:
        self.preparation = preparation
        self.layout = LayoutResolver(preparation.registry)
        self.portrayal_compiler = RasterPortrayalCompiler(preparation)

    def render(self, portrayal_ref: dict[str, str], resolved_layout: dict[str, Any],
               context: ExecutionContext) -> StoredArtifact:
        portrayal = self.portrayal_compiler.load_verified(portrayal_ref, context)
        report, evidence = self.preparation.load_verified(portrayal["prepared_ref"])
        self.layout.validate(resolved_layout)
        page = resolved_layout["page"]
        if max(page["width_px"], page["height_px"]) > MAX_DIMENSION or page["width_px"] * page["height_px"] > MAX_PIXELS:
            raise ProtocolError("RASTER_RENDER_SIZE_LIMIT", "Page exceeds the static raster output profile")
        frame = self.layout.map_frame(resolved_layout)["bounds_px"]
        info = evidence["raster_info"]
        rect = fitted_rect(frame, info["bounds"])
        width, height = rect[2:]
        np, rasterio, matplotlib, colors, image, PIL, Image = _dependencies()
        content = self.preparation.snapshot_bytes(report["source_snapshot"], "source", ".tif")
        # In-memory, self-contained GTiff: do not re-open original paths or discover PAM/sidecars.
        # Full-resolution read avoids trusting pre-existing internal overviews for classifications.
        try:
            with rasterio.Env(GDAL_PAM_ENABLED="NO", GDAL_NUM_THREADS="1"):
                with rasterio.io.MemoryFile(content) as memory:
                    with memory.open(driver="GTiff") as source:
                        if (source.driver != "GTiff" or source.count != 1 or source.crs is None
                                or not source.crs.is_projected or source.crs.to_string() != info["crs"]
                                or (source.width, source.height) != (info["width"], info["height"])
                                or source.dtypes[0] != info["bands"][0]["dtype"]
                                or source.nodata != info["bands"][0]["nodata"]
                                or list(source.transform)[:6] != info["transform"]
                                or list(source.bounds) != info["bounds"]):
                            raise ProtocolError("RASTER_DECODE_BINDING_MISMATCH", "Frozen TIFF metadata differs from MCP evidence")
                        data = source.read(1, masked=True)
        except rasterio.errors.RasterioError:
            raise ProtocolError("RASTER_DECODE_FAILED", "Frozen TIFF cannot be decoded under the static profile") from None
        source_mask = np.ma.getmaskarray(data)
        values, counts = np.unique(data.compressed(), return_counts=True)
        actual = [{"value": int(v), "count": int(c)} for v, c in zip(values, counts)]
        if (actual != evidence["statistics"]["classes"] or int(source_mask.sum()) != evidence["statistics"]["masked_pixels"]):
            # Integrity check against previously obtained evidence, NOT a replacement statistics service.
            raise ProtocolError("RASTER_DECODE_BINDING_MISMATCH", "Decoded class domain/mask differs from MCP evidence")
        rows = sorted(portrayal["lookup_table"], key=lambda r: r["value"])
        keys = np.array([row["value"] for row in rows], dtype=np.int64)
        # Indexed conversion is bounded by number of classes, not by the largest category code.
        indices = np.searchsorted(keys, np.where(source_mask, keys[0], data.data)).astype(np.int32)
        if np.any(indices >= len(keys)) or np.any(keys[indices[~source_mask]] != data.data[~source_mask]):
            raise ProtocolError("RASTER_CLASS_COVERAGE_MISMATCH", "Every valid pixel must have an explicit classification")
        hidden = np.array([row["display"] == "hidden" for row in rows])
        indices[source_mask | hidden[indices]] = -1
        if not np.any(indices >= 0):
            raise ProtocolError("RASTER_NO_VISIBLE_CLASSES", "All observed pixels are masked or explicitly hidden")
        # Preserve discrete indices BEFORE colorization. Never bilinear/cubic/continuous normalization.
        resized = Image.fromarray(indices).resize((width, height), resample=Image.Resampling.NEAREST)
        small = np.asarray(resized)
        if not np.any(small >= 0):
            raise ProtocolError("RASTER_NO_VISIBLE_PIXELS_AT_SCALE", "No displayed category survives nearest-neighbor fitting; use a larger map")
        cmap = colors.ListedColormap([row["color"] or "#000000" for row in rows])
        cmap = cmap.with_extremes(bad=(0, 0, 0, 0))
        norm = colors.BoundaryNorm(np.arange(len(rows) + 1) - 0.5, cmap.N)
        rgba = cmap(norm(np.ma.array(small, mask=small < 0)), bytes=True)
        stream = io.BytesIO()
        image.imsave(stream, rgba, format="png", origin="upper", dpi=page["dpi"])
        png = stream.getvalue()
        with Image.open(io.BytesIO(png)) as check:
            if check.size != (width, height) or check.mode != "RGBA":
                raise ProtocolError("RASTER_IMAGE_DIMENSIONS_INVALID", "Encoded image differs from fitted map body")
        left, bottom, right, top = info["bounds"]
        sx, sy = width / (right - left), height / (top - bottom)
        body = {
            "schema_version": 1, "kind": "raster-map-body", "renderer_id": "rasterio-matplotlib",
            "renderer_version": VERSION, "renderer_code_digest": renderer_digest(), "portrayal_ref": portrayal_ref,
            "layout_digest": sha256_digest(resolved_layout), "image": self.preparation._asset(png, "map-body", ".png"),
            "width_px": width, "height_px": height, "dpi": page["dpi"], "frame_rect": frame, "image_rect": rect,
            "bounds": info["bounds"], "crs": info["crs"],
            # Affine maps projected coordinates to PNG-local pixels; add image_rect[:2] for page coordinates.
            "ground_to_image": [sx, 0, -left * sx, 0, -sy, top * sy],
            "legend_items": portrayal["legend_items"],
            "environment": {"python": platform.python_version(), "rasterio": rasterio.__version__,
                            "gdal": rasterio.__gdal_version__, "numpy": np.__version__,
                            "matplotlib": matplotlib.__version__, "pillow": PIL.__version__},
        }
        return self.preparation.save_document(body, "raster-map-body")

    def compose(self, body_ref: dict[str, str], resolved_layout: dict[str, Any], overlays: list[dict[str, Any]],
                output_path: Path, context: ExecutionContext, *, inline_fonts: list[tuple[str, bytes]] | None = None) -> Path:
        """Internal integration hook; re-render to verify body provenance, not a public export command.

        Caller supplies one legend overlay; its items are filled from the SAME frozen
        classification as the map. Remaining overlays (title, source, etc.) use the existing layout.
        """
        body = self.preparation._json_ref(body_ref, "raster-map-body")
        verified = self.render(body["portrayal_ref"], resolved_layout, context)
        if verified.digest != body_ref["digest"]:
            raise ProtocolError("RASTER_MAP_BODY_CHANGED", "Body, layout, renderer or environment differs from frozen output")
        from copy import deepcopy
        overlays = deepcopy(overlays)
        legends = [item for item in overlays if item.get("type") == "legend"]
        if len(legends) != 1:
            raise ProtocolError("RASTER_LEGEND_REQUIRED", "A classified map must bind exactly one legend frame")
        expected = [{"label": item["label"], "color": item["color"], "symbol": "fill"} for item in body["legend_items"]]
        if "legend_items" in legends[0] and legends[0]["legend_items"] != expected:
            raise ProtocolError("RASTER_LEGEND_MISMATCH", "Legend must match the rendered classification exactly")
        legends[0]["legend_items"] = expected
        placed = self.layout.place_overlays(resolved_layout, overlays)
        self.preparation.snapshot_bytes(body["image"], "map-body", ".png")
        page = resolved_layout["page"]
        return SvgCompositor(page["width_px"], page["height_px"], self.preparation.project_guard).compose(
            Path(body["image"]["artifact_ref"]["uri"]), placed, output_path,
            inline_fonts=inline_fonts, resolved_layout=resolved_layout, map_image_rect=body["image_rect"])
