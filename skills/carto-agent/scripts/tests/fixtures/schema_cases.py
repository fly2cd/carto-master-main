from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from carto_core.canonical import sha256_digest

D = "sha256:" + "0" * 64
A = {"id": "artifact", "version": "1.0.0", "digest": D}
E = {"id": "choropleth/sequential", "version": "1.0.0", "digest": D}
T = {"kind": "map-scenario", "id": "test-scenario", "version": "1.0.0", "digest": D}
P = {"source_type": "official", "source_ref": "catalog:item", "version": "2026", "retrieved_at": "2026-09-14T00:00:00Z", "classification": "internal"}
R = {"id": "required-rule", "strength": "hard_rule", "path": "/value", "description": "必须满足"}
RESOLVED_LAYOUT = json.loads((Path(__file__).parent / "resolved-layout.valid.json").read_text(encoding="utf-8"))
EXECUTION = {
    "intent_ref": A,
    "profile_refs": [],
    "business_scene": "general_thematic_mapping",
    "map_tasks": ["thematic-map"],
    "template_refs": [T],
    "dependency_refs": [E],
    "policy_refs": [],
    "dataset_refs": [A],
    "prepared_data_refs": [],
    "knowledge_evidence_refs": [],
    "tool_binding_refs": [],
    "transformation_refs": [],
    "ownership": {"scenario": "map-scenario"},
    "shared_semantics": {"theme_tags": ["unit-theme"], "data_nature": "observed"},
    "views": [{"id": "main-view", "extent": [100, 20, 101, 21], "layer_ids": ["area-layer"], "target_ids": ["a3-pdf"]}],
    "targets": {"a3-pdf": {"format": "pdf", "display_crs": {"authority": "EPSG", "code": "4490"}, "dpi": 144, "width_mm": 420, "height_mm": 297}},
    "resolved_assets": [E, A],
    "resolved_layout": RESOLVED_LAYOUT,
    "environment": {"renderer_id": "maplibre-web", "renderer_version": "1.0.0", "frontend_build": "2026.09.15", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "fingerprint": D},
}
EXECUTION_DIGEST = sha256_digest(EXECUTION)

CARTOGRAPHY = {"schema_version": 1, "style_id": "technical-map", "version": "1.0.0", "visual_language": "technical", "symbolization": {"color_system": "sequential", "symbol_catalogs": ["ramps/test-theme@1.0.0"], "default_opacity": 0.8}, "labeling": {"density": "medium", "collision_policy": "prioritize", "font_role": "body"}, "generalization": {"scale_dependent": True, "strategy": "simplify"}, "defaults": {"line_width_mm": 0.2, "point_size_mm": 3, "opacity": 0.8}, "rules": [R]}
LAYOUT = {"schema_version": 1, "layout_id": "a3-landscape", "version": "1.0.0", "category": "report", "canvas": {"width": 420, "height": 297, "unit": "mm", "orientation": "landscape", "safe_margin": 10}, "frames": [{"id": "main-map", "content_id": "main-view", "type": "map", "coordinate_space": "page", "bounds": [20, 30, 380, 230], "overflow_policy": "clip"}], "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}"], "capacity": {"legend_items": 12, "title_characters": 40}, "rules": [R]}
BUSINESS_CONTRACTS = {"scenario": "contracts/scenario.yaml", "data_schema": "contracts/data.schema.yaml", "spatial_behavior": "contracts/spatial-behavior.yaml", "portrayal": "contracts/portrayal.yaml", "delivery": "contracts/delivery.yaml", "quality_gates": "contracts/quality-gates.yaml"}
PACKAGE_FILES = [*BUSINESS_CONTRACTS.values(), "dependencies.lock.yaml"]
MAP_EXPRESSION = {"schema_version": 1, "expression_id": "choropleth/sequential", "version": "1.0.0", "title": "Sequential choropleth", "status": "active", "geometry_types": ["polygon"], "field_requirements": [{"semantic_role": "thematic-value", "value_type": "number", "required": True, "nullable": True}], "parameter_definitions": [{"name": "class-count", "type": "integer", "required": True, "default": 5}], "visual_variables": [{"variable": "fill-color", "source_role": "thematic-value", "algorithm_id": "sequential-classification"}], "legend": {"type": "classed-color", "show_no_data": True, "label_source": "class-breaks"}, "missing_value_policy": "explicit-symbol", "outlier_policy": "clip-to-domain", "checker_refs": [{"id": "protocol.schema-valid", "version": "1.0.0"}], "fixture_refs": [A]}

TEMPLATE_CREATE_REQUEST = {
    "schema_version": 2,
    "request_id": "test-template-request",
    "kind": "map-scenario",
    "namespace": "local",
    "template_id": "test-scenario",
    "version": "1.0.0",
    "profile": "test-profile",
    "purpose": "Protocol request",
    "audience": ["thematic-planner"],
    "reuse_intent": "Reuse with authorized role-compatible inputs",
    "supported_uses": ["engineering-preview"],
    "excluded_uses": ["navigation", "formal-delivery"],
    "authoring_mode": "standard",
    "targets": ["svg", "pdf", "png"],
    "scope": "project:project-one",
    "subject": {
        "tenant_id": "tenant-one",
        "project_id": "project-one",
        "requester_subject_id": "operator-one",
        "approver_subject_id": "reviewer-one",
        "environment": "local",
    },
    "source_manifest_path": "source-manifest.yaml",
    "data_nature": "observed",
    "contains_production_data": False,
    "contains_sensitive_coordinates": False,
    "source_crs": {"authority": "EPSG", "code": "4326"},
    "display_crs": {"authority": "EPSG", "code": "3857"},
    "role_bindings": {"area_source": "area-source", "point_source": "point-source"},
    "decisions": [],
    "requested_at": "2026-09-18T00:00:00Z",
}
TEMPLATE_EVIDENCE = [
    {"path": "/sources/area-source/record_count", "value_origin": "source_fact", "value": 2, "source_ref": f"source:area-source@{D}"},
    {"path": "/sources/point-source/record_count", "value_origin": "source_fact", "value": 2, "source_ref": f"source:point-source@{D}"},
    {"path": "/purpose", "value_origin": "user_decision", "value": TEMPLATE_CREATE_REQUEST["purpose"], "source_ref": "request:test-template-request"},
    {"path": "/targets", "value_origin": "user_decision", "value": ["svg", "pdf", "png"], "source_ref": "request:test-template-request"},
    {"path": "/portrayal/map-expressions", "value_origin": "system_suggestion", "value": ["choropleth/sequential@1.0.0", "proportional-symbol/count@1.0.0"], "rationale": "Registered expressions match the declared data roles."},
    {"path": "/layout/canvas", "value_origin": "derived", "value": "A3 landscape 420x297mm", "source_ref": "profile:test-profile@1.0.0", "rationale": "Derived from the frozen profile."},
]
TEMPLATE_ANALYSIS = {
    "schema_version": 1,
    "analysis_id": "analysis-test-template-request",
    "request_digest": D,
    "source_manifest_digest": D,
    "source_summaries": [
        {"source_id": "area-source", "kind": "geojson", "digest": D, "license": "project-approved", "data_nature": "observed", "record_count": 2, "field_names": ["thematic_value"], "geometry_types": ["polygon"]},
        {"source_id": "point-source", "kind": "geojson", "digest": D, "license": "project-approved", "data_nature": "observed", "record_count": 2, "field_names": ["count"], "geometry_types": ["point"]},
    ],
    "evidence_records": TEMPLATE_EVIDENCE,
    "open_questions": [],
}
TEMPLATE_BRIEF = {
    "schema_version": 1,
    "brief_id": "brief-test-template-request",
    "kind": "map-scenario",
    "namespace": "local",
    "template_id": "test-scenario",
    "version": "1.0.0",
    "scope": "project:project-one",
    "purpose": TEMPLATE_CREATE_REQUEST["purpose"],
    "audience": ["thematic-planner"],
    "reuse_intent": TEMPLATE_CREATE_REQUEST["reuse_intent"],
    "supported_uses": ["engineering-preview"],
    "excluded_uses": ["navigation", "formal-delivery"],
    "sources": [
        {"id": "area-source", "version": "1.0.0", "digest": D, "uri": "source:area-source"},
        {"id": "point-source", "version": "1.0.0", "digest": D, "uri": "source:point-source"},
    ],
    "source_license_summary": [
        {"source_id": "area-source", "license": "project-approved", "data_nature": "observed"},
        {"source_id": "point-source", "license": "project-approved", "data_nature": "observed"},
    ],
    "authoring_mode": "standard",
    "targets": ["svg", "pdf", "png"],
    "data_roles": [
        {"role_id": "area-role", "source_id": "area-source", "geometry_types": ["polygon", "multipolygon"], "value_field": "thematic_value", "semantic_role": "thematic-value"},
        {"role_id": "point-role", "source_id": "point-source", "geometry_types": ["point"], "value_field": "count", "semantic_role": "count-value"},
    ],
    "spatial_applicability": {"source_crs": {"authority": "EPSG", "code": "4326"}, "display_crs": {"authority": "EPSG", "code": "3857"}, "extent_policy": "data"},
    "evidence_records": TEMPLATE_EVIDENCE,
    "decisions": [TEMPLATE_EVIDENCE[2], TEMPLATE_EVIDENCE[3]],
    "open_questions": [],
    "revision": 1,
}
PROTOTYPE_DESCRIPTION = {
    "schema_version": 1,
    "prototype_id": "area-overview",
    "status": "pending-validation",
    "render_required": True,
    "renderer_execution": "not-run",
    "layout_id": "a3-landscape",
    "target_ids": ["a3-svg", "a3-pdf", "a3-png"],
    "layer_ids": ["area-layer", "point-layer"],
    "fixture_ref": "fixtures/validation-input.json",
    "limitations": ["Browser rendering is deferred."],
}

CARTOGRAPHY.update(schema_version=2, version="2.0.0", typography={'title_pt': 18, 'body_pt': 9, 'legend_pt': 10, 'legend_heading_pt': 11, 'line_spacing': 1.25})
LAYOUT["content_padding_mm"] = 2

TEMPLATE_CREATE_REQUEST["geometry"] = "raster"

VALID_CASES = {
    "manifest": {"schema_version": 1, "package": {"namespace": "local", "kind": "map-scenario", "id": "test-scenario", "version": "1.0.0", "status": "draft", "summary": "Schema 测试对象"}, "business_contracts": BUSINESS_CONTRACTS, "dependencies": [], "dependency_lock": "dependencies.lock.yaml", "targets": ["svg", "pdf", "png"], "files": PACKAGE_FILES, "checksums": {path: D for path in PACKAGE_FILES}},
    "template-create-request": TEMPLATE_CREATE_REQUEST,
    "template-analysis": TEMPLATE_ANALYSIS,
    "template-brief": TEMPLATE_BRIEF,
    "prototype-description": PROTOTYPE_DESCRIPTION,
    "style": CARTOGRAPHY,
    "layout": LAYOUT,
    "resolved-layout": RESOLVED_LAYOUT,
    "scenario": {"schema_version": 1, "scenario_id": "test-scenario", "version": "1.0.0", "business_scene": "general_thematic_mapping", "tasks": ["thematic-map"], "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal", "delivery", "quality-gates"], "embedded": {"style": CARTOGRAPHY, "layout": LAYOUT}, "replaceable_segments": ["style", "layout"], "data_role_refs": ["area-role", "point-role"], "target_ids": ["a3-pdf", "a3-png"], "application": {"supported_uses": ["engineering-preview"], "excluded_uses": ["navigation", "formal-delivery"]}, "compatibility": {"target_profiles": ["a3-landscape"], "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}"]}, "rules": [R]},
    "data-role": {"schema_version": 1, "roles": [{"id": "area-role", "required": True, "geometry_types": ["polygon", "multipolygon"], "fields": [{"name": "thematic_value", "type": "number", "unit": "percent", "nullable": True, "semantic_role": "thematic-value"}], "join": {"key": "admin_code", "minimum_coverage": 0.98}, "freshness": {"max_age_days": 30}, "license_policy": "project-approved"}]},
    "spatial-behavior": {"schema_version": 1, "source_crs_policy": "reproject-approved", "display_crs": {"authority": "EPSG", "code": "4490"}, "extent_policy": "administrative-boundary", "scale_bands": [{"id": "regional", "min_denominator": 10000, "max_denominator": 1000000, "generalization": "simplify"}], "topology": {"preserve_adjacency": True, "preserve_route_order": False}, "rules": [R]},
    "portrayal": {"schema_version": 1, "layers": [{"id": "area-layer", "data_role": "area-role", "geometry": "polygon", "z_order": 10, "map_expression_ref": {"id": "choropleth/sequential", "version": "1.0.0", "digest": D}, "value_role": "thematic-value", "symbol": {"catalog_ref": "ramps/test-theme@1.0.0", "parameters": {"opacity": 0.8}}, "classification": {"method": "quantile", "classes": 4, "field_role": "thematic-value"}, "no_data": "explicit-symbol"}], "legend": {"generated_from_layers": True, "show_no_data": True, "overflow_policy": "reject"}, "rules": [R]},
    "delivery": {"schema_version": 1, "targets": [{"id": "a3-pdf", "delivery_class": "engineering-preview", "format": "pdf", "composition": "raster-map-vector-overlay", "vector_claim": "overlay-only", "page": {"width_mm": 420, "height_mm": 297, "orientation": "landscape", "dpi": 300, "safe_margin_mm": 10}, "color_mode": "rgb", "font_policy": "embed-approved", "production_ready": False}], "rules": [R]},
    "quality-gates": {"schema_version": 1, "baseline": A, "checks": [{"id": "protocol.schema-valid", "version": "1.0.0", "params": {}}]},
    "map-expression": MAP_EXPRESSION,
    "template-index": {"schema_version": 1, "index_id": "local-template-index", "version": "1.0.0", "repository_scope": "local:templates", "entries": [{"namespace": "local", "kind": "map-scenario", "id": "test-scenario", "version": "1.0.0", "digest": D, "manifest_path": "map-scenario/test-scenario/1.0.0/manifest.yaml", "manifest_digest": D, "evidence_digest": D, "publication_receipt_path": "transactions/publication.yaml", "status": "published", "published_at": "2026-09-17T00:00:00Z"}], "generated_at": "2026-09-17T00:00:00Z", "digest": D},
    "dependency-lock": {"schema_version": 1, "lock_id": "test-scenario-lock", "package": {"namespace": "local", "kind": "map-scenario", "id": "test-scenario", "version": "1.0.0", "digest": D}, "dependencies": [], "resources": [{"id": "choropleth/sequential", "version": "1.0.0", "digest": D}, {"id": "proportional-symbol/count", "version": "1.0.0", "digest": D}], "resolver_version": "1.0.0", "generated_at": "2026-09-17T00:00:00Z"},
    "template-validation-evidence": {"schema_version": 1, "evidence_id": "validation-evidence-one", "namespace": "local", "package_ref": T, "manifest_digest": D, "dependency_lock_digest": D, "fixture_set_digest": D, "checker_set_digest": D, "renderer": {"renderer_id": "maplibre-web", "renderer_profile_digest": D, "adapter_version": "1.0.0", "frontend_build": "2026.09.18", "renderer_version": "1.0.0", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "environment_fingerprint": D}, "render_receipt_ref": A, "preview_artifacts": [{"target": "svg", "artifact_ref": A}], "status": "passed", "counts": {"blocker": 0, "error": 0, "warning": 0, "info": 0}, "results": [{"check_id": "template.package-closed", "version": "1.0.0", "status": "passed", "severity": "blocker", "details": {}}], "created_at": "2026-09-18T00:00:00Z", "evidence_digest": D},
    "publication-receipt": {"schema_version": 1, "receipt_id": "publication-receipt-one", "namespace": "local", "package_ref": T, "manifest_digest": D, "evidence_ref": A, "dependency_lock_ref": A, "index_digest_before": D, "index_digest_after": D, "repository_scope": "local:templates", "approval_ref": A, "publication_object_ref": A, "published_at": "2026-09-17T00:00:00Z", "idempotency_key": "publish-test-0001"},
    "template-publication": {"schema_version": 1, "run_id": "run-one", "request_digest": D, "package_ref": T, "evidence_ref": A, "repository_scope": "local:templates", "repository_root": "/tmp/carto-repo", "idempotency_key": "publish-test-0001"},
    "template-proposal": {"schema_version": 1, "proposal_id": "prop-one", "kind": "derive", "base_ref": T, "change_set": {"typography": {"title_pt": 20}}, "recovered": {}, "unrecoverable": [{"field": "crs", "reason": "not in image", "requires_user": True}], "confidence": {"palette": 0.0, "layout": 0.0, "typography": 0.0}, "provenance": {"source_type": "derived", "source_ref": "base", "method": "restricted-change-set"}, "selected_segments": ["style"]},
    "segment-create-request": {"schema_version": 1, "request_id": "seg-request-one", "kind": "map-style", "namespace": "local", "template_id": "seg-style", "version": "1.0.0", "purpose": "段作者协议测试", "audience": ["cartographer"], "reuse_intent": "复用外观", "supported_uses": ["engineering-preview"], "excluded_uses": ["navigation"], "authoring_mode": "standard", "targets": ["png"], "scope": "project:test-project", "subject": {"tenant_id": "tenant-one", "project_id": "test-project", "requester_subject_id": "user-1", "approver_subject_id": "approver-1", "environment": "test"}, "design": deepcopy(CARTOGRAPHY), "requested_at": "2026-11-23T00:00:00Z"},
    "segment-analysis": {"schema_version": 1, "analysis_id": "analysis-seg-request-one", "request_digest": D, "design_digest": D, "kind": "map-style", "evidence_records": [{"path": "/purpose", "value_origin": "user_decision", "value": "段作者协议测试", "source_ref": "request:seg-request-one"}], "open_questions": []},
    "segment-brief": {"schema_version": 1, "brief_id": "brief-seg-request-one", "kind": "map-style", "namespace": "local", "template_id": "seg-style", "version": "1.0.0", "scope": "project:test-project", "purpose": "段作者协议测试", "audience": ["cartographer"], "reuse_intent": "复用外观", "supported_uses": ["engineering-preview"], "excluded_uses": ["navigation"], "authoring_mode": "standard", "targets": ["png"], "design_digest": D, "evidence_records": [{"path": "/purpose", "value_origin": "user_decision", "value": "段作者协议测试", "source_ref": "request:seg-request-one"}], "decisions": [{"path": "/purpose", "value_origin": "user_decision", "value": "段作者协议测试", "source_ref": "request:seg-request-one"}], "open_questions": [], "revision": 1},
    "validation-host": {"schema_version": 1, "host_id": "general-thematic-raster-host", "version": "1.0.0", "shell_digest": D, "style_digest": D, "layout_digest": D, "fixture_digest": D, "display_crs": {"authority": "EPSG", "code": "3857"}, "output_profile": {"width_mm": 297, "height_mm": 210, "dpi": 300}},
    "segment-validation-evidence": {"schema_version": 1, "evidence_id": "seg-validation-one", "namespace": "local", "package_ref": T, "manifest_digest": D, "dependency_lock_digest": D, "design_digest": D, "host_ref": A, "checker_set_digest": D, "status": "passed", "counts": {"blocker": 0, "error": 0, "warning": 0, "info": 0}, "results": [{"check_id": "segment.package-closed", "version": "1.0.0", "status": "passed", "severity": "info", "details": {}}], "renderer": {"renderer_id": "rasterio-matplotlib-page"}, "render_receipt_ref": A, "render_scene_ref": A, "preview_artifacts": [{"target": "png", "artifact_ref": A}], "created_at": "2026-11-23T00:00:00Z", "evidence_digest": D},
    "generate-request": {"schema_version": 1, "request_id": "request-one", "project_id": "test-project", "goal": "校验制图请求结构", "geometry": "raster", "panels": [{"id": "base-view", "source_id": "ref-a", "title": "Base"}], "sources": [A], "requested_outputs": ["pdf", "png"], "subject": {"subject_id": "user-1", "tenant_id": "tenant-one", "namespace": "project-one"}, "idempotency_key": "request-one-00001"},
    "measurement-rule": {"schema_version": 1, "rule_id": "reference-design-a3-144dpi", "version": "1.0.0", "reference_width_px": 2381, "reference_height_px": 1684, "scale_floor": 1.0, "scale_function": "min-ratio-floor"},
    "symbol-measurement": {"kind": "reference-design-px", "value": 6, "rule_ref": deepcopy(A)},
    "card-parameters": {"sizing": {"width": {"mode": "fit-content-up-to-limit", "limit": {"kind": "reference-design-px", "value": 500, "rule_ref": deepcopy(A)}}}, "inset": {"kind": "reference-design-px", "value": 4, "rule_ref": deepcopy(A)}, "sections": {"gap": {"kind": "reference-design-px", "value": 6, "rule_ref": deepcopy(A)}}, "title": {"wrap_mode": "single-line-reject-overflow"}},
    "component-definition": {"schema_version": 1, "component_id": "information-card", "version": "1.0.0", "type": "information-card", "parameter_schema": "card-parameters", "structure_modes": ["atomic-card"], "measurement_modes": ["reference-design-px"], "backend_capabilities": ["image-overlay"], "appearance_roles": ["card-title", "card-body", "card-background", "card-leader"], "content_roles": ["card-title-text", "card-body-lines"]},
    "annotation-placement": {"mode": "preferred", "offset": {"x": {"kind": "reference-design-px", "value": 45, "rule_ref": deepcopy(A)}, "y": {"kind": "reference-design-px", "value": -135, "rule_ref": deepcopy(A)}}},
    "basemap-display": {"crop": {"parameters": {"white_threshold": 245}}},
    "role-appearance": {"font": {"size": {"kind": "reference-design-px", "value": 22, "rule_ref": deepcopy(A)}, "weight": 700, "color": "#FFFFFF"}},
    "route-parameters": {"arrows": {"head_size": {"kind": "reference-design-px", "value": 8, "rule_ref": deepcopy(A)}, "repeat_spacing": {"kind": "reference-design-px", "value": 200, "rule_ref": deepcopy(A)}}},
    "linked-label-parameters": {"inset": {"kind": "reference-design-px", "value": 4, "rule_ref": deepcopy(A)}},
    "double-outline-parameters": {"inner_stroke_width": {"kind": "physical-mm", "value": 0.25}, "stroke_gap": {"kind": "physical-mm", "value": 1.0}, "outer_stroke_width": {"kind": "physical-mm", "value": 0.5}},
    "map-intent": {"schema_version": 1, "intent_id": "intent-one", "revision": 1, "profile_version": "2.0.0", "business_scene": "general_thematic_mapping", "theme_tags": ["unit-theme"], "tasks": ["thematic-map"], "intent_status": "resolved", "readiness_status": "ready", "missing_items": [], "evidence_refs": [A]},
    "intent-profiles": {'schema_version': 1, 'catalog_version': '2.0.0', 'profiles': [{'business_scene': 'unit_scene', 'purpose_terms': ['unit purpose'], 'task_ids': ['unit-task'], 'required_information': ['theme_tags'], 'unsupported_actions': []}], 'themes': [{'id': 'unit-theme', 'label': 'Unit topic', 'terms': ['unit topic']}]},
    "map-brief": {"schema_version": 1, "brief_id": "map-brief-one", "revision": 1, "intent_ref": A, "purpose": "空间信息展示", "audience": "授权使用者", "source_plan": [{"role": "area-role", "source_ref": A, "allowed_operations": ["read", "join", "classify"]}], "targets": ["pdf", "png"], "template_candidates": [T], "delegation": {"allow_data_agent": False, "max_tool_calls": 10}, "approval_required": True, "business_scene": "government_thematic", "theme_tags": ["unit-theme"], "tasks": ["indicator-map"]},
    "source-manifest": {"schema_version": 1, "manifest_id": "source-manifest-one", "sources": [{"source_id": "area-data", "kind": "geopackage", "location_ref": "project-source:area.gpkg", "digest": D, "provenance": P, "license": "project-approved", "captured_at": "2026-09-14T00:00:00Z"}]},
    "tool-binding": {"schema_version": 1, "binding_id": "renderer-capability-register", "version": "1.0.0", "capability_id": "renderer-capability-register", "adapter": "local", "input_schema_digest": D, "output_schema_digest": D, "authorization_policy": "environment-probe", "effect": "read", "snapshot_policy": "receipt-only"},
    "knowledge-evidence": {"schema_version": 1, "evidence_id": "evidence-one", "claim": "指标字段单位为百分比", "publisher": "示例标准机构", "source": P, "applicability": {"jurisdiction": "示例地区", "valid_from": "2026-01-01", "industry": "emergency"}, "digest": D},
    "data-preparation-task": {"schema_version": 1, "task_id": "prepare-one", "required_roles": ["area-role"], "allowed_sources": [A], "allowed_operations": ["filter", "join", "reproject", "classify"], "budget": {"max_tool_calls": 10, "max_seconds": 300}, "acceptance_checks": ["schema-valid"]},
    "prepared-data-bundle": {"schema_version": 1, "bundle_id": "bundle-one", "task_ref": A, "datasets": [A], "transformations": [], "tool_receipts": [A], "quality_evidence": [A], "open_issues": [], "digest": D},
    "map-plan": {"schema_version": 3, "plan_id": "plan-one", "revision": 1, "project_id": "test-project", "intent_ref": A, "brief_ref": A, "business_scene": "general_thematic_mapping", "tasks": ["thematic-map"], "template_refs": [T], "data_bindings": [{"role": "area-role", "dataset_ref": A}], "decisions": {"classification": "quantile", "class_count": 5, "extent": [100, 20, 101, 21], "title": "Protocol title", "legend_source": "actual-encoding", "renderer_id": "maplibre-web", "point_scaling": "area-proportional"}, "open_issues": []},
    "resolved-map": {"schema_version": 1, "candidate_id": "candidate-one", "project_id": "test-project", "run_id": "run-one", "execution_digest": EXECUTION_DIGEST, "execution": EXECUTION, "open_issues": [], "created_at": "2026-09-14T00:00:00Z"},
    "map-spec-lock": {"schema_version": 1, "lock_id": "lock-one", "project_id": "test-project", "run_id": "run-one", "candidate_ref": A, "execution_digest": EXECUTION_DIGEST, "execution": EXECUTION, "evidence": {"preflight_ref": A, "preview_ref": A}, "approvals": {"brief_ref": "approval:brief", "freeze_ref": "approval:freeze"}, "candidate_digest": D, "preview_evidence_digest": D, "render_receipt_ref": A, "environment_fingerprint": D, "created_at": "2026-09-14T00:00:00Z"},
    "render-attempt": {"schema_version": 1, "attempt_id": "render-attempt-run-one-1", "project_id": "test-project", "run_id": "run-one", "lock_ref": A, "lock_digest": D, "business_execution_digest": EXECUTION_DIGEST, "target_id": "formal-map", "attempt_number": 1, "status": "succeeded", "render_scene_digest": D, "renderer_profile_digest": D, "renderer_execution_digest": D, "resource_set_digest": D, "environment_fingerprint": D, "output_artifacts": [{"target": "pdf", "artifact_ref": A}, {"target": "png", "artifact_ref": A}], "render_receipt_ref": A, "retryable": False, "started_at": "2026-09-21T00:00:00Z", "completed_at": "2026-09-21T00:00:05Z"},
    "formal-render-evidence": {"schema_version": 1, "evidence_id": "formal-render-run-one-1", "project_id": "test-project", "run_id": "run-one", "lock_ref": A, "lock_digest": D, "business_execution_digest": EXECUTION_DIGEST, "attempt_ref": A, "attempt_digest": D, "render_scene_digest": D, "renderer_profile_digest": D, "renderer_execution_digest": D, "resource_set_digest": D, "environment_fingerprint": D, "render_receipt_ref": A, "output_artifacts": [{"target": "pdf", "artifact_ref": A, "size_bytes": 1024, "media_type": "application/pdf"}, {"target": "png", "artifact_ref": A, "size_bytes": 2048, "media_type": "image/png"}], "required_targets": ["pdf", "png"], "scenario_notice": "场景使用限制", "quality_status": "not-checked", "created_at": "2026-09-21T00:00:05Z", "evidence_digest": D},
    "map-preview-evidence": {"schema_version": 1, "evidence_id": "preview-evidence-one", "project_id": "test-project", "run_id": "run-one", "candidate_digest": D, "candidate_execution_digest": EXECUTION_DIGEST, "render_scene_digest": D, "render_receipt_ref": A, "render_execution_digest": D, "environment_fingerprint": D, "output_artifacts": [{"target": "svg", "artifact_ref": A}], "checks": [{"check_id": "preview.binding", "owner": "adapter", "status": "passed", "severity": "blocker", "details": {}}], "status": "passed", "created_at": "2026-09-18T00:00:00Z", "evidence_digest": D},
    "delivery-manifest": {"schema_version": 1, "manifest_id": "manifest-one", "project_id": "test-project", "tenant_id": "tenant-one", "run_id": "run-one", "lock_ref": A, "lock_digest": D, "execution_digest": EXECUTION_DIGEST, "render_attempt_ref": A, "renderer_execution_digest": D, "validation_report_ref": A, "artifacts": [{"path": "output/map.pdf", "format": "pdf", "digest": D, "size_bytes": 1024}, {"path": "output/map.png", "format": "png", "digest": D, "size_bytes": 2048}], "recipient": {"recipient_id": "reviewer-one", "recipient_type": "project-user"}, "destination": {"kind": "local-allowed-root", "relative_path": "deliveries/delivery-one"}, "scope": "project:test-project", "environment": "local", "licenses": ["unit-test-only"], "limitations": ["场景使用限制"], "idempotency_key": "delivery-one-00000001", "created_at": "2026-09-21T00:00:00Z"},
    "delivery-receipt": {"schema_version": 1, "receipt_id": "delivery-receipt-one", "delivery_id": "delivery-one", "transaction_id": "transaction-one", "manifest_ref": A, "manifest_digest": D, "idempotency_key": "delivery-one-00000001", "final_path": "deliveries/delivery-one", "artifacts": [{"path": "package/map.pdf", "format": "pdf", "digest": D, "size_bytes": 1024}, {"path": "package/map.png", "format": "png", "digest": D, "size_bytes": 2048}], "g3_approval_ref": A, "status": "committed", "delivered_at": "2026-09-21T00:00:00Z"},
    "delivery-transaction": {"schema_version": 1, "transaction_id": "transaction-one", "delivery_id": "delivery-one", "project_id": "test-project", "tenant_id": "tenant-one", "run_id": "run-one", "manifest_ref": A, "manifest_digest": D, "idempotency_key": "delivery-one-00000001", "recipient": {"recipient_id": "reviewer-one", "recipient_type": "project-user"}, "destination": {"kind": "local-allowed-root", "relative_path": "deliveries/delivery-one"}, "staging_path": "deliveries/.delivery-one.staging-0000000000000000", "final_path": "deliveries/delivery-one", "approval_ref": A, "status": "receipt-written", "phase": "receipt", "artifacts": [{"path": "map.pdf", "format": "pdf", "digest": D, "size_bytes": 1024}, {"path": "map.png", "format": "png", "digest": D, "size_bytes": 2048}], "receipt_ref": A, "created_at": "2026-09-21T00:00:00Z", "updated_at": "2026-09-21T00:00:02Z", "committed_at": "2026-09-21T00:00:01Z"},
    "approval-receipt": {"schema_version": 1, "receipt_id": "receipt-one", "issuer": "test-issuer", "subject_id": "test-reviewer", "tenant_id": "test-tenant", "action": "approve-freeze", "object_type": "resolved-map", "object_digest": D, "scope": "project:test-project", "policy_id": "carto-security", "environment": "local", "nonce": "test-nonce-0000000000000001", "issued_at": "2026-09-14T00:00:00Z", "expires_at": "2026-09-15T00:00:00Z", "signature_algorithm": "hmac-sha256", "signature": "0" * 64},
    "job-state": {"schema_version": 1, "revision": 1, "status": "running", "step": "validate", "attempt": 1, "run_id": "run-one", "input_fingerprint": D, "last_receipt": "receipts/validate-1.json"},
    "step-receipt": {"schema_version": 1, "receipt_id": "receipt-step-one", "run_id": "run-one", "step": "validate", "attempt": 1, "status": "succeeded", "input_fingerprint": D, "prerequisite_fingerprints": {"policy": D}, "tool_versions": {"schema-validate": "1.0.0"}, "output_refs": [A], "started_at": "2026-09-15T00:00:00Z", "completed_at": "2026-09-15T00:00:01Z"},
    "state-transition": {"schema_version": 1, "transition_id": "transition-one", "run_id": "run-one", "expected_revision": 1, "receipt_path": "receipts/validate-1.json", "receipt_digest": D, "previous_state": {"schema_version": 1, "revision": 1, "status": "running", "step": "validate", "attempt": 1, "run_id": "run-one", "input_fingerprint": D, "last_receipt": "receipts/prior.json"}, "next_state": {"schema_version": 1, "revision": 2, "status": "pending", "step": "publish", "attempt": 1, "run_id": "run-one", "input_fingerprint": D, "last_receipt": "receipts/validate-1.json"}, "created_at": "2026-09-15T00:00:01Z"},
    "tool-result": {"schema_version": 1, "invocation_id": "invocation-one", "capability_id": "schema-validate", "binding_version": "1.0.0", "status": "succeeded", "input_digest": D, "output_digest": D, "artifact_refs": [A], "started_at": "2026-09-15T00:00:00Z", "completed_at": "2026-09-15T00:00:01Z"},
    "validation-report": {"schema_version": 1, "report_id": "report-one", "phase": "validate", "subject_digest": D, "status": "passed", "results": [{"check_id": "protocol.schema-valid", "version": "1.0.0", "status": "passed", "severity": "blocker", "details": {}}], "created_at": "2026-09-15T00:00:00Z"},
    "environment-fingerprint": {"schema_version": 1, "probe_id": "renderer-capability-probe", "status": "unavailable", "platform": "Windows", "python_version": "3.11.0", "tools": {"browser": {"available": False, "command": None, "executable": None, "version": None, "exit_code": None}, "node": {"available": False, "executable": None, "version": None, "exit_code": None}}, "chinese_fonts": [], "capabilities": {"webgl_available": False, "offline_rendering": False, "svg_composition": True, "headless_export": False, "chinese_font": False, "max_canvas_width": 16384, "max_canvas_height": 16384, "supported_export_formats": ["svg"]}, "renderer_profile": {"renderer_id": "maplibre-web", "frontend_build": "2026.09.15", "renderer_version": "1.0.0", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "browser_engine": "unavailable", "webgl_available": False, "supported_export_formats": ["svg"], "max_canvas_width": 16384, "max_canvas_height": 16384, "device_pixel_ratio": 2.0, "available_fonts": [], "offline_rendering": False}, "probed_at": "2026-09-15T00:00:00Z", "fingerprint": D, "error": {"code": "CAPABILITY_NOT_AVAILABLE", "message": "Controlled renderer handshake unavailable"}},
    "render-scene": {
        "schema_version": 1, "scene_id": "scene-unit-001", "revision": 1, "renderer_id": "maplibre-web",
        "spatial_context": {"display_crs": {"authority": "EPSG", "code": "4490"}, "axis_order": "longitude-latitude", "coordinate_units": "degrees"},
        "renderer_requirements": {"renderer_id": "maplibre-web", "require_webgl": True, "require_offline_rendering": True, "required_capabilities": ["svg-overlay", "geographic-anchor", "headless-export"], "required_fonts": ["Noto Sans CJK SC"], "minimum_device_pixel_ratio": 2},
        "viewport": {"width_px": 1684, "height_px": 1191, "device_pixel_ratio": 2, "background": "#FFFFFF"},
        "camera": {"bounds": [112.1, 28.0, 114.2, 29.8], "bearing": 0, "pitch": 0, "padding": {"top": 80, "right": 320, "bottom": 90, "left": 80}},
        "map": {"style_ref": A, "sources": [{"id": "area-source", "type": "geojson", "resource_id": "area-data"}], "layers": [{"id": "area-layer", "source_id": "area-source", "type": "fill", "paint": {"fill-color": "#005EA8"}, "z_index": 10}]},
        "overlays": [{"id": "map-title", "type": "text", "coordinate_space": "page", "position": {"x": 0.05, "y": 0.04, "unit": "normalized"}, "content": "协议标题", "style_role": "map-title"}, {"id": "survey-point-01", "type": "symbol", "coordinate_space": "geographic", "anchor": {"longitude": 113.1, "latitude": 28.7}, "screen_position": {"x": 840, "y": 600, "unit": "pixel"}, "symbol_ref": "survey-location", "label": "调研点一"}],
        "resources": [{"id": "area-data", "kind": "geojson", "ref": A, "required": True}, {"id": "survey-location", "kind": "icon", "ref": A, "required": True}, {"id": "noto-font", "kind": "font", "ref": A, "required": True, "font_family": "Noto Sans CJK SC"}],
        "export": {"targets": ["svg", "png"], "dpi": 300}, "random_seed": 20260918, "provenance": [P]
    },
    "render-receipt": {
        "schema_version": 1, "receipt_id": "render-receipt-one", "session_id": "session-one", "scene_id": "scene-unit-001", "scene_revision": 1, "scene_digest": D, "execution_digest": D, "resource_set_digest": D, "environment_fingerprint": D, "random_seed": 20260918,
        "renderer_id": "maplibre-web", "renderer_profile_digest": D, "frontend_build_version": "2026.09.15", "renderer_version": "1.0.0", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "browser_version": "Chromium 117.0", "status": "succeeded",
        "viewport": {"width_px": 1684, "height_px": 1191, "device_pixel_ratio": 2},
        "resource_evidence": [{"resource_id": "area-data", "digest": D, "status": "loaded"}, {"resource_id": "survey-location", "digest": D, "status": "loaded"}, {"resource_id": "noto-font", "digest": D, "status": "loaded"}],
        "output_artifacts": [{"target": "svg", "media_type": "image/svg+xml", "size_bytes": 1024, "composition": "mixed", "artifact_ref": A}, {"target": "png", "media_type": "image/png", "size_bytes": 1024, "composition": "raster", "artifact_ref": A}], "composition": {"map_body": "maplibre-webgl-raster", "overlays": "svg-vector", "svg": "raster-map-with-vector-overlays", "png": "rasterized-composite", "pdf": "not-requested"}, "controls": {"network_policy": "deny-all", "timeout_seconds": 30, "cpu_seconds": 25, "memory_bytes": 1073741824, "temporary_disk_bytes": 268435456}, "warnings": [],
        "render_started_at": "2026-09-15T00:00:00Z", "render_completed_at": "2026-09-15T00:00:05Z", "attestation_algorithm": "hmac-sha256", "renderer_attestation": "0" * 64
    },
}

# A protocol-only input, not a default scene or bundled business data.
VALID_CASES["intent-request"] = json.loads((Path(__file__).parent / "intent-request.valid.json").read_text(encoding="utf-8"))
VALID_CASES["generate-request"]["intent"] = deepcopy(VALID_CASES["intent-request"]["selection"])
VALID_CASES["map-plan"]["theme_tags"] = ["unit-theme"]

# Structural bindings only: no bundled dataset or enabled scene accompanies these values.
VALID_CASES["generate-request"]["template"] = {"namespace": "local", "kind": "map-scenario", "id": "test-scenario", "version": "1.0.0"}
VALID_CASES["generate-request"]["source_bindings"] = [{
    "role": "area-role", "source_ref": A, "path": "not-a-bundled-input.geojson", "format": "geojson",
    "crs": {"authority": "EPSG", "code": "4326"}, "geometry_types": ["polygon"],
    "field_bindings": [{"semantic_role": "thematic-value", "source_field": "value", "value_type": "number"}],
    "unit_bindings": [{"semantic_role": "thematic-value", "unit": "count"}],
    "freshness": {"observed_at": "2026-09-14T00:00:00Z", "max_age_days": 30}, "join": {"required": False},
}]

# Runtime-independent host protocol fixture; no local paths/config/credentials.
VALID_CASES["host-preflight"] = json.loads((Path(__file__).parent / "host-preflight.valid.json").read_text(encoding="utf-8"))

# Scenario constraints are separate from reusable structural request protocols.
VALID_CASES["scenario-capabilities"] = json.loads((Path(__file__).parent / "scenario-capabilities.valid.json").read_text(encoding="utf-8"))

# The registered general-thematic scenario narrows the shared request protocols; synthetic values only.
_general_generate = json.loads((Path(__file__).parent / "raster-formal" / "generate-request.valid.json").read_text(encoding="utf-8"))
_general_generate["goal"] = "编制土地覆盖通用专题图"
_general_generate["template"]["id"] = "general-thematic-map"
_general_generate["template"]["version"] = "3.0.0"
_general_generate["layout_parameters"] = {"rows":1,"columns":1,"legend_mode":"independent"}
_general_generate["panels"] = [{"id":"main-view","source_id":_general_generate["source_bindings"][0]["source_ref"]["id"],"title":_general_generate["goal"]}]
_general_generate["intent"].update({"business_scene": "general_thematic_mapping",
                                    "theme_tags": ["land-cover"], "tasks": ["thematic-map"],
                                    "fields": {"geography": "unit-region", "source": "user-supplied",
                                               "output": "pdf"}})
_general_generate["source_bindings"][0]["data_nature"] = "user-provided"
VALID_CASES["general-generate-request"] = _general_generate

# The registered leadership-visit scenario narrows the shared request envelope for
# itinerary route maps; synthetic values only, no bundled dataset.
_leadership_generate = {
    "schema_version": 1,
    "request_id": "leadership-request-one",
    "project_id": "test-project",
    "goal": "编制领导调研行程路线图",
    "geometry": "vector",
    "sources": [deepcopy(A)],
    "requested_outputs": ["pdf", "png"],
    "subject": {"tenant_id": "test-tenant", "subject_id": "test-subject",
                "approver_subject_id": "synthetic-reviewer", "namespace": "test-project"},
    "idempotency_key": "leadership-req-0001",
    "intent": {
        "business_scene": "leadership_visit",
        "theme_tags": [],
        "tasks": ["visit-route-map"],
        "fields": {"itinerary": "甲地至乙地", "visit-order": "1,2", "route-mode": "road",
                   "geography": "unit-region", "confidentiality": "internal", "output": "pdf"},
    },
    "template": {"namespace": "local", "kind": "map-scenario",
                 "id": "leadership-visit-map", "version": "1.0.0"},
    "run_id": "test-run",
    "audience": "synthetic test only",
    "scope": "project:test-project",
    "environment": "local",
    "requested_at": "2026-11-18T00:00:00Z",
    "allowed_capabilities": ["read", "render-preview", "geo-to-image-pixels",
                             "image-display-bounds", "annotation-layout"],
    "font": {"path": "fixture-project/selected-font.ttf", "family": "Noto Sans CJK SC", "version": "1.0.0"},
    "itinerary_structure": {"source_ref": deepcopy(A), "normalized_ref": deepcopy(A)},
    "basemap": {"mode": "registered-transform", "image_ref": deepcopy(A), "parameters_ref": deepcopy(A)},
    "source_bindings": [{
        "role": "route-stops",
        "source_ref": deepcopy(A),
        "path": "stops.geojson",
        "geometry_types": ["point"],
        "field_bindings": [{"semantic_role": "visit-order", "source_field": "visit_order"},
                           {"semantic_role": "stop-label", "source_field": "stop_name"}],
    }],
    "page_layout": {"model": "image-native", "width_mm": 420, "height_mm": 297, "dpi": 300},
    "annotation_layout": {"seed": 7, "iterations": 200, "gap_px": 8},
}
VALID_CASES["leadership-visit-generate-request"] = _leadership_generate

# Image itinerary portrayal parameters (the template portrayal contract's
# image_itinerary section); synthetic values only.
VALID_CASES["image-itinerary-style"] = {
    "schema_version": 1,
    "groups": [
        {"id": "morning", "label": "上午", "color": "#1769D2"},
        {"id": "afternoon", "label": "下午", "color": "#E43D96"},
        {"id": "default", "label": "行程", "color": "#403B96", "right_offset_px": 12},
    ],
    "default_group": "default",
    "route": {"width_px": 6, "halo_width_px": 2, "right_offset_px": 12,
              "arrows": {"size_px": 8, "spacing_px": 200}},
    "pin": {"radius_px": 12, "font_size_px": 12},
    "callout": {"width_px": 500, "title_font_px": 22, "body_font_px": 14, "padding_px": 8,
                "line_gap_px": 4, "opacity": 0.88, "leader_width_px": 1.5,
                "offset_x_px": 16, "offset_y_px": -16, "font_weight": 700,
                "title_wrap": True, "show_arrival_time": True, "fit_content": False},
    "support_label": {"color": "#E65C6C", "text_color": "#FFFFFF", "point_radius_px": 6,
                      "font_size_px": 14, "padding_px": 4, "opacity": 0.88,
                      "leader_width_px": 1, "offset_x_px": 12, "offset_y_px": -12},
    "numbering": "per-date-group",
    "white_threshold": 245,
}

# Request-level patch subset of image-itinerary-style (leadership-visit
# style_overrides); synthetic values only, all sections optional.
VALID_CASES["image-itinerary-style-override"] = {
    "groups": [
        {"id": "morning", "color": "#228833"},
        {"id": "default", "label": "全部行程", "right_offset_px": 20},
    ],
    "route": {"width_px": 8, "arrows": {"size_px": 10, "spacing_px": 300}},
    "pin": {"radius_px": 14},
    "callout": {"title_font_px": 24, "body_font_px": 16, "opacity": 0.9,
                "title_color": "#FFFFFF"},
    "support_label": {"color": "#C41E3A", "font_size_px": 18},
    "page_furniture": {"title_font_pt": 22, "body_font_pt": 10,
                       "frame_border": {"color": "#1A3A5C", "inner_width_mm": 0.5,
                                        "gap_mm": 1.0, "outer_width_mm": 1.0}},
    "numbering": "global",
    "white_threshold": 240,
}

# ToolGateway capability I/O for the migrated image algorithms (typed request/
# result pairs; digest-bound references, synthetic values only).
AU = {**A, "uri": "data/basemap.png"}
_VALID_PROJECTION_STOPS = [{"feature_id": "stop-1", "visit_order": 1, "position": {"x": 1190.5, "y": 842.5}}]
VALID_CASES["image-projection-request"] = {
    "schema_version": 1,
    "image_ref": AU,
    "parameters_ref": {**A, "uri": "registration.yaml"},
    "stops_ref": {**A, "uri": "data/prepared/route-stops.geojson"},
    "route_ref": {**A, "uri": "data/prepared/route-line.geojson"},
}
VALID_CASES["image-projection-result"] = {
    "schema_version": 1,
    "method": "registered-affine",
    "method_version": "1.0.0",
    "pixel_convention": "image-edge; x-right; y-down; center-offset-applied-once",
    "source_size": {"width_px": 2381, "height_px": 1684},
    "stops": _VALID_PROJECTION_STOPS,
    "routes": [{"feature_id": "leg-1", "parts": [[{"x": 1190.5, "y": 842.5}, {"x": 1290.5, "y": 842.5}]],
                "original_parts": [[{"x": 1190.5, "y": 842.5}, {"x": 1290.5, "y": 842.5}]],
                "outside_vertex_count": 0, "route_mode": "straight_line"}],
}
VALID_CASES["image-display-request"] = {
    "schema_version": 1,
    "image_ref": AU,
    "white_threshold": 245,
}
VALID_CASES["image-display-result"] = {
    "schema_version": 1,
    "display_window": {"x": 60, "y": 60, "width": 2261, "height": 1561},
    "source_size": {"width_px": 2381, "height_px": 1684},
}
VALID_CASES["annotation-layout-request"] = {
    "schema_version": 1,
    "items": [{"id": "callout-1", "anchor_x": 100, "anchor_y": 100, "w": 500, "h": 120},
              {"id": "callout-2", "anchor_x": 300, "anchor_y": 300, "w": 500, "h": 120,
               "fixed": {"x": 310, "y": 310}}],
    "hard_lines": [{"points": [{"x": 0, "y": 0}, {"x": 200, "y": 200}], "width_px": 6}],
    "hard_boxes": [{"x": 88, "y": 88, "w": 24, "h": 36}],
    "canvas": {"width": 2260, "height": 1560},
    "gap_px": 8,
    "seed": 7,
    "iterations": 200,
}
VALID_CASES["annotation-layout-result"] = {
    "schema_version": 1,
    "algorithm": "greedy-sa-v2",
    "status": "placed",
    "assignments": [{"id": "callout-1", "status": "placed", "x": 110, "y": 130,
                     "w": 500, "h": 120, "dx": 10, "dy": 30},
                    {"id": "callout-2", "status": "placed", "x": 310, "y": 310,
                     "w": 500, "h": 120, "dx": 10, "dy": 10}],
    "iterations": 200,
    "seed": 7,
}
VALID_CASES["data-summary-request"] = {
    "schema_version": 1,
    "data_dir": "data",
}
VALID_CASES["data-summary-result"] = {
    "schema_version": 1,
    "data_dir": "data",
    "file_count": 2,
    "categories": [{"category": "document", "count": 1},
                   {"category": "geographic-vector", "count": 1}],
    "summary_md": "# 数据目录内容\n",
}

# Frontend Image Canvas v2 document (the canvas payload itself); synthetic
# millimetre geometry only.
VALID_CASES["frontend-map-document"] = {
    "id": "map-scene-unit-001", "name": "领导调研行程路线图 unit", "category": "leadership_visit",
        "designWidth": 420.0, "designHeight": 297.0,
        "canvasData": {"type": "Grid", "features": [
            {"type": "Rect", "RectIndex": 0, "x": 0.0, "y": 0.0, "w": 420.0, "h": 297.0,
             "fillColor": "#FFFFFF"},
            {"type": "MultiLineString", "RectIndex": 1,
             "coordinates": [[10.0, 10.0], [200.0, 150.0], [400.0, 20.0]],
             "color": "#1769D2", "strokeWidth": 1.5, "strokeDash": "", "closed": False},
            {"type": "MultiPoint", "RectIndex": 2, "coordinates": [[200.0, 150.0]],
             "size": 6.0, "color": "#C41E3A"},
            {"type": "Text", "RectIndex": 3, "x": 100.0, "y": 10.0, "w": 220.0, "h": 12.0,
             "text": "领导调研行程路线图", "fontSize": 10.0, "lineHeight": 1.2,
             "color": "#1A3A5C", "textAlign": "center", "bold": True, "italic": False,
             "underline": False},
        ], "mapData": {"layers": [
            {"id": "basemap", "type": "basemap", "rect_indices": [0]},
            {"id": "route-layer", "type": "route", "rect_indices": [1],
             "fields": ["route_mode", "itinerary_group"]},
            {"id": "stops", "type": "stops", "rect_indices": [2]},
            {"id": "furniture", "type": "furniture", "rect_indices": [3]},
        ]}},
}

_general_create = deepcopy(TEMPLATE_CREATE_REQUEST)
_general_create.update({
    "request_id": "general-template-request",
    "template_id": "general-thematic-map",
    "version": "3.0.0",
    "profile": "general-thematic-authoring",
    "purpose": "通用专题图模板协议请求",
    "targets": ["pdf", "png"],
    "data_nature": "user-provided",
    "source_crs": {"authority": "EPSG", "code": "4326"},
    "display_crs": {"authority": "EPSG", "code": "4326"},
    "role_bindings": {"classified_surface": "legend-sample"},
    "geometry": "raster",
})
VALID_CASES["general-template-create-request"] = _general_create

# Leadership visit template creation request (closed profile, synthetic values only).
_leadership_create = json.loads(json.dumps(VALID_CASES["general-template-create-request"]))
_leadership_create.update({
    "request_id": "leadership-template-request",
    "template_id": "leadership-visit-map",
    "version": "1.0.0",
    "profile": "leadership-visit-authoring",
    "purpose": "领导调研行程路线图模板（合成验收）",
    "geometry": "vector",
    "role_bindings": {"route-stops": "visit-route-sample"},
})
VALID_CASES["leadership-visit-template-create-request"] = _leadership_create

# A1.2 / A2 contracts: design revision, persistent budget, and material
# extraction / adoption. INVALID_CASES are auto-derived below (unknown-field).
VALID_CASES["design-revision-proposal"] = {
    "schema_version": 1, "proposal_id": "proposal-test-001", "run_id": "run-test-001",
    "parent_revision": 1, "changes": {"goal": {"new_value": "Updated map title"}},
    "justification": "Reflect the updated scope",
}
# Design B: same-run data revision (leg re-planning). The outbound declaration
# is protocol data (digest-covered by the G1 approval face via the proposal ref),
# not conversational discipline.
VALID_CASES["data-revision-proposal"] = {
    "schema_version": 1, "proposal_id": "proposal-data-001", "run_id": "run-test-001",
    "parent_revision": 1,
    "changes": {"route_legs": [{"leg_id": "leg-1",
                                "via_points": [{"lon": 120.01, "lat": 30.005}]}]},
    "outbound_declaration": [{"name": "示例途经点", "city": "示例市"}],
    "justification": "Synthetic data-revision acceptance",
}
VALID_CASES["budget-state"] = {
    "schema_version": 1, "saved_at": "2026-11-12T00:00:00Z",
    "max_tool_calls": 20, "max_model_calls": 10, "max_revisions": 3,
    "max_elapsed_seconds": 1200.0, "max_cost_units": 100.0, "max_context_bytes": 1000000,
    "tool_calls": 0, "model_calls": 0, "revisions": 0,
    "cost_units": 0.0, "context_bytes": 0, "started_at": 0.0,
}
VALID_CASES["material-source"] = {
    "schema_version": 1, "source_id": "material-001", "format": "text/plain",
    "origin": {"path_digest": D}, "content_ref": A,
    "extraction_tool": "plain-text-extractor", "extraction_version": "1.0.0",
    "extraction_digest": D,
}
VALID_CASES["extraction-result"] = {
    "schema_version": 1, "result_id": "extract-001", "source_ref": A,
    "extracted_at": "2026-11-12T00:00:00Z", "content_type": "text",
    "source_format": "text/plain",
    "fields": [{"name": "line", "data_type": "string", "nullable": False}],
    "row_count": 1, "byte_length": 5,
    "rows": [{"index": 0, "cells": {"line": "hello"},
              "source_location": {"line_start": 1, "line_end": 1, "byte_offset": 0, "byte_length": 5}}],
    "text_content": "hello", "issues": [], "digest": D,
}
VALID_CASES["data-facts"] = {
    "schema_version": 1, "facts_id": "facts-001", "source_kind": "document",
    "facts_digest": D, "material_refs": [A],
    "observed_dimensions": {"row_count": 1, "byte_size": 5},
}

VALID_CASES["chart"] = {
    "chart_id": "chart-001", "content_id": "industry-chart",
    "kind": "bar-horizontal", "title": "Top industries", "unit": "100M CNY",
    "value_max": 150,
    "series": [
        {"label": "Electronics", "value": 120, "color": "#2288CC"},
        {"label": "Equipment", "value": 150, "color": "#CC3322"},
    ],
}

# S0 advisory segment matching: protocol-only fixtures, no bundled library assets.
VALID_CASES["template-matching-policy"] = {
    "schema_version": 1, "policy_id": "template-matching", "version": "0.1.0",
    "confirmation_status": "pending-business-review", "match_threshold": 0.80,
    "color_delta_e_max": 4.0,
    "defaults_relative_deviation_max": 0.15, "capacity_relative_deviation_max": 0.30,
}
VALID_CASES["template-match-request"] = {
    "schema_version": 1, "kind": "map-layout", "segment": deepcopy(LAYOUT),
}
VALID_CASES["template-match-result"] = {
    "schema_version": 1, "kind": "map-layout", "policy_version": "0.1.0",
    "confirmation_status": "pending-business-review", "match_threshold": 0.80,
    "candidates": [{"template_ref": {"kind": "map-layout", "id": "test-layout", "version": "1.0.0", "digest": D},
                    "score": 0.92, "matched": True}],
}

VALID_CASES["color-redlines-policy"] = {
    "schema_version": 1, "policy_id": "color-redlines", "version": "0.1.0",
    "confirmation_status": "pending-business-review",
    "enforcement": {"ramp_semantics": "blocker", "adjacent_distinguishability": "blocker", "cvd_safety": "warning"},
    "lightness_monotonic_tolerance": 0.5, "adjacent_delta_e_min": 10.0, "cvd_delta_e_min": 12.0,
}

# S1 segment-reference protocol reservation: referenced layout, embedded cartography.
# Additive constants — the canonical VALID_CASES stay fully embedded so every existing
# consumer (compose_scenario, lock fixtures) passes unchanged. Runtime admission of
# referenced packages stays closed until S2 wires the validate/publish chain.
SEGMENT_REF_LAYOUT = {"kind": "map-layout", "id": "test-layout", "version": "1.0.0", "digest": D}
REFERENCED_SCENARIO = deepcopy(VALID_CASES["scenario"])
REFERENCED_SCENARIO["embedded"].pop("layout")
REFERENCED_SCENARIO["segment_refs"] = {"layout": deepcopy(SEGMENT_REF_LAYOUT)}
REFERENCED_LOCK = deepcopy(VALID_CASES["dependency-lock"])
REFERENCED_LOCK["dependencies"] = [deepcopy(SEGMENT_REF_LAYOUT)]

# Declared intentional containment (additive layout protocol, map-layout design §8.3).
# Legal sample: a north arrow fully enclosed by the map frame and explicitly declared.
# Kept outside VALID_CASES so the schema-coverage invariant (registry schemas == fixture
# keys) stays exact; the resolver-level illegal variants live in test_layout_contract.
LAYOUT_CONTAINMENT_VALID = {
    **deepcopy(VALID_CASES["layout"]),
    "layout_id": "a3-landscape-contained-north",
    "frames": [
        {"id": "main-map", "content_id": "main-view", "type": "map", "coordinate_space": "page",
         "bounds": [20, 30, 380, 230], "overflow_policy": "clip"},
        {"id": "north", "content_id": "north", "type": "north-arrow", "coordinate_space": "page",
         "bounds": [360, 40, 30, 30], "overflow_policy": "reject", "inside_frame": "main-map"},
    ],
}

VALID_CASES["reference-intake"] = {
    "schema_version": 1, "intake_id": "intake-fixture", "source_image": deepcopy(A),
    "width_px": 64, "height_px": 64, "format": "PNG", "color_mode": "RGB",
    "license": "CC-BY-4.0", "byte_size": 1024, "dpi": 300.0,
}

VALID_CASES["design-requirement"] = {
    "schema_version": 1, "requirement_id": "req-fixture", "revision": 1, "object_scope": "layout",
    "conditions": [
        {"id": "c-width", "strength": "hard", "source_ref": "user:msg-1",
         "predicate": {"kind": "measure", "path": "/canvas/width", "op": "eq", "value": 420, "unit": "mm"}},
        {"id": "c-count", "strength": "hard", "source_ref": "user:msg-1",
         "predicate": {"kind": "count", "role": "main-map", "op": "eq", "value": 2}},
    ],
}

VALID_CASES["design-resolution-result"] = {
    "schema_version": 1, "requirement_id": "req-fixture", "revision": 1, "branch": "reuse",
    "assessments": [
        {"candidate_ref": deepcopy(T), "usable": True, "structural_aggregate": "satisfied",
         "parameter_domain": "not-applicable", "execution_admission": "allowed",
         "validation_coverage": "covered"},
    ],
}

VALID_CASES["publication-request"] = {
    "schema_version": 1, "publication_request_id": "pubreq-fixture", "request_id": "seg-request-one",
    "kind": "map-style", "intent_state": "ready",
    "target": {"repository_scope": "local:templates", "namespace": "local",
               "template_id": "seg-style", "version": "1.0.0"},
}

VALID_CASES["draft-import-record"] = {
    "schema_version": 1, "import_id": "import-seg-publish-b", "source_run_id": "seg-request-one",
    "source_draft_digest": D, "source_evidence_digest": D, "source_evidence_id": "seg-validation-one",
    "imported_design_digest": D, "created_at": "2026-11-23T00:00:00Z",
}

VALID_CASES["nlp-requirement-candidate"] = {
    "schema_version": 1, "source_ref": "artifact:msg-1",
    "claims": [
        {"id": "c-count", "origin": "user-stated", "strength": "hard",
         "predicate": {"kind": "count", "role": "main-map", "op": "eq", "value": 2},
         "source_locator": {"start": 0, "end": 4}},
    ],
}

INVALID_CASES = {}
for name, case in VALID_CASES.items():
    invalid = deepcopy(case)
    invalid["unexpected_parallel_protocol"] = True
    INVALID_CASES[name] = invalid
# generate-request is an OPEN envelope: an unknown field is admitted (unknown-field closure
# is the profile's job, tested via general-generate-request). Its invalid fixture must
# violate an ENVELOPE-level constraint instead — here, the required geometry field.
INVALID_CASES["generate-request"] = {k: v for k, v in deepcopy(VALID_CASES["generate-request"]).items()
                                     if k != "geometry"}
SEMANTIC_INVALID_CASES = {}

_invalid_manifest = deepcopy(VALID_CASES["manifest"])
_invalid_manifest["business_contracts"].pop("quality_gates")
SEMANTIC_INVALID_CASES["manifest-contract-gap"] = ("manifest", _invalid_manifest)

_invalid_scenario = deepcopy(VALID_CASES["scenario"])
_invalid_scenario["owned_segments"] = list(reversed(_invalid_scenario["owned_segments"]))
SEMANTIC_INVALID_CASES["scenario-contract-order"] = ("scenario", _invalid_scenario)

_invalid_cartography = deepcopy(VALID_CASES["style"])
_invalid_cartography["defaults"]["renderer_script"] = "dynamic()"
SEMANTIC_INVALID_CASES["cartography-open-defaults"] = ("style", _invalid_cartography)

_invalid_layout = deepcopy(VALID_CASES["layout"])
_invalid_layout["frames"][0]["bounds"] = [-1, 30, 380, 230]
SEMANTIC_INVALID_CASES["layout-non-page-bounds"] = ("layout", _invalid_layout)

_invalid_containment = deepcopy(LAYOUT_CONTAINMENT_VALID)
_invalid_containment["frames"][1]["inside_frame"] = "Not A Valid Identifier"
SEMANTIC_INVALID_CASES["layout-containment-invalid-identifier"] = ("layout", _invalid_containment)

# Constraint single authority: allowed sets and numeric ranges live ONLY in
# validation.rules. parameter_definitions must not carry a second copy.
_duplicated_constraint = deepcopy(VALID_CASES["map-expression"])
_duplicated_constraint["parameter_definitions"][0]["maximum"] = 12
SEMANTIC_INVALID_CASES["map-expression-duplicated-constraint"] = ("map-expression", _duplicated_constraint)

_invalid_portrayal = deepcopy(VALID_CASES["portrayal"])
_invalid_portrayal["layers"][0]["map_expression_ref"]["version"] = "latest"
SEMANTIC_INVALID_CASES["portrayal-floating-expression"] = ("portrayal", _invalid_portrayal)

_invalid_delivery = deepcopy(VALID_CASES["delivery"])
_invalid_delivery["targets"][0]["production_ready"] = True
SEMANTIC_INVALID_CASES["delivery-production-claim"] = ("delivery", _invalid_delivery)

_invalid_quality_gates = deepcopy(VALID_CASES["quality-gates"])
_invalid_quality_gates["checks"][0]["strength"] = "hard_rule"
SEMANTIC_INVALID_CASES["quality-gates-platform-override"] = ("quality-gates", _invalid_quality_gates)

_invalid_expression = deepcopy(VALID_CASES["map-expression"])
_invalid_expression["script"] = "import os"
SEMANTIC_INVALID_CASES["map-expression-executable-content"] = ("map-expression", _invalid_expression)

_invalid_index = deepcopy(VALID_CASES["template-index"])
_invalid_index["entries"][0]["status"] = "draft"
SEMANTIC_INVALID_CASES["template-index-unpublished-entry"] = ("template-index", _invalid_index)

_invalid_lock = deepcopy(VALID_CASES["dependency-lock"])
_invalid_lock["resources"][0]["version"] = "^1.0"
SEMANTIC_INVALID_CASES["dependency-lock-floating-version"] = ("dependency-lock", _invalid_lock)

_invalid_publication = deepcopy(VALID_CASES["publication-receipt"])
_invalid_publication["command"] = "publish --force"
SEMANTIC_INVALID_CASES["publication-receipt-command"] = ("publication-receipt", _invalid_publication)

_invalid_pub_object = deepcopy(VALID_CASES["template-publication"])
_invalid_pub_object.pop("repository_root")
SEMANTIC_INVALID_CASES["template-publication-missing-root"] = ("template-publication", _invalid_pub_object)

_invalid_template_request = deepcopy(VALID_CASES["template-create-request"])
_invalid_template_request["contains_production_data"] = "yes"
SEMANTIC_INVALID_CASES["template-create-request-invalid-data-flag"] = ("template-create-request", _invalid_template_request)

_invalid_template_analysis = deepcopy(VALID_CASES["template-analysis"])
_invalid_template_analysis["evidence_records"][4].pop("rationale")
SEMANTIC_INVALID_CASES["template-analysis-suggestion-without-rationale"] = ("template-analysis", _invalid_template_analysis)

_invalid_prototype = deepcopy(VALID_CASES["prototype-description"])
_invalid_prototype["renderer_execution"] = "succeeded"
SEMANTIC_INVALID_CASES["prototype-description-false-render-claim"] = ("prototype-description", _invalid_prototype)

_invalid_matching_policy = deepcopy(VALID_CASES["template-matching-policy"])
_invalid_matching_policy["match_threshold"] = 1.5
SEMANTIC_INVALID_CASES["template-matching-policy-threshold-range"] = ("template-matching-policy", _invalid_matching_policy)

_invalid_match_request = deepcopy(VALID_CASES["template-match-request"])
_invalid_match_request["kind"] = "map-scenario"
SEMANTIC_INVALID_CASES["template-match-request-scenario-kind"] = ("template-match-request", _invalid_match_request)

_invalid_match_result = deepcopy(VALID_CASES["template-match-result"])
_invalid_match_result["candidates"][0]["score"] = 1.2
SEMANTIC_INVALID_CASES["template-match-result-score-range"] = ("template-match-result", _invalid_match_result)

_invalid_scenario_kind = deepcopy(REFERENCED_SCENARIO)
_invalid_scenario_kind["segment_refs"]["layout"]["kind"] = "map-scenario"
SEMANTIC_INVALID_CASES["scenario-segment-ref-kind-boundary"] = ("scenario", _invalid_scenario_kind)

_invalid_scenario_coverage = deepcopy(REFERENCED_SCENARIO)
_invalid_scenario_coverage["segment_refs"].pop("layout")
SEMANTIC_INVALID_CASES["scenario-segment-source-missing"] = ("scenario", _invalid_scenario_coverage)

_invalid_scenario_segment = deepcopy(REFERENCED_SCENARIO)
_invalid_scenario_segment["segment_refs"]["portrayal"] = deepcopy(SEGMENT_REF_LAYOUT)
SEMANTIC_INVALID_CASES["scenario-segment-ref-unknown-segment"] = ("scenario", _invalid_scenario_segment)

_invalid_create_ref_kind = deepcopy(VALID_CASES["template-create-request"])
_invalid_create_ref_kind["segment_refs"] = {"layout": {**deepcopy(SEGMENT_REF_LAYOUT), "kind": "map-scenario"}}
SEMANTIC_INVALID_CASES["template-create-request-segment-ref-kind"] = ("template-create-request", _invalid_create_ref_kind)

_invalid_create_ref_segment = deepcopy(VALID_CASES["template-create-request"])
_invalid_create_ref_segment["segment_refs"] = {"portrayal": deepcopy(SEGMENT_REF_LAYOUT)}
SEMANTIC_INVALID_CASES["template-create-request-segment-ref-unknown"] = ("template-create-request", _invalid_create_ref_segment)

# P4: project-level segment selection on the generate request. Legal sample plus
# kind-boundary / unknown-segment / unpinned / empty refusals (same shape and kind
# binding as scenario.segment_refs and template-create-request.segment_refs).
SEGMENT_REF_STYLE = {"kind": "map-style", "id": "test-style", "version": "1.0.0", "digest": D}
GENERATE_REQUEST_SEGMENT_REFS = deepcopy(VALID_CASES["generate-request"])
GENERATE_REQUEST_SEGMENT_REFS["segment_refs"] = {"layout": deepcopy(SEGMENT_REF_LAYOUT),
                                                 "style": deepcopy(SEGMENT_REF_STYLE)}

_invalid_generate_ref_kind = deepcopy(GENERATE_REQUEST_SEGMENT_REFS)
_invalid_generate_ref_kind["segment_refs"]["layout"]["kind"] = "map-scenario"
SEMANTIC_INVALID_CASES["generate-request-segment-ref-kind"] = ("generate-request", _invalid_generate_ref_kind)

_invalid_generate_ref_segment = deepcopy(GENERATE_REQUEST_SEGMENT_REFS)
_invalid_generate_ref_segment["segment_refs"]["portrayal"] = deepcopy(SEGMENT_REF_LAYOUT)
SEMANTIC_INVALID_CASES["generate-request-segment-ref-unknown"] = ("generate-request", _invalid_generate_ref_segment)

_invalid_generate_ref_unpinned = deepcopy(GENERATE_REQUEST_SEGMENT_REFS)
_invalid_generate_ref_unpinned["segment_refs"]["layout"].pop("digest")
SEMANTIC_INVALID_CASES["generate-request-segment-ref-unpinned"] = ("generate-request", _invalid_generate_ref_unpinned)

_invalid_generate_ref_empty = deepcopy(GENERATE_REQUEST_SEGMENT_REFS)
_invalid_generate_ref_empty["segment_refs"] = {}
SEMANTIC_INVALID_CASES["generate-request-segment-ref-empty"] = ("generate-request", _invalid_generate_ref_empty)

# P6 measurement contracts: discriminated unit, closed kind, precise rule binding.
_invalid_measurement_kind = {"kind": "physical-cm", "value": 6}
SEMANTIC_INVALID_CASES["symbol-measurement-unknown-kind"] = ("symbol-measurement", _invalid_measurement_kind)

_invalid_measurement_missing_rule = {"kind": "reference-design-px", "value": 6}
SEMANTIC_INVALID_CASES["symbol-measurement-reference-missing-rule"] = ("symbol-measurement", _invalid_measurement_missing_rule)

_invalid_measurement_physical_extra = {"kind": "physical-pt", "value": 12, "rule_ref": deepcopy(A)}
SEMANTIC_INVALID_CASES["symbol-measurement-physical-extra-field"] = ("symbol-measurement", _invalid_measurement_physical_extra)

_invalid_measurement_negative = {"kind": "physical-mm", "value": -1}
SEMANTIC_INVALID_CASES["symbol-measurement-negative-value"] = ("symbol-measurement", _invalid_measurement_negative)

_invalid_rule_function = deepcopy(VALID_CASES["measurement-rule"])
_invalid_rule_function["scale_function"] = "linear-no-floor"
SEMANTIC_INVALID_CASES["measurement-rule-unknown-function"] = ("measurement-rule", _invalid_rule_function)

_invalid_rule_reference = deepcopy(VALID_CASES["measurement-rule"])
_invalid_rule_reference["reference_width_px"] = 0
SEMANTIC_INVALID_CASES["measurement-rule-zero-reference"] = ("measurement-rule", _invalid_rule_reference)

_invalid_card_wrap = deepcopy(VALID_CASES["card-parameters"])
_invalid_card_wrap["title"]["wrap_mode"] = "auto-shrink"
SEMANTIC_INVALID_CASES["card-parameters-unknown-wrap-mode"] = ("card-parameters", _invalid_card_wrap)

_invalid_card_width = deepcopy(VALID_CASES["card-parameters"])
_invalid_card_width["sizing"]["width"].pop("limit")
SEMANTIC_INVALID_CASES["card-parameters-width-missing-limit"] = ("card-parameters", _invalid_card_width)

_invalid_card_bag = deepcopy(VALID_CASES["card-parameters"])
_invalid_card_bag["extra_knob"] = 1
SEMANTIC_INVALID_CASES["card-parameters-open-extension-bag"] = ("card-parameters", _invalid_card_bag)

_invalid_component_type = deepcopy(VALID_CASES["component-definition"])
_invalid_component_type["type"] = "map-card"
SEMANTIC_INVALID_CASES["component-definition-unknown-type"] = ("component-definition", _invalid_component_type)

_invalid_placement_mode = deepcopy(VALID_CASES["annotation-placement"])
_invalid_placement_mode["mode"] = "auto"
SEMANTIC_INVALID_CASES["annotation-placement-unknown-mode"] = ("annotation-placement", _invalid_placement_mode)

_invalid_basemap_threshold = deepcopy(VALID_CASES["basemap-display"])
_invalid_basemap_threshold["crop"]["parameters"]["white_threshold"] = 300
SEMANTIC_INVALID_CASES["basemap-display-threshold-range"] = ("basemap-display", _invalid_basemap_threshold)

_invalid_redlines_enforcement = deepcopy(VALID_CASES["color-redlines-policy"])
_invalid_redlines_enforcement["enforcement"]["cvd_safety"] = "sometimes"
SEMANTIC_INVALID_CASES["color-redlines-policy-enforcement-enum"] = ("color-redlines-policy", _invalid_redlines_enforcement)

_invalid_redlines_threshold = deepcopy(VALID_CASES["color-redlines-policy"])
_invalid_redlines_threshold["adjacent_delta_e_min"] = 150.0
SEMANTIC_INVALID_CASES["color-redlines-policy-threshold-range"] = ("color-redlines-policy", _invalid_redlines_threshold)

_invalid_template_brief = deepcopy(VALID_CASES["template-brief"])
_invalid_template_brief["kind"] = "map-style"
SEMANTIC_INVALID_CASES["template-brief-wrong-kind"] = ("template-brief", _invalid_template_brief)

_invalid_validation_evidence = deepcopy(VALID_CASES["template-validation-evidence"])
_invalid_validation_evidence.pop("render_receipt_ref")
SEMANTIC_INVALID_CASES["template-validation-passed-without-receipt"] = ("template-validation-evidence", _invalid_validation_evidence)

# The raster fixture-render binding requires its frozen scene reference; the
# browser binding must stay closed (no raster-only fields may leak into it).
_raster_binding = {
    "renderer_id": "rasterio-matplotlib-page", "renderer_profile_digest": D,
    "adapter_version": "1.0.0", "renderer_version": "1.0.0", "renderer_code_digest": D,
    "runtime": {name: "1.0.0" for name in ("python", "rasterio", "gdal", "numpy",
                                             "matplotlib", "pillow", "freetype", "fonttools", "zlib")},
    "environment_fingerprint": D,
}
_invalid_raster_evidence = deepcopy(VALID_CASES["template-validation-evidence"])
_invalid_raster_evidence["renderer"] = deepcopy(_raster_binding)
SEMANTIC_INVALID_CASES["template-validation-raster-without-scene"] = ("template-validation-evidence", _invalid_raster_evidence)

_invalid_mixed_evidence = deepcopy(VALID_CASES["template-validation-evidence"])
_invalid_mixed_evidence["renderer"] = {**deepcopy(_raster_binding), "maplibre_version": "3.6.0"}
_invalid_mixed_evidence["render_scene_ref"] = deepcopy(A)
SEMANTIC_INVALID_CASES["template-validation-mixed-renderer-binding"] = ("template-validation-evidence", _invalid_mixed_evidence)

_invalid_delivery_manifest_time = deepcopy(VALID_CASES["delivery-manifest"])
_invalid_delivery_manifest_time["delivered_at"] = "2026-09-21T00:00:00Z"
SEMANTIC_INVALID_CASES["delivery-manifest-post-commit-field"] = (
    "delivery-manifest", _invalid_delivery_manifest_time
)

_invalid_delivery_manifest_artifacts = deepcopy(VALID_CASES["delivery-manifest"])
_invalid_delivery_manifest_artifacts["artifacts"] = [
    item for item in _invalid_delivery_manifest_artifacts["artifacts"] if item["format"] != "png"
]
SEMANTIC_INVALID_CASES["delivery-manifest-missing-png"] = (
    "delivery-manifest", _invalid_delivery_manifest_artifacts
)

_invalid_delivery_manifest_limitation = deepcopy(VALID_CASES["delivery-manifest"])
_invalid_delivery_manifest_limitation["limitations"] = []
SEMANTIC_INVALID_CASES["delivery-manifest-empty-limitations"] = (
    "delivery-manifest", _invalid_delivery_manifest_limitation
)

_invalid_delivery_receipt_time = deepcopy(VALID_CASES["delivery-receipt"])
_invalid_delivery_receipt_time.pop("delivered_at")
SEMANTIC_INVALID_CASES["delivery-receipt-missing-delivered-at"] = (
    "delivery-receipt", _invalid_delivery_receipt_time
)

_invalid_delivery_receipt_status = deepcopy(VALID_CASES["delivery-receipt"])
_invalid_delivery_receipt_status["status"] = "pending"
SEMANTIC_INVALID_CASES["delivery-receipt-not-committed"] = (
    "delivery-receipt", _invalid_delivery_receipt_status
)

_invalid_succeeded_attempt = deepcopy(VALID_CASES["render-attempt"])
_invalid_succeeded_attempt.pop("render_receipt_ref")
SEMANTIC_INVALID_CASES["render-attempt-succeeded-without-receipt"] = (
    "render-attempt", _invalid_succeeded_attempt
)

_invalid_failed_attempt = deepcopy(VALID_CASES["render-attempt"])
for _field in ("renderer_execution_digest", "resource_set_digest", "output_artifacts", "render_receipt_ref"):
    _invalid_failed_attempt.pop(_field)
_invalid_failed_attempt["status"] = "failed"
_invalid_failed_attempt["retryable"] = False
SEMANTIC_INVALID_CASES["render-attempt-failed-without-error"] = (
    "render-attempt", _invalid_failed_attempt
)

_invalid_formal_evidence_targets = deepcopy(VALID_CASES["formal-render-evidence"])
_invalid_formal_evidence_targets["required_targets"] = ["pdf"]
SEMANTIC_INVALID_CASES["formal-render-evidence-missing-png"] = (
    "formal-render-evidence", _invalid_formal_evidence_targets
)

_invalid_formal_evidence_notice = deepcopy(VALID_CASES["formal-render-evidence"])
_invalid_formal_evidence_notice["scenario_notice"] = ""
SEMANTIC_INVALID_CASES["formal-render-evidence-empty-notice"] = (
    "formal-render-evidence", _invalid_formal_evidence_notice
)

_invalid_delivery_transaction_commit = deepcopy(VALID_CASES["delivery-transaction"])
_invalid_delivery_transaction_commit["status"] = "committed"
_invalid_delivery_transaction_commit.pop("committed_at")
_invalid_delivery_transaction_commit.pop("receipt_ref")
SEMANTIC_INVALID_CASES["delivery-transaction-commit-without-time"] = (
    "delivery-transaction", _invalid_delivery_transaction_commit
)

_invalid_delivery_transaction_phase = deepcopy(VALID_CASES["delivery-transaction"])
_invalid_delivery_transaction_phase["phase"] = "staging"
SEMANTIC_INVALID_CASES["delivery-transaction-receipt-in-staging"] = (
    "delivery-transaction", _invalid_delivery_transaction_phase
)
# Capability authorization remains fail-closed despite generic request structure.
SEMANTIC_INVALID_CASES["scenario-capabilities-default-allow-forbidden"] = (
    "scenario-capabilities", json.loads((Path(__file__).parent / "scenario-capabilities.invalid.json").read_text(encoding="utf-8"))
)

# ADR-001 §9.5 项④: geometry is a data-adaptation variant of one capability profile.
# Synthetic single-profile policy: the shared segment is declared once and every variant
# carries only what actually differs per geometry.
VARIANT_CAPABILITIES_POLICY = {
    "schema_version": 1, "version": "9.9.0", "default": "deny",
    "profiles": [{
        "id": "unit-scenario", "version": "9.9.0", "implementation": "general-thematic",
        "routes": ["create-template", "generate-map"],
        "request_schemas": {"create-template": "general-template-create-request",
                            "generate-map": "general-generate-request"},
        "intent_constraints": {"business_scene": "general_thematic_mapping",
                               "allowed_tasks": ["thematic-map"],
                               "allowed_theme_tags": ["land-cover"], "required_theme_tags": []},
        "data_nature": "user-provided", "production_enabled": False,
        "notice": "单元测试能力档案，不代表任何真实业务准入",
        "licenses": ["user-declared-source-license"],
        "internal_field_names": [],
        "geometry_variants": [
            {"geometry": "raster",
             "template": {"kind": "map-scenario", "id": "unit-scenario-map", "version": "9.9.0"},
             "authoring_profile": "unit-raster-authoring",
             "renderer_id": "rasterio-matplotlib-page"},
            {"geometry": "vector",
             "template": {"kind": "map-scenario", "id": "unit-scenario-map", "version": "9.8.0"},
             "authoring_profile": "unit-vector-authoring",
             "renderer_id": "matplotlib-vector-page"},
        ],
    }],
}


def _variant_policy(mutate):
    policy = deepcopy(VARIANT_CAPABILITIES_POLICY)
    mutate(policy)
    return policy


def _unknown_geometry(policy):
    policy["profiles"][0]["geometry_variants"][0]["geometry"] = "point-cloud"


def _variant_missing_renderer(policy):
    policy["profiles"][0]["geometry_variants"][1].pop("renderer_id")


def _variant_legacy_geometry_field(policy):
    # The pre-项④ per-geometry field must not be re-declared inside a variant.
    policy["profiles"][0]["geometry_variants"][0]["template_geometry"] = "raster"


def _profile_level_legacy_fields(policy):
    # Nor at profile level: the old shape is not admitted in parallel with the new one.
    profile = policy["profiles"][0]
    variant = profile["geometry_variants"][0]
    profile["template"] = deepcopy(variant["template"])
    profile["authoring_profile"] = variant["authoring_profile"]
    profile["template_geometry"] = variant["geometry"]
    profile["renderer_id"] = variant["renderer_id"]
    profile["allowed_geometries"] = [variant["geometry"]]


def _no_geometry_variant(policy):
    policy["profiles"][0]["geometry_variants"] = []


SEMANTIC_INVALID_CASES["scenario-capabilities-variant-unknown-geometry"] = (
    "scenario-capabilities", _variant_policy(_unknown_geometry))
SEMANTIC_INVALID_CASES["scenario-capabilities-variant-missing-renderer"] = (
    "scenario-capabilities", _variant_policy(_variant_missing_renderer))
SEMANTIC_INVALID_CASES["scenario-capabilities-variant-legacy-geometry-field"] = (
    "scenario-capabilities", _variant_policy(_variant_legacy_geometry_field))
SEMANTIC_INVALID_CASES["scenario-capabilities-profile-level-legacy-geometry-fields"] = (
    "scenario-capabilities", _variant_policy(_profile_level_legacy_fields))
SEMANTIC_INVALID_CASES["scenario-capabilities-profile-without-geometry-variant"] = (
    "scenario-capabilities", _variant_policy(_no_geometry_variant))

_legacy_theme = deepcopy(VALID_CASES["intent-request"])
_legacy_theme["selection"]["theme"] = "untyped topic"
SEMANTIC_INVALID_CASES["intent-request-legacy-theme"] = ("intent-request", _legacy_theme)
_wrong_topic = deepcopy(VALID_CASES["map-intent"])
_wrong_topic["theme_tags"] = ["Topic label with spaces"]
SEMANTIC_INVALID_CASES["map-intent-topic-label-as-id"] = ("map-intent", _wrong_topic)
_missing_scene = deepcopy(VALID_CASES["map-intent"])
_missing_scene["business_scene"] = None
SEMANTIC_INVALID_CASES["map-intent-resolved-without-scene"] = ("map-intent", _missing_scene)
_old_hint = deepcopy(VALID_CASES["general-generate-request"])
_old_hint["scene_hint"] = "government_thematic"
SEMANTIC_INVALID_CASES["generate-request-legacy-scene-hint"] = ("general-generate-request", _old_hint)

# Missing geometry field: generate-request now requires explicit geometry.
_missing_geom = deepcopy(VALID_CASES["general-generate-request"])
_missing_geom.pop("geometry")
SEMANTIC_INVALID_CASES["generate-request-missing-geometry"] = ("generate-request", _missing_geom)

# MCP/raster protocols are fixtures only, not registered scenarios or operator configuration.
for _name in ("raster-input", "geospatial-mcp-config", "geospatial-request", "geospatial-wire", "geospatial-result"):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# Static raster protocols are synthetic examples, never runtime inputs.
for _name in ('raster-classification-request', 'raster-classification-answers', 'raster-prepared-data', 'raster-map-body'):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# Internal page output is not a formal rendering attestation or delivery.
for _name in ("page-request", "page-output"):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# Registered raster backdrop component. The invalid fixture mixes both registration
# parameterizations — one geo-to-pixel affine, declared exactly one way.
VALID_CASES["basemap"] = json.loads((Path(__file__).parent / "basemap.valid.json").read_text(encoding="utf-8"))
INVALID_CASES["basemap"] = json.loads((Path(__file__).parent / "basemap.invalid.json").read_text(encoding="utf-8"))

# Shared categorical portrayal does not register a business scenario or renderer receipt.
for _name in ("map-expression-catalog", "resolved-portrayal"):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))
for _name, _schema in (("portrayal-raster", "portrayal"), ("map-expression-raster", "map-expression")):
    SEMANTIC_INVALID_CASES[_name] = (_schema, json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8")))

# S1-A/B contracts are strict synthetic fixtures, not enabled multi-panel execution.
for _name in ("page-bindings", "resolved-appearance", "category-counts"):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

for _name in ("grid-parameters", "bundle-inputs"):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# S2 strict synthetic vector protocols (not approval or admission evidence).
for _name in ('vector-input', 'vector-encoding', 'vector-prepared-data'):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# ADR-001 stage 2: backend-independent encoding IR (key_mode-based, geometry-decoupled).
# The invalid fixture is a scaling encoding on a raster-cell carrier — rejected by the
# combination matrix (scaling requires a point carrier), not by a structural defect.
VALID_CASES['encoding-ir'] = json.loads((Path(__file__).parent / "encoding-ir.valid.json").read_text(encoding="utf-8"))
INVALID_CASES['encoding-ir'] = json.loads((Path(__file__).parent / "encoding-ir.invalid.json").read_text(encoding="utf-8"))

# Geometry-vs-panels conflict: explicit geometry field must match the panel/source family.
# These are rejected by the allOf conditional + oneOf in general-generate-request.schema.json
# (the open generate-request envelope no longer carries body-field constraints).
_raster_geom_vector_panels = deepcopy(VALID_CASES["general-generate-request"])
_p = {"id": "conflict-view", "source_id": "raster-source", "title": "Conflict", "extent": [-1, -1, 2, 2],
      "encoding": deepcopy(VALID_CASES["vector-encoding"])}
_raster_geom_vector_panels["vector_panels"] = [_p]
SEMANTIC_INVALID_CASES["generate-request-raster-geometry-with-vector-panels"] = ("general-generate-request", _raster_geom_vector_panels)

_vector_geom_raster_panels = deepcopy(VALID_CASES["general-generate-request"])
_vector_geom_raster_panels["geometry"] = "vector"
for _f in ("source_bindings", "prepared_raster_bindings"):
    _vector_geom_raster_panels.pop(_f, None)
SEMANTIC_INVALID_CASES["generate-request-vector-geometry-with-raster-panels"] = ("general-generate-request", _vector_geom_raster_panels)

# Capability roadmap declares queueable not-implemented features (admission_class taxonomy).
for _name in ("capability-roadmap",):
    VALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# Vector variants of unified request schemas (not cacheable as inline JSON fixtures —
# they are programmatically derived from raster fixtures above). Variant cases are
# keyed by schema name + ".vector" and live outside VALID_CASES/INVALID_CASES so the
# schema-coverage invariant (registry schemas == fixture keys) stays exact.
VARIANT_CASES = {}
VARIANT_INVALID_CASES = {}

_vector_tc = deepcopy(VALID_CASES["general-template-create-request"])
_vector_tc.update(version="4.0.0", profile="general-vector-authoring", geometry="vector", role_bindings={"thematic_features":"legend-sample"})
_vector_tc["geometry"] = "vector"
VARIANT_CASES["general-template-create-request.vector"] = _vector_tc
VARIANT_INVALID_CASES["general-template-create-request.vector"] = {**deepcopy(_vector_tc), "geometry": "raster"}

_vector_gr = deepcopy(VALID_CASES["general-generate-request"])
for _field in ("source_bindings", "prepared_raster_bindings", "panels", "geometry"):
    _vector_gr.pop(_field, None)
_vector_gr["template"]["version"] = "4.0.0"
_vector_gr["geometry"] = "vector"
_vector_source = deepcopy(VALID_CASES["vector-input"])
_vector_source["data_nature"] = "user-provided"
_vector_gr.update(vector_sources=[_vector_source], vector_panels=[{"id": "main-view", "source_id": "source-a", "title": _vector_gr["goal"], "extent": [-1,-1,2,2], "encoding": deepcopy(VALID_CASES["vector-encoding"])}])
VARIANT_CASES["general-generate-request.vector"] = _vector_gr
VARIANT_INVALID_CASES["general-generate-request.vector"] = {**deepcopy(_vector_gr), "unexpected": True}

# Vector geometry variants of the unified page contracts (variant case, not a schema key).
for _name in ("page-request.vector", "page-output.vector", "page-request.canvas"):
    VARIANT_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.valid.json").read_text(encoding="utf-8"))
    VARIANT_INVALID_CASES[_name] = json.loads((Path(__file__).parent / f"{_name}.invalid.json").read_text(encoding="utf-8"))

# Affine registration variant of the backdrop component (explicit registration document).
VARIANT_CASES["basemap.affine"] = json.loads((Path(__file__).parent / "basemap.affine.valid.json").read_text(encoding="utf-8"))
VARIANT_INVALID_CASES["basemap.affine"] = json.loads((Path(__file__).parent / "basemap.affine.invalid.json").read_text(encoding="utf-8"))

# A3.1 fixtures use explicit business designs; old request shapes are rejected.
from tests.fixtures.thematic_cases import canonical_request, RASTER_DESIGN
for _name in ('generate-request','general-generate-request'):
    canonical_request(VALID_CASES[_name])
for _name, _value in VARIANT_CASES.items():
    if 'request_id' in _value and 'goal' in _value:canonical_request(_value)
_plan=VALID_CASES['map-plan']
_plan['schema_version']=4
_plan['decisions']={'title':'Protocol title','legend_source':'actual-encoding','renderer_id':'rasterio-matplotlib-page','legend_capacity':12,
    'thematic_views':[{'view_id':'main-view','source_id':'ref-a','data_ref':deepcopy(A),'design':deepcopy(RASTER_DESIGN),'encoding':None,'statistics':None}]}
VALID_CASES['thematic-design']=deepcopy(RASTER_DESIGN)
VALID_CASES['thematic-attribute-join']={'source_id':'table-one','path':'table.csv','digest':A['digest'],'size_bytes':50,
    'geometry_key':'region','table_key':'region','fields':[{'column':'value','field':'population','value_type':'number'}],
    'coverage':'exact','missing_policy':'reject'}
for _n in ('thematic-design','thematic-attribute-join'):
    INVALID_CASES[_n]={**deepcopy(VALID_CASES[_n]),'unexpected':True}
if 'design-revision-proposal' in VALID_CASES:
    _c=VALID_CASES['design-revision-proposal']['changes']
    if 'goal' in _c:_c['map_title']=_c.pop('goal')

VALID_CASES["map-plan"]["bindings"] = deepcopy(VALID_CASES["page-bindings"])
VALID_CASES["map-plan"]["layout_parameters"] = {"rows":1,"columns":1,"legend_mode":"independent"}

from carto_core.compiler.portrayal_resolver import expression_reference
VALID_CASES["map-plan"]["decisions"]["thematic_views"][0]["expression_ref"] = expression_reference("categorical")

VALID_CASES['product-review']={'schema_version':1,'review_id':'review-one','run_id':'run-one','project_id':'project-one',
    'report_ref':deepcopy(A),'approval':deepcopy(VALID_CASES['approval-receipt']),'reviewed_at':'2026-11-13T00:00:00Z'}
INVALID_CASES['product-review']={**deepcopy(VALID_CASES['product-review']),'unexpected':True}
VALID_CASES['design-review-record']={'schema_version':1,'review_id':'design-review-one','run_id':'run-one','project_id':'project-one',
    'candidate_ref':deepcopy(A),'preview_evidence_ref':deepcopy(A),'approval':deepcopy(VALID_CASES['approval-receipt']),'reviewed_at':'2026-11-13T00:00:00Z'}
INVALID_CASES['design-review-record']={**deepcopy(VALID_CASES['design-review-record']),'unexpected':True}
VALID_CASES['candidate-set']={'schema_version':1,'set_id':'candidate-set-one','run_id':'run-one','project_id':'project-one',
    'candidates':[{'variant_id':'variant-a','candidate_id':'candidate-run-one-variant-a','resolved_map_digest':deepcopy(D),
        'render_scene_digest':deepcopy(D),'preflight_status':'passed','preflight_report_digest':deepcopy(D)}],
    'created_at':'2026-11-13T00:00:00Z'}
INVALID_CASES['candidate-set']={**deepcopy(VALID_CASES['candidate-set']),'unexpected':True}
VALID_CASES['revision-dependency-graph']={'schema_version':1,'revision':2,'run_id':'run-one','proposal_id':'proposal-one',
    'invalidated_nodes':['candidate','preflight','preview','scene'],'data_evidence_reusable':True,
    'bundle_input_digest':deepcopy(D),'earliest_step':'compile','created_at':'2026-11-13T00:00:00Z'}
INVALID_CASES['revision-dependency-graph']={**deepcopy(VALID_CASES['revision-dependency-graph']),'unexpected':True}
VALID_CASES['delivery-manifest']['review_ref']=deepcopy(A)

# --- online basemap binding: legal + semantic illegal samples (2026-11-21) ---
# Legal: the frontend document gains the online-view sections (frontend doc
# sections 4/5) when the request declares online_basemap.
_online_doc = deepcopy(VALID_CASES["frontend-map-document"])
_online_doc["baseMap"] = {"type": "Tianditu", "layer": "vec_w", "opacity": 1.0,
                          "minZoom": 3, "maxZoom": 18}
_online_doc["mapData"] = {
    "x": 20.0, "y": 30.0, "w": 380.0, "h": 230.0, "type": "Vector",
    "extent": {"west": 119.97, "south": 29.97, "east": 120.03, "north": 30.03, "unit": "degree"},
    "center": {"lon": 120.0, "lat": 30.0}, "bearing": 0,
    "zoomRule": "contain-replicate", "referenceZoom": 9.5,
    "coordinateSystem": "WGS84",
    "features": [
        {"type": "stops", "name": "上午行程点", "properties": {"period": "morning", "points": [
            {"id": "stop-1", "name": "甲地", "formattedAddress": "合成地址", "lon": 120.0,
             "lat": 30.0, "label": "出发点", "RectIndex": 2,
             "style": {"icon": "star", "size": 4.0, "color": "#C41E3A"}}]}},
        {"type": "route", "name": "路线", "properties": {"period": "default", "legs": [
            {"fromName": "甲地", "toName": "乙地",
             "polyline": [[120.0, 30.0], [120.02, 29.98]]}]},
         "style": {"strokeColor": "#403B96", "strokeWidth": 0.8, "strokeDash": ""}},
    ],
}
VALID_CASES["frontend-map-document"] = _online_doc

_leadership_online = deepcopy(VALID_CASES["leadership-visit-generate-request"])
_leadership_online["online_basemap"] = {"provider": "Tianditu", "layer": "vec_w"}
SEMANTIC_INVALID_CASES["leadership-online-provider"] = (
    "leadership-visit-generate-request",
    {**deepcopy(_leadership_online), "online_basemap": {"provider": "Amap", "layer": "vec_w"}})
SEMANTIC_INVALID_CASES["leadership-online-layer"] = (
    "leadership-visit-generate-request",
    {**deepcopy(_leadership_online), "online_basemap": {"provider": "Tianditu", "layer": "terrain"}})
SEMANTIC_INVALID_CASES["leadership-online-zoom"] = (
    "leadership-visit-generate-request",
    {**deepcopy(_leadership_online),
     "online_basemap": {"provider": "Tianditu", "layer": "vec_w", "minZoom": -1}})
_lon_doc = deepcopy(VALID_CASES["frontend-map-document"])
_lon_doc["mapData"]["features"][0]["properties"]["points"][0]["lon"] = 200.0
SEMANTIC_INVALID_CASES["frontend-geo-lon-range"] = ("frontend-map-document", _lon_doc)
_zoom_doc = deepcopy(VALID_CASES["frontend-map-document"])
_zoom_doc["mapData"]["zoomRule"] = "fit"
SEMANTIC_INVALID_CASES["frontend-geo-zoomrule"] = ("frontend-map-document", _zoom_doc)
_revision_basemap = deepcopy(VALID_CASES["design-revision-proposal"])
_revision_basemap["changes"] = {"basemap": {"new_value": {"mode": "registered-transform"}}}
SEMANTIC_INVALID_CASES["revision-basemap-missing-refs"] = ("design-revision-proposal", _revision_basemap)
