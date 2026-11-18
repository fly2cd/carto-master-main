"""``carto intent`` — resolve a typed map intent (no capability authorization)."""
from __future__ import annotations

from ..schema_registry import load_document
from ..security.paths import PathGuard
from ..workflow.intent import IntentResolver
from ._shared import policy_path


def register(sub) -> None:
    intent = sub.add_parser("intent", help="Resolve a typed map intent")
    intent_sub = intent.add_subparsers(dest="intent_command", required=True)
    resolve = intent_sub.add_parser("resolve", help="Resolve business purpose and topic IDs, without enabling a capability")
    resolve.add_argument("request", help="intent-request JSON/YAML: schema_version, text, selection (fields/tasks/business_scene/theme_tags)")
    resolve.add_argument("--allowed-root", action="append", required=True)


def handle(args) -> dict:
    path = PathGuard(args.allowed_root).resolve(args.request, must_exist=True)
    request = load_document(path)
    if not isinstance(request, dict):
        raise ValueError("Intent request must be an object")
    result = IntentResolver(policy_path("intent-profiles.yaml")).resolve(request)
    return {"intent": result}