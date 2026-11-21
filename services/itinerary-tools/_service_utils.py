"""Shared service utilities: path guard, canonical digest, atomic writes.

Zero carto_core dependency by design. ``canonical_json_bytes`` replicates the
kernel's v1 canonical JSON (sorted keys, compact separators, ensure_ascii=False,
allow_nan=False) byte-identically — locked by golden tests
(test_request_scaffold.py compares against digests computed with the kernel
implementation on real E2E materials).

Error convention: tools return ``{"status": "error", "code", "message"}``
(matching geocode/plan_route) instead of raising across the MCP boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ServiceError(Exception):
    """Tool-level error carried as {status, code, message} across MCP."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def service_error_result(exc: ServiceError) -> dict[str, Any]:
    return {"status": "error", "code": exc.code, "message": exc.message}


# ---------------------------------------------------------------- digests

def canonical_json_bytes(value: Any) -> bytes:
    """Kernel-equivalent v1 canonical JSON (see carto_core.canonical)."""
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text.encode("utf-8")


def sha256_digest(value: Any) -> str:
    """Canonical-JSON digest — kernel sha256_digest equivalent."""
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def raw_file_digest(path: Path) -> str:
    """Raw-bytes sha256 (basemap images; kernel file_digest equivalent)."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


# ---------------------------------------------------------------- path guard

def resolve_under_root(path: str, root: Path, *, must_exist: bool = False) -> Path:
    """Resolve a project-relative or absolute path, confined to the allowed root.

    Relative paths resolve against ``root``; the result must stay inside the
    root (the service's --allowed-root becomes a real boundary for the
    file-touching preparation tools).
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ServiceError("PATH_OUTSIDE_ROOT", f"path is outside the allowed root: {path}")
    if must_exist and not resolved.exists():
        raise ServiceError("PATH_NOT_FOUND", f"path does not exist: {path}")
    return resolved


# ---------------------------------------------------------------- atomic write

def atomic_write_text(path: Path, text: str) -> None:
    """Temp-file + os.replace atomic write (newline-stable, UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=".tmp-", suffix=path.suffix)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def dump_json_text(value: Any) -> str:
    """Host-facing JSON serialization (matches prior E2E host output)."""
    return json.dumps(value, ensure_ascii=False, indent=2)
