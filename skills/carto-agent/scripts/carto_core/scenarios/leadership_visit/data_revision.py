"""leadership-visit data_revision_contract: scenario data-revision semantics (Design B).

The kernel keeps revision numbering, refs, drift gates, schema validation and the
state transition; this component supplies the scenario-specific data-revision
change vocabulary and the data-side hooks the kernel needs:

- ``rules``: ``route_legs`` invalidates the data evidence plus every compiled
  product (the kernel's ``compute_invalidation`` turns that into
  ``data_evidence_reusable: False`` and compile re-prepares);
- ``apply_changes``: rebinds ``itinerary_structure.source_ref.digest`` from the
  pending forward declaration to the actual evidence digest — the request-side
  change that separates the revision's product addressing (goal/intent stay
  untouched, so the intent input binding does not drift);
- ``evidence_uri``: the scenario-side path of the evidence document. The kernel
  resolves and digest-binds it without reading scenario body vocabulary;
- ``validate_evidence``: leg-level membership check of the proposal against the
  actual prepared evidence (scenario structure knowledge stays here).

v1 vocabulary is deliberately leg-level (via_points / strategy). Stops and
places additions are v2: they change the draft contract and the request's
forward-declaration digest, a different magnitude of request surgery.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...canonical import sha256_digest
from ...errors import ProtocolError

_COMPILATION_NODES = ("candidate", "preview", "preflight", "scene")


class RouteDataRevisionContract:
    """Scenario data-revision semantics (leg-level route re-planning)."""

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------

    def rules(self) -> dict[str, tuple[str, ...]]:
        return {
            "route_legs": ("data-evidence",) + _COMPILATION_NODES,
        }

    # ------------------------------------------------------------------
    # apply_changes
    # ------------------------------------------------------------------

    def apply_changes(self, request: dict[str, Any], changes: dict[str, Any],
                      evidence: dict[str, Any]) -> dict[str, Any]:
        """Bind the request to the actual evidence; no intent-relevant field moves.

        The revision upgrades ``itinerary_structure.source_ref.digest`` from a
        forward declaration (the draft digest, "data will be prepared") to a
        bound-facts declaration (the digest of the evidence the revision was
        approved against — the same digest the dependency graph records and
        compile re-verifies). That single field change is what separates the
        revision's product addressing: the kernel's immutable store keys the
        frontend document (and the design identity) by the request digest, so
        a revision whose request is byte-identical would collide with the
        previous design's create-once artifacts. Goal and intent stay
        untouched — a goal annotation would drift the intent input binding
        (MAP_INTENT_INPUT_DRIFT).
        """
        if set(changes) != {"route_legs"}:
            unknown = ",".join(sorted(set(changes) - {"route_legs"}))
            raise ProtocolError("LEADERSHIP_DATA_REVISION_UNKNOWN_KEY",
                                f"Unknown data-revision key: {unknown or '(empty)'}")
        legs = changes["route_legs"]
        seen: set[str] = set()
        for leg in legs:
            leg_id = leg.get("leg_id")
            if not leg_id or not isinstance(leg_id, str):
                raise ProtocolError("LEADERSHIP_DATA_REVISION_LEG_INVALID",
                                    "route_legs entries require a non-empty leg_id")
            if leg_id in seen:
                raise ProtocolError("LEADERSHIP_DATA_REVISION_LEG_INVALID",
                                    f"Duplicate leg_id in proposal: {leg_id}")
            seen.add(leg_id)
            via = leg.get("via_points")
            if not isinstance(via, list) or not via:
                raise ProtocolError("LEADERSHIP_DATA_REVISION_LEG_INVALID",
                                    f"leg '{leg_id}' requires at least one via point")
            for point in via:
                if (not isinstance(point, dict) or "lon" not in point
                        or "lat" not in point):
                    raise ProtocolError("LEADERSHIP_DATA_REVISION_LEG_INVALID",
                                        f"leg '{leg_id}' via points require lon/lat")
        revised = deepcopy(request)
        revised["itinerary_structure"]["source_ref"]["digest"] = sha256_digest(evidence)
        return revised

    # ------------------------------------------------------------------
    # evidence hooks
    # ------------------------------------------------------------------

    def evidence_uri(self, request: dict[str, Any]) -> str:
        """Scenario-side location of the prepared data evidence document."""
        return request["itinerary_structure"]["source_ref"]["uri"]

    def validate_evidence(self, evidence: dict[str, Any],
                          changes: dict[str, Any]) -> None:
        """Check the proposal's legs exist in the actual prepared evidence."""
        travel_ids = {leg.get("leg_id") for leg in evidence.get("legs", [])
                      if leg.get("kind") == "travel"}
        missing = [leg["leg_id"] for leg in changes.get("route_legs", [])
                   if leg.get("leg_id") not in travel_ids]
        if missing:
            raise ProtocolError("LEADERSHIP_DATA_REVISION_LEG_UNKNOWN",
                                f"Proposal references legs absent from the evidence: "
                                f"{sorted(missing)}")


DATA_REVISION_CONTRACT = RouteDataRevisionContract()
