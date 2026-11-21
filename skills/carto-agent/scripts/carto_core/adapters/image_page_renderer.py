"""Matplotlib + PIL image-basemap page renderer (image-itinerary-page).

A fully independent renderer class dispatched via ``IMPL_IMAGE_ITINERARY`` —
it never enters ``FormalRenderer``'s raster/vector duality. It consumes the
frozen RenderScene's ``image_graphics`` plus the referenced image page-request
(basemap placement, texts, legends, font) and exports PDF + PNG with an
HMAC-signed RenderReceipt. The same graphics list feeds
``scenarios.leadership_visit.frontend_document.FrontendDocumentBuilder`` so
the PDF/PNG and the frontend map_json stay pixel-consistent (same placement
transform, same style lengths).

Layering: a render backend is governed by the RenderReceipt (HMAC, code/dep
fingerprint, resource evidence) — deliberately NOT a ToolGateway capability;
tool capabilities with authorization/evidence semantics are bound separately
in adapters/image_tools.py.
"""
from __future__ import annotations

import hashlib
import hmac
import platform
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from ..artifacts import publish_bytes, utc_now
from ..backend_registry import IMAGE_ITINERARY_PAGE
from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from .image_layout import contain_layout
from .route_display import direction_arrows, display_points

RENDERER_VERSION = "1.0.0"
MAX_PAGE_PIXELS = 20000000
MAX_SOURCE_PIXELS = 16000000
MAX_BASEMAP_BYTES = 67108864


def _image_renderer_digest() -> str:
    root = Path(__file__).resolve().parents[3]
    paths = [
        Path(__file__),
        root / "scripts/carto_core/adapters/image_layout.py",
        root / "scripts/carto_core/adapters/image_display.py",
        root / "scripts/carto_core/adapters/geo_to_image_pixels.py",
        root / "scripts/carto_core/adapters/route_display.py",
        root / "scripts/carto_core/adapters/render_backend.py",
    ]
    paths += [root / "schemas" / (name + ".schema.json") for name in
              ("render-scene", "render-receipt", "page-request", "common")]
    return sha256_digest({"files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


def _runtime_versions() -> dict[str, str]:
    import numpy
    import matplotlib
    import PIL
    import pyproj
    from matplotlib import ft2font
    try:
        import fontTools
        fonttools_version = fontTools.__version__
    except ImportError:  # pragma: no cover - matplotlib normally ships fonttools
        fonttools_version = "unknown"
    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "matplotlib": matplotlib.__version__,
        "pillow": PIL.__version__,
        "pyproj": pyproj.__version__,
        "freetype": ft2font.__freetype_version__,
        "fonttools": fonttools_version,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
    }


@dataclass(frozen=True, slots=True)
class ImageRendererProfile:
    renderer_id: str
    renderer_version: str
    renderer_code_digest: str
    runtime: dict[str, str]
    platform: str
    machine: str
    supported_export_formats: tuple[str, ...] = ("pdf", "png")
    max_canvas_width: int = 16384
    max_canvas_height: int = 16384
    max_page_pixels: int = MAX_PAGE_PIXELS

    @classmethod
    def current(cls) -> "ImageRendererProfile":
        return cls(IMAGE_ITINERARY_PAGE.renderer_id, RENDERER_VERSION, _image_renderer_digest(),
                   _runtime_versions(), platform.platform(), platform.machine())

    def profile_digest(self) -> str:
        return sha256_digest(asdict(self))

    @property
    def environment_fingerprint(self) -> str:
        return sha256_digest({"backend_profile": asdict(self)})

    def environment_snapshot(self) -> dict[str, Any]:
        return {"renderer_id": self.renderer_id, "renderer_version": self.renderer_version,
                "renderer_code_digest": self.renderer_code_digest, "runtime": dict(self.runtime),
                "fingerprint": self.environment_fingerprint}


def environment_snapshot(renderer_id: str | None = None) -> dict[str, Any]:
    """Composition-root entry for the image itinerary renderer environment."""
    return ImageRendererProfile.current().environment_snapshot()


def _font_family(path: Path) -> str:
    try:
        from fontTools.ttLib import TTFont
        with TTFont(str(path), lazy=True) as font:
            family = font["name"].getDebugName(1)
        if family:
            return family
    except Exception:
        pass
    return "sans-serif"


class ImagePageRenderer:
    """Registered-basemap itinerary page renderer; PDF+PNG from frozen graphics."""

    def __init__(self, renderer_id: str = IMAGE_ITINERARY_PAGE.renderer_id, *,
                 path_guard, output_root, attestation_key, registry: SchemaRegistry | None = None,
                 project_root: Path | None = None, context=None) -> None:
        from ..security.paths import PathGuard  # noqa: F401 — type documentation only
        if renderer_id != IMAGE_ITINERARY_PAGE.renderer_id:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", renderer_id)
        if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
            raise SecurityError("RENDER_ATTESTATION_KEY_INVALID", "Attestation requires at least 32 bytes")
        self.renderer_id = renderer_id
        self.path_guard = path_guard
        self.output_root = path_guard.resolve(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.registry = registry or SchemaRegistry()
        self.key = attestation_key
        self.profile = ImageRendererProfile.current()
        self.environment_fingerprint = self.profile.environment_fingerprint

    @property
    def renderer_version(self) -> str:
        return self.profile.renderer_version

    def environment_snapshot(self) -> dict[str, Any]:
        return self.profile.environment_snapshot()

    # ------------------------------------------------------------------
    # Scene / page validation
    # ------------------------------------------------------------------

    def _page(self, scene: dict[str, Any]) -> dict[str, Any]:
        ref = scene["page_request_ref"]
        page_path = self.path_guard.resolve(ref["uri"], must_exist=True)
        if page_path.stat().st_size > 5 * 1024 * 1024:
            raise ProtocolError("PAGE_REQUEST_SIZE_LIMIT", str(page_path))
        page = load_document(page_path)
        self.registry.validate("page-request", page)
        if page.get("geometry") != "image":
            raise ProtocolError("PAGE_REQUEST_GEOMETRY_MISMATCH", "image page request required")
        if sha256_digest(page) != ref.get("digest"):
            raise ProtocolError("PAGE_REQUEST_DRIFT", "page request differs from the frozen reference")
        if page["resolved_layout"] != scene["resolved_layout"]:
            raise ProtocolError("PAGE_REQUEST_LAYOUT_MISMATCH", "page layout differs from the scene")
        return page

    def validate_scene(self, scene: dict[str, Any], execution: dict[str, Any] | None = None) -> dict[str, Any]:
        self.registry.validate("render-scene", scene)
        if scene["renderer_id"] != self.renderer_id:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", scene["renderer_id"])
        LayoutResolver(self.registry).validate_scene(scene)
        viewport = scene["viewport"]
        if viewport["width_px"] * viewport["height_px"] > MAX_PAGE_PIXELS:
            raise ProtocolError("RENDER_PAGE_LIMIT", "page pixel budget exceeded")
        page = self._page(scene)
        basemap = page["basemap"]
        image_path = self.path_guard.resolve(basemap["image"]["path"], must_exist=True)
        if image_path.stat().st_size > MAX_BASEMAP_BYTES:
            raise ProtocolError("IMAGE_SIZE_LIMIT", "basemap exceeds the renderer resource limit")
        image_bytes = image_path.read_bytes()
        if "sha256:" + hashlib.sha256(image_bytes).hexdigest() != basemap["image"]["digest"]:
            raise ProtocolError("IMAGE_INPUT_DRIFT", "basemap image differs from the frozen page")
        from .image_layout import inspect_png
        if inspect_png(image_bytes) != basemap["source_size"]:
            raise ProtocolError("IMAGE_SOURCE_SIZE_MISMATCH", "basemap dimensions differ from the page request")
        frame = LayoutResolver.map_frame(scene["resolved_layout"])
        frame_box = {key: value for key, value in zip(("x", "y", "width", "height"), frame["bounds_px"])}
        placement = contain_layout({"width_px": basemap["display_window"]["width"],
                                    "height_px": basemap["display_window"]["height"]}, frame_box)
        if execution is not None:
            if execution.get("environment") != self.environment_snapshot():
                raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Code/runtime differs from the frozen execution")
            if (execution.get("page_inputs") != {k: scene[k] for k in ("prepared_bundle_ref", "page_request_ref")}):
                raise ProtocolError("RENDER_PAGE_INPUT_DRIFT", "Execution page inputs differ from the scene")
        from .image_layout import validate_image_geometry
        frame_context = {**basemap, "frame": frame_box, "id": frame["id"]}
        graphics = scene.get("image_graphics", [])
        try:
            validate_image_geometry(frame_context, graphics, viewport)
        except ProtocolError as exc:
            raise ProtocolError("IMAGE_GRAPHIC_INVALID", exc.message) from exc
        return {"page": page, "placement": placement, "frame": frame, "image_path": image_path}

    def scene_texts(self, scene: dict[str, Any]) -> list[str]:
        return [item["text"] for item in self.validate_scene(scene)["page"]["texts"]]

    # ------------------------------------------------------------------
    # Session directory
    # ------------------------------------------------------------------

    def _directory(self, session_id: str) -> Path:
        identifier = self.registry.schemas["common"]["$defs"]["identifier"]
        if not isinstance(session_id, str) or any(
                len(value) > identifier["maxLength"] or re.fullmatch(identifier["pattern"], value) is None
                for value in (session_id, "receipt-" + session_id)):
            raise SecurityError("RENDER_SESSION_ID_INVALID", "Expected a bounded local session/receipt identifier")
        return self.path_guard.resolve(self.output_root / session_id)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, session_id: str, scene: dict[str, Any]) -> dict[str, Any]:
        directory = self._directory(session_id)
        inputs = self.validate_scene(scene)
        started = utc_now()
        outputs = self._paint(scene, inputs, directory)
        self._write_frontend_document(scene, inputs["page"], directory)
        return self._receipt(session_id, scene, outputs, started, utc_now())

    def _write_frontend_document(self, scene: dict[str, Any], page: dict[str, Any],
                                 directory: Path) -> None:
        """Write the frontend map document next to the rendered outputs.

        Only when the frozen page contract declares one (``page.document``);
        the same neutral builder and the same frozen inputs the scenario
        compiler used, so this copy is byte-identical to the compile-time
        original in the project's immutable store.
        """
        meta = page.get("document")
        if not meta:
            return
        from .frontend_canvas import build_canvas_document
        from ..artifacts import atomic_json
        document = build_canvas_document(
            self.registry, scene, page,
            identifier=f"map-{scene['context']['run_id']}",
            name=meta.get("name", "map"), category=meta["category"])
        atomic_json(self.path_guard.resolve(directory / "map-document.json"), document)

    def _paint(self, scene: dict[str, Any], inputs: dict[str, Any], directory: Path) -> dict[str, dict]:
        import io as _io

        import matplotlib
        matplotlib.use("Agg", force=True)
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure
        from matplotlib.patches import Circle, Rectangle
        from PIL import Image

        page = inputs["page"]
        placement, frame = inputs["placement"], inputs["frame"]
        basemap = page["basemap"]
        window = basemap["display_window"]
        viewport = scene["viewport"]
        dpi = scene["export"]["dpi"]
        scale = placement["scale"]
        offset_x, offset_y = window["x"] * scale, window["y"] * scale

        with Image.open(inputs["image_path"]) as image:
            cropped = image.convert("RGB").crop(
                (window["x"], window["y"], window["x"] + window["width"], window["y"] + window["height"]))
            buffer = _io.BytesIO()
            cropped.save(buffer, format="PNG")

        family = _font_family(self.path_guard.resolve(page["font"]["path"], must_exist=True))
        figure = Figure(figsize=(viewport["width_px"] / dpi, viewport["height_px"] / dpi), dpi=dpi)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(figure)
        axes = figure.add_axes((0, 0, 1, 1))
        axes.set_xlim(0, viewport["width_px"])
        axes.set_ylim(viewport["height_px"], 0)
        axes.axis("off")
        axes.imshow(cropped, extent=(placement["x"], placement["x"] + placement["width"],
                                     placement["y"] + placement["height"], placement["y"]),
                    interpolation="none", zorder=0)

        def px(x: float, y: float) -> tuple[float, float]:
            return x * scale - offset_x + placement["x"], y * scale - offset_y + placement["y"]

        for graphic in scene.get("image_graphics", []):
            gid = graphic["id"]
            color = graphic.get("color", "#1A3A5C")
            if graphic["type"] == "line":
                # display_points subtracts the window origin (already scaled); adding
                # the frame placement once then lands lines on the same px() transform
                # the pins use. Never pass a placement-adjusted origin here — the
                # follow-up + placement would double it and detach routes from stops.
                displayed = display_points(graphic, scale, (offset_x, offset_y))
                points = [(x + placement["x"], y + placement["y"]) for x, y in displayed]
                width = graphic.get("width_px", 4) * scale
                halo = graphic.get("halo_width_px", 2) * scale
                xs, ys = zip(*points)
                axes.plot(xs, ys, color="#FFFFFF", linewidth=width + 2 * halo,
                          solid_capstyle="round", solid_joinstyle="round", zorder=2)
                axes.plot(xs, ys, color=color, linewidth=width,
                          solid_capstyle="round", solid_joinstyle="round", zorder=3)
                if "arrows" in graphic:
                    for arrow in direction_arrows(points, {k: v * scale for k, v in graphic["arrows"].items()}):
                        ax, ay = zip(*arrow)
                        axes.plot(ax, ay, color="#FFFFFF", linewidth=max(1.0, width / 3),
                                  solid_capstyle="round", zorder=3)
                continue
            x, y = px(graphic["position"]["x"], graphic["position"]["y"])
            if graphic["type"] == "callout":
                left = x + graphic["offset_x_px"]
                top = y + graphic["offset_y_px"]
                width, height = graphic["width_px"], graphic["height_px"]
                cx = min(max(x, left), left + width)
                cy = min(max(y, top), top + height)
                axes.plot([x, cx], [y, cy], color=color, linewidth=graphic["leader_width_px"], zorder=4)
                axes.add_patch(Rectangle((left, top), width, height, facecolor=color,
                                         edgecolor="none", alpha=graphic["opacity"], zorder=5))
                cursor = top + graphic["padding_px"]
                for line in graphic["lines"]:
                    row = graphic["body_font_px"] * 1.3
                    axes.text(left + graphic["padding_px"], cursor + row / 2, line,
                              color=graphic.get("body_color", "#FFFFFF"),
                              fontsize=graphic["body_font_px"] * 72 / dpi,
                              family=family, va="center", ha="left", zorder=6)
                    cursor += row
                if graphic["lines"]:
                    axes.plot([left + graphic["padding_px"], left + width - graphic["padding_px"]],
                              [cursor + graphic["line_gap_px"]] * 2, color="#FFFFFF", linewidth=1, zorder=6)
                    cursor += 2 * graphic["line_gap_px"]
                from .image_layout import callout_text
                title_lines, _ = callout_text(graphic)
                if not graphic["lines"] and len(title_lines) == 1:
                    axes.text(left + graphic["padding_px"], top + height / 2, title_lines[0],
                              color=graphic.get("title_color", "#FFFFFF"), fontsize=graphic["title_font_px"] * 72 / dpi,
                              family=family, fontweight=graphic.get("font_weight", 400),
                              va="center", ha="left", zorder=6)
                else:
                    for line in title_lines:
                        row = graphic["title_font_px"] * 1.25
                        axes.text(left + graphic["padding_px"], cursor + row / 2, line,
                                  color=graphic.get("title_color", "#FFFFFF"), fontsize=graphic["title_font_px"] * 72 / dpi,
                                  family=family, fontweight=graphic.get("font_weight", 400),
                                  va="center", ha="left", zorder=6)
                        cursor += row
                continue
            if graphic["type"] == "point":
                radius = graphic.get("radius_px", 12) * scale
                if graphic.get("shape", "pin") == "pin":
                    self._pin(axes, x, y, radius, color)
                else:
                    axes.add_patch(Circle((x, y), radius, facecolor=color, edgecolor="#FFFFFF",
                                          linewidth=2 * scale, zorder=7))
                if graphic.get("show_number", True):
                    axes.text(x, y - 2 * radius, str(graphic["visit_order"]), color="#FFFFFF",
                              fontsize=graphic.get("font_size_px", 12) * scale * 72 / dpi,
                              family=family, ha="center", va="center", zorder=8)
                continue
            if graphic["type"] == "label":
                lx = x + graphic.get("offset_x_px", 16) * scale
                ly = y + graphic.get("offset_y_px", -16) * scale
                axes.text(lx, ly, graphic["content"], color=color,
                          fontsize=graphic.get("font_size_px", 16) * scale * 72 / dpi, family=family,
                          zorder=8)
        # Page furniture: texts and legends in their layout frames. Nominal font
        # sizes come from the frozen page contract (style page_furniture) with the
        # historical 18pt/9pt fallback, capped so text always fits its frame —
        # never the oversized-pixels-as-points regression. The derivation is the
        # SHARED image_layout.furniture_font_pt the frontend document builder
        # consumes, keeping the PDF and map_json pixel-consistent.
        from .image_layout import callout_text, frame_border_rects, furniture_font_pt, legend_font_pt
        pt_per_px = 72 / dpi
        frames = {f["content_id"]: f for f in scene["resolved_layout"]["frames"] if f["type"] != "map"}
        for item in page["texts"]:
            bounds = frames.get(item["content_id"])
            if bounds is None:
                continue
            x, y, w, h = bounds["bounds_px"]
            fontsize = furniture_font_pt(item, (x, y, w, h), pt_per_px)
            axes.text(x + w / 2, y + h / 2, item["text"], color="#1A3A5C",
                      fontsize=fontsize, family=family,
                      ha="center", va="center",
                      fontweight=700 if item["content_id"] == "title" else 400, zorder=9)
        # Map frame border (frozen furniture): double stroke around the placed map
        # window — inner line on the frame path, outer line gap-mm out. Same shared
        # geometry (image_layout.frame_border_rects) the frontend draws.
        border = (page.get("furniture") or {}).get("frame_border")
        if border:
            px_per_mm = dpi / 25.4
            inner, outer = frame_border_rects(placement, border, px_per_mm)
            for rect, width_mm in ((inner, border["inner_width_mm"]),
                                   (outer, border["outer_width_mm"])):
                path = [(rect["x"], rect["y"]),
                        (rect["x"] + rect["width"], rect["y"]),
                        (rect["x"] + rect["width"], rect["y"] + rect["height"]),
                        (rect["x"], rect["y"] + rect["height"]),
                        (rect["x"], rect["y"])]
                axes.plot(*zip(*path), color=border["color"],
                          linewidth=width_mm * 72 / 25.4,
                          solid_capstyle="butt", solid_joinstyle="miter", zorder=9)
        for legend in page.get("legends", []):
            bounds = frames.get(legend["content_id"])
            if bounds is None:
                continue
            x, y, w, h = bounds["bounds_px"]
            # Shared derivation (image_layout.legend_font_pt) — the frontend
            # document builder consumes the same function, keeping the legend
            # pixel-consistent between the PDF and map_json.
            font = legend_font_pt(legend, (x, y, w, h), pt_per_px)
            font_px = font / pt_per_px
            axes.text(x + 4, y + font_px * 1.5, legend["title"], color="#1A3A5C",
                      fontsize=font, family=family, ha="left", va="center", fontweight=700, zorder=9)
            for index, entry in enumerate(legend["items"]):
                cy = y + (index + 2.2) * font_px * 1.5
                axes.add_patch(Rectangle((x + 4, cy - font_px * .35), font_px * 2, font_px * .7,
                                         facecolor=entry["color"], edgecolor="none", zorder=9))
                axes.text(x + 4 + font_px * 2.6, cy, entry["label"], color="#333333",
                          fontsize=font, family=family, ha="left", va="center", zorder=9)
        outputs: dict[str, dict] = {}
        png_buffer = _io.BytesIO()
        figure.savefig(png_buffer, format="png", dpi=dpi, metadata={"Software": "carto image-itinerary-page"})
        png_bytes = png_buffer.getvalue()
        publish_bytes(self.path_guard, directory / "map.png", png_bytes)
        outputs["png"] = {"size_bytes": len(png_bytes), "digest": "sha256:" + hashlib.sha256(png_bytes).hexdigest()}
        pdf_buffer = _io.BytesIO()
        with PdfPages(pdf_buffer, metadata={"Title": "", "Author": "", "Creator": "carto image-itinerary-page",
                                            "CreationDate": None, "ModDate": None}) as pdf:
            pdf.savefig(figure, dpi=dpi)
        pdf_bytes = pdf_buffer.getvalue()
        publish_bytes(self.path_guard, directory / "map.pdf", pdf_bytes)
        outputs["pdf"] = {"size_bytes": len(pdf_bytes), "digest": "sha256:" + hashlib.sha256(pdf_bytes).hexdigest()}
        return outputs

    @staticmethod
    def _pin(axes, x: float, y: float, radius: float, color: str) -> None:
        """Teardrop pin: circular head, tapered tail, contrasting inner dot."""
        from matplotlib.patches import Circle, Polygon
        head = Circle((x, y - 2 * radius), radius, facecolor=color, edgecolor="#FFFFFF",
                      linewidth=1, zorder=7)
        tail = Polygon([[x - radius * .35, y - radius * 1.1], [x + radius * .35, y - radius * 1.1], [x, y]],
                       closed=True, facecolor=color, edgecolor="none", zorder=7)
        dot = Circle((x, y - 2 * radius), radius * .55, facecolor="#FFFFFF", edgecolor="none", zorder=8)
        axes.add_patch(head)
        axes.add_patch(tail)
        axes.add_patch(dot)

    # ------------------------------------------------------------------
    # Receipt
    # ------------------------------------------------------------------

    def _receipt(self, session_id: str, scene: dict[str, Any], outputs: dict[str, dict],
                 started: str, completed: str) -> dict[str, Any]:
        resources = [{"resource_id": item["id"], "digest": item["ref"]["digest"], "status": "loaded"}
                     for item in scene["resources"]]
        resource_digest = sha256_digest(resources)
        execution_digest = sha256_digest({"scene_digest": sha256_digest(scene), "resource_set_digest": resource_digest,
                                          "renderer_profile_digest": self.profile.profile_digest(),
                                          "environment_fingerprint": self.environment_fingerprint,
                                          "random_seed": scene["random_seed"]})
        media = {"pdf": "application/pdf", "png": "image/png"}
        artifacts = []
        for kind in scene["export"]["targets"]:
            if kind not in outputs:
                raise ProtocolError("RENDER_OUTPUT_MISSING", kind)
            artifacts.append({"target": kind, "media_type": media[kind], "size_bytes": outputs[kind]["size_bytes"],
                              "composition": "raster" if kind == "png" else "mixed",
                              "artifact_ref": {"id": "map-" + kind, "version": "1.0.0",
                                               "digest": outputs[kind]["digest"],
                                               "uri": str(self._directory(session_id) / ("map." + kind))}})
        receipt = {"schema_version": 1, "receipt_id": "receipt-" + session_id, "session_id": session_id,
                   "scene_id": scene["scene_id"], "scene_revision": scene["revision"],
                   "scene_digest": sha256_digest(scene), "random_seed": scene["random_seed"],
                   "environment_fingerprint": self.environment_fingerprint,
                   "resource_set_digest": resource_digest, "execution_digest": execution_digest,
                   "renderer_id": self.renderer_id, "renderer_profile_digest": self.profile.profile_digest(),
                   "renderer_version": self.renderer_version, "renderer_code_digest": self.profile.renderer_code_digest,
                   "runtime": dict(self.profile.runtime), "status": "succeeded",
                   "viewport": dict(scene["viewport"]), "resource_evidence": resources, "output_artifacts": artifacts,
                   "controls": {"input_policy": "frozen-project-local", "network_isolation": "not-provided",
                                "process_isolation": "in-process", "max_source_pixels": MAX_SOURCE_PIXELS,
                                "max_page_pixels": MAX_PAGE_PIXELS, "max_basemap_bytes": MAX_BASEMAP_BYTES},
                   "composition": {"map_body": "pillow-registered-image", "overlays": "matplotlib-vector",
                                   "svg": "not-requested", "png": "rasterized-composite",
                                   "pdf": "raster-map-with-embedded-truetype"},
                   "warnings": [], "render_started_at": started, "render_completed_at": completed,
                   "attestation_algorithm": "hmac-sha256"}
        from .webmap_renderer import compute_renderer_attestation
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, self.key)
        self.registry.validate("render-receipt", receipt)
        return receipt

    def validate_receipt(self, scene: dict[str, Any], receipt: dict[str, Any], *,
                         verify_outputs: bool = True, expected_session_id: str | None = None) -> None:
        from .webmap_renderer import compute_renderer_attestation
        self.registry.validate("render-receipt", receipt)
        if receipt["renderer_id"] != self.renderer_id:
            raise ProtocolError("RENDER_BACKEND_MISMATCH", "Receipt renderer_id does not match this backend")
        if not hmac.compare_digest(receipt["renderer_attestation"], compute_renderer_attestation(receipt, self.key)):
            raise SecurityError("RENDER_ATTESTATION_INVALID", "Renderer attestation does not verify")
        if expected_session_id is not None and receipt["session_id"] != expected_session_id:
            raise ProtocolError("RENDER_RECEIPT_SESSION_MISMATCH", "Receipt belongs to a different attempt")
        self.validate_scene(scene)
        if (receipt["scene_digest"] != sha256_digest(scene)
                or receipt["renderer_profile_digest"] != self.profile.profile_digest()
                or receipt["environment_fingerprint"] != self.environment_fingerprint
                or receipt["renderer_code_digest"] != self.profile.renderer_code_digest
                or receipt["runtime"] != self.profile.runtime):
            raise ProtocolError("RENDER_RECEIPT_BINDING_MISMATCH", "Receipt differs from the frozen scene or runtime")
        started = datetime.fromisoformat(receipt["render_started_at"].replace("Z", "+00:00"))
        completed = datetime.fromisoformat(receipt["render_completed_at"].replace("Z", "+00:00"))
        if completed < started:
            raise ProtocolError("RENDER_RECEIPT_TIME_INVALID", "Completion precedes rendering")
        if verify_outputs:
            for item in receipt["output_artifacts"]:
                path = self.path_guard.resolve(item["artifact_ref"]["uri"], must_exist=True)
                if not path.is_file() or path.stat().st_size != item["size_bytes"]:
                    raise ProtocolError("FORMAL_RENDER_OUTPUT_DRIFT", item["target"])
                if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != item["artifact_ref"]["digest"]:
                    raise ProtocolError("FORMAL_RENDER_OUTPUT_DRIFT", item["target"])
