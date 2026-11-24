"""Plan route tool: origin+destination → road geometry, with three-tier fallback.

Plan A: Dual-graph offline (local road network, no network/key required)
Plan B: Amap online routing (requires CARTO_AMAP_KEY + network)
Plan C: Straight-line fallback (only when both fail and explicitly allowed)

Uses the copied RouteEngine which implements the full fallback logic.

Result reference protocol (zero-script host integration): when a ctx with
allowed_root is supplied (the MCP server always does), the complete result is
atomically persisted under route-results/ and returned as {uri, digest} in
addition to the inline results. Large polylines never need to round-trip
through the host LLM context: itinerary_assemble accepts the reference and
re-verifies the byte digest itself. ``base_result_ref`` moves the incremental
merge server-side too — the host passes only the changed legs plus the
previous result's reference; unchanged legs are carried from the persisted
file verbatim (no re-routing, byte-stable reuse).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from routing.route_engine import RouteEngine
from _service_utils import (
    ServiceError,
    atomic_write_text,
    raw_file_digest,
    resolve_under_root,
)

_DIGEST_PATTERN = "sha256:"
_ROUTE_RESULTS_DIR = "route-results"


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message}


def _load_base_result(base_ref: Any, root: Path) -> list[dict[str, Any]]:
    """Resolve and digest-verify a base result reference; return its results."""
    if not isinstance(base_ref, dict) or not isinstance(base_ref.get("uri"), str) \
            or not isinstance(base_ref.get("digest"), str):
        raise ServiceError("ROUTE_RESULT_REF_INVALID",
                           "base_result_ref must be {uri, digest}")
    try:
        ref_path = resolve_under_root(base_ref["uri"], root, must_exist=True)
    except ServiceError:
        raise
    if raw_file_digest(ref_path) != base_ref["digest"]:
        raise ServiceError(
            "ROUTE_RESULT_DIGEST_MISMATCH",
            f"base result file {base_ref['uri']} does not match the declared digest")
    try:
        document = json.loads(ref_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ServiceError("BASE_RESULT_INVALID",
                           f"base result {base_ref['uri']} is not parseable JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise ServiceError("BASE_RESULT_INVALID",
                           f"base result {base_ref['uri']} has no results list")
    return document["results"]


def _persist(root: Path, response: dict[str, Any]) -> dict[str, str]:
    """Atomically persist the result under route-results/; return the ref."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / _ROUTE_RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"plan-{stamp}-{len(response['results'])}legs.json"
    counter = 0
    while path.exists():  # same-microsecond collision: append a counter
        counter += 1
        path = directory / f"plan-{stamp}-{counter}-{len(response['results'])}legs.json"
    document = {"status": response["status"], "results": response["results"]}
    atomic_write_text(path, json.dumps(document, ensure_ascii=False, indent=2))
    uri = path.resolve().relative_to(root.resolve()).as_posix()
    return {"uri": uri, "digest": raw_file_digest(path)}


def plan_route(arguments: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        legs: [{"leg_id", "origin": {"lon", "lat"}, "destination": {"lon", "lat"},
                "via_points": optional, "strategy": optional}] — only the legs
                that need (re-)routing when base_result_ref is supplied
        allow_straight_line: optional bool (default false)
        base_result_ref: optional {uri, digest} — previous persisted result;
            legs absent from this call are carried over verbatim
    Output:
        status=complete/partial: {"results": [...],
                                  "result_ref": {"uri", "digest"}}  (ref when ctx present)
        status=error: named refusal (nothing routed, nothing written)
    """
    legs = arguments.get("legs", [])
    if not legs:
        return _fail("LEGS_REQUIRED", "legs is required")

    root = None
    if ctx is not None and ctx.get("allowed_root") is not None:
        root = Path(ctx["allowed_root"])

    base_results: list[dict[str, Any]] = []
    base_ref = arguments.get("base_result_ref")
    if base_ref is not None:
        if root is None:
            return _fail("CTX_REQUIRED",
                         "base_result_ref needs the allowed-root context (ctx)")
        try:
            base_results = _load_base_result(base_ref, root)
        except ServiceError as exc:
            return _fail(exc.code, exc.message)

    allow_straight = arguments.get("allow_straight_line", False)
    engine = RouteEngine(allow_online=True)

    results = []
    for leg in legs:
        origin = leg.get("origin", {})
        destination = leg.get("destination", {})
        if "lon" not in origin or "lon" not in destination:
            results.append({
                "leg_id": leg.get("leg_id", ""),
                "status": "error",
                "message": "origin and destination must have lon/lat coordinates",
            })
            continue

        try:
            t0 = time.perf_counter()
            result = asyncio.run(engine.reroute_leg(
                origin=origin,
                destination=destination,
                via_points=leg.get("via_points"),
                strategy=leg.get("strategy", "2"),
            ))
            print(f"[plan_route] {leg.get('leg_id', '')} engine={result.get('engine', '?')} "
                  f"{time.perf_counter() - t0:.1f}s", file=sys.stderr)

            polyline = result.get("polyline", [])
            distance_m = result.get("distance", 0)
            duration_s = result.get("duration", 0)

            if not polyline or len(polyline) < 2:
                if allow_straight:
                    polyline = [[origin["lon"], origin["lat"]],
                                [destination["lon"], destination["lat"]]]
                    engine_name = "straight_line"
                else:
                    results.append({
                        "leg_id": leg.get("leg_id", ""),
                        "status": "failed",
                        "message": "no route found; set allow_straight_line=true for fallback",
                    })
                    continue
            else:
                engine_name = result.get("engine", "unknown")

            # Unified fallback-contract gate: a straight-line engine result is a
            # degraded route. allow_straight_line=false must mean that NO
            # straight line — self-built or engine-returned — survives as
            # complete, so downstream evidence can never be silently polluted.
            if engine_name == "straight_line" and not allow_straight:
                results.append({
                    "leg_id": leg.get("leg_id", ""),
                    "status": "failed",
                    "message": ("routing degraded to straight_line with "
                                "allow_straight_line=false; fix the root cause "
                                "(see engine failure detail) or explicitly pass "
                                "allow_straight_line=true"),
                })
                continue

            results.append({
                "leg_id": leg.get("leg_id", ""),
                "status": "complete",
                "geometry": {"type": "LineString", "coordinates": polyline},
                "distance_km": round(distance_m / 1000, 2),
                "duration_min": round(duration_s / 60, 1),
                "engine": engine_name,
                **({"degraded": True} if engine_name == "straight_line" else {}),
            })
        except Exception as exc:
            results.append({
                "leg_id": leg.get("leg_id", ""),
                "status": "failed",
                "message": str(exc)[:200],
            })

    # Server-side incremental merge: legs rerouted by this call replace their
    # base entries; every other base leg is carried over verbatim (no
    # re-routing, byte-stable reuse). Deterministic order by leg_id.
    if base_results:
        changed_ids = {r.get("leg_id") for r in results}
        results = ([r for r in base_results if r.get("leg_id") not in changed_ids]
                   + results)
        results.sort(key=lambda r: str(r.get("leg_id", "")))

    all_ok = all(r.get("status") == "complete" for r in results)
    response = {"status": "complete" if all_ok else "partial", "results": results}
    if root is not None:
        response["result_ref"] = _persist(root, response)
    return response
