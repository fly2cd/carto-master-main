"""Itinerary check tool: validate the host's draft (advisory layer).

Validates data/itinerary-draft.json against the itinerary-structure contract
BEFORE request assembly and geocoding, reporting field-level errors the host
(LLM) can act on. This mirrors rules the kernel will enforce at compile
(scenarios/leadership_visit/data_preparer._from_contract) — deliberately
advisory: the kernel remains the sole authority; this tool exists to give the
host early, actionable feedback instead of a compile-time rejection.

Stateless by design (no revision store): drift protection between stages is
the kernel's G2 prepared-data-bundle digest binding.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _service_utils import ServiceError, resolve_under_root, sha256_digest

ACTIVITY_TYPES = frozenset({
    "departure", "visit", "meeting", "meal", "rest",
    "meal_and_rest", "transfer", "end",
})
PERIODS = frozenset({"morning", "afternoon"})
ROUTE_MODES = frozenset({"road_network", "provided_geometry", "schematic", "straight_line"})
METRIC_SOURCES = frozenset({"document", "routing", "none"})
LEG_KINDS = frozenset({"travel", "stay"})


def _err(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _warn(warnings: list[dict[str, str]], code: str, path: str, message: str) -> None:
    warnings.append({"code": code, "path": path, "message": message})


def _validate_draft(document: Any, errors: list, warnings: list) -> dict[str, int]:
    """Populate errors/warnings; return the summary counts."""
    if not isinstance(document, dict):
        _err(errors, "ITINERARY_DRAFT_SHAPE", "", "draft must be a JSON object")
        return {"places": 0, "stops": 0, "legs": 0}

    places = document.get("places")
    stops = document.get("stops")
    legs = document.get("legs")
    if not isinstance(places, list) or not places:
        _err(errors, "ITINERARY_PLACE_INVALID", "/places", "places must be a non-empty list")
        places = []
    if not isinstance(stops, list) or not stops:
        _err(errors, "ITINERARY_STOP_INVALID", "/stops", "stops must be a non-empty list")
        stops = []
    if not isinstance(legs, list):
        _err(errors, "ITINERARY_LEG_INVALID", "/legs", "legs must be a list")
        legs = []

    place_ids: set[str] = set()
    for i, place in enumerate(places):
        if not isinstance(place, dict):
            _err(errors, "ITINERARY_PLACE_INVALID", f"/places/{i}", "place must be an object")
            continue
        pid = place.get("place_id", "")
        if not pid or not isinstance(pid, str):
            _err(errors, "ITINERARY_PLACE_INVALID", f"/places/{i}/place_id", "place_id is required")
            continue
        if pid in place_ids:
            _err(errors, "ITINERARY_PLACE_INVALID", f"/places/{i}/place_id",
                 f"duplicate place_id '{pid}'")
            continue
        place_ids.add(pid)
        if not place.get("name"):
            _err(errors, "ITINERARY_PLACE_INVALID", f"/places/{i}/name",
                 f"place '{pid}' needs a name (keep the original text)")
        query = place.get("geocoding_query")
        if not isinstance(query, dict) or not query.get("name") or not query.get("city"):
            _err(errors, "ITINERARY_PLACE_INVALID", f"/places/{i}/geocoding_query",
                 f"place '{pid}' needs geocoding_query {{name, city}} for the MCP geocode call")
        if place.get("location"):
            _warn(warnings, "ITINERARY_LOCATION_PREFILLED", f"/places/{i}/location",
                  f"place '{pid}' already has a location — coordinates should come from "
                  "geocode (user-confirmed), not be hand-filled")

    stop_ids: set[str] = set()
    stop_place: dict[str, str] = {}
    for i, stop in enumerate(stops):
        if not isinstance(stop, dict):
            _err(errors, "ITINERARY_STOP_INVALID", f"/stops/{i}", "stop must be an object")
            continue
        sid = stop.get("stop_id", "")
        if not sid or not isinstance(sid, str):
            _err(errors, "ITINERARY_STOP_INVALID", f"/stops/{i}/stop_id", "stop_id is required")
            continue
        if sid in stop_ids:
            _err(errors, "ITINERARY_STOP_DUPLICATE", f"/stops/{i}/stop_id",
                 f"duplicate stop_id '{sid}'")
            continue
        stop_ids.add(sid)
        pid = stop.get("place_id", "")
        if pid not in place_ids:
            _err(errors, "ITINERARY_PLACE_UNKNOWN", f"/stops/{i}/place_id",
                 f"stop '{sid}' references unknown place_id '{pid}'")
        else:
            stop_place[sid] = pid
        activities = stop.get("activities", [])
        if not isinstance(activities, list) or not activities:
            _err(errors, "ITINERARY_ACTIVITY_INVALID", f"/stops/{i}/activities",
                 f"stop '{sid}' needs at least one activity")
        for j, activity in enumerate(activities):
            if not isinstance(activity, dict):
                continue
            if activity.get("type") not in ACTIVITY_TYPES:
                _err(errors, "ITINERARY_ACTIVITY_INVALID",
                     f"/stops/{i}/activities/{j}/type",
                     f"activity type must be one of {sorted(ACTIVITY_TYPES)}")
            period = activity.get("period")
            if period is not None and period not in PERIODS:
                _err(errors, "ITINERARY_ACTIVITY_INVALID",
                     f"/stops/{i}/activities/{j}/period",
                     "period must be morning or afternoon (omit if unknown — do not guess)")

    travel_pairs: list[tuple[str, str]] = []
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            _err(errors, "ITINERARY_LEG_INVALID", f"/legs/{i}", "leg must be an object")
            continue
        kind = leg.get("kind")
        if kind not in LEG_KINDS:
            _err(errors, "ITINERARY_LEG_INVALID", f"/legs/{i}/kind",
                 "kind must be travel or stay")
            continue
        for end in ("from_stop_id", "to_stop_id"):
            if leg.get(end) not in stop_ids:
                _err(errors, "ITINERARY_LEG_INVALID", f"/legs/{i}/{end}",
                     f"leg '{leg.get('leg_id', i)}' references unknown stop")
        if kind == "stay":
            p_from = stop_place.get(leg.get("from_stop_id", ""))
            p_to = stop_place.get(leg.get("to_stop_id", ""))
            if p_from and p_to and p_from != p_to:
                _err(errors, "ITINERARY_LEG_INVALID", f"/legs/{i}",
                     "a stay leg must join two stops at the SAME place "
                     "(split same-place consecutive activities into two stops)")
            continue
        travel_pairs.append((leg.get("from_stop_id", ""), leg.get("to_stop_id", "")))
        if leg.get("route_mode") not in ROUTE_MODES:
            _err(errors, "ITINERARY_LEG_INVALID", f"/legs/{i}/route_mode",
                 f"route_mode must be one of {sorted(ROUTE_MODES)}")
        source = leg.get("metric_source")
        if source not in METRIC_SOURCES:
            _err(errors, "ITINERARY_METRIC_INVALID", f"/legs/{i}/metric_source",
                 f"metric_source must be one of {sorted(METRIC_SOURCES)}")
        elif source == "document":
            metrics = leg.get("document_metrics")
            if not isinstance(metrics, dict):
                _err(errors, "ITINERARY_METRIC_INVALID", f"/legs/{i}/document_metrics",
                     "metric_source=document requires document_metrics")
            else:
                for key in ("distance_km", "duration_min"):
                    value = metrics.get(key)
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        _err(errors, "ITINERARY_METRIC_INVALID",
                             f"/legs/{i}/document_metrics/{key}",
                             "document metrics must be numbers from the source text")

    # Chain connectivity — advisory (the kernel assigns visit_order by chain order).
    referenced: set[str] = set()
    for a, b in travel_pairs:
        referenced.update(x for x in (a, b) if x in stop_ids)
    for stop in stops:
        if isinstance(stop, dict) and stop.get("stop_id") in stop_ids \
                and stop["stop_id"] not in referenced:
            _warn(warnings, "ITINERARY_CHAIN_GAP",
                  f"/stops/{stop.get('stop_id', '')}",
                  "stop is not connected by any leg — check the travel chain")

    return {"places": len(places), "stops": len(stops), "legs": len(legs)}


def _load_draft(path: Path, errors: list) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        _err(errors, "ITINERARY_DRAFT_UNPARSEABLE", "",
             f"draft must be UTF-8: {exc}")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        position = f"（行 {exc.lineno}，列 {exc.colno}）" if exc.lineno else ""
        _err(errors, "ITINERARY_DRAFT_UNPARSEABLE", "",
             f"invalid JSON{position}: {exc.msg}；请修正格式后复检")
        return None


def itinerary_check(arguments: dict[str, Any], ctx: dict[str, Path]) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        draft_path: project-relative or absolute path to itinerary-draft.json
        expected_digest: optional "sha256:..." to detect host-side draft drift
    Output:
        status=complete: draft passes all contract checks
        status=invalid: report.errors is non-empty (field-level, for the host)
    """
    root = ctx["allowed_root"]
    draft_path_arg = arguments.get("draft_path", "")
    if not draft_path_arg:
        return {"status": "error", "code": "DRAFT_PATH_REQUIRED",
                "message": "draft_path is required"}

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    try:
        draft_path = resolve_under_root(draft_path_arg, root, must_exist=True)
    except ServiceError as exc:
        return {"status": "error", "code": exc.code, "message": exc.message}

    raw = draft_path.read_bytes()
    draft_digest = "sha256:" + __import__("hashlib").sha256(raw).hexdigest()
    expected = arguments.get("expected_digest")
    if expected and expected != draft_digest:
        _err(errors, "ITINERARY_INPUT_DRIFT", "/",
             f"draft changed since digest {expected} was recorded")

    document = _load_draft(draft_path, errors)
    summary = _validate_draft(document, errors, warnings) if document is not None \
        else {"places": 0, "stops": 0, "legs": 0}

    return {
        "status": "invalid" if errors else "complete",
        "report": {"errors": errors, "warnings": warnings, "summary": summary},
        "draft_digest": draft_digest,
    }
