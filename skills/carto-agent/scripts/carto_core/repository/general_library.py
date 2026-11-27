"""Publish the general template library (4 layouts + 4 styles) as reusable segments.

Bootstrap publication of the general-purpose map-layout / map-style presets into a
template repository so they are discoverable and selectable via segment_refs. This is
an engineering/bootstrap publication (synthetic approval); production publication of
business templates still requires the validate + TP approval workflow.

The packages are closed (manifest + checksums + dependency lock) and integrity-verified
by the repository on publish and on every later fetch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifacts import file_digest
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from .general_layout_presets import all_general_layouts
from .general_style_presets import all_general_styles
from .template_repository import TemplateRepository

_D = "sha256:" + "0" * 64


def _publish_segment(repo: TemplateRepository, root: Path, kind: str, seg_id: str,
                     contract: dict[str, Any], contract_rel: str, idem: str) -> dict[str, Any]:
    staging = root / f"staging-{seg_id}"
    (staging / "contracts").mkdir(parents=True, exist_ok=True)
    (staging / contract_rel).write_text(json.dumps(contract), encoding="utf-8")
    lock = {"schema_version": 1, "lock_id": f"{seg_id}-lock",
            "package": {"namespace": "local", "kind": kind, "id": seg_id,
                        "version": "1.0.0", "digest": _D},
            "dependencies": [], "resources": [], "resolver_version": "1.0.0",
            "generated_at": "2026-11-26T00:00:00Z"}
    (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
    files = ["dependencies.lock.yaml", contract_rel]
    manifest = {"schema_version": 1,
                "package": {"namespace": "local", "kind": kind, "id": seg_id,
                            "version": "1.0.0", "status": "published",
                            "summary": f"General library {kind} {seg_id}"},
                "dependency_lock": "dependencies.lock.yaml", "files": files,
                "checksums": {rel: file_digest(staging / rel) for rel in files}}
    (staging / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
    md = file_digest(staging / "manifest.yaml")
    lines = [f"{manifest['checksums'][rel][7:]}  {rel}" for rel in files]
    lines.append(f"{md[7:]}  manifest.yaml")
    (staging / "checksums.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    snapshot = {"package_digest": file_digest(staging / "checksums.sha256"),
                "manifest_digest": md, "manifest": manifest,
                "dependency_lock_digest": file_digest(staging / "dependencies.lock.yaml")}
    pub = repo.publish(
        package_root=staging, snapshot=snapshot, evidence={"evidence_digest": _D},
        approval={"synthetic": "general-library-bootstrap"}, idempotency_key=idem,
        publication_object={"schema_version": 1, "run_id": "general-library-run",
                            "request_digest": _D,
                            "package_ref": {"kind": kind, "id": seg_id, "version": "1.0.0",
                                            "digest": snapshot["package_digest"]},
                            "evidence_ref": {"id": "template-validation-evidence",
                                             "version": "1.0.0", "digest": _D, "uri": "evidence.yaml"},
                            "repository_scope": repo.repository_scope,
                            "repository_root": repo.root.as_posix(),
                            "idempotency_key": idem})
    return {"kind": kind, "id": seg_id, "version": "1.0.0", "digest": pub["package_ref"]["digest"]}


def publish_general_library(repository_root: str | Path, *,
                            repository_scope: str = "local:templates",
                            registry: SchemaRegistry | None = None) -> list[dict[str, Any]]:
    """Publish all general layout + style presets; return their pinned refs."""
    root = Path(repository_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    guard = PathGuard([root])
    repo = TemplateRepository(path_guard=guard, root=root,
                              repository_scope=repository_scope, registry=registry)
    refs = []
    for i, (lid, layout) in enumerate(all_general_layouts().items()):
        refs.append(_publish_segment(repo, root, "map-layout", lid, layout,
                                     "contracts/layout.yaml", f"gen-lib-layout-{i:04d}"))
    for i, (sid, style) in enumerate(all_general_styles().items()):
        refs.append(_publish_segment(repo, root, "map-style", sid, style,
                                     "contracts/cartography.yaml", f"gen-lib-style-{i:04d}"))
    return refs