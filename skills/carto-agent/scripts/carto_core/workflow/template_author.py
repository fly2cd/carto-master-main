from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..repository.staging_package import StagingPackageWriter
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard


class MapScenarioAuthor:
    def __init__(self, path_guard: PathGuard, work_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.work_root = self.path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._package_inputs(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).write(
            manifest_base, documents
        )

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        manifest_base, documents = self._package_inputs(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).verify_existing(
            manifest_base, documents
        )

    def _package_inputs(
        self,
        request: dict[str, Any],
        brief: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if request["kind"] != "map-scenario" or request["profile"] != "flood-risk-overview":
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE", "Only the flood-risk-overview MapScenario author is open")
        expression_refs = self._expression_refs()
        documents = self._documents(request, brief, expression_refs)
        manifest_base = {
            "schema_version": 1,
            "package": {
                "namespace": request["namespace"],
                "kind": "map-scenario",
                "id": request["template_id"],
                "version": request["version"],
                "status": "draft",
                "summary": request["purpose"],
            },
            "business_contracts": {
                "scenario": "contracts/scenario.yaml",
                "data_schema": "contracts/data.schema.yaml",
                "spatial_behavior": "contracts/spatial-behavior.yaml",
                "portrayal": "contracts/portrayal.yaml",
                "delivery": "contracts/delivery.yaml",
                "quality_gates": "contracts/quality-gates.yaml",
            },
            "dependencies": [],
            "dependency_lock": "dependencies.lock.yaml",
            "targets": request["targets"],
        }
        return manifest_base, documents

    def _expression_refs(self) -> dict[str, dict[str, str]]:
        catalog_path = Path(__file__).resolve().parents[3] / "policies" / "map-expression-catalog.yaml"
        catalog = load_document(catalog_path)
        by_id: dict[str, dict[str, str]] = {}
        for entry in catalog["entries"]:
            self.registry.validate("map-expression", entry)
            by_id[entry["expression_id"]] = {
                "id": entry["expression_id"],
                "version": entry["version"],
                "digest": sha256_digest(entry),
            }
        required = {"choropleth/sequential", "proportional-symbol/count"}
        if set(by_id) != required:
            raise ProtocolError("MAP_EXPRESSION_CATALOG_MISMATCH", str(sorted(by_id)))
        return by_id

    def _documents(
        self,
        request: dict[str, Any],
        brief: dict[str, Any],
        expressions: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        provenance = {
            "source_type": "derived",
            "source_ref": f"template-brief:{brief['brief_id']}",
            "version": request["version"],
            "retrieved_at": request["requested_at"],
            "classification": "internal",
        }
        rule = {
            "id": "synthetic-preview-only",
            "strength": "hard_rule",
            "path": "/application/excluded_uses",
            "description": "Draft package is limited to synthetic engineering previews and is not a published product.",
            "value": True,
        }
        identity = {
            "schema_version": 1,
            "identity_id": "neutral-emergency",
            "version": "1.0.0",
            "organization": "Synthetic Cartography Workspace",
            "colors": [{"role": "primary", "hex": "#1F4E79", "provenance": provenance}],
            "typography": [{"role": "body", "family": "Noto Sans CJK SC", "weight": 400}],
            "attribution": {
                "organization_format": "Cartography: {organization}",
                "data_source_format": "Synthetic source: {source}",
            },
            "rules": [rule],
        }
        cartography = {
            "schema_version": 1,
            "style_id": "flood-risk-technical",
            "version": "1.0.0",
            "visual_language": "technical",
            "symbolization": {
                "color_system": "sequential",
                "symbol_catalogs": ["ramps/flood-risk@1.0.0", "symbols/shelter@1.0.0"],
                "default_opacity": 0.82,
            },
            "labeling": {"density": "medium", "collision_policy": "prioritize", "font_role": "body"},
            "generalization": {"scale_dependent": True, "strategy": "simplify"},
            "defaults": {"line_width_mm": 0.2, "point_size_mm": 3.0, "opacity": 0.82},
            "rules": [rule],
        }
        layout = {
            "schema_version": 1,
            "layout_id": "a3-landscape",
            "version": "1.0.0",
            "category": "report",
            "canvas": {"width": 420, "height": 297, "unit": "mm", "orientation": "landscape", "safe_margin": 10},
            "frames": [
                {"id": "main-map", "type": "map", "coordinate_space": "page", "bounds": [15, 28, 310, 250], "overflow_policy": "clip"},
                {"id": "legend", "type": "legend", "coordinate_space": "page", "bounds": [330, 55, 75, 170], "overflow_policy": "reject"},
                {"id": "map-title", "type": "title", "coordinate_space": "page", "bounds": [15, 10, 390, 14], "overflow_policy": "shrink"},
            ],
            "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"],
            "capacity": {"legend_items": 12, "title_characters": 40},
            "rules": [rule],
        }
        target_ids = [f"a3-{target}" for target in request["targets"]]
        scenario = {
            "schema_version": 1,
            "scenario_id": request["template_id"],
            "version": request["version"],
            "business_scene": "emergency_mapping",
            "tasks": ["hazard-result-map"],
            "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal", "delivery", "quality-gates"],
            "embedded": {"identity": identity, "cartography": cartography, "layout": layout},
            "replaceable_segments": ["identity", "cartography", "layout"],
            "data_role_refs": ["risk-area", "shelter-point"],
            "target_ids": target_ids,
            "application": {
                "supported_uses": request["supported_uses"],
                "excluded_uses": request["excluded_uses"],
            },
            "compatibility": {
                "target_profiles": ["a3-landscape"],
                "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"],
            },
            "rules": [rule],
        }
        data_schema = {
            "schema_version": 1,
            "roles": [
                {
                    "id": "risk-area",
                    "required": True,
                    "geometry_types": ["polygon", "multipolygon"],
                    "fields": [
                        {"name": "risk_pct", "type": "number", "unit": "percent", "nullable": True, "semantic_role": "risk-value"}
                    ],
                    "license_policy": "project-approved",
                },
                {
                    "id": "shelter-point",
                    "required": True,
                    "geometry_types": ["point"],
                    "fields": [
                        {"name": "capacity", "type": "integer", "unit": "people", "nullable": False, "semantic_role": "count-value"}
                    ],
                    "license_policy": "project-approved",
                },
            ],
        }
        spatial = {
            "schema_version": 1,
            "source_crs_policy": "reproject-approved",
            "display_crs": request["display_crs"],
            "extent_policy": "data",
            "scale_bands": [
                {"id": "overview", "min_denominator": 10000, "max_denominator": 1000000, "generalization": "simplify"}
            ],
            "topology": {"preserve_adjacency": True, "preserve_route_order": False},
            "rules": [rule],
        }
        portrayal = {
            "schema_version": 1,
            "layers": [
                {
                    "id": "risk-layer",
                    "data_role": "risk-area",
                    "geometry": "polygon",
                    "z_order": 10,
                    "map_expression_ref": expressions["choropleth/sequential"],
                    "value_role": "risk-value",
                    "symbol": {"catalog_ref": "ramps/flood-risk@1.0.0", "parameters": {"opacity": 0.82}},
                    "classification": {"method": "quantile", "classes": 5, "field_role": "risk-value"},
                    "no_data": "explicit-symbol",
                },
                {
                    "id": "shelter-layer",
                    "data_role": "shelter-point",
                    "geometry": "point",
                    "z_order": 20,
                    "map_expression_ref": expressions["proportional-symbol/count"],
                    "value_role": "count-value",
                    "symbol": {"catalog_ref": "symbols/shelter@1.0.0", "parameters": {"shape": "circle"}},
                    "scaling": {"method": "area-proportional", "field_role": "count-value", "minimum_size_mm": 2, "maximum_size_mm": 12},
                    "no_data": "explicit-symbol",
                },
            ],
            "legend": {"generated_from_layers": True, "show_no_data": True, "overflow_policy": "reject"},
            "rules": [rule],
        }
        targets = []
        for target in request["targets"]:
            is_vector_container = target in {"svg", "pdf"}
            targets.append(
                {
                    "id": f"a3-{target}",
                    "delivery_class": "engineering-preview",
                    "format": target,
                    "composition": "raster-map-vector-overlay" if is_vector_container else "flattened-raster",
                    "vector_claim": "overlay-only" if is_vector_container else "none",
                    "page": {"width_mm": 420, "height_mm": 297, "orientation": "landscape", "dpi": 144, "safe_margin_mm": 10},
                    "color_mode": "rgb",
                    "font_policy": "embed-approved",
                    "production_ready": False,
                }
            )
        delivery = {"schema_version": 1, "targets": targets, "rules": [rule]}
        baseline_path = Path(__file__).resolve().parents[3] / "policies" / "scope-baseline.yaml"
        baseline = load_document(baseline_path)
        quality_gates = {
            "schema_version": 1,
            "baseline": {
                "id": baseline["baseline_id"],
                "version": str(baseline["version"]),
                "digest": "sha256:" + hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                "uri": "policy:scope-baseline",
            },
            "checks": [
                {"id": "protocol.schema-valid", "version": "1.0.0", "params": {}},
                {"id": "security.synthetic-only", "version": "1.0.0", "params": {"contains_production_data": False}},
            ],
        }
        fixture = {
            "type": "FeatureCollection",
            "carto_metadata": {
                "data_nature": "synthetic",
                "contains_production_data": False,
                "contains_sensitive_coordinates": False,
                "source_crs": "EPSG:4326",
            },
            "features": [
                {
                    "type": "Feature",
                    "id": "synthetic-risk-a",
                    "properties": {"fixture_role": "risk-area", "risk_pct": 25.0},
                    "geometry": {"type": "Polygon", "coordinates": [[[0.00, 0.00], [0.08, 0.00], [0.08, 0.08], [0.00, 0.08], [0.00, 0.00]]]},
                },
                {
                    "type": "Feature",
                    "id": "synthetic-risk-b",
                    "properties": {"fixture_role": "risk-area", "risk_pct": 70.0},
                    "geometry": {"type": "Polygon", "coordinates": [[[0.10, 0.00], [0.18, 0.00], [0.18, 0.08], [0.10, 0.08], [0.10, 0.00]]]},
                },
                {
                    "type": "Feature",
                    "id": "synthetic-shelter-a",
                    "properties": {"fixture_role": "shelter-point", "capacity": 120},
                    "geometry": {"type": "Point", "coordinates": [0.04, 0.04]},
                },
                {
                    "type": "Feature",
                    "id": "synthetic-shelter-b",
                    "properties": {"fixture_role": "shelter-point", "capacity": 300},
                    "geometry": {"type": "Point", "coordinates": [0.14, 0.04]},
                },
            ],
        }
        prototype = {
            "schema_version": 1,
            "prototype_id": "risk-overview",
            "status": "pending-validation",
            "render_required": True,
            "renderer_execution": "not-run",
            "layout_id": "a3-landscape",
            "target_ids": target_ids,
            "layer_ids": ["risk-layer", "shelter-layer"],
            "fixture_ref": "fixtures/flood-risk.synthetic.geojson",
            "limitations": [
                "No browser renderer is executed in U-P2.2.",
                "The fixture is synthetic and is not suitable for operational emergency decisions.",
            ],
        }
        package_identity = {
            "namespace": request["namespace"],
            "kind": "map-scenario",
            "id": request["template_id"],
            "version": request["version"],
        }
        dependency_lock = {
            "schema_version": 1,
            "lock_id": f"{request['template_id']}-lock",
            "package": {**package_identity, "digest": sha256_digest(package_identity)},
            "dependencies": [],
            "resources": [expressions["choropleth/sequential"], expressions["proportional-symbol/count"]],
            "resolver_version": "1.0.0",
            "generated_at": request["requested_at"],
        }
        design_spec = self._design_spec(request, brief)
        return {
            "templates/design_spec.md": design_spec,
            "contracts/scenario.yaml": scenario,
            "contracts/data.schema.yaml": data_schema,
            "contracts/spatial-behavior.yaml": spatial,
            "contracts/portrayal.yaml": portrayal,
            "contracts/delivery.yaml": delivery,
            "contracts/quality-gates.yaml": quality_gates,
            "fixtures/flood-risk.synthetic.geojson": fixture,
            "prototypes/risk-overview.yaml": prototype,
            "dependencies.lock.yaml": dependency_lock,
        }

    @staticmethod
    def _design_spec(request: dict[str, Any], brief: dict[str, Any]) -> str:
        return f"""# {request['template_id']} Design Spec

- Kind: `map-scenario`
- Version: `{request['version']}`
- Status: draft staging package
- Purpose: {request['purpose']}
- Reuse intent: {request['reuse_intent']}
- Source data: synthetic only; EPSG:4326
- Display CRS: EPSG:3857
- Canvas: A3 landscape, 420 x 297 mm
- Expressions: `choropleth/sequential@1.0.0`, `proportional-symbol/count@1.0.0`
- Brief: `{brief['brief_id']}` revision {brief['revision']}

This specification describes an engineering-preview prototype. Rendering, validation and publication are intentionally deferred.
"""