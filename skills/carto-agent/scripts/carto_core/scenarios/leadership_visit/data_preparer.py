"""leadership-visit data_preparer: itinerary normalization and GeoJSON export.

Migrates the normalize_itinerary logic from the old framework's
workflow/itinerary_structure.py. Constructor matches DataPreparerFactory Protocol:
(path_guard, project_root, output_root, registry=None) -> DataPreparer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...canonical import sha256_digest
from ...errors import ProtocolError

_VALID_ROUTE_MODES = frozenset({
    "road_network", "provided_geometry", "schematic", "straight_line",
})
_VALID_MAP_ROLES = frozenset({"origin", "visit", "waypoint", "destination"})
_WGS84 = {"authority": "EPSG", "code": "4326"}


def _iter_points(value: Any):
    """Yield [x, y] pairs from arbitrarily nested GeoJSON coordinates."""
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]):
        yield value[:2]
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_points(item)


def _collection_bbox(collection: dict[str, Any]) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        for x, y in _iter_points(geometry.get("coordinates", [])):
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]

# Old itinerary-structure contract (the MCP itinerary service's finalize output):
# places/stops are separate entities joined by place_id, activities carry the
# morning/afternoon period, legs carry document/routing display metrics and the
# real road geometry. The adapter flattens that contract into the simplified
# preparation format this scenario consumes.
_PERIOD_LABELS = {"morning": "上午", "afternoon": "下午"}
_PRIMARY_ACTIVITY_TYPES = ("visit", "meeting")


def _looks_like_contract(raw: dict[str, Any]) -> bool:
    return isinstance(raw.get("places"), list) and bool(raw.get("places"))


def _from_contract(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten the itinerary-structure contract into the simplified format.

    - place_id references resolve to names and WGS84 locations;
    - consecutive stays (kind=stay legs, same place) merge into one display stop;
    - the display metrics (distance/duration) come from the incoming travel leg,
      selected by its metric_source (document vs routing);
    - period (morning/afternoon) becomes the itinerary group and display label;
    - travel legs keep their road geometry and route_mode.
    """
    places = {p["place_id"]: p for p in raw["places"]}
    stops = raw.get("stops", [])
    legs = raw.get("legs", [])
    if not stops or not places:
        raise ProtocolError("LEADERSHIP_ITINERARY_EMPTY",
                            "Contract itinerary must contain places and stops")
    input_crs = raw.get("input_crs")
    if input_crs and str(input_crs).upper() not in {"EPSG:4326", "4326", "WGS84"}:
        raise ProtocolError("LEADERSHIP_ITINERARY_CRS",
                            f"input_crs '{input_crs}' — only EPSG:4326 is admitted")
    by_id: dict[str, dict[str, Any]] = {}
    for stop in stops:
        sid = stop.get("stop_id", "")
        if sid in by_id:
            raise ProtocolError("LEADERSHIP_ITINERARY_STOP_DUPLICATE", sid)
        place = places.get(stop.get("place_id"))
        if place is None:
            raise ProtocolError("LEADERSHIP_ITINERARY_PLACE_UNKNOWN", str(stop.get("place_id")))
        if not place.get("location"):
            raise ProtocolError("LEADERSHIP_ITINERARY_LOCATION_UNRESOLVED",
                                f"Place '{place.get('name', place['place_id'])}' has no resolved "
                                "location — complete geocoding.resolve before cartography")
        by_id[sid] = stop
    # Merge consecutive stays: a stay leg joins two stops at the same place.
    stay_next: dict[str, str] = {}
    for leg in legs:
        if leg.get("kind") == "stay":
            stay_next[leg.get("from_stop_id", "")] = leg.get("to_stop_id", "")
    groups: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for stop in stops:
        sid = stop.get("stop_id", "")
        if sid in consumed:
            continue
        group = {"ids": [sid], "activities": list(stop.get("activities", [])),
                 "arrival_time": stop.get("arrival_time")}
        consumed.add(sid)
        current = sid
        while current in stay_next:
            nxt = stay_next[current]
            if nxt in consumed or nxt not in by_id:
                break
            merged = by_id[nxt]
            group["ids"].append(nxt)
            group["activities"].extend(merged.get("activities", []))
            if merged.get("arrival_time"):
                group["arrival_time"] = merged["arrival_time"]
            consumed.add(nxt)
            current = nxt
        groups.append(group)
    travel_legs = [leg for leg in legs if leg.get("kind") == "travel"]
    incoming = {leg.get("to_stop_id", ""): leg for leg in travel_legs}

    def selected_metrics(leg: dict[str, Any] | None) -> dict[str, Any]:
        if not leg:
            return {}
        source = leg.get("metric_source")
        metrics = (leg.get("document_metrics") if source == "document"
                   else leg.get("routing_metrics") if source == "routing" else None)
        if not metrics:
            return {}
        return {"distance_km": metrics.get("distance_km"),
                "duration_min": metrics.get("duration_min")}

    date_label = raw.get("date_label", "")
    out_stops: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        first = by_id[group["ids"][0]]
        place = places[first["place_id"]]
        activities = group["activities"]
        primary = next((a for a in activities if a.get("type") in _PRIMARY_ACTIVITY_TYPES), None)
        reference = primary or (activities[-1] if activities else {})
        period = reference.get("period") or ""
        out_stops.append({
            "stop_id": group["ids"][0],
            "name": place.get("name", ""),
            "formatted_address": place.get("formatted_address", "") or place.get("address", ""),
            "visit_order": index + 1,
            "location": dict(place["location"]),
            "stop_type": reference.get("type", "visit"),
            "itinerary_group": period or "default",
            "visit_period": _PERIOD_LABELS.get(period, ""),
            "visit_date": date_label,
            "arrival_time": group.get("arrival_time") or "",
            "activities": [{"type": reference.get("type", "visit")}],
            **selected_metrics(incoming.get(group["ids"][0])),
        })
    representative: dict[str, str] = {}
    for group in groups:
        for sid in group["ids"]:
            representative[sid] = group["ids"][0]
    out_legs: list[dict[str, Any]] = []
    for leg in travel_legs:
        out_legs.append({
            "leg_id": leg.get("leg_id", ""),
            "kind": "travel",
            "from_stop_id": representative.get(leg.get("from_stop_id", ""), leg.get("from_stop_id", "")),
            "to_stop_id": representative.get(leg.get("to_stop_id", ""), leg.get("to_stop_id", "")),
            "route_mode": leg.get("route_mode") or "straight_line",
            "geometry": leg.get("geometry"),
            "itinerary_group": leg.get("period") or "default",
        })
    normalized = dict(raw)
    normalized["stops"] = out_stops
    normalized["legs"] = out_legs
    return normalized


class RouteDataPreparer:
    """Prepare itinerary data: normalize, validate, export GeoJSON, freeze as PreparedDataBundle."""

    def __init__(self, path_guard: Any, project_root: Path, output_root: Path,
                 registry: Any = None) -> None:
        self._path_guard = path_guard
        self._project_root = project_root
        self._output_root = output_root
        self._registry = registry

    # ------------------------------------------------------------------
    # prepare — the framework entry point
    # ------------------------------------------------------------------

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        itin = request["itinerary_structure"]
        source_ref = itin["source_ref"]
        # Resolve and load the source itinerary file
        source_path = self._path_guard.resolve(
            source_ref.get("uri", ""), base_root=self._project_root, must_exist=False)
        if not source_path.is_file():
            # Check if the request declared pending preparation (G1 后 MCP 工具链)
            pending = any(b.get("pending") for b in request.get("source_bindings", []))
            if pending:
                raise ProtocolError(
                    "LEADERSHIP_ITINERARY_NOT_PREPARED",
                    "Itinerary data has not been prepared yet. Complete the MCP tool chain "
                    "(geocode + plan_route, then hand-assemble itinerary.json) after G1, "
                    "then re-enter compile. Do NOT edit generate-request.yaml — the request "
                    "is fingerprint-locked at intake. "
                    "See workflows/generate-map/leadership-visit-data-prep.md")
            raise ProtocolError(
                "LEADERSHIP_ITINERARY_NOT_FOUND",
                f"Itinerary file not found: {source_ref.get('uri', '')}")
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        # Normalize: validate structure, merge consecutive stays, assign map_role
        normalized = self._normalize_itinerary(raw)
        # Export GeoJSON for route-stops and route-line
        stops_gj = self._export_stops_geojson(normalized)
        route_gj = self._export_route_geojson(normalized)
        # Write normalized outputs
        output_dir = self._output_root / "prepared"
        output_dir.mkdir(parents=True, exist_ok=True)
        norm_path = output_dir / "itinerary-normalized.json"
        stops_path = output_dir / "route-stops.geojson"
        route_path = output_dir / "route-line.geojson"
        norm_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        stops_path.write_text(json.dumps(stops_gj, ensure_ascii=False), encoding="utf-8")
        route_path.write_text(json.dumps(route_gj, ensure_ascii=False), encoding="utf-8")
        # Build the PreparedDataBundle on the shared kernel contract
        # (prepared-data-bundle schema). The revision reuse gate re-validates the
        # stored bundle against that schema, so the scenario must emit the
        # protocol shape — a scenario-local bundle shape is a latent reuse-path
        # failure (first compile never validates, reuse does).
        fields: dict[str, dict[str, str]] = {}
        for binding in request.get("source_bindings", []):
            role = binding.get("role")
            fields[role] = {item["semantic_role"]: item["source_field"]
                            for item in binding.get("field_bindings", [])}
        dataset_ref = dict(source_ref)
        stops_ref = self._prepared_ref(stops_gj, stops_path)
        route_ref = self._prepared_ref(route_gj, route_path)
        bundle = {
            "schema_version": 1,
            "bundle_id": f"leadership-visit-{request['run_id']}",
            "task_ref": request_ref,
            "datasets": [dataset_ref],
            "transformations": [],
            "tool_receipts": [],
            "quality_evidence": [stops_ref, route_ref],
            "open_issues": [],
            "role_bindings": [
                {
                    "data_type": "vector", "source_id": "route-stops", "role": "route-stops",
                    "dataset_ref": dataset_ref, "prepared_ref": stops_ref,
                    "geometry_types": ["point"],
                    "feature_count": len(stops_gj.get("features", [])),
                    "bbox": _collection_bbox(stops_gj), "crs": dict(_WGS84),
                    "semantic_fields": fields.get("route-stops", {}),
                },
                {
                    "data_type": "vector", "source_id": "route-line", "role": "route-line",
                    "dataset_ref": dataset_ref, "prepared_ref": route_ref,
                    "geometry_types": ["linestring"],
                    "feature_count": len(route_gj.get("features", [])),
                    "bbox": _collection_bbox(route_gj), "crs": dict(_WGS84),
                    "semantic_fields": fields.get("route-line", {}),
                },
            ],
            "summary": {"data_nature": "itinerary"},
        }
        bundle["digest"] = sha256_digest(bundle)
        if self._registry is not None:
            self._registry.validate("prepared-data-bundle", bundle)
        # Kernel contract (workflow.map_generation): prepare() returns a dict with a
        # "bundle" key (plus the request ref), matching the general scenario preparers.
        return {"bundle": bundle, "request_ref": request_ref}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _prepared_ref(self, document: dict[str, Any], path: Path) -> dict[str, str]:
        # POSIX separators: the uri is protocol data (digest-bound refs and the
        # scene's derived bundle uri are joined with posixpath downstream).
        return {"id": "vector-prepared-data", "version": "1.0.0",
                "digest": sha256_digest(document),
                "uri": path.relative_to(self._project_root).as_posix()}

    # ------------------------------------------------------------------
    # normalize_itinerary — core business logic (migrated from old framework)
    # ------------------------------------------------------------------

    def _normalize_itinerary(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate places/stops/legs, merge consecutive stays, assign map_role.

        Accepts both input shapes:
        - the simplified preparation format (stops carry name/location directly);
        - the old itinerary-structure contract (MCP finalize output: places +
          stops joined by place_id, activities with periods, display metrics on
          legs) — flattened by ``_from_contract`` first.
        """
        if _looks_like_contract(raw):
            raw = _from_contract(raw)
        stops = raw.get("stops", [])
        if not stops:
            raise ProtocolError("LEADERSHIP_ITINERARY_EMPTY",
                                "Itinerary must contain at least one stop")
        # Validate visit_order: consecutive from 1, no duplicates, no gaps
        orders = [s.get("visit_order", 0) for s in stops]
        if sorted(orders) != list(range(1, len(stops) + 1)):
            raise ProtocolError("LEADERSHIP_ITINERARY_VISIT_ORDER",
                                "visit_order must be consecutive from 1 with no gaps or duplicates")
        # Assign map_role
        normalized_stops = []
        for i, stop in enumerate(stops):
            stop = dict(stop)
            if i == 0:
                stop["map_role"] = "origin"
            elif i == len(stops) - 1:
                stop["map_role"] = "destination"
            else:
                # Determine if this is a visit or waypoint
                activities = stop.get("activities", [])
                has_visit = any(a.get("type") in {"visit", "meeting"} for a in activities)
                stop["map_role"] = "visit" if has_visit else "waypoint"
            stop.setdefault("itinerary_group", "default")
            stop.setdefault("visit_period", "")
            stop.setdefault("formatted_address", stop.get("address", ""))
            normalized_stops.append(stop)
        # Determine route_mode from legs if present
        route_mode = "straight_line"
        legs = raw.get("legs", [])
        if legs:
            modes = {leg.get("route_mode", "") for leg in legs
                     if leg.get("kind") == "travel"}
            modes.discard("")
            if modes:
                if len(modes) == 1:
                    mode = modes.pop()
                    if mode in _VALID_ROUTE_MODES:
                        route_mode = mode
                else:
                    route_mode = "provided_geometry"
        normalized = dict(raw)
        normalized["stops"] = normalized_stops
        normalized["route_mode"] = route_mode
        return normalized

    # ------------------------------------------------------------------
    # export_geojson — GeoJSON FeatureCollection builders
    # ------------------------------------------------------------------

    def _export_stops_geojson(self, normalized: dict[str, Any]) -> dict[str, Any]:
        features = []
        for stop in normalized.get("stops", []):
            loc = stop.get("location", {})
            coords = [loc.get("lon", 0), loc.get("lat", 0)]
            features.append({
                "type": "Feature",
                "id": stop.get("stop_id") or f"stop-{stop.get('visit_order', 0)}",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {
                    "visit_order": stop.get("visit_order", 0),
                    "stop_name": stop.get("name", ""),
                    "formatted_address": stop.get("formatted_address", ""),
                    "stop_type": stop.get("stop_type", "visit"),
                    "map_role": stop.get("map_role", "visit"),
                    "itinerary_group": stop.get("itinerary_group", "default"),
                    "visit_period": stop.get("visit_period", ""),
                    "visit_date": stop.get("visit_date", ""),
                    "arrival_time": stop.get("arrival_time", ""),
                    "distance_km": stop.get("distance_km", 0),
                    "duration_min": stop.get("duration_min", 0),
                },
            })
        return {"type": "FeatureCollection", "features": features}

    def _export_route_geojson(self, normalized: dict[str, Any]) -> dict[str, Any]:
        features = []
        legs = normalized.get("legs", [])
        route_mode = normalized.get("route_mode", "straight_line")
        for i, leg in enumerate(legs):
            if leg.get("kind") != "travel":
                continue
            geom = leg.get("geometry")
            if geom and isinstance(geom, dict) and geom.get("type") == "LineString":
                coords = geom["coordinates"]
            else:
                # Auto-generate straight line between stops
                from_stop = next((s for s in normalized["stops"]
                                  if s.get("stop_id") == leg.get("from_stop_id")), None)
                to_stop = next((s for s in normalized["stops"]
                                if s.get("stop_id") == leg.get("to_stop_id")), None)
                if from_stop and to_stop:
                    fl = from_stop.get("location", {})
                    tl = to_stop.get("location", {})
                    coords = [[fl.get("lon", 0), fl.get("lat", 0)],
                              [tl.get("lon", 0), tl.get("lat", 0)]]
                else:
                    coords = [[0, 0], [0, 0]]
            features.append({
                "type": "Feature",
                "id": leg.get("leg_id", f"leg-{i}"),
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "leg_id": leg.get("leg_id", f"leg-{i}"),
                    "from_stop_id": leg.get("from_stop_id", ""),
                    "to_stop_id": leg.get("to_stop_id", ""),
                    "route_mode": leg.get("route_mode", route_mode),
                    "itinerary_group": leg.get("itinerary_group", "default"),
                },
            })
        return {"type": "FeatureCollection", "features": features}