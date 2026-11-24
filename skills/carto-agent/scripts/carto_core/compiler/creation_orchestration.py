"""Four-branch creation orchestration (plan phase 2, design §7/§8/§12).

Consumes a read-only ``design-resolution-result`` and turns the decision into a concrete
creation action WITHOUT a second state machine:

  * reuse / instantiate -> return the exact published reference (no new package, no index write);
  * derive              -> apply a restricted change-set to a project draft (no business version
                           reservation, design §7.1);
  * create              -> a confirmed complete design becomes a project draft;
  * clarify / unsupported / search-incomplete -> stop with an explicit report.

The orchestrator never auto-follows publication, never lets a model output grant approval, and
never downgrades an unsupported capability. Draft identity is project-scoped (``draft-<id>`` /
``0.0.0-draft.r<revision>``); the business library identity is only assigned later by an explicit
publication run. The result is the resolution decision extended additively with ``action`` and a
``published_ref`` or ``draft_ref`` substructure (design §12.1: ProjectDraft lives in the
design-resolution-result branch, not a separate library).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .template_derivation import derive_draft, draft_identity

_STOP_BRANCHES = ("clarify", "unsupported", "search-incomplete")

# First-version restricted derivation profiles per segment kind. allowed_keys is a conservative
# reviewed set (mirrors the existing style derivation test); identity keys are always forbidden
# inside derive_draft regardless. Widening this set is a policy decision, not an orchestrator guess.
SEGMENT_DERIVATION_PROFILE: dict[str, dict[str, Any]] = {
    "map-style": {"schema": "style", "id_field": "style_id", "allowed_keys": ("typography",)},
    "map-layout": {"schema": "layout", "id_field": "layout_id", "allowed_keys": ("capacity",)},
}


def _draft_ref(kind: str, id_field: str, draft_id: str, revision: int,
               draft: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    ref = {
        "kind": kind,
        "draft_id": draft_id,
        "revision": revision,
        "id": draft[id_field],
        "version": draft["version"],
        "content_digest": provenance["content_digest"],
    }
    if "base_ref" in provenance:
        ref["base_ref"] = deepcopy(provenance["base_ref"])
        ref["base_contract_digest"] = provenance["base_contract_digest"]
        ref["change_set"] = deepcopy(provenance["change_set"])
    return ref


def orchestrate_creation(requirement: dict[str, Any], resolution: dict[str, Any], *,
                         draft_id: str, revision: int,
                         registry: SchemaRegistry | None = None,
                         base: dict[str, Any] | None = None,
                         base_ref: dict[str, Any] | None = None,
                         change_set: dict[str, Any] | None = None,
                         design: dict[str, Any] | None = None,
                         schema: str | None = None, id_field: str | None = None,
                         kind: str | None = None,
                         allowed_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    """Execute the resolution branch as a creation action (pure; no repository/workflow write).

    The resolution must bind the same requirement_id/revision (a stale decision cannot drive a
    new requirement). reuse/instantiate select a usable candidate and return its published ref;
    derive/create require explicit trusted inputs and fail closed when missing — the orchestrator
    never invents a base, change-set or design. clarify/unsupported/search-incomplete stop.
    """
    registry = registry or SchemaRegistry()
    registry.validate("design-requirement", requirement)
    registry.validate("design-resolution-result", resolution)
    if resolution["requirement_id"] != requirement["requirement_id"]:
        raise ProtocolError("ORCHESTRATION_REQUIREMENT_MISMATCH", requirement["requirement_id"])
    if resolution["revision"] != requirement["revision"]:
        raise ProtocolError("ORCHESTRATION_REVISION_MISMATCH", requirement["requirement_id"])
    branch = resolution["branch"]
    result = deepcopy(resolution)

    if branch in ("reuse", "instantiate"):
        usable = [a for a in resolution["assessments"] if a["usable"]]
        if not usable:
            raise ProtocolError("ORCHESTRATION_NO_USABLE_CANDIDATE", branch)
        result["action"] = "return-published-ref"
        result["published_ref"] = deepcopy(usable[0]["candidate_ref"])
        return result

    if branch in _STOP_BRANCHES:
        result["action"] = "stop"
        return result

    if branch == "derive":
        if base is None or base_ref is None or change_set is None:
            raise ProtocolError("ORCHESTRATION_INPUT_MISSING",
                                "derive requires base, base_ref and change_set")
        if None in (schema, id_field, kind):
            raise ProtocolError("ORCHESTRATION_INPUT_MISSING",
                                "derive requires schema, id_field and kind")
        draft, provenance = derive_draft(
            base, change_set, schema=schema, id_field=id_field, kind=kind,
            allowed_keys=allowed_keys, base_ref=base_ref, draft_id=draft_id,
            revision=revision, registry=registry)
        result["action"] = "draft"
        result["draft_ref"] = _draft_ref(kind, id_field, draft_id, revision, draft, provenance)
        return result

    if branch == "create":
        if design is None or None in (schema, id_field, kind):
            raise ProtocolError("ORCHESTRATION_INPUT_MISSING",
                                "create requires design, schema, id_field and kind")
        draft = deepcopy(design)
        registry.validate(schema, draft)
        draft[id_field], draft["version"] = draft_identity(draft_id, revision)
        registry.validate(schema, draft)
        provenance = {"draft_id": draft_id, "revision": revision,
                      "content_digest": sha256_digest(draft)}
        result["action"] = "draft"
        result["draft_ref"] = _draft_ref(kind, id_field, draft_id, revision, draft, provenance)
        return result

    raise ProtocolError("ORCHESTRATION_BRANCH_UNSUPPORTED", branch)