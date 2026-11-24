"""leadership-visit source_contract: data admission guard for leadership visit maps.

Validates that data sources declare acceptable roles (route-stops as Point,
route-line as LineString), licenses, CRS, and sensitivity. Trip-sensitive
declarations must not log coordinate data.
"""
from __future__ import annotations

from typing import Any

from ...errors import ProtocolError, SecurityError

_ROUTE_STOPS_ROLE = "route-stops"
_ROUTE_LINE_ROLE = "route-line"
_BASEMAP_RESOURCE = "basemap"

_ADMITTED_ROLES = frozenset({_ROUTE_STOPS_ROLE, _ROUTE_LINE_ROLE})
_ADMITTED_LICENSES = frozenset({"public", "project-approved"})
_REQUIRED_CRS = "EPSG:4326"


class RouteSourceContract:
    """Data admission guard for leadership visit itinerary sources."""

    # ------------------------------------------------------------------
    # suggestions
    # ------------------------------------------------------------------

    def suggestions(self, profile_definition: dict[str, Any]) -> list[dict[str, Any]]:
        """Role suggestions as template-analysis evidence records."""
        return [
            {
                "path": "/data/roles/route-stops",
                "value_origin": "system_suggestion",
                "value": ["route-stops", "route-line"],
                "rationale": "行程路线图需要 route-stops（必填 Point，携带 visit_order/stop_name）"
                             "与 route-line（可选 LineString）数据角色，另需配准底图资源"
                             "（basemap.png + registration.yaml）。",
                "source_ref": f"policy:{profile_definition.get('id', 'leadership-visit-mapping')}",
            },
        ]

    # ------------------------------------------------------------------
    # validate_role_bindings
    # ------------------------------------------------------------------

    def validate_role_bindings(self, request: dict[str, Any],
                               summaries: list[dict[str, Any]]) -> None:
        """Validate role bindings for template authoring (create-request shape)."""
        bindings = request.get("role_bindings") or {}
        if not isinstance(bindings, dict):
            raise ProtocolError("LEADERSHIP_SOURCE_ROLE_UNKNOWN", "role_bindings must map roles to source ids")
        unknown = set(bindings) - _ADMITTED_ROLES
        if unknown:
            raise ProtocolError("LEADERSHIP_SOURCE_ROLE_UNKNOWN",
                                f"Unknown roles: {sorted(unknown)}")
        if _ROUTE_STOPS_ROLE not in bindings:
            raise ProtocolError("LEADERSHIP_SOURCE_ROUTE_STOPS_REQUIRED",
                                "At least one route-stops role binding is required")
        by_source = {item["source_id"]: item for item in summaries}
        for role, source_id in bindings.items():
            summary = by_source.get(source_id)
            if summary is None:
                raise ProtocolError("LEADERSHIP_SOURCE_ROUTE_STOPS_REQUIRED",
                                    f"Role '{role}' binds undeclared source '{source_id}'")
            types = set(summary.get("geometry_types", []))
            if role == _ROUTE_STOPS_ROLE and not types.intersection({"point", "multipoint"}):
                raise ProtocolError("LEADERSHIP_SOURCE_GEOMETRY_MISMATCH",
                                    f"route-stops requires point geometry, got {sorted(types)}")
            if role == _ROUTE_LINE_ROLE and types and not types.intersection(
                    {"linestring", "multilinestring", "line", "multiline"}):
                raise ProtocolError("LEADERSHIP_SOURCE_GEOMETRY_MISMATCH",
                                    f"route-line requires linestring geometry, got {sorted(types)}")

    # ------------------------------------------------------------------
    # brief_roles
    # ------------------------------------------------------------------

    def brief_roles(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        """Route role summary for the template-creation brief (role_bindings shape)."""
        roles: list[dict[str, Any]] = []
        for role, source_id in (request.get("role_bindings") or {}).items():
            entry: dict[str, Any] = {
                "role_id": role,
                "source_id": source_id,
                "geometry_types": ["point"] if role == _ROUTE_STOPS_ROLE else ["linestring"],
                "value_field": "visit_order" if role == _ROUTE_STOPS_ROLE else "route_mode",
                "semantic_role": "visit-order" if role == _ROUTE_STOPS_ROLE else "route-mode",
            }
            roles.append(entry)
        if not roles:
            roles.append({
                "role_id": _ROUTE_STOPS_ROLE, "source_id": "visit-route-sample",
                "geometry_types": ["point"], "value_field": "visit_order",
                "semantic_role": "visit-order",
            })
        return roles

    # ------------------------------------------------------------------
    # validate_source_profile
    # ------------------------------------------------------------------

    @staticmethod
    def validate_source_profile(source: dict[str, Any],
                                 request: dict[str, Any]) -> None:
        """Admission gate for declared template-authoring sources (fail closed).

        Reads the source-manifest shape: ``data_profile`` carries the data
        nature, production/sensitivity flags and declared source CRS.
        """
        source_id = source.get("source_id", "<unknown>")
        profile = source.get("data_profile")
        if not isinstance(profile, dict):
            raise SecurityError("SOURCE_PROFILE_REQUIRED", source_id)
        if profile.get("contains_sensitive_coordinates") or request.get("contains_sensitive_coordinates"):
            raise SecurityError("LEADERSHIP_SOURCE_SENSITIVE_REJECTED",
                                f"Source '{source_id}' declares sensitive coordinates — "
                                "real itinerary data must be processed in a secure environment")
        if profile.get("contains_production_data") != request.get("contains_production_data"):
            raise ProtocolError("SOURCE_PRODUCTION_FLAG_MISMATCH", source_id)
        if profile.get("data_nature") != request.get("data_nature"):
            raise ProtocolError("SOURCE_DATA_NATURE_MISMATCH", source_id)
        license_value = source.get("license", "")
        if license_value not in _ADMITTED_LICENSES:
            raise SecurityError("LEADERSHIP_SOURCE_LICENSE_REJECTED",
                                f"Source '{source_id}' license '{license_value}' is not admitted")
        # The preserve policy: only WGS84 itinerary data is admitted, no implicit reprojection.
        declared_crs = profile.get("source_crs")
        if declared_crs != {"authority": "EPSG", "code": "4326"}:
            raise ProtocolError("LEADERSHIP_SOURCE_CRS_REJECTED",
                                f"Source '{source_id}' CRS '{declared_crs}' — only EPSG:4326 is admitted")


SOURCE_CONTRACT = RouteSourceContract()