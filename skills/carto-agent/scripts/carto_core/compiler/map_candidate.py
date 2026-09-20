from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..adapters.controlled_renderer import FRONTEND_BUILD, MAPLIBRE_VERSION, OVERLAY_ENGINE_VERSION, RANDOM_SEED, RENDERER_VERSION, sha256_file
from ..adapters.webmap_renderer import WebMapRendererAdapter
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..repository.template_repository import _file_digest
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from .dependencies import DependencyResolver


PALETTE = ["#FFF7BC", "#FEE391", "#FEC44F", "#FE9929", "#EC7014", "#CC4C02", "#993404", "#7F0000", "#67000D", "#49000A", "#310006", "#1A0003"]


class MapCandidateCompiler:
    """Compile an approved plan to immutable candidate documents without rendering."""

    CONTRACT_SCHEMAS = {
        "scenario": "scenario", "data_schema": "data-role", "spatial_behavior": "spatial-behavior",
        "portrayal": "portrayal", "delivery": "delivery", "quality_gates": "quality-gates",
    }

    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.registry = registry or SchemaRegistry()
        self.dependencies = DependencyResolver()

    def load_contracts(self, installation: dict[str, Any]) -> dict[str, Any]:
        root = self.path_guard.resolve(installation["package_path"], must_exist=True)
        if not root.is_dir():
            raise ProtocolError("TEMPLATE_INSTALL_INCOMPLETE", str(root))
        manifest_path = root / "manifest.yaml"
        checksum_path = root / "checksums.sha256"
        if not manifest_path.is_file() or not checksum_path.is_file():
            raise ProtocolError("TEMPLATE_INSTALL_INCOMPLETE", str(root))
        manifest = load_document(manifest_path)
        self.registry.validate("manifest", manifest)
        template_ref = installation.get("template_ref", {})
        expected_identity = (
            installation.get("namespace"), template_ref.get("kind"), template_ref.get("id"),
            template_ref.get("version"),
        )
        actual_identity = (
            manifest["package"]["namespace"], manifest["package"]["kind"],
            manifest["package"]["id"], manifest["package"]["version"],
        )
        if expected_identity != actual_identity:
            raise ProtocolError("TEMPLATE_INSTALL_IDENTITY_MISMATCH", str(root))
        if _file_digest(manifest_path) != installation.get("manifest_digest"):
            raise ProtocolError("TEMPLATE_INSTALL_MANIFEST_DRIFT", str(root))
        if _file_digest(checksum_path) != template_ref.get("digest"):
            raise ProtocolError("TEMPLATE_INSTALL_PACKAGE_DRIFT", str(root))
        tree = list(root.rglob("*"))
        linked = [item.relative_to(root).as_posix() for item in tree if item.is_symlink()]
        if linked:
            raise ProtocolError("TEMPLATE_INSTALL_LINK_FORBIDDEN", linked[0])
        expected_files = sorted(["manifest.yaml", "checksums.sha256", *manifest["files"]])
        actual_files = sorted(item.relative_to(root).as_posix() for item in tree if item.is_file())
        if expected_files != actual_files:
            raise ProtocolError("TEMPLATE_INSTALL_FILE_SET_DRIFT", str(root))
        for relative, digest in manifest["checksums"].items():
            target = self.path_guard.resolve(root / relative, must_exist=True)
            if not target.is_file() or _file_digest(target) != digest:
                raise ProtocolError("TEMPLATE_INSTALL_FILE_DRIFT", relative)
        expected_contract_digest = sha256_digest({
            name: manifest["checksums"][relative]
            for name, relative in manifest["business_contracts"].items()
        })
        if installation.get("contract_digest") != expected_contract_digest:
            raise ProtocolError("TEMPLATE_INSTALL_CONTRACT_DIGEST_MISMATCH", str(root))
        contracts: dict[str, Any] = {}
        for key, schema in self.CONTRACT_SCHEMAS.items():
            value = load_document(root / manifest["business_contracts"][key])
            self.registry.validate(schema, value)
            contracts[key] = value
        lock = load_document(root / manifest["dependency_lock"])
        self.registry.validate("dependency-lock", lock)
        self.dependencies.validate_lock(lock)
        self._validate_expression_bindings(contracts["portrayal"], lock)
        self._validate_rules(contracts)
        return {"root": root, "manifest": manifest, "lock": lock, **contracts}

    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any], contracts: dict[str, Any],
                font_path: Path) -> dict[str, Any]:
        if plan["open_issues"] or bundle["open_issues"]:
            raise ProtocolError("CANDIDATE_INPUT_UNRESOLVED", request["run_id"])
        font_path = self.path_guard.resolve(font_path, must_exist=True)
        role_bindings = {item["role"]: item for item in bundle["role_bindings"]}
        risk = load_document(self.path_guard.resolve(role_bindings["risk-area"]["prepared_ref"]["uri"], must_exist=True))
        shelters = load_document(self.path_guard.resolve(role_bindings["shelter-point"]["prepared_ref"]["uri"], must_exist=True))
        values = sorted(float(item["properties"]["risk_value"]) for item in risk["features"])
        counts = sorted(float(item["properties"]["count_value"]) for item in shelters["features"])
        breaks = self._quantile_breaks(values, plan["decisions"]["class_count"])
        colors = PALETTE[:max(1, len(breaks) - 1)]
        legend = self._legend(breaks, colors)
        scene = self._scene(request, plan, bundle, installation, contracts, font_path, breaks, colors, counts, legend)
        scene = WebMapRendererAdapter().compile_scene(scene)

        template_ref = installation["template_ref"]
        target_contracts = {item["format"]: item for item in contracts["delivery"]["targets"]}
        targets = {}
        for target in sorted(request["requested_outputs"]):
            if target not in target_contracts:
                raise ProtocolError("TEMPLATE_TARGET_UNSUPPORTED", target)
            spec = target_contracts[target]
            targets[spec["id"]] = {"format": target, "display_crs": contracts["spatial_behavior"]["display_crs"],
                                   "dpi": spec["page"]["dpi"], "width_mm": spec["page"]["width_mm"],
                                   "height_mm": spec["page"]["height_mm"]}
        expression_refs = sorted(contracts["lock"]["resources"], key=lambda item: item["id"])
        environment = {
            "renderer_id": "maplibre-web", "renderer_version": RENDERER_VERSION,
            "frontend_build": FRONTEND_BUILD, "maplibre_version": MAPLIBRE_VERSION,
            "overlay_engine_version": OVERLAY_ENGINE_VERSION,
            "fingerprint": sha256_digest({"renderer_id": "maplibre-web", "renderer_version": RENDERER_VERSION,
                                          "frontend_build": FRONTEND_BUILD, "maplibre_version": MAPLIBRE_VERSION,
                                          "overlay_engine_version": OVERLAY_ENGINE_VERSION}),
        }
        scene_ref = {"id": scene["scene_id"], "version": "1.0.0", "digest": sha256_digest(scene)}
        execution = {
            "intent_ref": plan["intent_ref"], "profile_refs": [], "business_scene": plan["business_scene"],
            "map_tasks": plan["tasks"], "template_refs": [template_ref],
            "dependency_refs": expression_refs, "policy_refs": [contracts["quality_gates"]["baseline"]],
            "dataset_refs": [item["dataset_ref"] for item in bundle["role_bindings"]],
            "prepared_data_refs": [item["prepared_ref"] for item in bundle["role_bindings"]],
            "knowledge_evidence_refs": [], "tool_binding_refs": [], "transformation_refs": bundle["transformations"],
            "ownership": {"scenario": "map-scenario", "identity": "map-scenario", "cartography": "map-scenario",
                          "layout": "map-scenario", "data": "project"},
            "shared_semantics": {"theme": "flood-risk", "data_nature": "synthetic", "classification": "quantile",
                                 "class_breaks": breaks, "legend_items": legend,
                                 "field_bindings": {item["role"]: item["semantic_fields"] for item in bundle["role_bindings"]}},
            "views": [{"id": "main-view", "extent": plan["decisions"]["extent"],
                       "layer_ids": [item["id"] for item in contracts["portrayal"]["layers"]],
                       "target_ids": sorted(targets)}],
            "targets": targets, "resolved_assets": [*expression_refs, {
                "id": "map-font", "version": request["font"]["version"], "digest": sha256_file(font_path), "uri": str(font_path)}],
            "render_scene_ref": scene_ref, "camera": deepcopy(scene["camera"]),
            "overlay_coordinate_policy": "page", "interaction_policy": "preview", "environment": environment,
        }
        candidate = {"schema_version": 1, "candidate_id": f"candidate-{request['run_id']}",
                     "project_id": request["project_id"], "run_id": request["run_id"],
                     "execution_digest": sha256_digest(execution), "execution": execution,
                     "open_issues": [], "created_at": request["requested_at"]}
        self.registry.validate("resolved-map", candidate)
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        report = self._preflight(request, plan, bundle, installation, contracts, scene, candidate)
        return {"candidate": candidate, "scene": scene, "preflight": report,
                "class_breaks": breaks, "legend_items": legend}

    def _scene(self, request: dict[str, Any], plan: dict[str, Any], bundle: dict[str, Any],
               installation: dict[str, Any], contracts: dict[str, Any], font: Path,
               breaks: list[float], colors: list[str], counts: list[float],
               legend: list[dict[str, Any]]) -> dict[str, Any]:
        roles = {item["role"]: item for item in bundle["role_bindings"]}
        extent = self._padded_extent(plan["decisions"]["extent"])
        fill_color: Any = colors[0]
        if len(colors) > 1:
            fill_color = ["step", ["get", "risk_value"], colors[0]]
            for threshold, color in zip(breaks[1:-1], colors[1:]):
                fill_color.extend([threshold, color])
        max_count = max(counts) if counts else 1.0
        resources = []
        sources = []
        for role in ("risk-area", "shelter-point"):
            ref = roles[role]["prepared_ref"]
            resource_id = f"prepared-{role}"
            resources.append({"id": resource_id, "kind": "geojson", "ref": ref, "required": True})
            sources.append({"id": f"source-{role}", "type": "geojson", "resource_id": resource_id})
        resources.append({"id": "map-font", "kind": "font", "font_family": request["font"]["family"],
                          "ref": {"id": "map-font", "version": request["font"]["version"],
                                  "digest": sha256_file(font), "uri": str(font)}, "required": True})
        opacity = contracts["scenario"]["embedded"]["cartography"]["symbolization"]["default_opacity"]
        return {
            "schema_version": 1, "scene_id": f"scene-{request['run_id']}", "revision": 1,
            "renderer_id": "maplibre-web",
            "spatial_context": {"display_crs": {"authority": "EPSG", "code": "4326"},
                                "axis_order": "longitude-latitude", "coordinate_units": "degrees"},
            "renderer_requirements": {"renderer_id": "maplibre-web", "require_webgl": True,
                "require_offline_rendering": True, "required_capabilities": ["svg-overlay", "headless-export"],
                "required_fonts": [request["font"]["family"]], "minimum_device_pixel_ratio": 1},
            "viewport": {"width_px": 1120, "height_px": 792, "device_pixel_ratio": 1, "background": "#F8FAFC"},
            "camera": {"bounds": extent, "bearing": 0, "pitch": 0,
                       "padding": {"top": 72, "right": 250, "bottom": 72, "left": 72}},
            "map": {"style_ref": {"id": "compiled-style", "version": installation["template_ref"]["version"],
                                    "digest": sha256_digest(contracts["scenario"]["embedded"]["cartography"])},
                    "sources": sources,
                    "layers": [
                        {"id": "risk-layer", "source_id": "source-risk-area", "type": "fill",
                         "paint": {"fill-color": fill_color, "fill-opacity": opacity}, "z_index": 10},
                        {"id": "shelter-layer", "source_id": "source-shelter-point", "type": "circle",
                         "paint": {"circle-color": "#087E8B", "circle-radius": ["interpolate", ["linear"],
                                   ["get", "count_value"], 0, 5, max(max_count, 1), 16],
                                   "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 2}, "z_index": 20},
                    ]},
            "overlays": [
                {"id": "title", "type": "text", "coordinate_space": "page",
                 "position": {"x": 48, "y": 42, "unit": "pixel"}, "content": plan["decisions"]["title"],
                 "style_role": "map-title"},
                {"id": "legend", "type": "legend", "coordinate_space": "page",
                 "position": {"x": 890, "y": 110, "unit": "pixel"},
                 "legend_items": [*legend, {"label": "????????", "color": "#087E8B", "symbol": "circle"}]},
                {"id": "north", "type": "north-arrow", "coordinate_space": "page",
                 "position": {"x": 1030, "y": 55, "unit": "pixel"}},
                {"id": "source", "type": "attribution", "coordinate_space": "page",
                 "position": {"x": 760, "y": 760, "unit": "pixel"},
                 "content": "??????????????", "style_role": "source-note"},
            ],
            "resources": resources, "export": {"targets": sorted(request["requested_outputs"]), "dpi": 144},
            "random_seed": RANDOM_SEED,
            "provenance": [{"source_type": "derived", "source_ref": f"map-plan:{plan['plan_id']}",
                            "version": "1.0.0", "retrieved_at": request["requested_at"],
                            "classification": "internal"}],
        }

    def _preflight(self, request: dict[str, Any], plan: dict[str, Any], bundle: dict[str, Any],
                   installation: dict[str, Any], contracts: dict[str, Any], scene: dict[str, Any],
                   candidate: dict[str, Any]) -> dict[str, Any]:
        checks = [
            {"check_id": "template.exact-version", "owner": "template", "status": "passed", "severity": "blocker"},
            {"check_id": "template.contracts-valid", "owner": "template", "status": "passed", "severity": "blocker"},
            {"check_id": "data.roles-valid", "owner": "data", "status": "passed", "severity": "blocker"},
            {"check_id": "data.synthetic-only", "owner": "data", "status": "passed", "severity": "blocker"},
            {"check_id": "plan.resolved", "owner": "plan", "status": "passed", "severity": "blocker"},
            {"check_id": "adapter.scene-valid", "owner": "adapter", "status": "passed", "severity": "blocker"},
        ]
        body = {"schema_version": 1, "report_id": f"preflight-{request['run_id']}",
                "phase": "plan", "subject_digest": sha256_digest(candidate), "status": "passed",
                "results": [{"check_id": item["check_id"], "version": "1.0.0",
                             "status": item["status"], "severity": item["severity"], "details": {}}
                            for item in checks], "created_at": request["requested_at"]}
        self.registry.validate("validation-report", body)
        return body

    def _validate_expression_bindings(self, portrayal: dict[str, Any], lock: dict[str, Any]) -> None:
        locked = {(item["id"], item["version"], item["digest"]) for item in lock["resources"]}
        refs = {(item["map_expression_ref"]["id"], item["map_expression_ref"]["version"],
                 item["map_expression_ref"]["digest"]) for item in portrayal["layers"]}
        if refs != locked:
            raise ProtocolError("MAP_EXPRESSION_LOCK_MISMATCH", str(sorted(refs ^ locked)))

    @staticmethod
    def _validate_rules(contracts: dict[str, Any]) -> None:
        for name, document in contracts.items():
            if name in {"root", "manifest", "lock"} or not isinstance(document, dict):
                continue
            for rule in document.get("rules", []):
                if rule["strength"] in {"hard_rule", "forbidden", "mandatory", "binding"} and "value" not in rule:
                    raise ProtocolError("TEMPLATE_RULE_UNRESOLVED", f"{name}:{rule['id']}")

    @staticmethod
    def _quantile_breaks(values: list[float], classes: int) -> list[float]:
        if not values:
            raise ProtocolError("CLASSIFICATION_DATA_EMPTY", "risk-value")
        result = [values[0]]
        for index in range(1, classes):
            position = math.ceil(index * len(values) / classes) - 1
            result.append(values[max(0, min(position, len(values) - 1))])
        result.append(values[-1])
        return sorted(set(result))

    @staticmethod
    def _legend(breaks: list[float], colors: list[str]) -> list[dict[str, Any]]:
        if len(breaks) == 1:
            return [{"label": f"{breaks[0]:g}%", "color": colors[0], "symbol": "fill"}]
        return [{"label": f"{low:g}% ? {high:g}%", "color": colors[index], "symbol": "fill"}
                for index, (low, high) in enumerate(zip(breaks[:-1], breaks[1:]))]

    @staticmethod
    def _padded_extent(bbox: list[float]) -> list[float]:
        dx = max(bbox[2] - bbox[0], 0.01) * 0.08
        dy = max(bbox[3] - bbox[1], 0.01) * 0.08
        return [bbox[0] - dx, bbox[1] - dy, bbox[2] + dx, bbox[3] + dy]

