#!/usr/bin/env python3
"""Generate synthetic flood sample data into a carto project's project-root.

Produces:
  <project_root>/data/risk.geojson       Polygon 风险区域，字段 risk_pct
  <project_root>/data/shelters.geojson   Point 避难场所，字段 capacity
  <project_root>/source-manifest.yaml    含真实文件 digest 的来源清单
  <project_root>/request-template.yaml   template-create-request，供 carto create-template analyze

结构镜像 skills/carto-agent/scripts/tests/test_up2_template.py 里已验证的样例，
坐标用 U-P2.0 文档合成范围（lon 110.0-110.3 / lat 30.0-30.3）使演示更有意义。
digest 由本脚本按文件实际字节计算，analyze 重算时必然一致。

用法：python generate_flood_sample.py <project_root>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required (a carto-agent dependency); install with the resolved interpreter.")


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _geojson(features):
    return {
        "type": "FeatureCollection",
        "carto_metadata": {
            "data_nature": "synthetic",
            "contains_production_data": False,
            "contains_sensitive_coordinates": False,
            "source_crs": "EPSG:4326",
        },
        "features": features,
    }


def risk_features():
    polys = [
        ("synthetic-risk-R01", 5.0, [[110.10, 30.10], [110.12, 30.10], [110.12, 30.12], [110.10, 30.12], [110.10, 30.10]]),
        ("synthetic-risk-R02", 15.0, [[110.12, 30.10], [110.14, 30.10], [110.14, 30.12], [110.12, 30.12], [110.12, 30.10]]),
        ("synthetic-risk-R03", 25.0, [[110.10, 30.12], [110.12, 30.12], [110.12, 30.14], [110.10, 30.14], [110.10, 30.12]]),
        ("synthetic-risk-R04", 35.0, [[110.12, 30.12], [110.14, 30.12], [110.14, 30.14], [110.12, 30.14], [110.12, 30.12]]),
    ]
    return [
        {"type": "Feature", "id": fid, "properties": {"risk_pct": rp},
         "geometry": {"type": "Polygon", "coordinates": [ring]}}
        for fid, rp, ring in polys
    ]


def shelter_features():
    pts = [
        ("synthetic-shelter-S01", 120, [110.11, 30.11]),
        ("synthetic-shelter-S02", 80, [110.13, 30.13]),
        ("synthetic-shelter-S03", 200, [110.115, 30.125]),
    ]
    return [
        {"type": "Feature", "id": fid, "properties": {"capacity": cap},
         "geometry": {"type": "Point", "coordinates": coord}}
        for fid, cap, coord in pts
    ]


def main(project_root: str) -> None:
    pr = Path(project_root).resolve()
    data = pr / "data"
    data.mkdir(parents=True, exist_ok=True)

    risk = data / "risk.geojson"
    shelter = data / "shelters.geojson"
    risk.write_text(json.dumps(_geojson(risk_features()), ensure_ascii=False), encoding="utf-8")
    shelter.write_text(json.dumps(_geojson(shelter_features()), ensure_ascii=False), encoding="utf-8")

    provenance = {
        "source_type": "derived",
        "source_ref": "fixture:host-sample",
        "version": "1.0.0",
        "retrieved_at": "2026-09-20T00:00:00Z",
        "classification": "internal",
    }
    data_profile = {
        "data_nature": "synthetic",
        "contains_production_data": False,
        "contains_sensitive_coordinates": False,
        "source_crs": {"authority": "EPSG", "code": "4326"},
    }
    manifest = {
        "schema_version": 1,
        "manifest_id": "flood-sources",
        "sources": [
            {"source_id": "risk-source", "kind": "geojson", "location_ref": "data/risk.geojson",
             "digest": file_digest(risk), "provenance": provenance, "license": "project-approved",
             "captured_at": "2026-09-20T00:00:00Z", "data_profile": data_profile},
            {"source_id": "shelter-source", "kind": "geojson", "location_ref": "data/shelters.geojson",
             "digest": file_digest(shelter), "provenance": provenance, "license": "project-approved",
             "captured_at": "2026-09-20T00:00:00Z", "data_profile": data_profile},
        ],
    }
    (pr / "source-manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    request = {
        "schema_version": 1,
        "request_id": "flood-template-request",
        "kind": "map-scenario",
        "namespace": "local",
        "template_id": "flood-scenario",
        "version": "1.0.0",
        "profile": "flood-risk-overview",
        "purpose": "Synthetic flood-risk engineering preview",
        "audience": ["emergency-planner"],
        "reuse_intent": "Reuse with approved synthetic role-compatible inputs",
        "supported_uses": ["engineering-preview"],
        "excluded_uses": ["navigation", "formal-delivery"],
        "authoring_mode": "standard",
        "targets": ["svg", "pdf", "png"],
        "scope": "project:carto-flood-a3",
        "subject": {
            "tenant_id": "tenant-one",
            "project_id": "carto-flood-a3",
            "requester_subject_id": "operator-one",
            "approver_subject_id": "reviewer-one",
            "environment": "local",
        },
        "source_manifest_path": "source-manifest.yaml",
        "data_nature": "synthetic",
        "contains_production_data": False,
        "contains_sensitive_coordinates": False,
        "source_crs": {"authority": "EPSG", "code": "4326"},
        "display_crs": {"authority": "EPSG", "code": "3857"},
        "role_bindings": {"risk_area_source": "risk-source", "shelter_source": "shelter-source"},
        "decisions": [],
        "requested_at": "2026-09-20T00:00:00Z",
    }
    (pr / "request-template.yaml").write_text(
        yaml.safe_dump(request, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    print(json.dumps({
        "risk_geojson": str(risk), "risk_digest": file_digest(risk),
        "shelter_geojson": str(shelter), "shelter_digest": file_digest(shelter),
        "manifest": str(pr / "source-manifest.yaml"),
        "request": str(pr / "request-template.yaml"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: generate_flood_sample.py <project_root>")
    main(sys.argv[1])
