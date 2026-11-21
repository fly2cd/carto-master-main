"""Request scaffold tool: build the pending generate-request.yaml mechanically.

Takes the validated draft plus explicit request identity, computes every
digest binding (draft / basemap / registration / template), and atomically
writes the leadership-visit generate request in the shape twice verified by
end-to-end runs (pending mode, mcp-itinerary-chain preparation, forward
digest declaration, 7 field bindings, A3 fixed-page 200 dpi, 4 capabilities).

Advisory by design: the sole authority over request validity is the kernel's
closed schema at intake (leadership-visit-generate-request.schema.json).
``requested_at`` is an explicit argument so tests can pin deterministic output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import re

import yaml

from _service_utils import (
    ServiceError,
    atomic_write_text,
    dump_json_text,
    resolve_under_root,
    raw_file_digest,
    sha256_digest,
)

_TEMPLATE_ID = "leadership-visit-map"
_FIELD_BINDINGS = [
    {"semantic_role": "stop-label", "source_field": "stop_name"},
    {"semantic_role": "visit-date", "source_field": "visit_date"},
    {"semantic_role": "arrival-time", "source_field": "arrival_time"},
    {"semantic_role": "distance-km", "source_field": "distance_km"},
    {"semantic_role": "duration-min", "source_field": "duration_min"},
    {"semantic_role": "itinerary-group", "source_field": "itinerary_group"},
    {"semantic_role": "map-role", "source_field": "map_role"},
]
_CAPABILITIES = ["read", "render-preview", "geo-to-image-pixels", "image-display-bounds"]


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message}


def _template_digest(repo: Path) -> dict[str, str]:
    """Read template-index.yaml → the published leadership-visit-map entry."""
    index_path = repo / "template-index.yaml"
    if not index_path.is_file():
        raise ServiceError("TEMPLATE_INDEX_MISSING",
                           f"template index not found: {index_path}")
    try:
        index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ServiceError("TEMPLATE_INDEX_INVALID", f"template index unparseable: {exc}") from exc
    entries = [e for e in (index or {}).get("entries", [])
               if isinstance(e, dict)
               and e.get("id") == _TEMPLATE_ID
               and e.get("status") == "published"]
    if not entries:
        raise ServiceError("TEMPLATE_NOT_PUBLISHED",
                           f"no published '{_TEMPLATE_ID}' entry in the template repository")
    best = max(entries, key=lambda e: str(e.get("version", "0")))
    digest = best.get("digest", "")
    if not str(digest).startswith("sha256:"):
        raise ServiceError("TEMPLATE_INDEX_INVALID", "template entry has no digest")
    return {"id": _TEMPLATE_ID, "version": str(best.get("version", "1.0.0")), "digest": digest}


def _load_registration(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ServiceError("REGISTRATION_UNPARSEABLE",
                           f"registration.yaml must be parseable YAML/JSON: {exc}") from exc


def request_scaffold(arguments: dict[str, Any], ctx: dict[str, Path]) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Required identity arguments (the approval binding surface — explicit,
    never defaulted): project_id, tenant_id, subject_id, approver_subject_id.
    Optional with defaults: request_id / run_id / idempotency_key (generated),
    basemap_path, registration_path, font_path, font_family, template_repo_path,
    goal, requested_at (for deterministic tests).
    """
    root = ctx["allowed_root"]
    required = ("project_id", "tenant_id", "subject_id", "approver_subject_id")
    missing = [k for k in required if not arguments.get(k)]
    if missing:
        return _fail("IDENTITY_REQUIRED", f"required identity fields: {missing}")
    draft_arg = arguments.get("draft_path", "")
    if not draft_arg:
        return _fail("DRAFT_PATH_REQUIRED", "draft_path is required")

    basemap_arg = arguments.get("basemap_path", "basemap.png")
    registration_arg = arguments.get("registration_path", "registration.yaml")
    font_arg = arguments.get("font_path", "fonts/simhei.ttf")
    font_family = arguments.get("font_family", "SimHei")
    repo_arg = arguments.get("template_repo_path", "template-repo")

    # The kernel's identifier contract is ^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$: no
    # uppercase, no bare separators. A literal "T" in the timestamp previously
    # produced request ids like "leadership-20261121T044115-0001" that the
    # kernel rejects at intake (SCHEMA_VALIDATION_FAILED) — digits only here.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    default_id = f"leadership-{stamp}"
    request_id = arguments.get("request_id") or f"{default_id}-0001"
    run_id = arguments.get("run_id") or f"run-{stamp}"
    idempotency_key = arguments.get("idempotency_key") or request_id
    # Validate the identity triple against the kernel's contract here — a clear
    # advisory error beats a late SCHEMA_VALIDATION_FAILED at intake.
    identifier = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    for field, value in (("request_id", request_id), ("run_id", run_id)):
        if len(value) > 80 or not identifier.fullmatch(value):
            return _fail("IDENTITY_INVALID",
                         f"{field} '{value}' violates the kernel identifier "
                         "contract ^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$ (max 80 chars)")
    if not (16 <= len(idempotency_key) <= 128):
        return _fail("IDENTITY_INVALID",
                     f"idempotency_key must be 16-128 chars, got {len(idempotency_key)}")
    requested_at = arguments.get("requested_at") or \
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    goal = arguments.get("goal", "编制领导调研行程路线图")

    try:
        draft_path = resolve_under_root(draft_arg, root, must_exist=True)
        basemap_path = resolve_under_root(basemap_arg, root, must_exist=True)
        registration_path = resolve_under_root(registration_arg, root, must_exist=True)
        repo = resolve_under_root(repo_arg, root, must_exist=True)
        font_resolved = resolve_under_root(font_arg, root, must_exist=True)
        output_path = resolve_under_root("generate-request.yaml", root)
    except ServiceError as exc:
        return _fail(exc.code, exc.message)

    if font_resolved.suffix.lower() != ".ttf":
        return _fail("FONT_FORMAT_UNSUPPORTED",
                     "font must be a single-face .ttf (collections .ttc cannot be embedded)")

    import json
    draft_digest = sha256_digest(json.loads(draft_path.read_text(encoding="utf-8")))
    try:
        registration = _load_registration(registration_path)
        template = _template_digest(repo)
    except ServiceError as exc:
        return _fail(exc.code, exc.message)
    registration_digest = sha256_digest(registration)
    basemap_digest = raw_file_digest(basemap_path)

    project_id = arguments["project_id"]
    request = {
        "schema_version": 1,
        "request_id": request_id,
        "project_id": project_id,
        "run_id": run_id,
        "goal": goal,
        "geometry": "vector",
        "requested_outputs": ["pdf", "png"],
        "subject": {
            "tenant_id": arguments["tenant_id"],
            "subject_id": arguments["subject_id"],
            "approver_subject_id": arguments["approver_subject_id"],
            "namespace": project_id,
        },
        "idempotency_key": idempotency_key,
        "scope": f"project:{project_id}",
        "environment": "local",
        "requested_at": requested_at,
        "audience": "内部演示",
        "sources": [{"id": "itinerary", "version": "1.0.0", "digest": draft_digest}],
        "template": {
            "namespace": "local", "kind": "map-scenario",
            "id": template["id"], "version": template["version"],
            "digest": template["digest"],
        },
        "font": {"path": font_arg, "family": font_family, "version": "1.0.0"},
        "intent": {
            "business_scene": "leadership_visit", "theme_tags": [],
            "tasks": ["visit-route-map"],
            "fields": {"itinerary": "调研行程", "visit-order": "1-6",
                       "route-mode": "road", "geography": "杭州",
                       "confidentiality": "internal", "output": "pdf"},
        },
        "itinerary_structure": {
            "source_ref": {"id": "itinerary-source", "version": "1.0.0",
                           "digest": draft_digest, "uri": "data/itinerary.json"},
            "normalized_ref": {"id": "itinerary-normalized", "version": "1.0.0",
                               "digest": draft_digest},
        },
        "basemap": {
            "mode": "registered-transform",
            "image_ref": {"id": "basemap-image", "version": "1.0.0",
                          "digest": basemap_digest, "uri": basemap_arg},
            "parameters_ref": {"id": "registration-parameters", "version": "1.0.0",
                               "digest": registration_digest, "uri": registration_arg},
        },
        "source_bindings": [{
            "role": "route-stops",
            "source_ref": {"id": "itinerary-source", "version": "1.0.0",
                           "digest": draft_digest},
            "path": "data/itinerary.json",
            "geometry_types": ["point"],
            "pending": True,
            "preparation": "mcp-itinerary-chain",
            "field_bindings": [dict(binding) for binding in _FIELD_BINDINGS],
        }],
        "page_layout": {"model": "fixed-page", "width_mm": 420, "height_mm": 297, "dpi": 200},
        "allowed_capabilities": list(_CAPABILITIES),
    }
    atomic_write_text(output_path, dump_json_text(request))

    return {
        "status": "built",
        "request_path": str(output_path),
        "bound_digests": {
            "draft": draft_digest,
            "basemap": basemap_digest,
            "registration": registration_digest,
            "template": template["digest"],
        },
        "identity": {"request_id": request_id, "run_id": run_id,
                     "idempotency_key": idempotency_key,
                     "scope": f"project:{project_id}"},
        "reminder": "pending 模式：intake 后请求指纹锁定，G1 后不得修改本文件；"
                    "实际数据绑定发生在 G2 的 prepared-data-bundle",
    }
