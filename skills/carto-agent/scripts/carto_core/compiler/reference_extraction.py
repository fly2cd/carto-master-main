"""Independent reference-image inverse extraction unit (MCP-ready).

Design goals (user: keep this module independent; it will be wrapped into an MCP tool later):
  * Pure functions only. Dependencies: numpy, Pillow, and the pure math module color_science.
    NO imports of workflow / repository / schema_registry / CLI. Schema validation is injected
    at the boundary by the caller (optional), never performed inside this unit.
  * Inverse-problem boundary is explicit: palette is recoverable; layout geometry and typography
    are recoverable only via pluggable backends (cv2 / OCR). When a backend is absent the field is
    UNRECOVERABLE and MUST be supplied by the user (user_layout / user_typography).
  * Output is a plain proposal dict (template-proposal shape). It is NEVER ingested here.

Public API for MCP wrapping:
    extract_palette(png_bytes, k) -> [hex]
    round_trip_palette(png_bytes, proposed) -> float   (max ΔE2000, lower=better)
    extract_proposal(png_bytes, ...) -> dict           (pure, no validation)
"""
from __future__ import annotations

import hashlib
import io
from typing import Any, Callable, Optional

import numpy as np
from PIL import Image

from .. import color_science

# Fields a rendered image can never determine; the user MUST supply them.
ALWAYS_UNRECOVERABLE = (
    ("data_role_refs", "rendered image carries no data bindings"),
    ("classification_breakpoints", "breakpoints are instance facts, not in the image"),
    ("crs", "projection/CRS is not recoverable from pixels"),
    ("semantic_roles", "business semantics are not visual"),
)
# Fields recoverable only with a pluggable backend; absent backend -> user supplies.
TOOL_GATED = (
    ("layout", "layout.frames.bounds", "frame detection backend (cv2) not provided"),
    ("typography", "typography", "OCR backend not provided"),
)


def _srgb_to_lab_array(rgb: np.ndarray) -> np.ndarray:
    x = rgb.astype(float) / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def _lab_to_hex(lab: np.ndarray) -> str:
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    def finv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    xyz = np.array([finv(fx), finv(fy), finv(fz)]) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    lin = np.clip(xyz @ m.T, 0, 1)
    s = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    r, g, b = (int(round(c * 255)) for c in np.clip(s, 0, 1))
    return f"#{r:02X}{g:02X}{b:02X}"


def extract_palette(png_bytes: bytes, k: int, seed: int = 0, max_pixels: int = 4096) -> list[str]:
    """Deterministic Lab k-means (farthest-point init); returns k uppercase hex centers."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    px = np.asarray(img).reshape(-1, 3)
    if len(px) > max_pixels:
        px = px[np.random.default_rng(seed).choice(len(px), max_pixels, replace=False)]
    lab = _srgb_to_lab_array(px)
    centers = [lab[0]]
    for _ in range(k - 1):
        d = np.min(((lab[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(-1), axis=1)
        centers.append(lab[int(d.argmax())])
    centers = np.array(centers)
    for _ in range(30):
        d = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        assign = d.argmin(1)
        new = np.array([lab[assign == j].mean(0) if (assign == j).any() else centers[j]
                        for j in range(k)])
        if np.allclose(new, centers):
            centers = new
            break
        centers = new
    return sorted(_lab_to_hex(c) for c in centers)


def round_trip_palette(png_bytes: bytes, proposed: list[str], k: int | None = None) -> float:
    ref = extract_palette(png_bytes, k or len(proposed))
    return max(min(color_science.delta_e2000(r, p) for p in proposed) for r in ref)


def extract_proposal(
    png_bytes: bytes, *, proposal_id: str, license: str, k: int,
    selected_segments: list[str],
    user_layout: Optional[dict] = None, user_typography: Optional[dict] = None,
    layout_backend: Optional[Callable[[bytes], dict]] = None,
    ocr_backend: Optional[Callable[[bytes], dict]] = None,
) -> dict[str, Any]:
    """Pure inverse-extraction -> proposal dict. No schema validation, no ingestion.

    layout/typography resolution order: user-supplied > pluggable backend > unrecoverable.
    """
    colors = extract_palette(png_bytes, k)
    rt = round_trip_palette(png_bytes, colors, k)
    recovered: dict[str, Any] = {"ramps": [
        {"ramp_id": "extracted", "colors": colors,
         "provenance": {"source_type": "extracted", "source_ref": "reference.png"}}]}
    confidence = {"palette": 1.0 if rt < 2 else 0.5, "layout": 0.0, "typography": 0.0}
    # P2-2: confidence is MEASUREMENT confidence only. A user-supplied field is a
    # responsibility transfer, not an algorithmic measurement, so it is recorded in
    # field_sources (source=user) and never inflates confidence to 1.0.
    field_sources = {"palette": "extracted", "layout": "absent", "typography": "absent"}
    unrecoverable = [{"field": f, "reason": r, "requires_user": True}
                     for f, r in ALWAYS_UNRECOVERABLE]

    layout = user_layout if user_layout is not None else (
        layout_backend(png_bytes) if layout_backend else None)
    if layout is not None:
        recovered["layout"] = layout
        if user_layout is not None:
            field_sources["layout"] = "user"
        else:
            field_sources["layout"] = "backend"
            confidence["layout"] = 0.6
    else:
        unrecoverable.append({"field": "layout.frames.bounds",
                              "reason": TOOL_GATED[0][2], "requires_user": True})

    typo = user_typography if user_typography is not None else (
        ocr_backend(png_bytes) if ocr_backend else None)
    if typo is not None:
        recovered["typography"] = typo
        if user_typography is not None:
            field_sources["typography"] = "user"
        else:
            field_sources["typography"] = "backend"
            confidence["typography"] = 0.6
    else:
        unrecoverable.append({"field": "typography",
                              "reason": TOOL_GATED[1][2], "requires_user": True})

    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "kind": "extract",
        "source_image": {"id": "reference-image", "version": "1.0.0",
                         "digest": "sha256:" + hashlib.sha256(png_bytes).hexdigest(),
                         "uri": "reference.png"},
        "license": license,
        "recovered": recovered,
        "unrecoverable": unrecoverable,
        "confidence": confidence,
        "field_sources": field_sources,
        "provenance": {"source_type": "extracted", "source_ref": "reference.png",
                       "method": "lab-kmeans+deltaE2000-roundtrip"},
        "selected_segments": selected_segments,
        "round_trip": {"delta_e2000_max": rt},
    }