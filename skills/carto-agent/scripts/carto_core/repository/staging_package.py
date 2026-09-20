from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..compiler.dependencies import DependencyResolver
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _serialize(path: str, value: Any) -> bytes:
    if path.endswith((".yaml", ".yml")):
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode("utf-8")
    if path.endswith((".json", ".geojson")):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if isinstance(value, str):
        return value.rstrip().encode("utf-8") + b"\n"
    raise ProtocolError("PACKAGE_CONTENT_TYPE_INVALID", path)


class StagingPackageWriter:
    """Create one closed, immutable staging package without publishing it."""

    def __init__(self, path_guard: PathGuard, work_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.work_root = self.path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()
        self.resolver = DependencyResolver()

    def write(self, manifest_base: dict[str, Any], documents: dict[str, Any]) -> dict[str, str]:
        package_root = self.path_guard.resolve(self.work_root / "staging/package")
        if package_root.exists():
            raise ProtocolError("STAGING_PACKAGE_EXISTS", str(package_root))
        manifest, payloads, snapshot = self._expected_payloads(manifest_base, documents)
        staging_root = self.path_guard.resolve(self.work_root / "staging")
        staging_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".package-", dir=staging_root))
        if temporary.parent.resolve() != staging_root.resolve():
            raise ProtocolError("STAGING_TEMP_INVALID", str(temporary))
        try:
            for relative, payload in payloads.items():
                target = temporary.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            all_checksums = {
                relative: _digest_bytes(payload)
                for relative, payload in payloads.items()
                if relative != "checksums.sha256"
            }
            self._verify_closed_package(temporary, manifest, all_checksums)
            os.replace(temporary, package_root)
            return {**snapshot, "package_path": package_root.as_posix()}
        finally:
            if temporary.exists():
                if temporary.parent.resolve() != staging_root.resolve():
                    raise ProtocolError("STAGING_TEMP_INVALID", str(temporary))
                shutil.rmtree(temporary)

    def verify_existing(
        self,
        manifest_base: dict[str, Any],
        documents: dict[str, Any],
    ) -> dict[str, str]:
        """Verify an existing staging package against the exact deterministic author output."""
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        if not package_root.is_dir():
            raise ProtocolError("STAGING_PACKAGE_INVALID", str(package_root))
        manifest, payloads, snapshot = self._expected_payloads(manifest_base, documents)
        expected_paths = sorted(payloads)
        actual_paths = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file()
        )
        if actual_paths != expected_paths:
            raise ProtocolError(
                "STAGING_PACKAGE_CONTEXT_MISMATCH",
                f"expected={expected_paths}; actual={actual_paths}",
            )
        linked = [
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_symlink()
        ]
        if linked:
            raise ProtocolError("STAGING_PACKAGE_CONTEXT_MISMATCH", linked[0])
        for relative, expected in payloads.items():
            if (package_root / relative).read_bytes() != expected:
                raise ProtocolError("STAGING_PACKAGE_CONTEXT_MISMATCH", relative)
        all_checksums = {
            relative: _digest_bytes(payload)
            for relative, payload in payloads.items()
            if relative != "checksums.sha256"
        }
        self._verify_closed_package(package_root, manifest, all_checksums)
        return {**snapshot, "package_path": package_root.as_posix()}

    def _expected_payloads(
        self,
        manifest_base: dict[str, Any],
        documents: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, bytes], dict[str, str]]:
        self._validate_relative_paths(documents)
        document_payloads = {
            relative: _serialize(relative, documents[relative])
            for relative in sorted(documents)
        }
        checksums = {
            relative: _digest_bytes(payload)
            for relative, payload in document_payloads.items()
        }
        manifest = {
            **manifest_base,
            "files": sorted(documents),
            "checksums": {path: checksums[path] for path in sorted(checksums)},
        }
        self.registry.validate("manifest", manifest)
        self.resolver.validate_manifest(manifest, manifest["files"])
        manifest_payload = _serialize("manifest.yaml", manifest)
        all_checksums = {"manifest.yaml": _digest_bytes(manifest_payload), **checksums}
        checksum_lines = [
            f"{all_checksums[path].removeprefix('sha256:')}  {path}"
            for path in sorted(all_checksums)
        ]
        checksum_payload = ("\n".join(checksum_lines) + "\n").encode("utf-8")
        payloads = {
            **document_payloads,
            "manifest.yaml": manifest_payload,
            "checksums.sha256": checksum_payload,
        }
        return manifest, payloads, {
            "package_digest": _digest_bytes(checksum_payload),
            "manifest_digest": all_checksums["manifest.yaml"],
        }

    @staticmethod
    def _validate_relative_paths(documents: dict[str, Any]) -> None:
        if not documents:
            raise ProtocolError("PACKAGE_EMPTY", "A package must contain documents")
        reserved = {"manifest.yaml", "checksums.sha256"}
        for raw in documents:
            path = PurePosixPath(raw)
            if raw in reserved or path.is_absolute() or ".." in path.parts or "\\" in raw:
                raise ProtocolError("PACKAGE_PATH_INVALID", raw)

    def _verify_closed_package(
        self,
        root: Path,
        manifest: dict[str, Any],
        all_checksums: dict[str, str],
    ) -> None:
        actual = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
        expected = sorted(["manifest.yaml", "checksums.sha256", *manifest["files"]])
        if actual != expected:
            raise ProtocolError("PACKAGE_FILE_SET_MISMATCH", f"expected={expected}; actual={actual}")
        for relative, digest in all_checksums.items():
            if _digest_bytes((root / relative).read_bytes()) != digest:
                raise ProtocolError("PACKAGE_CHECKSUM_MISMATCH", relative)
        lock = yaml.safe_load((root / manifest["dependency_lock"]).read_text(encoding="utf-8"))
        self.registry.validate("dependency-lock", lock)
        self.resolver.validate_lock(lock)
        contract_schemas = {
            "scenario": "scenario",
            "data_schema": "data-role",
            "spatial_behavior": "spatial-behavior",
            "portrayal": "portrayal",
            "delivery": "delivery",
            "quality_gates": "quality-gates",
        }
        for key, schema_name in contract_schemas.items():
            contract = yaml.safe_load((root / manifest["business_contracts"][key]).read_text(encoding="utf-8"))
            self.registry.validate(schema_name, contract)
        prototype = yaml.safe_load((root / "prototypes/risk-overview.yaml").read_text(encoding="utf-8"))
        self.registry.validate("prototype-description", prototype)