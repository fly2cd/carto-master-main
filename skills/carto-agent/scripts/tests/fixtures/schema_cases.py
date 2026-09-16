from __future__ import annotations

from copy import deepcopy

from carto_core.canonical import sha256_digest

D = "sha256:" + "0" * 64
A = {"id": "artifact", "version": "1.0.0", "digest": D}
T = {"kind": "map-scenario", "id": "flood-scenario", "version": "1.0.0", "digest": D}
P = {"source_type": "official", "source_ref": "catalog:item", "version": "2026", "retrieved_at": "2026-09-14T00:00:00Z", "classification": "internal"}
R = {"id": "required-rule", "strength": "hard_rule", "path": "/value", "description": "必须满足"}
EXECUTION = {
    "intent_ref": A,
    "profile_refs": [],
    "business_scene": "emergency_mapping",
    "map_tasks": ["hazard-result-map"],
    "template_refs": [T],
    "dependency_refs": [],
    "policy_refs": [],
    "dataset_refs": [A],
    "prepared_data_refs": [],
    "knowledge_evidence_refs": [],
    "tool_binding_refs": [],
    "transformation_refs": [],
    "ownership": {"scenario": "map-scenario"},
    "shared_semantics": {"hazard": "flood", "data_nature": "simulated"},
    "views": [{"id": "main-view", "extent": [100, 20, 101, 21], "layer_ids": ["risk-layer"], "target_ids": ["a3-pdf"]}],
    "targets": {"a3-pdf": {"format": "pdf", "display_crs": {"authority": "EPSG", "code": "4490"}, "dpi": 300, "width_mm": 420, "height_mm": 297}},
    "resolved_assets": [],
    "environment": {"renderer_id": "maplibre-web", "renderer_version": "1.0.0", "frontend_build": "2026.09.15", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "fingerprint": D},
}
EXECUTION_DIGEST = sha256_digest(EXECUTION)

VALID_CASES = {
    "manifest": {"schema_version": 1, "package": {"namespace": "local", "kind": "map-scenario", "id": "flood-scenario", "version": "1.0.0", "status": "draft", "summary": "洪涝制图场景"}, "dependencies": [], "targets": ["pdf", "png"], "files": ["contracts/scenario.yaml"], "checksums": {"contracts/scenario.yaml": D}},
    "template-brief": {"schema_version": 1, "brief_id": "brief-one", "kind": "map-scenario", "purpose": "创建洪涝场景方案", "sources": [A], "authoring_mode": "standard", "targets": ["pdf", "png"], "decisions": {}, "open_questions": [], "revision": 1},
    "identity": {"schema_version": 1, "identity_id": "government-blue", "version": "1.0.0", "organization": "示例机构", "colors": [{"role": "primary", "hex": "#005EA8", "provenance": P}], "typography": [{"role": "title", "family": "Noto Sans CJK SC", "weight": 700}], "attribution": {"organization_format": "制图：{organization}", "data_source_format": "数据来源：{source}"}, "rules": [R]},
    "cartography": {"schema_version": 1, "style_id": "technical-map", "version": "1.0.0", "visual_language": "technical", "symbolization": {"ramp": "sequential"}, "labeling": {"density": "medium", "collision_policy": "prioritize"}, "generalization": {"scale_dependent": True, "strategy": "simplify"}, "defaults": {}, "rules": [R]},
    "layout": {"schema_version": 1, "layout_id": "a3-landscape", "version": "1.0.0", "category": "report", "canvas": {"width": 420, "height": 297, "unit": "mm"}, "frames": [{"id": "main-map", "type": "map", "bounds": [20, 30, 380, 230]}], "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}"], "capacity": {"legend_items": 12}, "rules": [R]},
    "scenario": {"schema_version": 1, "scenario_id": "flood-scenario", "version": "1.0.0", "business_scene": "emergency_mapping", "tasks": ["hazard-result-map"], "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal", "delivery", "quality-gates"], "replaceable_segments": ["identity", "cartography", "layout"], "data_role_refs": ["risk-area", "shelter-point"], "target_ids": ["a3-pdf", "a3-png"], "rules": [R]},
    "data-role": {"schema_version": 1, "roles": [{"id": "risk-area", "required": True, "geometry_types": ["polygon", "multipolygon"], "fields": [{"name": "risk_pct", "type": "number", "unit": "percent", "nullable": True, "semantic_role": "risk-value"}], "join": {"key": "admin_code", "minimum_coverage": 0.98}, "freshness": {"max_age_days": 30}, "license_policy": "project-approved"}]},
    "spatial-behavior": {"schema_version": 1, "source_crs_policy": "reproject-approved", "display_crs": {"authority": "EPSG", "code": "4490"}, "extent_policy": "administrative-boundary", "scale_bands": [{"id": "regional", "min_denominator": 10000, "max_denominator": 1000000, "generalization": "simplify"}], "topology": {"preserve_adjacency": True, "preserve_route_order": False}, "rules": [R]},
    "portrayal": {"schema_version": 1, "layers": [{"id": "risk-layer", "data_role": "risk-area", "geometry": "polygon", "z_order": 10, "symbol": {"catalog_ref": "ramps/flood-risk@1", "parameters": {"opacity": 0.8}}, "classification": {"method": "quantile", "classes": 4, "field": "risk_pct"}, "no_data": "explicit-symbol"}], "legend": {"generated_from_layers": True, "show_no_data": True}, "rules": [R]},
    "delivery": {"schema_version": 1, "targets": [{"id": "a3-pdf", "medium": "print", "format": "pdf", "page": {"width_mm": 420, "height_mm": 297, "dpi": 300, "safe_margin_mm": 10, "bleed_mm": 0}, "color_mode": "rgb", "font_policy": "embed-approved"}], "rules": [R]},
    "quality-gates": {"schema_version": 1, "baseline": A, "checks": [{"id": "schema-valid", "version": "1.0.0", "strength": "hard_rule", "failure_severity": "blocker", "params": {}}]},
    "generate-request": {"schema_version": 1, "request_id": "request-one", "project_id": "flood-project", "goal": "制作洪涝风险专题图", "scene_hint": "emergency_mapping", "sources": [A], "requested_outputs": ["pdf", "png"], "subject": {"subject_id": "user-1", "tenant_id": "tenant-one", "namespace": "project-one"}, "idempotency_key": "request-one-00001"},
    "map-intent": {"schema_version": 1, "intent_id": "intent-one", "revision": 1, "profile_version": "1.0.0", "business_scene": "emergency_mapping", "theme": "flood", "tasks": ["hazard-result-map"], "intent_status": "resolved", "readiness_status": "ready", "missing_items": [], "evidence_refs": [A]},
    "intent-profiles": {"schema_version": 1, "catalog_version": "1.0.0", "profiles": [{"scene_id": "government_thematic", "task_ids": ["indicator-map"], "required_information": ["theme"], "unsupported_actions": []}, {"scene_id": "emergency_mapping", "task_ids": ["hazard-result-map"], "required_information": ["hazard"], "unsupported_actions": ["hazard-prediction"]}, {"scene_id": "leadership_visit", "task_ids": ["visit-route-map"], "required_information": ["itinerary"], "unsupported_actions": ["reorder-visits"]}]},
    "map-brief": {"schema_version": 1, "brief_id": "map-brief-one", "revision": 1, "intent_ref": A, "purpose": "风险研判", "audience": "应急管理人员", "source_plan": [{"role": "risk-area", "source_ref": A, "allowed_operations": ["read", "join", "classify"]}], "targets": ["pdf", "png"], "template_candidates": [T], "delegation": {"allow_data_agent": False, "max_tool_calls": 10}, "approval_required": True},
    "source-manifest": {"schema_version": 1, "manifest_id": "source-manifest-one", "sources": [{"source_id": "risk-data", "kind": "geopackage", "location_ref": "project-source:risk.gpkg", "digest": D, "provenance": P, "license": "project-approved", "captured_at": "2026-09-14T00:00:00Z"}]},
    "tool-binding": {"schema_version": 1, "binding_id": "renderer-capability-register", "version": "1.0.0", "capability_id": "renderer-capability-register", "adapter": "local", "input_schema_digest": D, "output_schema_digest": D, "authorization_policy": "environment-probe", "effect": "read", "snapshot_policy": "receipt-only"},
    "knowledge-evidence": {"schema_version": 1, "evidence_id": "evidence-one", "claim": "风险等级字段单位为百分比", "publisher": "示例标准机构", "source": P, "applicability": {"jurisdiction": "示例地区", "valid_from": "2026-01-01", "industry": "emergency"}, "digest": D},
    "data-preparation-task": {"schema_version": 1, "task_id": "prepare-one", "required_roles": ["risk-area"], "allowed_sources": [A], "allowed_operations": ["filter", "join", "reproject", "classify"], "budget": {"max_tool_calls": 10, "max_seconds": 300}, "acceptance_checks": ["schema-valid"]},
    "prepared-data-bundle": {"schema_version": 1, "bundle_id": "bundle-one", "task_ref": A, "datasets": [A], "transformations": [], "tool_receipts": [A], "quality_evidence": [A], "open_issues": [], "digest": D},
    "map-plan": {"schema_version": 1, "plan_id": "plan-one", "revision": 1, "project_id": "flood-project", "intent_ref": A, "brief_ref": A, "business_scene": "emergency_mapping", "tasks": ["hazard-result-map"], "template_refs": [T], "data_bindings": [{"role": "risk-area", "dataset_ref": A}], "decisions": {"classification": "quantile"}, "open_issues": []},
    "resolved-map": {"schema_version": 1, "candidate_id": "candidate-one", "project_id": "flood-project", "run_id": "run-one", "execution_digest": EXECUTION_DIGEST, "execution": EXECUTION, "open_issues": [], "created_at": "2026-09-14T00:00:00Z"},
    "map-spec-lock": {"schema_version": 1, "lock_id": "lock-one", "project_id": "flood-project", "run_id": "run-one", "candidate_ref": A, "execution_digest": EXECUTION_DIGEST, "execution": EXECUTION, "evidence": {"preflight_ref": A, "preview_ref": A}, "approvals": {"brief_ref": "approval:brief", "freeze_ref": "approval:freeze"}, "created_at": "2026-09-14T00:00:00Z"},
    "delivery-manifest": {"schema_version": 1, "delivery_id": "delivery-one", "project_id": "flood-project", "lock_ref": A, "execution_digest": EXECUTION_DIGEST, "artifacts": [{"path": "output/map.pdf", "format": "pdf", "digest": D, "size_bytes": 1024}], "limitations": ["模拟数据"], "delivered_at": "2026-09-14T00:00:00Z"},
    "approval-receipt": {"schema_version": 1, "receipt_id": "receipt-one", "issuer": "local-host", "subject_id": "user-1", "tenant_id": "tenant-one", "action": "approve-freeze", "object_type": "resolved-map", "object_digest": D, "scope": "project:flood-project", "policy_id": "carto-security", "environment": "local", "issued_at": "2026-09-14T00:00:00Z", "expires_at": "2026-09-15T00:00:00Z", "nonce": "nonce-0000000001", "signature_algorithm": "hmac-sha256", "signature": "0" * 64},
    "job-state": {"schema_version": 1, "status": "running", "step": "validate", "attempt": 1, "run_id": "run-one", "input_fingerprint": D, "last_receipt": "steps/validate.json"},
    "step-receipt": {"schema_version": 1, "receipt_id": "receipt-step-one", "run_id": "run-one", "step": "validate", "attempt": 1, "status": "succeeded", "input_fingerprint": D, "prerequisite_fingerprints": {"policy": D}, "tool_versions": {"schema-validate": "1.0.0"}, "output_refs": [A], "started_at": "2026-09-15T00:00:00Z", "completed_at": "2026-09-15T00:00:01Z"},
    "tool-result": {"schema_version": 1, "invocation_id": "invocation-one", "capability_id": "schema-validate", "binding_version": "1.0.0", "status": "succeeded", "input_digest": D, "output_digest": D, "artifact_refs": [A], "started_at": "2026-09-15T00:00:00Z", "completed_at": "2026-09-15T00:00:01Z"},
    "validation-report": {"schema_version": 1, "report_id": "report-one", "phase": "validate", "subject_digest": D, "status": "passed", "results": [{"check_id": "protocol.schema-valid", "version": "1.0.0", "status": "passed", "severity": "blocker", "details": {}}], "created_at": "2026-09-15T00:00:00Z"},
    "environment-fingerprint": {"schema_version": 1, "probe_id": "renderer-capability-probe", "status": "unavailable", "platform": "Windows", "python_version": "3.11.0", "tools": {"browser": {"available": False, "command": None, "executable": None, "version": None, "exit_code": None}, "node": {"available": False, "executable": None, "version": None, "exit_code": None}}, "chinese_fonts": [], "capabilities": {"webgl_available": False, "offline_rendering": False, "svg_composition": True, "headless_export": False, "chinese_font": False, "max_canvas_width": 16384, "max_canvas_height": 16384, "supported_export_formats": ["svg"]}, "renderer_profile": {"renderer_id": "maplibre-web", "frontend_build": "2026.09.15", "renderer_version": "1.0.0", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "browser_engine": "unavailable", "webgl_available": False, "supported_export_formats": ["svg"], "max_canvas_width": 16384, "max_canvas_height": 16384, "device_pixel_ratio": 2.0, "available_fonts": [], "offline_rendering": False}, "probed_at": "2026-09-15T00:00:00Z", "fingerprint": D, "error": {"code": "CAPABILITY_NOT_AVAILABLE", "message": "Controlled renderer handshake unavailable"}},
    "render-scene": {
        "schema_version": 1, "scene_id": "scene-flood-001", "revision": 1, "renderer_id": "maplibre-web",
        "spatial_context": {"display_crs": {"authority": "EPSG", "code": "4490"}, "axis_order": "longitude-latitude", "coordinate_units": "degrees"},
        "renderer_requirements": {"renderer_id": "maplibre-web", "require_webgl": True, "require_offline_rendering": True, "required_capabilities": ["svg-overlay", "geographic-anchor", "headless-export"], "required_fonts": ["Noto Sans CJK SC"], "minimum_device_pixel_ratio": 2},
        "viewport": {"width_px": 1684, "height_px": 1191, "device_pixel_ratio": 2, "background": "#FFFFFF"},
        "camera": {"bounds": [112.1, 28.0, 114.2, 29.8], "bearing": 0, "pitch": 0, "padding": {"top": 80, "right": 320, "bottom": 90, "left": 80}},
        "map": {"style_ref": A, "sources": [{"id": "risk-source", "type": "geojson", "resource_id": "risk-data"}], "layers": [{"id": "risk-layer", "source_id": "risk-source", "type": "fill", "paint": {"fill-color": "#005EA8"}, "z_index": 10}]},
        "overlays": [{"id": "map-title", "type": "text", "coordinate_space": "page", "position": {"x": 0.05, "y": 0.04, "unit": "normalized"}, "content": "洪涝灾害风险专题图", "style_role": "map-title"}, {"id": "survey-point-01", "type": "symbol", "coordinate_space": "geographic", "anchor": {"longitude": 113.1, "latitude": 28.7}, "screen_position": {"x": 840, "y": 600, "unit": "pixel"}, "symbol_ref": "survey-location", "label": "调研点一"}],
        "resources": [{"id": "risk-data", "kind": "geojson", "ref": A, "required": True}, {"id": "survey-location", "kind": "icon", "ref": A, "required": True}, {"id": "noto-font", "kind": "font", "ref": A, "required": True}],
        "export": {"targets": ["svg", "png"], "dpi": 300}, "provenance": [P]
    },
    "render-receipt": {
        "schema_version": 1, "receipt_id": "render-receipt-one", "session_id": "session-one", "scene_id": "scene-flood-001", "scene_revision": 1, "scene_digest": D,
        "renderer_id": "maplibre-web", "renderer_profile_digest": D, "frontend_build_version": "2026.09.15", "renderer_version": "1.0.0", "maplibre_version": "3.6.0", "overlay_engine_version": "1.0.0", "browser_version": "Chromium 117.0", "status": "succeeded",
        "viewport": {"width_px": 1684, "height_px": 1191, "device_pixel_ratio": 2},
        "resource_evidence": [{"resource_id": "risk-data", "digest": D, "status": "loaded"}, {"resource_id": "survey-location", "digest": D, "status": "loaded"}, {"resource_id": "noto-font", "digest": D, "status": "loaded"}],
        "output_artifacts": [{"target": "svg", "artifact_ref": A}, {"target": "png", "artifact_ref": A}], "warnings": [],
        "render_started_at": "2026-09-15T00:00:00Z", "render_completed_at": "2026-09-15T00:00:05Z", "attestation_algorithm": "hmac-sha256", "renderer_attestation": "0" * 64
    },
}

INVALID_CASES = {}
for name, case in VALID_CASES.items():
    invalid = deepcopy(case)
    invalid["unexpected_parallel_protocol"] = True
    INVALID_CASES[name] = invalid
