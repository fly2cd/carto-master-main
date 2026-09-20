from __future__ import annotations

from typing import Any

from ..schema_registry import SchemaRegistry


def build_template_brief(
    request: dict[str, Any],
    analysis: dict[str, Any],
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or SchemaRegistry()
    sources = [
        {
            "id": item["source_id"],
            "version": "1.0.0",
            "digest": item["digest"],
            "uri": f"source:{item['source_id']}",
        }
        for item in analysis["source_summaries"]
    ]
    licenses = [
        {
            "source_id": item["source_id"],
            "license": item["license"],
            "data_nature": item["data_nature"],
        }
        for item in analysis["source_summaries"]
    ]
    decisions = [
        record for record in analysis["evidence_records"] if record["value_origin"] == "user_decision"
    ]
    brief = {
        "schema_version": 1,
        "brief_id": f"brief-{request['request_id']}",
        "kind": "map-scenario",
        "namespace": request["namespace"],
        "template_id": request["template_id"],
        "version": request["version"],
        "scope": request["scope"],
        "purpose": request["purpose"],
        "audience": request["audience"],
        "reuse_intent": request["reuse_intent"],
        "supported_uses": request["supported_uses"],
        "excluded_uses": request["excluded_uses"],
        "sources": sources,
        "source_license_summary": licenses,
        "authoring_mode": request["authoring_mode"],
        "targets": request["targets"],
        "data_roles": [
            {
                "role_id": "risk-area",
                "source_id": request["role_bindings"]["risk_area_source"],
                "geometry_types": ["polygon", "multipolygon"],
                "value_field": "risk_pct",
                "semantic_role": "risk-value",
            },
            {
                "role_id": "shelter-point",
                "source_id": request["role_bindings"]["shelter_source"],
                "geometry_types": ["point"],
                "value_field": "capacity",
                "semantic_role": "count-value",
            },
        ],
        "spatial_applicability": {
            "source_crs": request["source_crs"],
            "display_crs": request["display_crs"],
            "extent_policy": "data",
        },
        "evidence_records": analysis["evidence_records"],
        "decisions": decisions,
        "open_questions": analysis["open_questions"],
        "revision": 1,
    }
    registry.validate("template-brief", brief)
    return brief