"""Controlled template derivation (create-template entry ②, threshold-outside branch).

derive = base contract + restricted change-set -> NEW version + base_ref provenance, then the
full closed-schema validation is re-run. It is NOT a free rewrite: only explicitly allowed keys
may change, and the result must still validate. Retrieval/derivation live on the create side and
are separate from generate-map's exact-ref consumption; only the advisory matching primitive
(template_matching) is shared. Thresholds come from the versioned, business-reviewed policy.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def _bump_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def derive(base: dict[str, Any], change_set: dict[str, Any], *, schema: str,
           id_field: str, kind: str, allowed_keys: tuple[str, ...],
           registry: SchemaRegistry | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply a restricted change-set to a base contract; return (new_contract, base_ref).

    Rejects any change outside allowed_keys (no free rewrite). Bumps the patch version and
    re-validates against the closed schema. base_ref pins the exact base for provenance.
    """
    registry = registry or SchemaRegistry()
    registry.validate(schema, base)
    illegal = set(change_set) - set(allowed_keys)
    if illegal:
        raise ProtocolError("DERIVATION_KEY_FORBIDDEN", ",".join(sorted(illegal)))
    new = deepcopy(base)
    for key, value in change_set.items():
        new[key] = deepcopy(value)
    new["version"] = _bump_patch(base["version"])
    registry.validate(schema, new)
    base_ref = {"kind": kind, "id": base[id_field], "version": base["version"],
                "digest": sha256_digest(base)}
    return new, base_ref


def draft_identity(draft_id: str, revision: int) -> tuple[str, str]:
    """Project-scoped internal draft identity (design §7.1).

    ``draft-<id>`` / ``0.0.0-draft.r<revision>`` stay inside the project draft namespace and
    never register or preoccupy a business library identity. The prerelease version is a valid
    semanticVersion but is distinct from any published patch line.
    """
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ProtocolError("DRAFT_REVISION_INVALID", str(revision))
    return f"draft-{draft_id}", f"0.0.0-draft.r{revision}"


def derive_draft(base: dict[str, Any], change_set: dict[str, Any], *, schema: str,
                 id_field: str, kind: str, allowed_keys: tuple[str, ...],
                 base_ref: dict[str, Any], draft_id: str, revision: int,
                 registry: SchemaRegistry | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Draft derivation (design §7.1): restricted change-set -> project draft content.

    Unlike :func:`derive`, this does NOT bump a business patch version or reserve a library
    identity: the trusted orchestrator assigns a project draft_id/revision and the draft carries
    an internal draft identity (see :func:`draft_identity`). Identity keys (namespace/id/version)
    are ALWAYS forbidden in the change-set, even if listed in allowed_keys, so a change-set can
    never rewrite the library identity or approval fields. ``base_ref`` pins the exact published
    package reference (kind/id/version/digest); the bare base contract digest is recorded
    separately as ``base_contract_digest`` and never impersonates the package digest. The result
    is re-validated closed-world; no repository write, publication or approval happens here.
    """
    registry = registry or SchemaRegistry()
    registry.validate(schema, base)
    if not isinstance(change_set, dict) or not change_set:
        raise ProtocolError("DERIVATION_CHANGE_SET_EMPTY", kind)
    forbidden = {id_field, "namespace", "version"}
    illegal = (set(change_set) - set(allowed_keys)) | (set(change_set) & forbidden)
    if illegal:
        raise ProtocolError("DERIVATION_KEY_FORBIDDEN", ",".join(sorted(illegal)))
    new = deepcopy(base)
    for key, value in change_set.items():
        new[key] = deepcopy(value)
    new[id_field], new["version"] = draft_identity(draft_id, revision)
    registry.validate(schema, new)
    provenance = {
        "base_ref": deepcopy(base_ref),
        "base_contract_digest": sha256_digest(base),
        "change_set": deepcopy(change_set),
        "draft_id": draft_id,
        "revision": revision,
        "content_digest": sha256_digest(new),
    }
    return new, provenance