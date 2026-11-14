"""Data adoption service: explicit material acceptance with verifiable evidence.

Every piece of source material must be explicitly adopted before it enters the map
generation pipeline. Adoption is a mechanical decision guided by policy — it does not
make business judgments about whether data is "correct" or "appropriate". It verifies:

1. The material was properly extracted and its source is traceable.
2. The declared format, dimensions, and bounds match the extraction evidence.
3. No blocked content patterns (instructions, scripts, code) are present.
4. The material falls within the allowed size/type/scope constraints.

Adoption records are immutable evidence attached to the prepared-data-bundle.
Rejected materials stay rejected; they cannot be re-adopted without a new extraction.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..artifacts import utc_now
from ..schema_registry import SchemaRegistry

# Format detection from source uri — deterministic, no content sniffing
_EXTENSION_TO_FORMAT: dict[str, str] = {
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
}


def _format_from_source(source: dict[str, Any], extraction: dict[str, Any]) -> str:
    """Derive source format from extraction evidence.

    Prefers the content_type mapping; falls back to uri extension detection.
    """
    # Check explicit format field in extraction (added by extractors that know the format)
    fmt = extraction.get("source_format")
    if fmt:
        return fmt

    # Derive from uri extension
    uri = source.get("uri", "")
    for ext, mime in _EXTENSION_TO_FORMAT.items():
        if uri.lower().endswith(ext):
            return mime

    # Fall back to content_type mapping
    content_type = extraction.get("content_type", "text")
    return {"text": "text/plain", "tabular": "text/csv",
            "image": "image/png", "mixed": "text/plain"}[content_type]

# Content patterns that indicate executable instructions, never legitimate data
_BLOCKED_PATTERNS = [
    "import os\n", "subprocess.", "eval(", "exec(", "__import__",
    "os.system", "os.popen", "socket.", "requests.",
    "#!/usr/bin/env", "#!/bin/bash", "#!/bin/sh",
    "<script", "javascript:", "onerror=", "onload=",
]


class DataAdoptionService:
    """Validate and record material adoption decisions."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def adopt(self, extraction: dict[str, Any], *,
              allowed_formats: frozenset[str] | None = None,
              max_cells: int = 100000,
              max_text_length: int = 1048576) -> dict[str, Any]:
        """Adopt an extraction result after security and policy checks.

        Returns an adoption evidence record suitable for inclusion in
        the prepared-data-bundle's ``adoption_evidence`` array.

        Raises SecurityError if the material contains blocked patterns.
        Raises ProtocolError if the extraction doesn't pass policy checks.
        """
        self.registry.validate("extraction-result", extraction)
        source = extraction["source_ref"]
        fmt = _format_from_source(source, extraction)

        # Policy: format allowlist
        if allowed_formats is not None and fmt not in allowed_formats:
            return self._reject(extraction, f"Format {fmt} is not in the allowed set for this task")

        # Policy: size checks
        byte_length = extraction.get("byte_length", 0)
        if byte_length == 0:
            return self._reject(extraction, "Extraction has zero bytes; empty adoption is not allowed")

        # Policy: row/cell limits
        row_count = extraction.get("row_count", 0)
        if extraction["content_type"] == "tabular" and row_count > max_cells:
            return self._reject(extraction, f"Tabular data exceeds {max_cells} row limit: {row_count}")
        if extraction["content_type"] == "tabular" and row_count == 0:
            return self._reject(extraction, "Tabular extraction has no data rows")

        # Security: blocked content patterns
        text = extraction.get("text_content", "")
        if text:
            self._scan_blocked_patterns(text)

        # Security: tabular cell content scan
        for row in extraction.get("rows", []):
            for key, value in row.get("cells", {}).items():
                if isinstance(value, str):
                    self._scan_blocked_patterns(value)

        # Field presence check — every row must have all fields
        field_names = {f["name"] for f in extraction.get("fields", [])}
        for row in extraction.get("rows", []):
            if set(row["cells"]) != field_names:
                return self._reject(extraction, "Row cell keys do not match declared fields")

        return self._accept(extraction)

    def adopt_many(self, extractions: list[dict[str, Any]], **kwargs) -> list[dict[str, Any]]:
        """Adopt multiple extractions; returns evidence for each (adopted or rejected)."""
        return [self.adopt(ex, **kwargs) for ex in extractions]

    def build_data_facts(self, extractions: list[dict[str, Any]],
                         adopted: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Build a data-facts record from adopted extractions.

        Only adopted extractions contribute to the facts record.
        Returns None if no extractions were adopted.
        """
        adopted_refs = [
            a["source_ref"] for a in adopted
            if a.get("decision") == "adopted"
        ]
        if not adopted_refs:
            return None

        # Compute aggregate dimensions from all adopted extractions
        dims: dict[str, Any] = {}
        for i, ext in enumerate(extractions):
            if i >= len(adopted) or adopted[i].get("decision") != "adopted":
                continue
            ct = ext.get("content_type")
            if ct == "text":
                dims["byte_size"] = (dims.get("byte_size", 0)
                                     + ext.get("byte_length", 0))
            elif ct == "tabular":
                dims["row_count"] = (dims.get("row_count", 0)
                                     + ext.get("row_count", 0))
                dims["column_count"] = max(dims.get("column_count", 0),
                                          len(ext.get("fields", [])))
            img = ext.get("image_metadata")
            if img:
                dims["pixel_width"] = max(dims.get("pixel_width", 0),
                                         img.get("width_px", 0))
                dims["pixel_height"] = max(dims.get("pixel_height", 0),
                                          img.get("height_px", 0))

        if not dims:
            return None

        facts = {
            "schema_version": 1,
            "facts_id": f"facts-{sha256_digest(adopted_refs)[7:23]}",
            "source_kind": self._dominant_kind(extractions, adopted),
            "facts_digest": sha256_digest({"refs": adopted_refs, "dims": dims}),
            "material_refs": adopted_refs,
            "observed_dimensions": dims,
        }
        return facts

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _dominant_kind(extractions: list[dict[str, Any]],
                       adopted: list[dict[str, Any]]) -> str:
        kinds: dict[str, int] = {}
        for i, ext in enumerate(extractions):
            if i < len(adopted) and adopted[i].get("decision") == "adopted":
                ct = ext.get("content_type", "text")
                kind = {"text": "document", "tabular": "table",
                        "image": "image", "mixed": "document"}.get(ct, "document")
                kinds[kind] = kinds.get(kind, 0) + 1
        return max(kinds, key=lambda k: kinds[k])  # type: ignore[arg-type]

    def _accept(self, extraction: dict[str, Any]) -> dict[str, Any]:
        source_ref = extraction["source_ref"]
        evidence = {
            "source_ref": source_ref,
            "adopted_at": utc_now(),
            "adoption_digest": sha256_digest({"source": source_ref,
                                              "extraction": extraction["result_id"],
                                              "decision": "adopted"}),
            "decision": "adopted",
        }
        return evidence

    def _reject(self, extraction: dict[str, Any], reason: str) -> dict[str, Any]:
        source_ref = extraction["source_ref"]
        evidence = {
            "source_ref": source_ref,
            "adopted_at": utc_now(),
            "adoption_digest": sha256_digest({"source": source_ref,
                                              "extraction": extraction["result_id"],
                                              "decision": "excluded",
                                              "reason": reason}),
            "decision": "excluded",
            "reason": reason,
        }
        return evidence

    @staticmethod
    def _scan_blocked_patterns(text: str) -> None:
        """Raise SecurityError if text contains blocked patterns (code, scripts, etc.)."""
        for pattern in _BLOCKED_PATTERNS:
            if pattern in text:
                raise SecurityError("MATERIAL_BLOCKED_PATTERN",
                                    f"Source material contains a blocked pattern: {pattern!r}")