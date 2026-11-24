"""Segment template authoring: confirmed design -> closed map-style/map-layout package.

Plan phase-1 foundation increment. Builds a complete, closed segment staging package from
a confirmed style/layout contract, reusing StagingPackageWriter and the SEGMENT_CONTRACTS
path convention (single source). A segment package carries exactly one contract, no
business_contracts and no prototype (manifest.schema forbids business_contracts for
non-scenario kinds); it has no data sources or CRS — segments are reusable appearance /
layout contracts, not business scenarios (plan §1.2.4).

Boundary: this module only authors an immutable staging package. It does not publish,
approve, render, or read the repository index. Validation-host rendering and workflow
kind-dispatch are separate increments. The lock pins the identity digest (not the package
content digest), mirroring the scenario author and avoiding the checksum circularity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from .staging_package import StagingPackageWriter
from .template_matching import SEGMENT_CONTRACTS

RESOLVER_VERSION = "1.0.0"
DEPENDENCY_LOCK_PATH = "dependencies.lock.yaml"


def segment_identity(kind: str, namespace: str, template_id: str, version: str) -> dict[str, str]:
    if kind not in SEGMENT_CONTRACTS:
        raise ProtocolError("SEGMENT_KIND_UNSUPPORTED", kind)
    return {"namespace": namespace, "kind": kind, "id": template_id, "version": version}


def segment_dependency_lock(
    identity: dict[str, Any], *, requested_at: str, lock_id: str,
    dependencies: Any = (), resources: Any = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "lock_id": lock_id,
        "package": {**identity, "digest": sha256_digest(identity)},
        "dependencies": list(dependencies),
        "resources": list(resources),
        "resolver_version": RESOLVER_VERSION,
        "generated_at": requested_at,
    }


def segment_manifest_base(
    identity: dict[str, Any], *, summary: str, dependencies: Any = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package": {**identity, "status": "draft", "summary": summary[:500]},
        "dependencies": list(dependencies),
        "dependency_lock": DEPENDENCY_LOCK_PATH,
    }


def build_segment_payloads(
    kind: str, namespace: str, template_id: str, version: str, contract: dict[str, Any],
    *, summary: str, requested_at: str, lock_id: str,
    registry: SchemaRegistry | None = None, dependencies: Any = (), resources: Any = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure assembly of (manifest_base, documents); validates the contract closed-world."""
    registry = registry or SchemaRegistry()
    identity = segment_identity(kind, namespace, template_id, version)
    contract_path, schema_name = SEGMENT_CONTRACTS[kind]
    registry.validate(schema_name, contract)
    manifest_base = segment_manifest_base(identity, summary=summary, dependencies=dependencies)
    documents = {
        contract_path: contract,
        DEPENDENCY_LOCK_PATH: segment_dependency_lock(
            identity, requested_at=requested_at, lock_id=lock_id,
            dependencies=dependencies, resources=resources),
    }
    return manifest_base, documents


def author_segment_package(
    path_guard: PathGuard, work_root: Path, *,
    kind: str, namespace: str, template_id: str, version: str, contract: dict[str, Any],
    summary: str, requested_at: str, lock_id: str,
    registry: SchemaRegistry | None = None, dependencies: Any = (), resources: Any = (),
) -> dict[str, str]:
    registry = registry or SchemaRegistry()
    manifest_base, documents = build_segment_payloads(
        kind, namespace, template_id, version, contract,
        summary=summary, requested_at=requested_at, lock_id=lock_id,
        registry=registry, dependencies=dependencies, resources=resources)
    return StagingPackageWriter(path_guard, work_root, registry).write(manifest_base, documents)


def verify_segment_package(
    path_guard: PathGuard, work_root: Path, *,
    kind: str, namespace: str, template_id: str, version: str, contract: dict[str, Any],
    summary: str, requested_at: str, lock_id: str,
    registry: SchemaRegistry | None = None, dependencies: Any = (), resources: Any = (),
) -> dict[str, str]:
    registry = registry or SchemaRegistry()
    manifest_base, documents = build_segment_payloads(
        kind, namespace, template_id, version, contract,
        summary=summary, requested_at=requested_at, lock_id=lock_id,
        registry=registry, dependencies=dependencies, resources=resources)
    return StagingPackageWriter(path_guard, work_root, registry).verify_existing(manifest_base, documents)