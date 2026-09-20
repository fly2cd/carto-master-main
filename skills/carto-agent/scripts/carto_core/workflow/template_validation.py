from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml

from ..adapters.controlled_renderer import (
    FRONTEND_BUILD, MAPLIBRE_VERSION, OVERLAY_ENGINE_VERSION, RANDOM_SEED,
    RENDERER_VERSION, BrowserLimits, ControlledBrowserRenderer,
    browser_version, discover_browser, sha256_file,
)
from ..adapters.webmap_renderer import (
    RendererCapabilityProfile, RendererCapabilityRegistry, WebMapRendererAdapter,
    compute_renderer_attestation,
)
from ..canonical import sha256_digest
from ..compiler.dependencies import DependencyResolver
from ..compiler.ownership import OwnershipResolver
from ..errors import CartoError, ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard

VALIDATOR_VERSION = "1.0.0"
ADAPTER_VERSION = "1.0.0"
CHECKERS = (
    ("template.package-closed", "blocker"),
    ("template.schema-valid", "blocker"),
    ("template.dependencies-pinned", "blocker"),
    ("template.kind-ownership", "error"),
    ("template.semantic-contracts", "error"),
    ("template.target-capability", "error"),
    ("template.fixture-render", "blocker"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_yaml_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        if load_document(path) == value:
            return
        raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


class TemplatePackageValidator:
    """Static-first validator and synthetic-fixture render evidence builder."""

    CONTRACT_SCHEMAS = {
        "scenario": "scenario", "data_schema": "data-role",
        "spatial_behavior": "spatial-behavior", "portrayal": "portrayal",
        "delivery": "delivery", "quality_gates": "quality-gates",
    }

    def __init__(self, *, path_guard: PathGuard, package_root: Path, evidence_root: Path,
                 attestation_key: bytes, registry: SchemaRegistry | None = None,
                 browser: str | Path | None = None, font_path: str | Path | None = None,
                 limits: BrowserLimits | None = None,
                 render_hook: Callable[[], None] | None = None) -> None:
        if len(attestation_key) < 32:
            raise SecurityError("RENDER_ATTESTATION_KEY_WEAK", "Attestation key must be at least 32 bytes")
        self.path_guard = path_guard
        self.package_root = path_guard.resolve(package_root, must_exist=True)
        self.evidence_root = path_guard.resolve(evidence_root)
        self.attestation_key = attestation_key
        self.registry = registry or SchemaRegistry()
        self.browser = path_guard.resolve(browser, must_exist=True) if browser else None
        self.font_path = path_guard.resolve(font_path, must_exist=True) if font_path else None
        self.limits = limits or BrowserLimits()
        self.render_hook = render_hook
        self.resolver = DependencyResolver()

    def validate(self, expected: dict[str, Any], expected_targets: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        snapshot = self._validate_static(expected, expected_targets, results)
        if self._has_blocking_failure(results):
            evidence = self._evidence(snapshot, results, renderer=None, receipt=None)
            self._write_evidence(evidence)
            return evidence

        receipt: dict[str, Any] | None = None
        renderer_binding: dict[str, Any] | None = None
        try:
            if self.render_hook is not None:
                self.render_hook()
            receipt, profile = self._render_fixture(snapshot, expected_targets)
            renderer_binding = {
                "renderer_id": profile.renderer_id,
                "renderer_profile_digest": profile.profile_digest(),
                "adapter_version": ADAPTER_VERSION,
                "frontend_build": FRONTEND_BUILD,
                "renderer_version": RENDERER_VERSION,
                "maplibre_version": MAPLIBRE_VERSION,
                "overlay_engine_version": OVERLAY_ENGINE_VERSION,
                "environment_fingerprint": receipt["environment_fingerprint"],
            }
            results.append(self._result("template.fixture-render", "blocker", True, {
                "receipt_digest": sha256_digest(receipt),
                "targets": sorted(item["target"] for item in receipt["output_artifacts"]),
            }))
        except (CartoError, OSError, ValueError) as exc:
            results.append(self._result("template.fixture-render", "blocker", False, exc))
        evidence = self._evidence(snapshot, results, renderer=renderer_binding, receipt=receipt)
        self._write_evidence(evidence, receipt)
        return evidence


    def _validate_static(self, expected: dict[str, Any], expected_targets: list[str],
                         results: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            snapshot = self._check_package_files()
            results.append(self._result("template.package-closed", "blocker", True, {
                "file_count": len(snapshot["actual_files"]),
                "package_digest": snapshot["package_digest"],
            }))
        except (CartoError, OSError, ValueError, TypeError) as exc:
            results.append(self._result("template.package-closed", "blocker", False, exc))
            return self._fallback_snapshot(expected)

        stages = (
            ("template.schema-valid", "blocker", lambda: self._check_schemas(snapshot),
             lambda value: snapshot.__setitem__("documents", value)),
            ("template.dependencies-pinned", "blocker", lambda: self._check_dependencies(snapshot), None),
            ("template.kind-ownership", "error", lambda: self._check_identity_and_ownership(snapshot, expected), None),
            ("template.semantic-contracts", "error", lambda: self._check_semantics(snapshot, expected, expected_targets), None),
            ("template.target-capability", "error", lambda: self._check_targets(snapshot, expected_targets), None),
        )
        for check_id, severity, operation, accept in stages:
            try:
                value = operation()
                if accept is not None:
                    accept(value)
                details: dict[str, Any] = {}
                if check_id == "template.schema-valid":
                    details["schemas"] = sorted(["manifest", "dependency-lock", "prototype-description", *self.CONTRACT_SCHEMAS.values()])
                elif check_id == "template.dependencies-pinned":
                    details["dependency_lock_digest"] = snapshot["dependency_lock_digest"]
                elif check_id == "template.kind-ownership":
                    details.update({"kind": snapshot["manifest"]["package"]["kind"], "ownership": "whole-segment"})
                elif check_id == "template.semantic-contracts":
                    details["fixture_set_digest"] = snapshot["fixture_set_digest"]
                else:
                    details.update({"targets": sorted(expected_targets), "renderer": "maplibre-web"})
                results.append(self._result(check_id, severity, True, details))
            except (CartoError, OSError, ValueError, TypeError) as exc:
                results.append(self._result(check_id, severity, False, exc))
                break
        return snapshot

    def inspect(self, expected: dict[str, Any], expected_targets: list[str],
                results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        output = results if results is not None else []
        snapshot = self._check_package_files()
        output.append(self._result("template.package-closed", "blocker", True, {
            "file_count": len(snapshot["actual_files"]), "package_digest": snapshot["package_digest"]}))
        snapshot["documents"] = self._check_schemas(snapshot)
        output.append(self._result("template.schema-valid", "blocker", True, {
            "schemas": sorted(["manifest", "dependency-lock", "prototype-description", *self.CONTRACT_SCHEMAS.values()])}))
        self._check_dependencies(snapshot)
        output.append(self._result("template.dependencies-pinned", "blocker", True, {
            "dependency_lock_digest": snapshot["dependency_lock_digest"]}))
        self._check_identity_and_ownership(snapshot, expected)
        output.append(self._result("template.kind-ownership", "error", True, {
            "kind": snapshot["manifest"]["package"]["kind"], "ownership": "whole-segment"}))
        self._check_semantics(snapshot, expected, expected_targets)
        output.append(self._result("template.semantic-contracts", "error", True, {
            "fixture_set_digest": snapshot["fixture_set_digest"]}))
        self._check_targets(snapshot, expected_targets)
        output.append(self._result("template.target-capability", "error", True, {
            "targets": sorted(expected_targets), "renderer": "maplibre-web"}))
        return snapshot

    def verify_evidence(self, evidence: dict[str, Any], expected: dict[str, Any],
                        expected_targets: list[str]) -> dict[str, Any]:
        self.registry.validate("template-validation-evidence", evidence)
        body = dict(evidence)
        supplied_digest = body.pop("evidence_digest")
        if sha256_digest(body) != supplied_digest:
            raise ProtocolError("VALIDATION_EVIDENCE_DIGEST_MISMATCH", evidence["evidence_id"])
        if evidence["status"] != "passed" or evidence["counts"]["blocker"] or evidence["counts"]["error"]:
            raise ProtocolError("TEMPLATE_VALIDATION_FAILED", evidence["evidence_id"])
        current_results: list[dict[str, Any]] = []
        snapshot = self.inspect(expected, expected_targets, current_results)
        bindings = {
            "namespace": snapshot["manifest"]["package"]["namespace"],
            "package_ref": self._package_ref(snapshot),
            "manifest_digest": snapshot["manifest_digest"],
            "dependency_lock_digest": snapshot["dependency_lock_digest"],
            "fixture_set_digest": snapshot["fixture_set_digest"],
            "checker_set_digest": self.checker_set_digest(),
        }
        for key, value in bindings.items():
            if evidence[key] != value:
                raise ProtocolError("VALIDATION_EVIDENCE_STALE", key)
        receipt_path = self.path_guard.resolve(evidence["render_receipt_ref"]["uri"], must_exist=True)
        receipt = load_document(receipt_path)
        self.registry.validate("render-receipt", receipt)
        if sha256_digest(receipt) != evidence["render_receipt_ref"]["digest"]:
            raise ProtocolError("VALIDATION_RENDER_RECEIPT_DRIFT", str(receipt_path))
        if receipt.get("renderer_attestation") != compute_renderer_attestation(receipt, self.attestation_key):
            raise ProtocolError("VALIDATION_RENDER_ATTESTATION_INVALID", receipt.get("receipt_id", "unknown"))
        renderer = evidence["renderer"]
        expected_renderer = {
            "renderer_id": receipt["renderer_id"],
            "adapter_version": ADAPTER_VERSION,
            "frontend_build": receipt["frontend_build_version"],
            "renderer_version": receipt["renderer_version"],
            "maplibre_version": receipt["maplibre_version"],
            "overlay_engine_version": receipt["overlay_engine_version"],
            "environment_fingerprint": receipt["environment_fingerprint"],
        }
        for key, value in expected_renderer.items():
            if renderer[key] != value:
                raise ProtocolError("VALIDATION_RENDERER_BINDING_MISMATCH", key)
        profile = RendererCapabilityProfile(
            renderer_id=receipt["renderer_id"], frontend_build=receipt["frontend_build_version"],
            renderer_version=receipt["renderer_version"], maplibre_version=receipt["maplibre_version"],
            overlay_engine_version=receipt["overlay_engine_version"],
            browser_engine=receipt["browser_version"], webgl_available=True,
            supported_export_formats=("svg", "png", "pdf"), max_canvas_width=4096,
            max_canvas_height=4096, device_pixel_ratio=2,
            available_fonts=("Noto Sans SC",), offline_rendering=True,
        )
        if renderer["renderer_profile_digest"] != profile.profile_digest():
            raise ProtocolError("VALIDATION_RENDERER_PROFILE_MISMATCH", receipt["renderer_id"])
        receipt_artifacts = {item["target"]: item["artifact_ref"] for item in receipt["output_artifacts"]}
        evidence_artifacts = {item["target"]: item["artifact_ref"] for item in evidence["preview_artifacts"]}
        if receipt_artifacts != evidence_artifacts or set(receipt_artifacts) != set(expected_targets):
            raise ProtocolError("VALIDATION_PREVIEW_BINDING_MISMATCH", evidence["evidence_id"])
        for artifact in evidence["preview_artifacts"]:
            path = self.path_guard.resolve(artifact["artifact_ref"]["uri"], must_exist=True)
            if sha256_file(path) != artifact["artifact_ref"]["digest"]:
                raise ProtocolError("VALIDATION_PREVIEW_DRIFT", artifact["target"])
        return snapshot

    def _check_package_files(self) -> dict[str, Any]:
        if not self.package_root.is_dir():
            raise ProtocolError("STAGING_PACKAGE_MISSING", str(self.package_root))
        package_paths = list(self.package_root.rglob("*"))
        linked = [path.relative_to(self.package_root).as_posix()
                  for path in package_paths if path.is_symlink()]
        if linked:
            raise ProtocolError("PACKAGE_LINK_FORBIDDEN", linked[0])
        actual = sorted(path.relative_to(self.package_root).as_posix()
                        for path in package_paths if path.is_file())
        checksum_path = self.package_root / "checksums.sha256"
        manifest_path = self.package_root / "manifest.yaml"
        if not checksum_path.is_file() or not manifest_path.is_file():
            raise ProtocolError("PACKAGE_REQUIRED_FILE_MISSING", "manifest.yaml/checksums.sha256")
        recorded: dict[str, str] = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64 or any(ch not in "0123456789abcdef" for ch in parts[0]):
                raise ProtocolError("PACKAGE_CHECKSUM_FORMAT_INVALID", line[:128])
            relative = PurePosixPath(parts[1])
            if relative.is_absolute() or ".." in relative.parts or "\\" in parts[1] or parts[1] in recorded:
                raise ProtocolError("PACKAGE_CHECKSUM_PATH_INVALID", parts[1])
            recorded[parts[1]] = "sha256:" + parts[0]
        expected_files = sorted(["checksums.sha256", *recorded])
        if actual != expected_files:
            raise ProtocolError("PACKAGE_FILE_SET_MISMATCH", f"expected={expected_files}; actual={actual}")
        for relative, digest in recorded.items():
            if _file_digest(self.package_root / relative) != digest:
                raise ProtocolError("PACKAGE_CHECKSUM_MISMATCH", relative)
        manifest = load_document(manifest_path)
        if not isinstance(manifest, dict):
            raise ProtocolError("PACKAGE_MANIFEST_INVALID", "manifest must be an object")
        if sorted(recorded) != sorted(["manifest.yaml", *manifest.get("files", [])]):
            raise ProtocolError("PACKAGE_MANIFEST_FILE_SET_MISMATCH", "checksums and manifest differ")
        for relative, digest in manifest.get("checksums", {}).items():
            if recorded.get(relative) != digest:
                raise ProtocolError("PACKAGE_MANIFEST_CHECKSUM_MISMATCH", relative)
        fixture_paths = sorted(path for path in manifest.get("files", []) if path.startswith("fixtures/"))
        return {
            "actual_files": actual, "recorded": recorded, "manifest": manifest,
            "package_digest": _file_digest(checksum_path),
            "manifest_digest": _file_digest(manifest_path),
            "dependency_lock_digest": _file_digest(self.package_root / manifest["dependency_lock"]),
            "fixture_set_digest": sha256_digest([{"path": path, "digest": recorded[path]} for path in fixture_paths]),
            "fixture_paths": fixture_paths,
        }

    def _check_schemas(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        manifest = snapshot["manifest"]
        self.registry.validate("manifest", manifest)
        self.resolver.validate_manifest(manifest, manifest["files"])
        documents: dict[str, Any] = {}
        lock = load_document(self.package_root / manifest["dependency_lock"])
        self.registry.validate("dependency-lock", lock)
        documents["dependency_lock"] = lock
        for key, schema_name in self.CONTRACT_SCHEMAS.items():
            value = load_document(self.package_root / manifest["business_contracts"][key])
            self.registry.validate(schema_name, value)
            documents[key] = value
        prototypes = sorted(path for path in manifest["files"]
                            if path.startswith("prototypes/") and path.endswith((".yaml", ".yml")))
        if prototypes != ["prototypes/risk-overview.yaml"]:
            raise ProtocolError("PROTOTYPE_SET_INVALID", str(prototypes))
        prototype = load_document(self.package_root / prototypes[0])
        self.registry.validate("prototype-description", prototype)
        documents["prototype"] = prototype
        if snapshot["fixture_paths"] != [prototype["fixture_ref"]]:
            raise ProtocolError("FIXTURE_SET_INVALID", str(snapshot["fixture_paths"]))
        fixture_path = self.package_root / prototype["fixture_ref"]
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("FIXTURE_INVALID", str(exc)) from exc
        if not isinstance(fixture, dict):
            raise ProtocolError("FIXTURE_INVALID", prototype["fixture_ref"])
        documents["fixture"] = fixture
        return documents

    def _check_dependencies(self, snapshot: dict[str, Any]) -> None:
        manifest = snapshot["manifest"]
        docs = snapshot["documents"]
        lock = docs["dependency_lock"]
        self.resolver.validate_lock(lock)
        identity = {key: manifest["package"][key] for key in ("namespace", "kind", "id", "version")}
        if ({key: lock["package"][key] for key in identity} != identity
                or lock["package"]["digest"] != sha256_digest(identity)):
            raise ProtocolError("DEPENDENCY_LOCK_PACKAGE_MISMATCH", manifest["package"]["id"])
        if lock["dependencies"] != manifest.get("dependencies", []):
            raise ProtocolError("DEPENDENCY_LOCK_SET_MISMATCH", manifest["package"]["id"])
        portrayal_refs = sorted((layer["map_expression_ref"] for layer in docs["portrayal"]["layers"]),
                                key=lambda item: (item["id"], item["version"], item["digest"]))
        lock_refs = sorted(lock["resources"], key=lambda item: (item["id"], item["version"], item["digest"]))
        if portrayal_refs != lock_refs:
            raise ProtocolError("MAP_EXPRESSION_LOCK_MISMATCH", manifest["package"]["id"])
        catalog_path = Path(__file__).resolve().parents[3] / "policies" / "map-expression-catalog.yaml"
        catalog = load_document(catalog_path)
        available = {(entry["expression_id"], entry["version"], sha256_digest(entry)) for entry in catalog["entries"]}
        locked = {(item["id"], item["version"], item["digest"]) for item in lock_refs}
        if locked != available:
            raise ProtocolError("MAP_EXPRESSION_CATALOG_MISMATCH", str(sorted(locked)))

    def _check_identity_and_ownership(self, snapshot: dict[str, Any], expected: dict[str, Any]) -> None:
        package = snapshot["manifest"]["package"]
        identity = {key: package[key] for key in ("namespace", "kind", "id", "version")}
        expected_identity = {key: expected[key] for key in identity}
        if identity != expected_identity:
            raise ProtocolError("TEMPLATE_IDENTITY_MISMATCH", f"expected={expected_identity}; actual={identity}")
        if package["kind"] != "map-scenario" or package["status"] != "draft":
            raise ProtocolError("TEMPLATE_KIND_STATUS_INVALID", f"{package['kind']}:{package['status']}")
        scenario = snapshot["documents"]["scenario"]
        composed = OwnershipResolver().compose_scenario(scenario, [])
        if set(composed["ownership"].values()) != {"map-scenario"}:
            raise ProtocolError("TEMPLATE_OWNERSHIP_INVALID", str(composed["ownership"]))
        if scenario["scenario_id"] != package["id"] or scenario["version"] != package["version"]:
            raise ProtocolError("SCENARIO_IDENTITY_MISMATCH", package["id"])

    def _check_semantics(self, snapshot: dict[str, Any], expected: dict[str, Any],
                         expected_targets: list[str]) -> None:
        docs = snapshot["documents"]
        fixture = docs["fixture"]
        metadata = fixture.get("carto_metadata", {})
        if fixture.get("type") != "FeatureCollection" or metadata != {
            "data_nature": "synthetic", "contains_production_data": False,
            "contains_sensitive_coordinates": False, "source_crs": "EPSG:4326",
        }:
            raise ProtocolError("FIXTURE_SAFETY_INVALID", "Fixture must be non-sensitive synthetic EPSG:4326 data")
        expected_source_crs = expected.get("source_crs")
        if expected_source_crs is not None:
            source_crs = f"{expected_source_crs['authority']}:{expected_source_crs['code']}"
            if metadata["source_crs"] != source_crs:
                raise ProtocolError("FIXTURE_SOURCE_CRS_MISMATCH", source_crs)
        expected_display_crs = expected.get("display_crs")
        if expected_display_crs is not None and docs["spatial_behavior"]["display_crs"] != expected_display_crs:
            raise ProtocolError("SPATIAL_DISPLAY_CRS_MISMATCH", str(expected_display_crs))
        roles = {role["id"]: role for role in docs["data_schema"]["roles"]}
        if set(docs["scenario"]["data_role_refs"]) != set(roles):
            raise ProtocolError("SCENARIO_DATA_ROLE_MISMATCH", str(sorted(roles)))
        layers = {layer["data_role"]: layer for layer in docs["portrayal"]["layers"]}
        if set(layers) != set(roles):
            raise ProtocolError("PORTRAYAL_DATA_ROLE_MISMATCH", str(sorted(layers)))
        geometry_alias = {"Polygon": "polygon", "MultiPolygon": "multipolygon", "Point": "point"}
        seen: set[str] = set()
        for feature in fixture.get("features", []):
            role_id = feature.get("properties", {}).get("fixture_role")
            if role_id not in roles:
                raise ProtocolError("FIXTURE_ROLE_UNKNOWN", str(role_id))
            seen.add(role_id)
            geometry = geometry_alias.get(feature.get("geometry", {}).get("type"))
            if geometry not in roles[role_id]["geometry_types"] or geometry != layers[role_id]["geometry"]:
                raise ProtocolError("FIXTURE_GEOMETRY_MISMATCH", str(role_id))
            properties = feature["properties"]
            for field in roles[role_id]["fields"]:
                value = properties.get(field["name"])
                if value is None and not field["nullable"]:
                    raise ProtocolError("FIXTURE_REQUIRED_FIELD_MISSING", f"{role_id}.{field['name']}")
                if value is not None and field["type"] == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ProtocolError("FIXTURE_FIELD_TYPE_MISMATCH", f"{role_id}.{field['name']}")
                if value is not None and field["type"] == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                    raise ProtocolError("FIXTURE_FIELD_TYPE_MISMATCH", f"{role_id}.{field['name']}")
            semantic_roles = {field["semantic_role"] for field in roles[role_id]["fields"]}
            if layers[role_id].get("value_role") not in semantic_roles:
                raise ProtocolError("PORTRAYAL_VALUE_ROLE_MISMATCH", role_id)
        required = {role_id for role_id, role in roles.items() if role["required"]}
        if not required.issubset(seen):
            raise ProtocolError("FIXTURE_REQUIRED_ROLE_MISSING", str(sorted(required - seen)))
        formats = {target["format"] for target in docs["delivery"]["targets"]}
        target_ids = {target["id"] for target in docs["delivery"]["targets"]}
        if formats != set(expected_targets) or set(docs["scenario"]["target_ids"]) != target_ids:
            raise ProtocolError("DELIVERY_TARGET_MISMATCH", str(sorted(formats)))
        prototype = docs["prototype"]
        if (set(prototype["target_ids"]) != target_ids
                or set(prototype["layer_ids"]) != {layer["id"] for layer in docs["portrayal"]["layers"]}):
            raise ProtocolError("PROTOTYPE_REFERENCE_MISMATCH", prototype["prototype_id"])

    @staticmethod
    def _check_targets(snapshot: dict[str, Any], expected_targets: list[str]) -> None:
        supported = {"svg", "png", "pdf"}
        targets = set(expected_targets)
        if not targets or not targets.issubset(supported):
            raise ProtocolError("RENDER_TARGET_UNSUPPORTED", str(sorted(targets - supported)))
        for target in snapshot["documents"]["delivery"]["targets"]:
            if target["production_ready"]:
                raise ProtocolError("DELIVERY_PRODUCTION_CLAIM_INVALID", target["id"])
            if target["format"] == "png" and target["vector_claim"] != "none":
                raise ProtocolError("DELIVERY_VECTOR_CLAIM_INVALID", target["id"])

    def _render_fixture(self, snapshot: dict[str, Any], targets: list[str]) -> tuple[dict[str, Any], RendererCapabilityProfile]:
        browser = self.browser or discover_browser()
        if browser is None or not browser.is_file():
            raise ProtocolError("RENDER_BROWSER_UNAVAILABLE", "A controlled Chromium browser is required")
        font = self._select_font()
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        output_root = self.path_guard.resolve(self.evidence_root / "previews")
        output_root.mkdir(parents=True, exist_ok=True)
        allowed_roots = [*self.path_guard.allowed_roots]
        if not any(self._is_within(font, root) for root in allowed_roots):
            allowed_roots.append(font.parent)
        renderer = ControlledBrowserRenderer(
            allowed_roots=allowed_roots, output_root=output_root,
            attestation_key=self.attestation_key, limits=self.limits, browser=browser,
        )
        profile = RendererCapabilityProfile(
            renderer_id="maplibre-web", frontend_build=FRONTEND_BUILD,
            renderer_version=RENDERER_VERSION, maplibre_version=MAPLIBRE_VERSION,
            overlay_engine_version=OVERLAY_ENGINE_VERSION,
            browser_engine=browser_version(browser), webgl_available=True,
            supported_export_formats=("svg", "png", "pdf"),
            max_canvas_width=4096, max_canvas_height=4096, device_pixel_ratio=2,
            available_fonts=("Noto Sans SC",), offline_rendering=True,
        )
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([profile]), renderer)
        scene = adapter.compile_scene(self._scene(snapshot, targets, font))
        session_id = f"template-validation-{snapshot['package_digest'][7:23]}"
        receipt = adapter.submit_render(session_id, scene, profile.renderer_id, FRONTEND_BUILD)
        adapter.validate_receipt(receipt, self.attestation_key)
        return receipt, profile

    def _scene(self, snapshot: dict[str, Any], targets: list[str], font: Path) -> dict[str, Any]:
        fixture_path = self.package_root / snapshot["fixture_paths"][0]
        fixture = snapshot["documents"]["fixture"]
        bounds = self._bounds(fixture)
        package = snapshot["manifest"]["package"]
        style_ref = {"id": "validation-style", "version": "1.0.0",
                     "digest": sha256_digest(snapshot["documents"]["scenario"]["embedded"]["cartography"])}
        fixture_ref = {"id": "validation-fixture", "version": package["version"],
                       "digest": _file_digest(fixture_path), "uri": str(fixture_path)}
        return {
            "schema_version": 1, "scene_id": f"{package['id']}-validation", "revision": 1,
            "renderer_id": "maplibre-web",
            "spatial_context": {"display_crs": {"authority": "EPSG", "code": "4326"},
                                "axis_order": "longitude-latitude", "coordinate_units": "degrees"},
            "renderer_requirements": {"renderer_id": "maplibre-web", "require_webgl": True,
                "require_offline_rendering": True, "required_capabilities": ["svg-overlay", "headless-export"],
                "required_fonts": ["Noto Sans SC"], "minimum_device_pixel_ratio": 1},
            "viewport": {"width_px": 1120, "height_px": 792, "device_pixel_ratio": 1, "background": "#F8FAFC"},
            "camera": {"bounds": bounds, "bearing": 0, "pitch": 0,
                       "padding": {"top": 72, "right": 250, "bottom": 72, "left": 72}},
            "map": {"style_ref": style_ref,
                "sources": [{"id": "fixture-source", "type": "geojson", "resource_id": "validation-fixture"}],
                "layers": [
                    {"id": "risk-fill", "source_id": "fixture-source", "type": "fill",
                     "filter": ["==", ["get", "fixture_role"], "risk-area"],
                     "paint": {"fill-color": ["interpolate", ["linear"], ["get", "risk_pct"], 0, "#FFF7BC", 50, "#FC8D59", 100, "#B10026"], "fill-opacity": 0.82}, "z_index": 10},
                    {"id": "shelter-points", "source_id": "fixture-source", "type": "circle",
                     "filter": ["==", ["get", "fixture_role"], "shelter-point"],
                     "paint": {"circle-color": "#087E8B", "circle-radius": ["interpolate", ["linear"], ["get", "capacity"], 0, 5, 500, 16], "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 2}, "z_index": 20},
                ]},
            "overlays": [
                {"id": "title", "type": "text", "coordinate_space": "page", "position": {"x": 48, "y": 42, "unit": "pixel"}, "content": "合成洪涝风险与避难场所模板验证图", "style_role": "map-title"},
                {"id": "legend", "type": "legend", "coordinate_space": "page", "position": {"x": 890, "y": 110, "unit": "pixel"}, "legend_items": [{"label": "较低风险", "color": "#FFF7BC", "symbol": "fill"}, {"label": "较高风险", "color": "#B10026", "symbol": "fill"}, {"label": "避难场所", "color": "#087E8B", "symbol": "circle"}]},
                {"id": "north", "type": "north-arrow", "coordinate_space": "page", "position": {"x": 1030, "y": 55, "unit": "pixel"}},
                {"id": "scale", "type": "scale-bar", "coordinate_space": "page", "position": {"x": 72, "y": 738, "unit": "pixel"}, "length_px": 140, "distance_label": "合成比例尺"},
                {"id": "source", "type": "attribution", "coordinate_space": "page", "position": {"x": 760, "y": 760, "unit": "pixel"}, "content": "数据来源：纯合成 Fixture", "style_role": "source-note"},
            ],
            "resources": [
                {"id": "validation-fixture", "kind": "geojson", "ref": fixture_ref, "required": True},
                {"id": "validation-font", "kind": "font", "font_family": "Noto Sans SC",
                 "ref": {"id": "validation-font", "version": "1.0.0", "digest": sha256_file(font), "uri": str(font)}, "required": True},
            ],
            "export": {"targets": sorted(targets), "dpi": 144}, "random_seed": RANDOM_SEED,
            "provenance": [{"source_type": "derived", "source_ref": "synthetic:template-validation",
                            "version": VALIDATOR_VERSION, "classification": "internal"}],
        }

    def _select_font(self) -> Path:
        candidates: list[Path] = []
        if self.font_path is not None:
            candidates.append(self.font_path)
        windows = os.environ.get("WINDIR")
        if windows:
            candidates.extend([
                Path(windows) / "Fonts" / "NotoSansSC-VF.ttf",
                Path(windows) / "Fonts" / "msyh.ttc",
                Path(windows) / "Fonts" / "simhei.ttf",
                Path(windows) / "Fonts" / "simsun.ttc",
            ])
        candidates.extend([
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ])
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        raise ProtocolError("RENDER_FONT_UNAVAILABLE", "No approved local font was found")

    def _evidence(self, snapshot: dict[str, Any], results: list[dict[str, Any]], *,
                  renderer: dict[str, Any] | None, receipt: dict[str, Any] | None) -> dict[str, Any]:
        counts = {severity: sum(1 for item in results
                                if item["severity"] == severity and item["status"] == "failed")
                  for severity in ("blocker", "error", "warning", "info")}
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "evidence_id": f"validation-{snapshot['package_digest'][7:23]}",
            "namespace": snapshot["manifest"]["package"]["namespace"],
            "package_ref": self._package_ref(snapshot),
            "manifest_digest": snapshot["manifest_digest"],
            "dependency_lock_digest": snapshot["dependency_lock_digest"],
            "fixture_set_digest": snapshot["fixture_set_digest"],
            "checker_set_digest": self.checker_set_digest(),
            "status": "failed" if counts["blocker"] or counts["error"] else "passed",
            "counts": counts, "results": results, "created_at": _now(),
        }
        if renderer is not None:
            evidence["renderer"] = renderer
        if receipt is not None:
            receipt_path = self.evidence_root / "render-receipt.yaml"
            evidence["render_receipt_ref"] = {
                "id": "fixture-render-receipt", "version": "1.0.0",
                "digest": sha256_digest(receipt), "uri": str(receipt_path),
            }
            evidence["preview_artifacts"] = [
                {"target": item["target"], "artifact_ref": item["artifact_ref"]}
                for item in receipt["output_artifacts"]
            ]
        evidence["evidence_digest"] = sha256_digest(evidence)
        self.registry.validate("template-validation-evidence", evidence)
        return evidence

    def _write_evidence(self, evidence: dict[str, Any], receipt: dict[str, Any] | None = None) -> None:
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        if receipt is not None:
            _atomic_yaml_once(self.evidence_root / "render-receipt.yaml", receipt)
        _atomic_yaml_once(self.evidence_root / "template-validation-evidence.yaml", evidence)

    def _fallback_snapshot(self, expected: dict[str, Any]) -> dict[str, Any]:
        digest = sha256_digest({"package_root": str(self.package_root), "expected": expected})
        return {
            "manifest": {"package": {**expected, "status": "draft"}},
            "package_digest": digest, "manifest_digest": digest,
            "dependency_lock_digest": digest, "fixture_set_digest": sha256_digest([]),
        }

    @staticmethod
    def _result(check_id: str, severity: str, passed: bool, details: Any) -> dict[str, Any]:
        if isinstance(details, Exception):
            safe_details = {"code": getattr(details, "code", type(details).__name__),
                            "message": str(details)[:500]}
        else:
            safe_details = details
        return {"check_id": check_id, "version": VALIDATOR_VERSION,
                "status": "passed" if passed else "failed", "severity": severity,
                "details": safe_details}

    @staticmethod
    def _has_blocking_failure(results: list[dict[str, Any]]) -> bool:
        return any(item["status"] == "failed" and item["severity"] in {"blocker", "error"}
                   for item in results)

    @staticmethod
    def checker_set_digest() -> str:
        return sha256_digest([{"id": check_id, "version": VALIDATOR_VERSION, "severity": severity}
                              for check_id, severity in CHECKERS])

    @staticmethod
    def _package_ref(snapshot: dict[str, Any]) -> dict[str, str]:
        package = snapshot["manifest"]["package"]
        return {"kind": package["kind"], "id": package["id"],
                "version": package["version"], "digest": snapshot["package_digest"]}

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _bounds(cls, fixture: dict[str, Any]) -> list[float]:
        coordinates: list[tuple[float, float]] = []

        def visit(value: Any) -> None:
            if (isinstance(value, list) and len(value) >= 2
                    and all(isinstance(item, (int, float)) for item in value[:2])):
                coordinates.append((float(value[0]), float(value[1])))
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for feature in fixture.get("features", []):
            visit(feature.get("geometry", {}).get("coordinates", []))
        if not coordinates:
            raise ProtocolError("FIXTURE_EXTENT_EMPTY", "Fixture has no coordinates")
        xs = [item[0] for item in coordinates]
        ys = [item[1] for item in coordinates]
        dx = max(max(xs) - min(xs), 0.01) * 0.15
        dy = max(max(ys) - min(ys), 0.01) * 0.15
        return [min(xs) - dx, min(ys) - dy, max(xs) + dx, max(ys) + dy]
