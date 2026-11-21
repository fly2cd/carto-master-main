"""Plan route tool: origin+destination → road geometry, with three-tier fallback.

Plan A: Dual-graph offline (local road network, no network/key required)
Plan B: Amap online routing (requires CARTO_AMAP_KEY + network)
Plan C: Straight-line fallback (only when both fail and allowed)

Uses the copied RouteEngine which implements the full fallback logic.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from routing.route_engine import RouteEngine


def plan_route(arguments: dict[str, Any]) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        legs: [{"leg_id", "origin": {"lon", "lat"}, "destination": {"lon", "lat"},
                "via_points": optional, "strategy": optional}]
        allow_straight_line: optional bool (default false)
    Output:
        status=complete: {"results": [{"leg_id", "geometry", "distance_km", "duration_min", "engine"}]}
    """
    legs = arguments.get("legs", [])
    if not legs:
        return {"status": "error", "message": "legs is required"}

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

            results.append({
                "leg_id": leg.get("leg_id", ""),
                "status": "complete",
                "geometry": {"type": "LineString", "coordinates": polyline},
                "distance_km": round(distance_m / 1000, 2),
                "duration_min": round(duration_s / 60, 1),
                "engine": engine_name,
            })
        except Exception as exc:
            results.append({
                "leg_id": leg.get("leg_id", ""),
                "status": "failed",
                "message": str(exc)[:200],
            })

    all_ok = all(r.get("status") == "complete" for r in results)
    return {"status": "complete" if all_ok else "partial", "results": results}
