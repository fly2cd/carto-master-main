"""P5-5 generation connection: assemble an explicit selection into generate-request
component selection (segment_refs), with the retrieval resolution attached as evidence.

The retrieval result is advisory evidence only; it never becomes the execution authority.
This helper turns an EXPLICIT user/LLM selection (chosen refs + parameters) into the
closed segment_refs structure consumed by the P4 load boundary. It does not run generate
(that still requires intake/G1); it only prepares the request fragment fail-closed.
"""
from __future__ import annotations

from typing import Any

from ..errors import ProtocolError

_KIND_TO_SEGMENT = {"map-style": "style", "map-layout": "layout"}


def assemble_segment_refs(selections: list[dict[str, Any]]) -> dict[str, Any]:
    """Build closed segment_refs from an explicit selection.

    Each selection must be an exactly pinned ref of an admitted segment kind. Duplicate
    segment ownership and unpinned/unknown-kind refs are refused (single effective source).
    """
    if not isinstance(selections, list) or not selections:
        raise ProtocolError("SELECTION_REQUIRED", "at least one explicit selection is required")
    refs: dict[str, Any] = {}
    for sel in selections:
        kind = sel.get("kind")
        segment = _KIND_TO_SEGMENT.get(kind)
        if segment is None:
            raise ProtocolError("SEGMENT_KIND_UNSUPPORTED", str(kind))
        if segment in refs:
            raise ProtocolError("SEGMENT_DOUBLE_SOURCED", segment)
        if not all(sel.get(k) for k in ("id", "version", "digest")):
            raise ProtocolError("SEGMENT_REF_UNPINNED", str(kind))
        refs[segment] = {"kind": kind, "id": sel["id"], "version": sel["version"],
                         "digest": sel["digest"]}
    return refs


def attach_resolution_evidence(request: dict[str, Any], resolution: dict[str, Any],
                               selected_refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach the retrieval resolution as evidence (not authority) to a generate request.

    The selected refs must be a subset of the resolution's assessed candidates (the user
    chose among retrieved options); a selection outside the retrieved set is refused so
    the evidence chain stays honest. The request's segment_refs is set from the selection.
    """
    assessed = {(_ref_key(a["candidate_ref"])) for a in resolution.get("assessments", [])}
    for sel in selected_refs:
        if _ref_key(sel) not in assessed:
            raise ProtocolError("SELECTION_OUTSIDE_RETRIEVAL", _ref_key(sel))
    request = dict(request)
    request["segment_refs"] = assemble_segment_refs(selected_refs)
    request["retrieval_evidence"] = {
        "requirement_id": resolution["requirement_id"],
        "revision": resolution["revision"],
        "branch": resolution["branch"],
    }
    return request


def _ref_key(ref: dict[str, Any]) -> tuple:
    return (ref.get("kind"), ref.get("id"), ref.get("version"), ref.get("digest"))