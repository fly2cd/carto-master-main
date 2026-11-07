from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts import atomic_write_bytes
from ..canonical import canonical_json_bytes, sha256_digest
from ..errors import ProtocolError
from ..security.paths import PathGuard


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    artifact_id: str
    version: str
    digest: str
    path: Path

    def ref(self) -> dict[str, str]:
        return {"id": self.artifact_id, "version": self.version, "digest": self.digest, "uri": self.path.as_posix()}


class ImmutableArtifactStore:
    """Content-addressed JSON store with create-once semantics."""

    def __init__(self, root: Path, *, path_guard: PathGuard | None = None) -> None:
        self.path_guard = path_guard
        self.root = path_guard.resolve(root) if path_guard else root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, artifact_id: str, version: str, value: Any) -> StoredArtifact:
        digest = sha256_digest(value)
        directory = self.root / artifact_id / version
        target = directory / f"{digest.removeprefix('sha256:')}.json"
        if self.path_guard:
            self.path_guard.resolve(directory)
            self.path_guard.resolve(target)
        directory.mkdir(parents=True, exist_ok=True)
        payload = canonical_json_bytes(value) + b"\n"
        if target.exists():
            if target.read_bytes() != payload:
                raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(target))
            return StoredArtifact(artifact_id, version, digest, target)
        atomic_write_bytes(target, payload)
        return StoredArtifact(artifact_id, version, digest, target)

    def get(self, artifact: StoredArtifact) -> Any:
        if self.path_guard:
            self.path_guard.resolve(artifact.path, must_exist=True)
        value = json.loads(artifact.path.read_text(encoding="utf-8"))
        if sha256_digest(value) != artifact.digest:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CORRUPT", str(artifact.path))
        return value
