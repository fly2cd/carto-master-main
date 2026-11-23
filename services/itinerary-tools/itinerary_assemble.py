"""Itinerary assemble tool: merge geocode/route results into itinerary.json.

Re-homes the deterministic part of the old framework's itinerary.finalize
(scenarios-side business.py#finalize): validate the draft, verify every place
is geocoded and every travel leg routed, merge coordinates and road geometry,
and atomically write data/itinerary.json — WITHOUT the old revision state
machine: stage-to-stage drift protection is the kernel's G2
prepared-data-bundle digest binding (its designed equivalent).

The kernel remains the sole validation authority at compile
(data_preparer._from_contract); this tool guarantees the file it writes is in
the contract shape that compile accepts, and refuses otherwise.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from _service_utils import (
    ServiceError,
    dump_json_text,
    raw_file_digest,
    resolve_under_root,
    atomic_write_text,
)
from itinerary_check import _validate_draft

_DEFAULT_OUTPUT = "data/itinerary.json"


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message}


def _resolve_route_result(arguments: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """Return the route result document: inline object or digest-verified ref.

    Pass-by-reference keeps large road polylines out of the host LLM context:
    the file is loaded and its byte digest re-verified server-side, so a
    re-typed or tampered result cannot enter evidence unnoticed.
    """
    inline = arguments.get("route_result")
    ref = arguments.get("route_result_ref")
    if inline is not None and ref is not None:
        raise ServiceError(
            "INPUT_CONFLICT",
            "pass either route_result or route_result_ref, not both")
    if ref is not None:
        if not isinstance(ref, dict) or not isinstance(ref.get("uri"), str) \
                or not isinstance(ref.get("digest"), str):
            raise ServiceError("ROUTE_RESULT_REF_INVALID",
                               "route_result_ref must be {uri, digest}")
        ref_path = resolve_under_root(ref["uri"], root, must_exist=True)
        if raw_file_digest(ref_path) != ref["digest"]:
            raise ServiceError(
                "ROUTE_RESULT_DIGEST_MISMATCH",
                f"route result file {ref['uri']} does not match the declared digest")
        try:
            document = json.loads(ref_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ServiceError(
                "ROUTE_RESULT_INVALID",
                f"route result {ref['uri']} is not parseable JSON: {exc}") from exc
        return document
    return inline


def itinerary_assemble(arguments: dict[str, Any], ctx: dict[str, Path]) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        draft_path:     path to itinerary-draft.json (contract shape)
        geocode_result: the complete output of the final (user-confirmed)
                        geocode tool call — status must be "complete"
        route_result:   the complete inline output of the plan_route tool
                        (mutually exclusive with route_result_ref)
        route_result_ref: {uri, digest} reference to a persisted plan_route
                        result — loaded and byte-digest re-verified server-side
        output_path:    optional, default data/itinerary.json
    Output:
        status=assembled: {output_path, output_digest, counts, evidence}
        status=error:     refusal with a named code (nothing is written)
    """
    root = ctx["allowed_root"]
    draft_arg = arguments.get("draft_path", "")
    geocode_result = arguments.get("geocode_result")
    output_arg = arguments.get("output_path", _DEFAULT_OUTPUT)
    if not draft_arg:
        return _fail("DRAFT_PATH_REQUIRED", "draft_path is required")
    if not isinstance(geocode_result, dict) or geocode_result.get("status") != "complete":
        return _fail("GEOCODE_INCOMPLETE",
                     "geocode_result must be the complete (user-confirmed) geocode output")
    try:
        route_result = _resolve_route_result(arguments, Path(root))
    except ServiceError as exc:
        return _fail(exc.code, exc.message)
    if not isinstance(route_result, dict) or route_result.get("status") != "complete":
        return _fail("ROUTE_INCOMPLETE",
                     "route_result must be a complete plan_route output "
                     "(rerun plan_route for failed legs)")

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    try:
        draft_path = resolve_under_root(draft_arg, root, must_exist=True)
        output_path = resolve_under_root(output_arg, root)
    except ServiceError as exc:
        return _fail(exc.code, exc.message)
    if output_path == draft_path:
        return _fail("ITINERARY_OUTPUT_COLLISION",
                     "draft and final itinerary must be separate files")

    document = json.loads(draft_path.read_text(encoding="utf-8"))
    summary = _validate_draft(document, errors, warnings)
    if errors:
        return _fail("ITINERARY_DRAFT_INVALID",
                     f"draft has {len(errors)} error(s); run itinerary_check first — "
                     f"first error: {errors[0]['code']} at {errors[0]['path']}")

    # --- every draft place must carry a user-confirmed coordinate ------------
    resolved = {r.get("place_id"): r for r in geocode_result.get("resolved", [])}
    missing = [p.get("place_id") for p in document["places"]
               if p["place_id"] not in resolved]
    if missing:
        return _fail("ITINERARY_LOCATION_UNRESOLVED",
                     f"places without resolved coordinates: {missing} — "
                     "complete geocoding (ambiguity needs user confirmation) first")

    # --- every travel leg must carry a routed road geometry ------------------
    results = {r.get("leg_id"): r for r in route_result.get("results", [])}
    travel_legs = [leg for leg in document.get("legs", []) if leg.get("kind") == "travel"]
    unrouted = [leg.get("leg_id") for leg in travel_legs
                if results.get(leg.get("leg_id"), {}).get("status") != "complete"]
    if unrouted:
        return _fail("ITINERARY_ROAD_GEOMETRY_REQUIRED",
                     f"travel legs without routed geometry: {unrouted}")
    for leg in travel_legs:
        routed = results[leg["leg_id"]]
        geometry = routed.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "LineString" or len(coordinates) < 2:
            return _fail("ITINERARY_ROAD_GEOMETRY_REQUIRED",
                         f"leg '{leg['leg_id']}' geometry must be a LineString with "
                         "at least 2 points")
        # Fallback-contract gate: a straight-line engine result may only enter
        # evidence when the draft explicitly declares that leg as
        # route_mode=straight_line. A road_network leg routed by the straight
        # fallback is a degraded route (e.g. missing CARTO_AMAP_KEY) and must
        # never silently become map evidence.
        engine = routed.get("engine", "")
        route_mode = leg.get("route_mode", "road_network")
        if engine == "straight_line" and route_mode != "straight_line":
            return _fail("ROUTE_ENGINE_DEGRADED",
                         f"leg '{leg['leg_id']}' was routed by the straight-line "
                         f"fallback (engine=straight_line) but the draft declares "
                         f"route_mode={route_mode}; rerun plan_route after fixing "
                         "the routing failure (check CARTO_AMAP_KEY / network)")
        # Metrics gate: a real routing engine returning zero/absent distance
        # for a travel leg is a corrupted result, not evidence.
        distance_km = routed.get("distance_km")
        if engine != "straight_line" and (
                not isinstance(distance_km, (int, float)) or distance_km <= 0):
            return _fail("ROUTE_METRICS_INVALID",
                         f"leg '{leg['leg_id']}' has invalid distance_km="
                         f"{distance_km!r} from engine={engine!r}")

    # --- merge (deepcopy: the draft stays untouched on disk) -----------------
    data = copy.deepcopy(document)
    for place in data["places"]:
        place["location"] = dict(resolved[place["place_id"]]["location"])
    for leg in data["legs"]:
        if leg.get("kind") != "travel":
            continue
        routed = results[leg["leg_id"]]
        leg["geometry"] = routed["geometry"]
        leg["routing_metrics"] = {
            "distance_km": routed.get("distance_km"),
            "duration_min": routed.get("duration_min"),
            "engine": routed.get("engine"),
        }

    geometry_points = sum(len(leg["geometry"]["coordinates"])
                          for leg in data["legs"] if leg.get("geometry"))
    atomic_write_text(output_path, dump_json_text(data))
    output_digest = _file_digest(output_path)

    return {
        "status": "assembled",
        "output_path": str(output_path),
        "output_digest": output_digest,
        "counts": {
            "places": summary["places"],
            "stops": summary["stops"],
            "travel_legs": len(travel_legs),
            "geometry_points": geometry_points,
        },
        "evidence": [
            {"uri": str(draft_path), "digest": _file_digest(draft_path)},
            {"uri": str(output_path), "digest": output_digest},
        ],
    }


def _file_digest(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
