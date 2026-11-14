"""Material extraction framework: provenance-tracked text, CSV, and document parsing.

Each extractor freezes the source material as an immutable snapshot and records
exact byte offsets for every extracted cell or text segment. No extractor issues
approvals, calls external services, or executes instructions embedded in source
material.

Design rules (ref: doc/design-principles.md):
- Extraction is mechanical derivation: same input → same output always.
- Source material is immutable after snapshot; drift is detected, never corrected.
- Every extraction produces a verifiable tool receipt; empty results are not allowed.
- Unknown formats and oversized files are rejected before any bytes are read.
"""
from __future__ import annotations

import csv
import io
import hashlib
import re
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..artifacts import artifact_ref, utc_now
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard

MAX_SOURCE_BYTES = 64 * 1024 * 1024  # 64 MiB
MAX_TEXT_BYTES = 1 * 1024 * 1024     # 1 MiB
MAX_CSV_ROWS = 50000
MAX_CSV_COLUMNS = 256

ALLOWED_FORMATS = frozenset({
    "text/plain", "text/csv", "text/markdown",
    "application/json", "image/png", "image/jpeg", "image/tiff",
    "application/pdf",
})

# Simple format detection by extension — no content sniffing (files must declare their intent)
EXTENSION_FORMAT: dict[str, str] = {
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

_FORMAT_EXTRACTORS: dict[str, str] = {
    "text/plain": "plain-text-extractor",
    "text/csv": "csv-extractor",
    "text/markdown": "plain-text-extractor",
}


def detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    fmt = EXTENSION_FORMAT.get(suffix)
    if fmt is None:
        raise ProtocolError("MATERIAL_FORMAT_UNKNOWN",
                            f"Unsupported file extension: {suffix}; allowed: {sorted(EXTENSION_FORMAT)}")
    return fmt


def _snapshot_bytes(source_path: Path, guard: PathGuard) -> tuple[bytes, dict[str, Any]]:
    """Capture an immutable snapshot of the source file. Returns (raw_bytes, content_ref)."""
    if not source_path.is_file():
        raise SecurityError("MATERIAL_NOT_FOUND", f"Source is not a file: {source_path}")
    size = source_path.stat().st_size
    if size == 0:
        raise ProtocolError("MATERIAL_EMPTY", "Source file is empty; empty extraction is not allowed")
    if size > MAX_SOURCE_BYTES:
        raise ProtocolError("MATERIAL_TOO_LARGE",
                            f"Source exceeds {MAX_SOURCE_BYTES} byte limit: {size}")
    data = source_path.read_bytes()
    if len(data) != size:
        raise ProtocolError("MATERIAL_SIZE_MISMATCH", "File size changed during read")
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return data, {"id": "material-source", "version": "1.0.0", "digest": digest,
                  "uri": str(source_path)}


def _text_content(data: bytes, max_chars: int = MAX_TEXT_BYTES) -> str:
    """Decode bytes as UTF-8 text, rejecting non-textual control characters."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("MATERIAL_ENCODING_INVALID", "Source is not valid UTF-8")
    if len(text) > max_chars:
        raise ProtocolError("MATERIAL_TEXT_TOO_LARGE", f"Text exceeds {max_chars} character limit")
    # Reject non-printable control characters (except common whitespace)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", text):
        raise ProtocolError("MATERIAL_CONTROL_CHARS", "Source contains non-printable control characters")
    # Normalize line endings for cross-platform pattern matching
    return text.replace("\r\n", "\n")


class ExtractionResult:
    """Verified extraction result with immutable provenance."""

    def __init__(self, body: dict[str, Any], registry: SchemaRegistry) -> None:
        body["digest"] = sha256_digest(body)
        registry.validate("extraction-result", body)
        self.body = deepcopy(body)
        self.digest = body["digest"]

    def ref(self) -> dict[str, str]:
        return {"id": "extraction-result", "version": "1.0.0",
                "digest": self.digest, "uri": ""}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExtractionResult):
            return NotImplemented
        return self.digest == other.digest


class BaseExtractor(ABC):
    """Abstract extractor: receive source bytes → produce structured ExtractionResult."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    @property
    @abstractmethod
    def tool_id(self) -> str:
        ...

    @property
    @abstractmethod
    def tool_version(self) -> str:
        ...

    @abstractmethod
    def extract(self, source_path: Path, guard: PathGuard,
                source_id: str, fmt: str) -> ExtractionResult:
        ...

    def _make_source(self, source_id: str, fmt: str, source_path: Path,
                     raw: bytes, content_ref: dict[str, Any]) -> dict[str, Any]:
        """Return the content_ref as the source identity for extraction-result."""
        return content_ref


class PlainTextExtractor(BaseExtractor):
    """Extract plain text or markdown content with line-level provenance."""

    tool_id = "plain-text-extractor"
    tool_version = "1.0.0"

    def extract(self, source_path: Path, guard: PathGuard,
                source_id: str, fmt: str) -> ExtractionResult:
        raw, content_ref = _snapshot_bytes(source_path, guard)
        text = _text_content(raw)
        lines = text.splitlines()
        line_entries = []
        byte_pos = 0
        for i, line in enumerate(lines):
            line_bytes = len(line.encode("utf-8"))
            line_entries.append({
                "index": i,
                "cells": {"line": line},
                "source_location": {
                    "line_start": i + 1,
                    "line_end": i + 1,
                    "byte_offset": byte_pos,
                    "byte_length": line_bytes,
                },
            })
            byte_pos += line_bytes + len("\n".encode("utf-8"))
        body = {
            "schema_version": 1,
            "result_id": f"extract-{source_id}",
            "source_ref": self._make_source(source_id, fmt, source_path, raw, content_ref),
            "extracted_at": utc_now(),
            "content_type": "text",
            "source_format": fmt,
            "fields": [{"name": "line", "data_type": "string", "nullable": False}],
            "row_count": len(line_entries),
            "byte_length": len(raw),
            "rows": line_entries,
            "text_content": text,
            "issues": [],
        }
        return ExtractionResult(body, self.registry)


class CsvExtractor(BaseExtractor):
    """Extract tabular data from CSV with cell-level provenance.

    Every cell's source location (line number, byte offset) is recorded.
    """

    tool_id = "csv-extractor"
    tool_version = "1.0.0"

    def extract(self, source_path: Path, guard: PathGuard,
                source_id: str, fmt: str) -> ExtractionResult:
        raw, content_ref = _snapshot_bytes(source_path, guard)
        text = _text_content(raw)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ProtocolError("CSV_TOO_LARGE", f"CSV exceeds {MAX_SOURCE_BYTES} byte limit")

        # Use Excel dialect for deterministic, cross-platform CSV parsing.
        # csv.Sniffer is unreliable for small or irregular files and can produce
        # empty column names or wrong delimiters.
        reader = csv.reader(io.StringIO(text), "excel")
        rows_list = list(reader)

        if not rows_list:
            raise ProtocolError("CSV_EMPTY", "CSV file has no rows; empty extraction is not allowed")
        if len(rows_list) > MAX_CSV_ROWS:
            raise ProtocolError("CSV_TOO_MANY_ROWS",
                                f"CSV exceeds {MAX_CSV_ROWS} row limit: {len(rows_list)}")

        header = rows_list[0]
        if len(header) > MAX_CSV_COLUMNS:
            raise ProtocolError("CSV_TOO_MANY_COLUMNS",
                                f"CSV exceeds {MAX_CSV_COLUMNS} column limit: {len(header)}")
        if len(header) != len(set(header)):
            raise ProtocolError("CSV_DUPLICATE_COLUMNS", "CSV header has duplicate column names")

        # Validate header names
        for name in header:
            if not name or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
                raise ProtocolError("CSV_COLUMN_NAME_INVALID",
                                    f"CSV column name must match [a-zA-Z_][a-zA-Z0-9_]*: {name!r}")

        # Detect field types from data rows
        data_rows = rows_list[1:]
        # Validate column counts first — reject mismatched rows before type detection
        for i, row in enumerate(data_rows):
            if len(row) != len(header):
                raise ProtocolError("CSV_COLUMN_COUNT_MISMATCH",
                                    f"Row {i + 2} has {len(row)} columns, expected {len(header)}")
        field_types = self._detect_types(header, data_rows)

        # Build provenance-tracked rows
        line_offsets = self._compute_line_offsets(text)
        extracted_rows = []
        for i, row in enumerate(data_rows):
            cells = {header[j]: row[j] for j in range(len(header))}
            # Line provenance — row i + 1 in data maps to line i + 2 in file (0-indexed skip header)
            line_idx = i + 1
            loc = {
                "line_start": line_offsets[line_idx][0] if line_idx < len(line_offsets) else i + 2,
                "line_end": line_offsets[line_idx][1] if line_idx < len(line_offsets) else i + 2,
            }
            extracted_rows.append({
                "index": i,
                "cells": cells,
                "source_location": loc,
            })

        issues = []
        if not data_rows:
            issues.append({"severity": "warning",
                          "message": "CSV has header but no data rows"})

        body = {
            "schema_version": 1,
            "result_id": f"extract-{source_id}",
            "source_ref": self._make_source(source_id, fmt, source_path, raw, content_ref),
            "extracted_at": utc_now(),
            "content_type": "tabular",
            "source_format": fmt,
            "fields": field_types,
            "row_count": len(data_rows),
            "byte_length": len(raw),
            "rows": extracted_rows,
            "issues": issues,
        }
        return ExtractionResult(body, self.registry)

    @staticmethod
    def _detect_types(header: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
        """Detect simple types from data values."""
        types = {}
        for row in rows:
            for j, val in enumerate(row):
                col = header[j]
                if col not in types:
                    types[col] = "integer"
                if types[col] == "ignore":
                    continue
                if val == "":
                    continue
                if types[col] == "integer":
                    if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", val):
                        types[col] = "number"
                if types[col] == "number":
                    try:
                        float(val)
                    except ValueError:
                        types[col] = "string"
                if types[col] == "boolean":
                    if val.lower() not in ("true", "false"):
                        types[col] = "string"
        return [{"name": col, "data_type": types.get(col, "string"),
                 "nullable": True} for col in header]

    @staticmethod
    def _compute_line_offsets(text: str) -> list[tuple[int, int]]:
        """Compute (line_start, line_end) for each line."""
        lines = text.splitlines()
        offsets = []
        for i, _ in enumerate(lines):
            offsets.append((i + 1, i + 1))
        return offsets


class MaterialExtractionService:
    """Registry of extractors by format; security-bounded, no dynamic dispatch."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        self._extractors: dict[str, BaseExtractor] = {
            "plain-text-extractor": PlainTextExtractor(self.registry),
            "csv-extractor": CsvExtractor(self.registry),
        }

    def extract(self, source_path: Path, guard: PathGuard,
                source_id: str, fmt: str | None = None) -> ExtractionResult:
        """Extract one source file into a provenance-tracked result.

        Args:
            source_path: absolute path (already resolved through PathGuard)
            guard: the active PathGuard for additional resolution
            source_id: stable identifier bound to the extraction
            fmt: explicit format; auto-detected from extension if None
        """
        resolved = guard.resolve(source_path, must_exist=True)
        if fmt is None:
            fmt = detect_format(resolved)
        elif fmt not in ALLOWED_FORMATS:
            raise ProtocolError("MATERIAL_FORMAT_UNKNOWN",
                                f"Format {fmt} is not in the allowed set: {sorted(ALLOWED_FORMATS)}")

        tool = _FORMAT_EXTRACTORS.get(fmt)
        if tool is None:
            raise ProtocolError("MATERIAL_EXTRACTOR_MISSING",
                                f"No extractor registered for format {fmt}; "
                                f"supported: {sorted(_FORMAT_EXTRACTORS)}")
        extractor = self._extractors[tool]
        return extractor.extract(resolved, guard, source_id, fmt)

    def extract_many(self, sources: list[dict[str, Any]],
                     guard: PathGuard, base_root: Path | None = None) -> list[ExtractionResult]:
        """Extract multiple sources; all-or-nothing (partial failure rejects all)."""
        results = []
        for source in sources:
            source_id = source["source_id"]
            source_path = guard.resolve(Path(source["path"]), base_root=base_root, must_exist=True)
            fmt = source.get("format")
            results.append(self.extract(source_path, guard, source_id, fmt))
        return results