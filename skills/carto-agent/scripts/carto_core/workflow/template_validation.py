from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, Callable


from ..adapters.controlled_renderer import FRONTEND_BUILD, MAPLIBRE_VERSION, OVERLAY_ENGINE_VERSION, RENDERER_VERSION, BrowserLimits, ControlledBrowserRenderer, browser_version, discover_browser
from ..adapters.webmap_renderer import (
    RendererCapabilityProfile, RendererCapabilityRegistry, WebMapRendererAdapter,
    compute_renderer_attestation,
)
from ..artifacts import atomic_yaml, file_digest, utc_now
from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..compiler.dependencies import DependencyResolver
from ..compiler.ownership import OwnershipResolver
from ..errors import CartoError, ProtocolError, SecurityError
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..validation.registry import CheckerRegistry
from ..validation.map_checks import MapQualityChecks

VALIDATOR_VERSION = "1.3.0"
ADAPTER_VERSION = "1.0.0"


class TemplatePackageValidator:
    """Static-first validator and scenario validation render evidence builder."""

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
        self.checkers = CheckerRegistry(schema_registry=self.registry)
        self.browser = path_guard.resolve(browser, must_exist=True) if browser else None
        self.font_path = path_guard.resolve(font_path, must_exist=True) if font_path else None
        self.limits = limits or BrowserLimits()
        self.render_hook = render_hook
        self.resolver = DependencyResolver()

    def validate(self, expected: dict[str, Any], expected_targets: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        snapshot = self._validate_static(expected, expected_targets, results)
        if self.checkers.has_blocking_failure(results):
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
            results.append(self._result("template.fixture-render", True, {
                "receipt_digest": sha256_digest(receipt),
                "targets": sorted(item["target"] for item in receipt["output_artifacts"]),
            }))
        except (CartoError, OSError, ValueError) as exc:
            results.append(self._result("template.fixture-render", False, exc))
        evidence = self._evidence(snapshot, results, renderer=renderer_binding, receipt=receipt)
        self._write_evidence(evidence, receipt)
        return evidence


    def _validate_static(self, expected: dict[str, Any], expected_targets: list[str],
                         results: list[dict[str, Any]], *, raise_errors: bool = False) -> dict[str, Any]:
        try:
            snapshot = self._check_package_files()
            results.append(self._result("template.package-closed", True, {
                "file_count": len(snapshot["actual_files"]),
                "package_digest": snapshot["package_digest"],
            }))
        except (CartoError, OSError, ValueError, TypeError) as exc:
            if raise_errors:
                raise
            results.append(self._result("template.package-closed", False, exc))
            return self._fallback_snapshot(expected)

        stages = (
            ("template.schema-valid", lambda: self._check_schemas(snapshot),
             lambda value: snapshot.__setitem__("documents", value)),
            ("template.dependencies-pinned", lambda: self._check_dependencies(snapshot), None),
            ("template.kind-ownership", lambda: self._check_identity_and_ownership(snapshot, expected), None),
            ("template.semantic-contracts", lambda: self._check_semantics(snapshot, expected, expected_targets), None),
            ("template.target-capability", lambda: self._check_targets(snapshot, expected_targets), None),
        )
        for check_id, operation, accept in stages:
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
                results.append(self._result(check_id, True, details))
            except (CartoError, OSError, ValueError, TypeError) as exc:
                if raise_errors:
                    raise
                results.append(self._result(check_id, False, exc))
                break
        return snapshot

    def inspect(self, expected: dict[str, Any], expected_targets: list[str],
                results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._validate_static(expected, expected_targets,
                                     results if results is not None else [], raise_errors=True)

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
            if file_digest(path) != artifact["artifact_ref"]["digest"]:
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
            if file_digest(self.package_root / relative) != digest:
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
            "package_digest": file_digest(checksum_path),
            "manifest_digest": file_digest(manifest_path),
            "dependency_lock_digest": file_digest(self.package_root / manifest["dependency_lock"]),
            "fixture_set_digest": sha256_digest([{"path": path, "digest": recorded[path]} for path in fixture_paths]),
            "fixture_paths": fixture_paths,
        }

    def _check_schemas(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        manifest = snapshot["manifest"]
        self.registry.validate("manifest", manifest)
        ScenarioRegistry(self.registry).for_template(manifest["package"])
        self.resolver.validate_manifest(manifest, manifest["files"])
        documents: dict[str, Any] = {}
        lock = load_document(self.package_root / manifest["dependency_lock"])
        self.registry.validate("dependency-lock", lock)
        documents["dependency_lock"] = lock
        for key, schema_name in self.CONTRACT_SCHEMAS.items():
            value = load_document(self.package_root / manifest["business_contracts"][key])
            self.registry.validate(schema_name, value)
            documents[key] = value
        MapQualityChecks(self.registry).selection(documents["quality_gates"])
        prototypes = sorted(path for path in manifest["files"]
                            if path.startswith("prototypes/") and path.endswith((".yaml", ".yml")))
        if len(prototypes) != 1:
            raise ProtocolError("PROTOTYPE_SET_INVALID", str(prototypes))
        prototype = load_document(self.package_root / prototypes[0])
        self.registry.validate("prototype-description", prototype)
        documents["prototype"] = prototype
        if snapshot["fixture_paths"] != [prototype["fixture_ref"]]:
            raise ProtocolError("FIXTURE_SET_INVALID", str(snapshot["fixture_paths"]))
        # Parsing and safety checks belong to the registered scenario. No assumed data format.
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
        from ..repository.map_expression_catalog import MapExpressionCatalog
        catalog = MapExpressionCatalog(self.registry)
        catalog.validate_portrayal(docs["portrayal"])
        for reference in lock_refs:
            catalog.require(reference)

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
        profile = ScenarioRegistry(self.registry).for_template(snapshot["manifest"]["package"])
        # Required, fail-closed component: validates content, source CRS, data roles and
        # licensing/sensitivity before any validation input can enter a published package.
        profile.component("validation_data_checker")(self.package_root, snapshot, expected)
        profile.require_contract(docs["scenario"])
        expected_display_crs = expected.get("display_crs")
        if expected_display_crs is not None and docs["spatial_behavior"]["display_crs"] != expected_display_crs:
            raise ProtocolError("SPATIAL_DISPLAY_CRS_MISMATCH", str(expected_display_crs))
        roles = {role["id"]: role for role in docs["data_schema"]["roles"]}
        if set(docs["scenario"]["data_role_refs"]) != set(roles):
            raise ProtocolError("SCENARIO_DATA_ROLE_MISMATCH", str(sorted(roles)))
        layers = {layer["data_role"]: layer for layer in docs["portrayal"]["layers"]}
        if set(layers) != set(roles):
            raise ProtocolError("PORTRAYAL_DATA_ROLE_MISMATCH", str(sorted(layers)))
        for role_id, layer in layers.items():
            semantic_roles = {field["semantic_role"] for field in roles[role_id]["fields"]}
            if layer.get("value_role") is not None and layer["value_role"] not in semantic_roles:
                raise ProtocolError("PORTRAYAL_VALUE_ROLE_MISMATCH", role_id)
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
        profile = ScenarioRegistry().for_template(snapshot["manifest"]["package"])
        resolved = LayoutResolver().resolve(snapshot["documents"]["scenario"]["embedded"]["layout"],
                                            profile.definition["output_profile"]["dpi"])
        if any(resolved["page"][key] != profile.definition["output_profile"][key]
               for key in ("width_mm", "height_mm", "dpi", "width_px", "height_px")):
            raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH", "Layout differs from the enabled output profile")
        LayoutResolver.validate_targets(resolved, [target["page"] for target in snapshot["documents"]["delivery"]["targets"]])
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
        profile = ScenarioRegistry(self.registry).for_template(snapshot["manifest"]["package"])
        return profile.component("validation_scene")(
            self.package_root, snapshot, targets, font, VALIDATOR_VERSION)

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
            "status": "failed" if self.checkers.has_blocking_failure(results) else "passed",
            "counts": counts, "results": results, "created_at": utc_now(),
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
            atomic_yaml(self.evidence_root / "render-receipt.yaml", receipt)
        atomic_yaml(self.evidence_root / "template-validation-evidence.yaml", evidence)

    def _fallback_snapshot(self, expected: dict[str, Any]) -> dict[str, Any]:
        digest = sha256_digest({"package_root": str(self.package_root), "expected": expected})
        return {
            "manifest": {"package": {**expected, "status": "draft"}},
            "package_digest": digest, "manifest_digest": digest,
            "dependency_lock_digest": digest, "fixture_set_digest": sha256_digest([]),
        }

    def _result(self, check_id: str, passed: bool, details: Any) -> dict[str, Any]:
        if isinstance(details, Exception):
            safe_details = {"code": getattr(details, "code", type(details).__name__),
                            "message": str(details)[:500]}
        else:
            safe_details = details
        return self.checkers.result(check_id, passed, safe_details).to_dict()

    def checker_set_digest(self) -> str:
        return self.checkers.phase_digest("template-validate")

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
