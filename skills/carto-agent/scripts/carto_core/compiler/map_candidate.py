from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..scenario_registry import ScenarioRegistry
from ..errors import ProtocolError
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..artifacts import file_digest
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..validation.map_checks import MapQualityChecks
from .dependencies import DependencyResolver


class MapCandidateCompiler:
    """Compile an approved plan to immutable candidate documents without rendering."""

    CONTRACT_SCHEMAS = {
        "scenario": "scenario", "data_schema": "data-role", "spatial_behavior": "spatial-behavior",
        "portrayal": "portrayal", "delivery": "delivery", "quality_gates": "quality-gates",
    }

    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None,
                 *, project_root: Path | None = None, context=None) -> None:
        self.path_guard = path_guard
        self.project_root, self.context = project_root, context
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
        if file_digest(manifest_path) != installation.get("manifest_digest"):
            raise ProtocolError("TEMPLATE_INSTALL_MANIFEST_DRIFT", str(root))
        if file_digest(checksum_path) != template_ref.get("digest"):
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
            if not target.is_file() or file_digest(target) != digest:
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
        MapQualityChecks(self.registry).selection(contracts["quality_gates"])
        lock = load_document(root / manifest["dependency_lock"])
        self.registry.validate("dependency-lock", lock)
        self.dependencies.validate_lock(lock)
        self._validate_expression_bindings(contracts["portrayal"], lock)
        self._validate_rules(contracts)
        return {"root": root, "manifest": manifest, "lock": lock, **contracts}


    def _validate_expression_bindings(self, portrayal: dict[str, Any], lock: dict[str, Any]) -> None:
        MapExpressionCatalog(self.registry).validate_portrayal(portrayal)
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


    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any], contracts: dict[str, Any],
                font_path: Path) -> dict[str, Any]:
        profile = ScenarioRegistry(self.registry).require_request_intent(request, intent)
        profile.require_contract(contracts["scenario"])
        self.registry.validate("map-plan", plan)
        profile.require_intent_projection(plan, intent, kind="PLAN")
        compiled = profile.component("candidate_compiler")(
            self.path_guard, self.registry, project_root=self.project_root, context=self.context,
        ).compile(
            request, intent, plan, bundle, installation, contracts, font_path)
        self.require_execution_intent(compiled["candidate"]["execution"], intent)
        candidate = compiled["candidate"]
        reference = MapQualityChecks(self.registry).reference(contracts["quality_gates"], compiled["scene"])
        candidate["execution"]["policy_refs"] = [
            ref for ref in candidate["execution"].get("policy_refs", []) if ref["id"] != reference["id"]
        ] + [reference]
        candidate["execution_digest"] = sha256_digest(candidate["execution"])
        compiled["preflight"] = self.check_candidate(
            request, compiled["candidate"], compiled["scene"], contracts, bundle=bundle)
        return compiled

    def check_candidate(self, request, candidate, scene, contracts, *, bundle=None):
        """Recompute the preflight so G2/replay bind actual gates, policy and inputs."""
        profile = ScenarioRegistry(self.registry).for_execution(candidate["execution"])
        profile.require_contract(contracts["scenario"])
        profile.require_scene(scene)
        self.registry.validate("resolved-map", candidate)
        self.registry.validate("render-scene", scene)
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        if candidate["execution"].get("render_scene_ref", {}).get("digest") != sha256_digest(scene):
            raise ProtocolError("CANDIDATE_SCENE_DIGEST_MISMATCH", candidate["candidate_id"])
        inputs = None
        if scene["renderer_id"] == "rasterio-matplotlib-page":
            if self.project_root is None or self.context is None:
                raise ProtocolError("RASTER_EXECUTION_CONTEXT_REQUIRED", "Raster candidates require trusted project context")
            from .raster_scene import RasterSceneCompiler
            from ..workflow.raster_preparation import RasterPreparationService
            preparation = RasterPreparationService(project_root=self.project_root,
                allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
            inputs = RasterSceneCompiler(preparation).validate_generation(
                scene, candidate["execution"], request, self.context)
            if bundle is not None and inputs["bundle"] != bundle:
                raise ProtocolError("RASTER_CANDIDATE_BUNDLE_MISMATCH", "Candidate must preserve the prepared bundle")
        return MapQualityChecks(self.registry).inspect(
            candidate, scene, contracts["quality_gates"], profile=profile, raster=inputs)

    @staticmethod
    def require_execution_intent(execution: dict[str, Any], intent: dict[str, Any]) -> None:
        if (execution.get("business_scene") != intent["business_scene"]
                or execution.get("map_tasks") != intent["tasks"]
                or execution.get("shared_semantics", {}).get("theme_tags") != intent["theme_tags"]
                or execution.get("intent_ref", {}).get("digest") != sha256_digest(intent)
                or execution.get("profile_refs") != [intent["evidence_refs"][0], intent["evidence_refs"][-1]]):
            raise ProtocolError("CANDIDATE_INTENT_MISMATCH", "Execution must preserve the resolved user intent")
