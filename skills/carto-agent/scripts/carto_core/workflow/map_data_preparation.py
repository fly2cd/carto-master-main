from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_yaml(path: Path, value: dict[str, Any], *, create_once: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if create_once and load_document(path) != value:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        if create_once:
            return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, value: dict[str, Any], *, create_once: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists():
        if create_once and path.read_text(encoding="utf-8") != payload:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        if create_once:
            return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


def artifact_ref(identifier: str, value: Any, uri: str | Path | None = None) -> dict[str, str]:
    result = {"id": identifier, "version": "1.0.0", "digest": sha256_digest(value)}
    if uri is not None:
        result["uri"] = str(uri)
    return result


class FloodDataPreparer:
    """Prepare the bounded U-P2 synthetic flood-risk input slice."""

    ROLE_SPECS = {
        "risk-area": {"geometries": {"polygon", "multipolygon"}, "semantic": "risk-value", "unit": "percent", "output": "risk_value"},
        "shelter-point": {"geometries": {"point"}, "semantic": "count-value", "unit": "people", "output": "count_value"},
    }

    def __init__(self, path_guard: PathGuard, project_root: Path, output_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = path_guard.resolve(project_root, must_exist=True)
        self.output_root = path_guard.resolve(output_root)
        self.registry = registry or SchemaRegistry()

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        bindings = request.get("source_bindings")
        if not isinstance(bindings, list):
            raise ProtocolError("GENERATE_SOURCE_BINDINGS_REQUIRED", "source_bindings")
        by_role = {item.get("role"): item for item in bindings if isinstance(item, dict)}
        if set(by_role) != set(self.ROLE_SPECS) or len(bindings) != len(by_role):
            raise ProtocolError("GENERATE_SOURCE_ROLES_INVALID", "risk-area and shelter-point are required exactly once")

        prepared: dict[str, dict[str, Any]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        raw: dict[str, dict[str, Any]] = {}
        for role in sorted(by_role):
            document, info = self._prepare_role(role, by_role[role], request)
            raw[role] = document
            prepared[role] = {"type": "FeatureCollection", "carto_metadata": {
                "data_nature": "synthetic", "source_crs": "EPSG:4326", "role": role,
            }, "features": info.pop("features")}
            metadata[role] = info

        for role, binding in by_role.items():
            metadata[role]["join_coverage"] = self._join_coverage(role, binding, raw, by_role)

        self.output_root.mkdir(parents=True, exist_ok=True)
        refs: dict[str, dict[str, str]] = {}
        for role in sorted(prepared):
            path = self.path_guard.resolve(self.output_root / f"{role}.prepared.geojson")
            atomic_json(path, prepared[role])
            refs[role] = {"id": f"prepared-{role}", "version": "1.0.0", "digest": file_digest(path), "uri": str(path)}

        role_bindings = []
        for role in sorted(by_role):
            info = metadata[role]
            role_bindings.append({
                "role": role, "dataset_ref": by_role[role]["source_ref"], "prepared_ref": refs[role],
                "geometry_types": info["geometry_types"], "semantic_fields": info["semantic_fields"],
                "feature_count": info["feature_count"], "bbox": info["bbox"],
                "crs": {"authority": "EPSG", "code": "4326"},
                "observed_at": by_role[role]["freshness"]["observed_at"],
                "join_coverage": info["join_coverage"],
            })
        combined = self._combine_bbox([item["bbox"] for item in role_bindings])
        quality = artifact_ref("data-quality-evidence", {
            "roles": [{"role": item["role"], "feature_count": item["feature_count"],
                       "geometry_types": item["geometry_types"], "join_coverage": item["join_coverage"]}
                      for item in role_bindings],
            "data_nature": "synthetic",
        })
        body = {
            "schema_version": 1, "bundle_id": f"bundle-{request['run_id']}",
            "task_ref": request_ref, "datasets": [by_role[role]["source_ref"] for role in sorted(by_role)],
            "transformations": [artifact_ref("normalize-semantic-fields", {"version": 1, "roles": sorted(by_role)})],
            "tool_receipts": [], "quality_evidence": [quality], "open_issues": [],
            "role_bindings": role_bindings,
            "summary": {"combined_bbox": combined, "data_nature": "synthetic"},
        }
        bundle = {**body, "digest": sha256_digest(body)}
        self.registry.validate("prepared-data-bundle", bundle)
        return {"bundle": bundle, "prepared": prepared, "refs": refs}

    def _prepare_role(self, role: str, binding: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        spec = self.ROLE_SPECS[role]
        if binding.get("synthetic") is not True:
            raise ProtocolError("PRODUCTION_DATA_FORBIDDEN", role)
        if binding.get("format") != "geojson":
            raise ProtocolError("SOURCE_FORMAT_UNSUPPORTED", role)
        if binding.get("crs") != {"authority": "EPSG", "code": "4326"}:
            raise ProtocolError("SOURCE_CRS_UNSUPPORTED", role)
        declared_geometries = set(binding.get("geometry_types", []))
        if not declared_geometries or not declared_geometries.issubset(spec["geometries"]):
            raise ProtocolError("SOURCE_GEOMETRY_DECLARATION_INVALID", role)
        fields = {item["semantic_role"]: item for item in binding.get("field_bindings", [])}
        units = {item["semantic_role"]: item["unit"] for item in binding.get("unit_bindings", [])}
        if set(fields) != {spec["semantic"]} or units != {spec["semantic"]: spec["unit"]}:
            raise ProtocolError("SOURCE_SEMANTIC_BINDING_INVALID", role)
        self._check_freshness(binding["freshness"], request["requested_at"], role)

        path = self.path_guard.resolve(binding["path"], base_root=self.project_root, must_exist=True)
        if file_digest(path) != binding["source_ref"]["digest"]:
            raise ProtocolError("SOURCE_DIGEST_MISMATCH", role)
        document = load_document(path)
        if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
            raise ProtocolError("GEOJSON_FEATURE_COLLECTION_REQUIRED", role)
        source_field = fields[spec["semantic"]]["source_field"]
        output_features = []
        observed_geometries: set[str] = set()
        coordinates: list[tuple[float, float]] = []
        for index, feature in enumerate(document.get("features", [])):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ProtocolError("GEOJSON_FEATURE_INVALID", f"{role}:{index}")
            geometry = feature.get("geometry") or {}
            geometry_type = str(geometry.get("type", "")).lower()
            if geometry_type not in spec["geometries"] or geometry_type not in declared_geometries:
                raise ProtocolError("SOURCE_GEOMETRY_TYPE_INVALID", f"{role}:{geometry_type}")
            self._collect_coordinates(geometry.get("coordinates"), coordinates)
            properties = feature.get("properties") or {}
            value = properties.get(source_field)
            expected_type = fields[spec["semantic"]]["value_type"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ProtocolError("SOURCE_FIELD_VALUE_INVALID", f"{role}:{source_field}")
            if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ProtocolError("SOURCE_FIELD_TYPE_INVALID", f"{role}:{source_field}")
            numeric = int(value) if expected_type == "integer" else float(value)
            if spec["unit"] == "percent" and not 0 <= numeric <= 100:
                raise ProtocolError("SOURCE_UNIT_DOMAIN_INVALID", role)
            if spec["unit"] == "people" and numeric < 0:
                raise ProtocolError("SOURCE_UNIT_DOMAIN_INVALID", role)
            output_features.append({"type": "Feature", "id": str(feature.get("id", f"{role}-{index + 1}")),
                                    "properties": {"carto_role": role, spec["output"]: numeric},
                                    "geometry": geometry})
            observed_geometries.add(geometry_type)
        if not output_features or not coordinates:
            raise ProtocolError("SOURCE_DATA_EMPTY", role)
        return document, {"features": output_features, "feature_count": len(output_features),
                          "geometry_types": sorted(observed_geometries),
                          "semantic_fields": {spec["semantic"]: spec["output"]},
                          "bbox": self._bbox(coordinates)}

    @staticmethod
    def _check_freshness(freshness: dict[str, Any], requested_at: str, role: str) -> None:
        observed = datetime.fromisoformat(freshness["observed_at"].replace("Z", "+00:00"))
        requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        age = (requested - observed).total_seconds() / 86400
        if age < 0 or age > freshness["max_age_days"]:
            raise ProtocolError("SOURCE_FRESHNESS_INVALID", role)

    @staticmethod
    def _join_coverage(role: str, binding: dict[str, Any], raw: dict[str, dict[str, Any]], bindings: dict[str, dict[str, Any]]) -> float:
        join = binding["join"]
        if not join["required"]:
            return 1.0
        key = join.get("key")
        if not key:
            raise ProtocolError("JOIN_KEY_REQUIRED", role)
        other_role = next(item for item in bindings if item != role)
        other_key = bindings[other_role].get("join", {}).get("key") or key
        other_values = {feature.get("properties", {}).get(other_key) for feature in raw[other_role].get("features", [])}
        features = raw[role].get("features", [])
        matched = sum(1 for feature in features if feature.get("properties", {}).get(key) in other_values)
        coverage = matched / len(features) if features else 0.0
        if "coverage" in join and not math.isclose(float(join["coverage"]), coverage, abs_tol=1e-9):
            raise ProtocolError("JOIN_COVERAGE_DECLARATION_MISMATCH", role)
        if coverage < float(join.get("minimum_coverage", 1.0)):
            raise ProtocolError("JOIN_COVERAGE_INSUFFICIENT", role)
        return coverage

    @classmethod
    def _collect_coordinates(cls, value: Any, output: list[tuple[float, float]]) -> None:
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2]):
            x, y = float(value[0]), float(value[1])
            if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
                raise ProtocolError("SOURCE_COORDINATE_INVALID", "EPSG:4326 coordinate outside domain")
            output.append((x, y))
            return
        if isinstance(value, list):
            for item in value:
                cls._collect_coordinates(item, output)

    @staticmethod
    def _bbox(coordinates: list[tuple[float, float]]) -> list[float]:
        xs = [item[0] for item in coordinates]
        ys = [item[1] for item in coordinates]
        return [min(xs), min(ys), max(xs), max(ys)]

    @staticmethod
    def _combine_bbox(values: list[list[float]]) -> list[float]:
        return [min(item[0] for item in values), min(item[1] for item in values),
                max(item[2] for item in values), max(item[3] for item in values)]


