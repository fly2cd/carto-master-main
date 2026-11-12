"""Shared immutable byte assets; data processors keep their own namespaces."""
from pathlib import Path
import hashlib
from typing import Any
from ..adapters.geospatial_mcp import _publish_bytes
from ..errors import ProtocolError

class StaticAssetStore:
    def read_bytes(self, path: Path, limit: int) -> bytes:
        path = self.guard.resolve(path, must_exist=True)
        if not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ProtocolError("RASTER_ASSET_SIZE_INVALID", "Expected a bounded regular file")
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        if not 0 < len(content) <= limit:
            raise ProtocolError("RASTER_ASSET_SIZE_INVALID", "Asset changed or exceeds its size limit")
        return content


    @staticmethod
    def digest_bytes(content: bytes) -> str:
        return "sha256:" + hashlib.sha256(content).hexdigest()


    def _asset(self, content: bytes, kind: str, extension: str) -> dict[str, Any]:
        digest = self.digest_bytes(content)
        path = self.project_guard.resolve(self.root / kind / (digest[7:] + extension))
        _publish_bytes(self.project_guard, path, content)
        return {"artifact_ref": {"id": kind, "version": "1.0.0", "digest": digest, "uri": path.as_posix()},
                "size_bytes": len(content)}


    def snapshot_bytes(self, asset: dict[str, Any], kind: str, extension: str) -> bytes:
        ref = asset["artifact_ref"]
        expected = self.project_guard.resolve(self.root / kind / (ref["digest"][7:] + extension), must_exist=True)
        if self.project_guard.resolve(ref["uri"], must_exist=True) != expected or ref["id"] != kind or ref["version"] != "1.0.0":
            raise ProtocolError("RASTER_SNAPSHOT_SCOPE_INVALID", "Snapshot must belong to this project's content store")
        limit = 268435456 if extension == ".tif" else 1048576 if extension == ".csv" else 67108864
        content = self.read_bytes(expected, limit)
        if len(content) != asset["size_bytes"] or self.digest_bytes(content) != ref["digest"]:
            raise ProtocolError("RASTER_SNAPSHOT_CHANGED", "Immutable raster asset has changed")
        return content

