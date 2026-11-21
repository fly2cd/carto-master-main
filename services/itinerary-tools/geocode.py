"""Geocode tool: place names → WGS-84 coordinates, with ambiguity detection.

Calls the Amap geocoding API (or returns needs_input when ambiguous).
No old-framework dependencies — uses the copied AmapClient modules directly.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from amap_client.coord_converter import CoordConverter
from amap_client.geocoder_amap import AmapGeocoder


async def _geocode_async(places: list[dict[str, Any]],
                          confirmations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    amap_key = os.environ.get("CARTO_AMAP_KEY", "")
    geocoder = AmapGeocoder(amap_key=amap_key)
    async with httpx.AsyncClient(trust_env=False, verify=True) as client:
        points = await geocoder.geocode_batch(
            client,
            [{"name": p["name"], "city": p.get("city", "")} for p in places],
            convert_to_wgs84=True,
        )
    resolved = []
    for point, place in zip(points, places):
        resolved.append({
            "place_id": place.get("place_id", ""),
            "name": place["name"],
            "location": {"lon": point.get("lon", 0), "lat": point.get("lat", 0)},
            "formatted_address": point.get("address", ""),
        })
    return {"status": "complete", "resolved": resolved}


async def _geocode_with_ambiguity(places: list[dict[str, Any]]) -> dict[str, Any]:
    """Geocode with full ambiguity checking via AmbiguityChecker."""
    amap_key = os.environ.get("CARTO_AMAP_KEY", "")
    geocoder = AmapGeocoder(amap_key=amap_key)

    from amap_client.ambiguity_checker import (
        Candidate, MultiGeoAmbiguityError, check_amap_pois,
    )

    locations = [{"name": p["name"], "city": p.get("city", "")} for p in places]
    async with httpx.AsyncClient(trust_env=False, verify=True) as client:
        try:
            points = await geocoder.geocode_batch(client, locations, convert_to_wgs84=True)
            resolved = []
            for point, place in zip(points, places):
                resolved.append({
                    "place_id": place.get("place_id", ""),
                    "name": place["name"],
                    "location": {"lon": point.get("lon", 0), "lat": point.get("lat", 0)},
                    "formatted_address": point.get("address", ""),
                })
            return {"status": "complete", "resolved": resolved}
        except MultiGeoAmbiguityError as exc:
            resolved = []
            for point, place in zip(exc.partial_points, places):
                if point:
                    resolved.append({
                        "place_id": place.get("place_id", ""),
                        "name": place["name"],
                        "location": {"lon": point.get("lon", 0), "lat": point.get("lat", 0)},
                        "formatted_address": point.get("address", ""),
                    })
            ambiguous = []
            for report in exc.items:
                candidates = []
                for cand in report.candidates:
                    lon, lat = cand.lon, cand.lat
                    converted = CoordConverter.gcj02_to_wgs84(lon, lat)
                    candidates.append({
                        "location": {"lon": converted[0], "lat": converted[1]},
                        "formatted_address": cand.address,
                        "name": cand.name,
                    })
                place_id = next(
                    (p.get("place_id", "") for p in places if p["name"] == report.input_name),
                    report.input_name,
                )
                ambiguous.append({
                    "place_id": place_id,
                    "name": report.input_name,
                    "block_reason": report.block_reason,
                    "candidates": candidates,
                })
            return {"status": "needs_input", "resolved": resolved, "ambiguous": ambiguous}


def geocode(arguments: dict[str, Any]) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        places: [{"place_id", "name", "city"}]
        confirmations: optional [{"place_id", "location": {"lon", "lat"}, "user_confirmed": true}]
    Output:
        status=complete: {"resolved": [...]}
        status=needs_input: {"resolved": [...], "ambiguous": [...]}
    """
    places = arguments.get("places", [])
    if not places:
        return {"status": "error", "message": "places is required"}

    confirmations = arguments.get("confirmations")
    if confirmations:
        # User confirmed — return confirmed coordinates directly
        resolved = []
        for conf in confirmations:
            resolved.append({
                "place_id": conf.get("place_id", ""),
                "location": conf["location"],
                "user_confirmed": True,
            })
        return {"status": "complete", "resolved": resolved}

    # First call: try with ambiguity detection
    try:
        return asyncio.run(_geocode_with_ambiguity(places))
    except Exception as exc:
        error_msg = str(exc)
        if "GeocodingProviderError" in type(exc).__name__ or "provider" in error_msg.lower():
            return {
                "status": "error",
                "message": "Geocoding service unavailable (no API key or network). "
                           "Set CARTO_AMAP_KEY environment variable, or provide "
                           "confirmations with coordinates directly.",
            }
        return {"status": "error", "message": error_msg[:200]}
