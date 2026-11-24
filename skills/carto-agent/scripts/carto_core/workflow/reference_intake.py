"""Reference-image intake and proposal->segment-design assembly (plan phase 2).

Two bounded, non-authoritative steps:
  * intake_reference: read an uploaded reference image through PathGuard with byte/pixel/
    format limits and freeze source evidence (digest, dimensions, DPI, color mode, license).
    The original stays in a controlled evidence directory; it is never auto-published.
  * assemble_segment_design: compile a CONFIRMED proposal's recovered fields plus a base
    contract into a complete closed segment design (style/layout) for segment-create-request.
    Incomplete required fields are rejected closed-world (the author never auto-fills).

Neither step ingests into the library or issues approvals; publication still requires
validate + round-trip + human TP.
"""
from __future__ import annotations

import hashlib
import io
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from ..artifacts import protocol_version
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry

MAX_REFERENCE_BYTES = 50 * 1024 * 1024
MAX_REFERENCE_PIXELS = 100_000_000
_ALLOWED_FORMATS = {"PNG", "JPEG"}


def intake_reference(path_guard: Any, image_path: str | Path, *, intake_id: str,
                     license: str, registry: SchemaRegistry | None = None,
                     max_bytes: int = MAX_REFERENCE_BYTES,
                     max_pixels: int = MAX_REFERENCE_PIXELS,
                     config: dict[str, Any] | None = None) -> tuple[dict[str, Any], bytes]:
    """Safely read and freeze a reference image; returns (intake_record, raw_bytes)."""
    registry = registry or SchemaRegistry()
    resolved = path_guard.resolve(image_path, must_exist=True)
    # §5.3.1: bound the expensive operations BEFORE reading/decoding. Check the on-disk size
    # first, then format/pixel header, then full decode; the digest is computed from the same
    # frozen bytes (never a second read of a possibly-changing path).
    byte_size = resolved.stat().st_size
    if byte_size == 0 or byte_size > max_bytes:
        raise SecurityError("REFERENCE_SIZE_INVALID", f"byte_size={byte_size}")
    raw = resolved.read_bytes()
    if len(raw) != byte_size:
        raise SecurityError("REFERENCE_SIZE_INVALID", "reference changed during read")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in _ALLOWED_FORMATS:
            raise ProtocolError("REFERENCE_FORMAT_UNSUPPORTED", str(img.format))
        width, height = img.size
        if width * height > max_pixels:
            raise SecurityError("REFERENCE_PIXEL_LIMIT_EXCEEDED", f"{width}x{height}")
        img.load()
    except (ProtocolError, SecurityError):
        raise
    except Exception as exc:
        raise ProtocolError("REFERENCE_DECODE_FAILED", str(exc)[:200]) from exc
    dpi = img.info.get("dpi")
    dpi_value = float(dpi[0]) if isinstance(dpi, tuple) and dpi and dpi[0] else None
    record: dict[str, Any] = {
        "schema_version": 1,
        "intake_id": intake_id,
        "source_image": {"id": "reference-image", "version": protocol_version("reference-image"),
                         "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "uri": resolved.name},
        "width_px": width,
        "height_px": height,
        "format": img.format,
        "color_mode": img.mode,
        "license": license,
        "byte_size": len(raw),
        "dpi": dpi_value,
    }
    if config is not None:
        record["config"] = deepcopy(config)
    registry.validate("reference-intake", record)
    return record, raw


def assemble_segment_design(proposal: dict[str, Any], *, kind: str,
                            base_design: dict[str, Any],
                            registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Compile a confirmed proposal + base contract into a complete closed segment design.

    Only complete recovered contract sub-fields are applied (style typography / layout).
    The result is validated closed-world; an incomplete required field is rejected, never
    auto-filled. Role-keyed category colors (裁决5) are a separate confirmation step.
    """
    registry = registry or SchemaRegistry()
    recovered = proposal.get("recovered", {})
    if kind == "map-style":
        design = deepcopy(base_design)
        if "typography" in recovered:
            design["typography"] = deepcopy(recovered["typography"])
        registry.validate("style", design)
        return design
    if kind == "map-layout":
        design = deepcopy(recovered["layout"]) if "layout" in recovered else deepcopy(base_design)
        registry.validate("layout", design)
        return design
    raise ProtocolError("SEGMENT_KIND_UNSUPPORTED", kind)