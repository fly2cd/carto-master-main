from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from ..errors import ProtocolError


_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class DependencyResolver:
    """Resolves explicitly supplied, immutable dependencies; no dynamic discovery."""

    MAP_SCENARIO_CONTRACTS = {
        "scenario": "contracts/scenario.yaml",
        "data_schema": "contracts/data.schema.yaml",
        "spatial_behavior": "contracts/spatial-behavior.yaml",
        "portrayal": "contracts/portrayal.yaml",
        "delivery": "contracts/delivery.yaml",
        "quality_gates": "contracts/quality-gates.yaml",
    }

    def resolve(self, roots: Iterable[str], graph: dict[str, list[str]]) -> list[str]:
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ProtocolError("DEPENDENCY_CYCLE", node)
            if node in visited:
                return
            if node not in graph:
                raise ProtocolError("DEPENDENCY_NOT_PINNED", node)
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)
            ordered.append(node)

        for root in roots:
            visit(root)
        return ordered

    @staticmethod
    def require_pinned(reference: dict[str, Any]) -> None:
        if not isinstance(reference, dict):
            raise ProtocolError("DEPENDENCY_NOT_PINNED", "reference must be an object")
        missing = [key for key in ("id", "version", "digest") if not reference.get(key)]
        if missing:
            raise ProtocolError("DEPENDENCY_NOT_PINNED", ",".join(missing))
        if not isinstance(reference["version"], str) or not _SEMVER.fullmatch(reference["version"]):
            raise ProtocolError("DEPENDENCY_VERSION_NOT_EXACT", str(reference["version"]))
        if not isinstance(reference["digest"], str) or not _DIGEST.fullmatch(reference["digest"]):
            raise ProtocolError("DEPENDENCY_DIGEST_INVALID", str(reference["digest"]))

    def validate_lock(self, lock: dict[str, Any]) -> None:
        package = lock.get("package")
        self.require_pinned(package)
        seen: set[tuple[str, str]] = set()
        for dependency in lock.get("dependencies", []):
            self.require_pinned(dependency)
            identity = (str(dependency.get("kind")), str(dependency["id"]))
            if identity in seen:
                raise ProtocolError("DEPENDENCY_DUPLICATE", ":".join(identity))
            seen.add(identity)
        for resource in lock.get("resources", []):
            self.require_pinned(resource)
            identity = ("map-expression", str(resource["id"]))
            if identity in seen:
                raise ProtocolError("DEPENDENCY_DUPLICATE", ":".join(identity))
            seen.add(identity)

    def validate_manifest(self, manifest: dict[str, Any], actual_files: Iterable[str] | None = None) -> None:
        files = manifest.get("files")
        checksums = manifest.get("checksums")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ProtocolError("MANIFEST_FILE_SET_INVALID", "files must be a string array")
        if len(files) != len(set(files)):
            raise ProtocolError("MANIFEST_FILE_DUPLICATE", "manifest files must be unique")
        if not isinstance(checksums, dict) or not all(isinstance(key, str) for key in checksums):
            raise ProtocolError("MANIFEST_CHECKSUM_SET_INVALID", "checksums must be an object")

        file_set = set(files)
        checksum_set = set(checksums)
        if file_set != checksum_set:
            missing = sorted(file_set - checksum_set)
            extra = sorted(checksum_set - file_set)
            raise ProtocolError(
                "MANIFEST_CHECKSUM_MISMATCH",
                f"missing={missing}; extra={extra}",
            )

        dependency_lock = manifest.get("dependency_lock")
        if dependency_lock not in file_set:
            raise ProtocolError("MANIFEST_DEPENDENCY_LOCK_MISSING", str(dependency_lock))

        package = manifest.get("package", {})
        if package.get("kind") == "map-scenario":
            contracts = manifest.get("business_contracts")
            if contracts != self.MAP_SCENARIO_CONTRACTS:
                raise ProtocolError(
                    "MANIFEST_BUSINESS_CONTRACTS_INVALID",
                    "MapScenario must declare exactly the six fixed business contracts",
                )
            missing_contract_files = sorted(set(self.MAP_SCENARIO_CONTRACTS.values()) - file_set)
            if missing_contract_files:
                raise ProtocolError("MANIFEST_BUSINESS_CONTRACT_FILE_MISSING", ",".join(missing_contract_files))

        for dependency in manifest.get("dependencies", []):
            self.require_pinned(dependency)

        if actual_files is not None:
            actual_list = list(actual_files)
            if len(actual_list) != len(set(actual_list)):
                raise ProtocolError("PACKAGE_FILE_DUPLICATE", "actual package files must be unique")
            actual_set = set(actual_list)
            if actual_set != file_set:
                missing = sorted(actual_set - file_set)
                absent = sorted(file_set - actual_set)
                raise ProtocolError(
                    "MANIFEST_FILE_SET_MISMATCH",
                    f"unlisted={missing}; missing={absent}",
                )
