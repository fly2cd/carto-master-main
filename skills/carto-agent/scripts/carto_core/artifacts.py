"""Shared artifact IO; all external paths must be checked by their caller."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .canonical import sha256_digest
from .errors import ProtocolError
from .schema_registry import load_document


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace a caller-validated path atomically; caller owns locking and CAS.

    This is not a security boundary or an inter-process create-once primitive.
    Immutable wrappers compare existing content under the caller's writer lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_yaml(path: Path, value: dict[str, Any], *, create_once: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if create_once and load_document(path) != value:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        if create_once:
            return
    atomic_write_bytes(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode("utf-8"))


def atomic_json(path: Path, value: dict[str, Any], *, create_once: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists():
        if create_once and path.read_text(encoding="utf-8") != payload:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        if create_once:
            return
    atomic_write_bytes(path, payload.encode("utf-8"))


def artifact_ref(identifier: str, value: Any, uri: str | Path | None = None) -> dict[str, str]:
    result = {"id": identifier, "version": "1.0.0", "digest": sha256_digest(value)}
    if uri is not None:
        result["uri"] = str(uri)
    return result
