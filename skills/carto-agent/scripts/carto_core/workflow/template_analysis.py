from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import MAX_DOCUMENT_BYTES, SchemaRegistry, load_document
from ..security.paths import PathGuard

MAX_SOURCE_RECORDS = 1_000
MAX_SOURCE_FIELDS = 100
_ALLOWED_GEOMETRIES = {
    "Point": "point",
    "MultiPoint": "multipoint",
    "LineString": "line",
    "MultiLineString": "multiline",
    "Polygon": "polygon",
    "MultiPolygon": "multipolygon",
}


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ControlledSourceAnalyzer:
    """Analyze bounded synthetic GeoJSON/CSV sources without retaining business rows."""

    def __init__(self, path_guard: PathGuard, project_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = self.path_guard.resolve(project_root, must_exist=True)
        self.registry = registry or SchemaRegistry()

    def load_inputs(self, request_path: str | Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        resolved_request = self.path_guard.resolve(request_path, must_exist=True)
        request = load_document(resolved_request)
        if not isinstance(request, dict):
            raise ProtocolError("TEMPLATE_REQUEST_INVALID", "Template request must be an object")
        self.registry.validate("template-create-request", request)
        self._require_open_kind(request["kind"])
        if request["scope"] != f"project:{request['subject']['project_id']}":
            raise SecurityError("PROJECT_SCOPE_DENIED", request["scope"])

        manifest_path = self.path_guard.resolve(
            request["source_manifest_path"], base_root=self.project_root, must_exist=True
        )
        manifest = load_document(manifest_path)
        if not isinstance(manifest, dict):
            raise ProtocolError("SOURCE_MANIFEST_INVALID", "Source manifest must be an object")
        self.registry.validate("source-manifest", manifest)
        summaries = self._analyze_sources(manifest)
        self._validate_role_bindings(request, summaries)
        return request, manifest, summaries

    def input_snapshot(self, request: dict[str, Any], manifest: dict[str, Any], summaries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "request": request,
            "source_manifest": manifest,
            "source_digests": {item["source_id"]: item["digest"] for item in summaries},
        }

    def analyze(self, request: dict[str, Any], manifest: dict[str, Any], summaries: list[dict[str, Any]]) -> dict[str, Any]:
        evidence: list[dict[str, Any]] = []
        for summary in summaries:
            source_ref = f"source:{summary['source_id']}@{summary['digest']}"
            evidence.extend(
                [
                    {
                        "path": f"/sources/{summary['source_id']}/record_count",
                        "value_origin": "source_fact",
                        "value": summary["record_count"],
                        "source_ref": source_ref,
                    },
                    {
                        "path": f"/sources/{summary['source_id']}/fields",
                        "value_origin": "source_fact",
                        "value": summary["field_names"],
                        "source_ref": source_ref,
                    },
                ]
            )
        evidence.extend(
            [
                {
                    "path": "/purpose",
                    "value_origin": "user_decision",
                    "value": request["purpose"],
                    "source_ref": f"request:{request['request_id']}",
                },
                {
                    "path": "/targets",
                    "value_origin": "user_decision",
                    "value": request["targets"],
                    "source_ref": f"request:{request['request_id']}",
                },
                {
                    "path": "/portrayal/map-expressions",
                    "value_origin": "system_suggestion",
                    "value": ["choropleth/sequential@1.0.0", "proportional-symbol/count@1.0.0"],
                    "rationale": "The U-P2 flood profile binds polygon risk values and point capacities to the registered expression slice.",
                },
                {
                    "path": "/layout/canvas",
                    "value_origin": "derived",
                    "value": "A3 landscape 420x297mm",
                    "source_ref": "profile:flood-risk-overview@1.0.0",
                    "rationale": "Derived from the frozen engineering-preview target profile.",
                },
            ]
        )
        for decision in request["decisions"]:
            evidence.append(
                {
                    "path": decision["path"],
                    "value_origin": "user_decision",
                    "value": decision["value"],
                    "source_ref": decision["source_ref"],
                }
            )
        analysis = {
            "schema_version": 1,
            "analysis_id": f"analysis-{request['request_id']}",
            "request_digest": sha256_digest(request),
            "source_manifest_digest": sha256_digest(manifest),
            "source_summaries": summaries,
            "evidence_records": evidence,
            "open_questions": [],
        }
        self.registry.validate("template-analysis", analysis)
        return analysis

    @staticmethod
    def _require_open_kind(kind: str) -> None:
        if kind != "map-scenario":
            raise ProtocolError(
                "CAPABILITY_NOT_AVAILABLE",
                f"U-P2.2 authoring is not open for template kind: {kind}",
            )

    def _analyze_sources(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        summaries: list[dict[str, Any]] = []
        for source in manifest["sources"]:
            source_id = source["source_id"]
            if source_id in seen:
                raise ProtocolError("SOURCE_ID_DUPLICATE", source_id)
            seen.add(source_id)
            if source["kind"] not in {"geojson", "csv"}:
                raise ProtocolError("SOURCE_TYPE_UNSUPPORTED", source["kind"])
            if source["license"] == "restricted":
                raise SecurityError("SOURCE_LICENSE_RESTRICTED", source_id)
            profile = source.get("data_profile")
            if not isinstance(profile, dict):
                raise SecurityError("SYNTHETIC_SOURCE_ATTESTATION_REQUIRED", source_id)
            path = self.path_guard.resolve(
                source["location_ref"], base_root=self.project_root, must_exist=True
            )
            if not path.is_file():
                raise SecurityError("SOURCE_PATH_INVALID", str(path))
            actual_digest = file_digest(path)
            if actual_digest != source["digest"]:
                raise ProtocolError("SOURCE_DIGEST_MISMATCH", source_id)
            if source["kind"] == "geojson":
                summary = self._analyze_geojson(path)
            else:
                summary = self._analyze_csv(path)
            summaries.append(
                {
                    "source_id": source_id,
                    "kind": source["kind"],
                    "digest": actual_digest,
                    "license": source["license"],
                    "data_nature": "synthetic",
                    **summary,
                }
            )
        return sorted(summaries, key=lambda item: item["source_id"])

    @staticmethod
    def _read_utf8(path: Path) -> str:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise SecurityError("SOURCE_TOO_LARGE", str(path))
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("SOURCE_ENCODING_INVALID", str(path)) from exc

    def _analyze_geojson(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(self._read_utf8(path))
        except json.JSONDecodeError as exc:
            raise ProtocolError("GEOJSON_PARSE_FAILED", str(exc)) from exc
        if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
            raise ProtocolError("GEOJSON_TYPE_INVALID", "Expected FeatureCollection")
        metadata = value.get("carto_metadata")
        expected_metadata = {
            "data_nature": "synthetic",
            "contains_production_data": False,
            "contains_sensitive_coordinates": False,
            "source_crs": "EPSG:4326",
        }
        if metadata != expected_metadata:
            raise SecurityError("SYNTHETIC_SOURCE_ATTESTATION_INVALID", path.name)
        features = value.get("features")
        if not isinstance(features, list) or len(features) > MAX_SOURCE_RECORDS:
            raise SecurityError("SOURCE_RECORD_LIMIT_EXCEEDED", path.name)
        fields: set[str] = set()
        geometries: set[str] = set()
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ProtocolError("GEOJSON_FEATURE_INVALID", path.name)
            properties = feature.get("properties")
            if not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties):
                raise ProtocolError("GEOJSON_PROPERTIES_INVALID", path.name)
            fields.update(properties)
            if len(fields) > MAX_SOURCE_FIELDS:
                raise SecurityError("SOURCE_FIELD_LIMIT_EXCEEDED", path.name)
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") not in _ALLOWED_GEOMETRIES:
                raise ProtocolError("GEOJSON_GEOMETRY_INVALID", path.name)
            geometries.add(_ALLOWED_GEOMETRIES[geometry["type"]])
            self._check_geometry(geometry)
        return {
            "record_count": len(features),
            "field_names": sorted(fields),
            "geometry_types": sorted(geometries),
        }

    def _analyze_csv(self, path: Path) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(self._read_utf8(path), newline=""))
        if not reader.fieldnames or len(reader.fieldnames) > MAX_SOURCE_FIELDS:
            raise ProtocolError("CSV_HEADER_INVALID", path.name)
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ProtocolError("CSV_HEADER_DUPLICATE", path.name)
        count = 0
        for row in reader:
            count += 1
            if count > MAX_SOURCE_RECORDS:
                raise SecurityError("SOURCE_RECORD_LIMIT_EXCEEDED", path.name)
            if None in row:
                raise ProtocolError("CSV_ROW_INVALID", path.name)
        return {"record_count": count, "field_names": sorted(reader.fieldnames), "geometry_types": ["none"]}

    @classmethod
    def _check_geometry(cls, geometry: dict[str, Any]) -> None:
        geometry_type = geometry["type"]
        coordinates = geometry.get("coordinates")
        if geometry_type == "Point":
            cls._check_position(coordinates)
        elif geometry_type == "MultiPoint":
            cls._check_position_sequence(coordinates, minimum=1)
        elif geometry_type == "LineString":
            cls._check_position_sequence(coordinates, minimum=2)
        elif geometry_type == "MultiLineString":
            for line in cls._require_coordinate_list(coordinates, minimum=1):
                cls._check_position_sequence(line, minimum=2)
        elif geometry_type == "Polygon":
            cls._check_polygon(coordinates)
        elif geometry_type == "MultiPolygon":
            for polygon in cls._require_coordinate_list(coordinates, minimum=1):
                cls._check_polygon(polygon)

    @classmethod
    def _check_polygon(cls, coordinates: Any) -> None:
        for ring in cls._require_coordinate_list(coordinates, minimum=1):
            positions = cls._require_coordinate_list(ring, minimum=4)
            for position in positions:
                cls._check_position(position)
            if positions[0] != positions[-1]:
                raise ProtocolError("GEOJSON_COORDINATES_INVALID", "Polygon rings must be closed")

    @classmethod
    def _check_position_sequence(cls, value: Any, *, minimum: int) -> None:
        for position in cls._require_coordinate_list(value, minimum=minimum):
            cls._check_position(position)

    @staticmethod
    def _require_coordinate_list(value: Any, *, minimum: int) -> list[Any]:
        if not isinstance(value, list) or len(value) < minimum:
            raise ProtocolError("GEOJSON_COORDINATES_INVALID", "Coordinate array has an invalid shape")
        return value

    @staticmethod
    def _check_position(value: Any) -> None:
        if not isinstance(value, list) or len(value) not in {2, 3}:
            raise ProtocolError("GEOJSON_COORDINATES_INVALID", "Position must contain two or three numbers")
        if any(
            not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)
            for item in value
        ):
            raise ProtocolError("GEOJSON_COORDINATES_INVALID", "Position must contain finite numbers")
        longitude, latitude = value[:2]
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ProtocolError("GEOJSON_COORDINATES_INVALID", "EPSG:4326 position is outside valid bounds")

    @staticmethod
    def _validate_role_bindings(request: dict[str, Any], summaries: list[dict[str, Any]]) -> None:
        by_id = {item["source_id"]: item for item in summaries}
        risk_id = request["role_bindings"]["risk_area_source"]
        shelter_id = request["role_bindings"]["shelter_source"]
        if risk_id == shelter_id:
            raise ProtocolError("ROLE_BINDING_DUPLICATE", risk_id)
        try:
            risk = by_id[risk_id]
            shelter = by_id[shelter_id]
        except KeyError as exc:
            raise ProtocolError("ROLE_SOURCE_NOT_FOUND", str(exc.args[0])) from exc
        if not set(risk["geometry_types"]).intersection({"polygon", "multipolygon"}) or "risk_pct" not in risk["field_names"]:
            raise ProtocolError("RISK_AREA_SOURCE_INCOMPATIBLE", risk_id)
        if "point" not in shelter["geometry_types"] or "capacity" not in shelter["field_names"]:
            raise ProtocolError("SHELTER_SOURCE_INCOMPATIBLE", shelter_id)