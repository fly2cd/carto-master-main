# -*- coding: utf-8 -*-
"""
route_engine.py — Single-leg routing with three-tier fallback.

Plan A (Dual Graph offline) -> Plan B (Amap online) -> Straight-line fallback.
Used by RoutePlanningHandler via ToolGateway.
"""

from __future__ import annotations
import logging
import asyncio
import os
from typing import Any

import httpx

from amap_client.geocoder_amap import AmapGeocoder


class RouteEngine:
    """Single-leg routing engine with Plan A -> Plan B -> straight-line fallback."""

    def __init__(self, amap_key: str = "",
                 enable_dual_graph: bool = True,
                 dual_graph_city: str = "Zhejiang",
                 dual_graph_geojson: str = "", allow_online: bool = True, cache_dir=None):
        self.amap_key = amap_key or os.environ.get("CARTO_AMAP_KEY", "")
        self.enable_dual_graph = enable_dual_graph
        self.allow_online = allow_online
        self.cache_dir = cache_dir
        self.dual_graph_city = dual_graph_city
        self.dual_graph_geojson = dual_graph_geojson or ""
        self._dual_graph_engine = None

    # ── lazy engine getters ──────────────────────────────────────

    def _get_geocoder(self):
        return AmapGeocoder(amap_key=self.amap_key)

    def _get_dual_graph_engine(self, clip_bbox=None):
        """Lazy-load Dual Graph engine (Plan A). Returns None on failure."""
        if not self.enable_dual_graph:
            return None

        try:
            from .router_dual_graph import create_dual_graph_engine
        except ImportError as e:
            logging.getLogger(__name__).debug("route_engine._get_dual_graph_engine.event")
            return None

        self._dual_graph_engine = create_dual_graph_engine(
            city_name=self.dual_graph_city,
            switch_penalty=1000.0,
            geojson_path=self.dual_graph_geojson or None,
            clip_bbox=clip_bbox,
            cache_dir=self.cache_dir,
        )
        return self._dual_graph_engine

    def _get_plan_b_router(self):
        """Create Amap router (Plan B)."""
        try:
            from .router_amap import AmapRouter
        except ImportError as e:
            logging.getLogger(__name__).debug("route_engine._get_plan_b_router.event")
            return None
        return AmapRouter(amap_key=self.amap_key)

    # ── public API ────────────────────────────────────────────────

    async def reroute_leg(self, origin: dict, destination: dict,
                          via_points: list[dict] | None = None,
                          strategy: str = "2") -> dict[str, Any]:
        """
        Re-plan a single leg: Plan A first -> Plan B fallback.

        Via points with name-only format are geocoded to coordinates first,
        then passed to dual graph. Falls back to Plan B when dual graph fails
        or origin/destination are name-only.

        Args:
            origin: {"lon": 120.1, "lat": 30.2} or {"name": "地点", "city": "城市"}
            destination: same format
            via_points: list of via points
            strategy: route strategy (Amap 0-6)

        Returns:
            {"fromName": str, "toName": str, "polyline": [...], "distance": int, "duration": int, "viaPoints": [...]}
        """
        from amap_client.coord_converter import CoordConverter

        async with httpx.AsyncClient(trust_env=False, verify=True) as client:
            # ── Resolve via points: name -> WGS-84 coordinates ──
            resolved_via_points = via_points or []
            via_coords = None

            if via_points:
                has_name_only = any("lon" not in p for p in via_points)
                if has_name_only:
                    geocoder = self._get_geocoder()
                    resolved = []
                    for p in via_points:
                        if "lon" in p:
                            resolved.append({
                                "lon": float(p["lon"]), "lat": float(p["lat"]),
                                "name": p.get("name", ""),
                            })
                        else:
                            gcj_lon, gcj_lat, addr = await geocoder.geocode_single(
                                client, p.get("name", ""), p.get("city", "")
                            )
                            wgs_lon, wgs_lat = CoordConverter.gcj02_to_wgs84(gcj_lon, gcj_lat)
                            resolved.append({"lon": wgs_lon, "lat": wgs_lat, "name": addr})
                            logging.getLogger(__name__).debug("route_engine.reroute_leg.event")
                    resolved_via_points = resolved
                via_coords = [(float(p["lon"]), float(p["lat"])) for p in resolved_via_points]

            # ── 1. Plan A: Dual Graph (origin/destination must be coordinate format) ──
            if self.enable_dual_graph and "lon" in origin and "lon" in destination:
                origin_coord = (float(origin["lon"]), float(origin["lat"]))
                dest_coord = (float(destination["lon"]), float(destination["lat"]))

                engine = self._get_dual_graph_engine()
                if engine:
                    try:
                        result = engine.route_leg(origin_coord, dest_coord, via_points=via_coords)
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "route_engine.reroute_leg.dual_graph_failed", exc_info=True
                        )
                        result = None
                    if result and len(result.get("polyline", [])) >= 2:
                        logging.getLogger(__name__).debug("route_engine.reroute_leg.event")
                        return {
                            "fromName": origin.get("name", ""),
                            "toName": destination.get("name", ""),
                            "polyline": result["polyline"],
                            "distance": result["distance"],
                            "duration": result["duration"],
                            "viaPoints": resolved_via_points,
                            "engine": "dual_graph",
                        }
                    logging.getLogger(__name__).debug("route_engine.reroute_leg.event")

            if not self.allow_online:
                return {'fromName': origin.get('name', ''), 'toName': destination.get('name', ''),
                        'polyline': [[origin['lon'], origin['lat']], [destination['lon'], destination['lat']]],
                        'distance': 0, 'duration': 0, 'engine': 'straight_line'}

            # ── 2. Plan B: Amap online ──
            plan_b = self._get_plan_b_router()
            geocoder = self._get_geocoder()

            result = await plan_b.reroute_leg_with_resolve(
                client=client,
                origin=origin,
                destination=destination,
                via_points=via_points,
                strategy=strategy,
                geocoder=geocoder,
            )

        logging.getLogger(__name__).debug("route_engine.reroute_leg.event")
        return result
