from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..scenario_registry import ScenarioRegistry
from ..errors import ProtocolError
from ..repository.map_expression_catalog import MapExpressionCatalog
from ..artifacts import file_digest, utc_now
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..validation.map_checks import MapQualityChecks
from .dependencies import DependencyResolver
from ..contracts.bundle import bundle_core as _bundle_core
from ..contracts.protocols import (BundlePreparerFactory, EnvironmentSnapshotProvider,
                                   MaterialFactsVerifier, PageContractFactory,
                                   PreparationServiceFactory)


class MapCandidateCompiler:
    """Compile an approved plan to immutable candidate documents without rendering."""

    CONTRACT_SCHEMAS = {
        "scenario": "scenario", "data_schema": "data-role", "spatial_behavior": "spatial-behavior",
        "portrayal": "portrayal", "delivery": "delivery", "quality_gates": "quality-gates",
    }

    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None,
                 *, project_root: Path | None = None, context=None,
                 preparations: PreparationServiceFactory | None = None,
                 material_facts: MaterialFactsVerifier | None = None,
                 bundles: BundlePreparerFactory | None = None,
                 pages: PageContractFactory | None = None,
                 environment: EnvironmentSnapshotProvider | None = None) -> None:
        self.path_guard = path_guard
        self.project_root, self.context = project_root, context
        self.registry = registry or SchemaRegistry()
        self.dependencies = DependencyResolver()
        # Execution-layer ports (Tier-2 去环 Step6), injected by the composition root.
        # They are optional only because load_contracts() / require_execution_intent()
        # need neither; every path that does need one fails closed through
        # _require_port instead of importing workflow from the kernel.
        self.bundles, self.preparations = bundles, preparations
        self.material_facts = material_facts
        self.pages, self.environment = pages, environment

    def _require_port(self, name: str):
        """Return an injected execution-layer port, or fail closed naming it."""
        port = getattr(self, name)
        if port is None:
            raise ProtocolError("COMPILER_PORT_NOT_INJECTED",
                f"MapCandidateCompiler.{name} must be injected by the composition root; "
                "the compiler layer does not import the execution layer")
        return port

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
        catalog = MapExpressionCatalog(self.registry)
        refs = {(ref["id"], ref["version"], ref["digest"]) for ref in catalog.references(portrayal)}
        locked = {(ref["id"], ref["version"], ref["digest"]) for ref in lock["resources"]}
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
        overrides = request.get("revised_cartography") or request.get("output_profile")
        if overrides:
            contracts = deepcopy(contracts)
            if request.get("revised_cartography"):
                contracts["scenario"]["embedded"]["cartography"] = deepcopy(request["revised_cartography"])
            if request.get("output_profile"):
                contracts.setdefault("scenario", {}).setdefault("embedded", {}).setdefault("layout", {}).setdefault("canvas", {})
                op = request["output_profile"]
                if "width_mm" in op:
                    contracts["scenario"]["embedded"]["layout"]["canvas"]["width"] = op["width_mm"]
                if "height_mm" in op:
                    contracts["scenario"]["embedded"]["layout"]["canvas"]["height"] = op["height_mm"]
        profile = ScenarioRegistry(self.registry).for_execution(candidate["execution"])
        profile.require_contract(contracts["scenario"])
        profile.require_scene(scene)
        self.registry.validate("resolved-map", candidate)
        self.registry.validate("render-scene", scene)
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        if candidate["execution"].get("render_scene_ref", {}).get("digest") != sha256_digest(scene):
            raise ProtocolError("CANDIDATE_SCENE_DIGEST_MISMATCH", candidate["candidate_id"])
        self._require_port("material_facts")(
            candidate["execution"], self.path_guard, self.project_root, self.registry)
        from ..backend_registry import RASTER_PAGE, VECTOR_PAGE
        inputs = None
        if scene["renderer_id"] == RASTER_PAGE.renderer_id:
            if self.project_root is None or self.context is None:
                raise ProtocolError("RASTER_EXECUTION_CONTEXT_REQUIRED", "Raster candidates require trusted project context")
            from .raster_scene import RasterSceneCompiler
            preparation = self._require_port("preparations")(
                "raster", project_root=self.project_root,
                allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
            inputs = RasterSceneCompiler(preparation, bundles=self._require_port("bundles"),
                pages=self._require_port("pages"), environment=self._require_port("environment")).validate_generation(
                scene, candidate["execution"], request, self.context)
            template_style = contracts["scenario"].get("embedded", {}).get("cartography")
            if scene['resolved_layout']['template_contract'] != contracts['scenario']['embedded']['layout']:
                raise ProtocolError('LAYOUT_TEMPLATE_MISMATCH','Layout differs from installed template')
            if any(layer['portrayal']['portrayal'] != contracts['portrayal'] for layer in inputs['layers'].values()):
                raise ProtocolError('PORTRAYAL_TEMPLATE_MISMATCH','Expression differs from installed template')
            if inputs["page"]["appearance"]["cartography"] != template_style:
                raise ProtocolError("APPEARANCE_TEMPLATE_MISMATCH", "Page appearance differs from the installed template")
            if bundle is not None and _bundle_core(inputs["bundle"]) != _bundle_core(bundle):
                raise ProtocolError("RASTER_CANDIDATE_BUNDLE_MISMATCH", "Candidate must preserve the prepared bundle")
        vector = None
        if scene["renderer_id"] == VECTOR_PAGE.renderer_id:
            from .vector_scene import VectorSceneCompiler
            service = self._require_port("preparations")(
                "vector", project_root=self.project_root,
                allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
            vector = VectorSceneCompiler(service, bundles=self._require_port("bundles"),
                pages=self._require_port("pages"), environment=self._require_port("environment")).validate_generation(scene, candidate["execution"], request, self.context)
            if (scene["resolved_layout"]["template_contract"] != contracts["scenario"]["embedded"]["layout"]
                    or vector["page"]["cartography"] != contracts["scenario"]["embedded"]["cartography"]):
                raise ProtocolError("VECTOR_TEMPLATE_MISMATCH", "Page layout or appearance differs from the installed template")
            if bundle is not None and _bundle_core(bundle) != _bundle_core(vector["bundle"]):
                raise ProtocolError("VECTOR_BUNDLE_MISMATCH", "Page does not preserve the prepared bundle")
        return MapQualityChecks(self.registry).inspect(
            candidate, scene, contracts["quality_gates"], profile=profile, raster=inputs, vector=vector)

    @staticmethod
    def require_execution_intent(execution: dict[str, Any], intent: dict[str, Any]) -> None:
        if (execution.get("business_scene") != intent["business_scene"]
                or execution.get("map_tasks") != intent["tasks"]
                or execution.get("shared_semantics", {}).get("theme_tags") != intent["theme_tags"]
                or execution.get("intent_ref", {}).get("digest") != sha256_digest(intent)
                or execution.get("profile_refs") != [intent["evidence_refs"][0], intent["evidence_refs"][-1]]):
            raise ProtocolError("CANDIDATE_INTENT_MISMATCH", "Execution must preserve the resolved user intent")

    @staticmethod
    def _apply_design_overrides(contracts, variant):
        # Inject one externally supplied variant's cartography/output_profile into a copy
        # of the contracts, mirroring the single-candidate override path. Deterministic;
        # never ranks or selects among variants.
        contracts = deepcopy(contracts)
        cartography = variant.get("revised_cartography")
        output_profile = variant.get("output_profile")
        if cartography:
            contracts.setdefault("scenario", {}).setdefault("embedded", {})
            contracts["scenario"]["embedded"]["cartography"] = deepcopy(cartography)
        if output_profile:
            canvas = contracts.setdefault("scenario", {}).setdefault("embedded", {})
            canvas = canvas.setdefault("layout", {}).setdefault("canvas", {})
            if "width_mm" in output_profile:
                canvas["width"] = output_profile["width_mm"]
            if "height_mm" in output_profile:
                canvas["height"] = output_profile["height_mm"]
        return contracts

    def compile_variants(self, request, intent, plan, bundle, installation, contracts,
                         font_path, variants):
        # Deterministically compile each externally supplied design variant into its own
        # candidate and assemble a candidate-set. The program compiles, formally validates
        # (preflight) and presents the comparison only; it never ranks or selects among
        # variants -- creative choice stays with the LLM/human (design-principles).
        if not isinstance(variants, list) or not variants:
            raise ProtocolError("CANDIDATE_VARIANTS_REQUIRED", "At least one design variant is required")
        if len(variants) > 8:
            raise ProtocolError("CANDIDATE_VARIANTS_LIMIT", "At most 8 variants per candidate set")
        seen = set()
        entries = []
        compiled_by_variant = {}
        for variant in variants:
            variant_id = variant.get("variant_id")
            if not isinstance(variant_id, str) or variant_id in seen:
                raise ProtocolError("CANDIDATE_VARIANT_DUPLICATE", "Variant ids must be unique strings")
            seen.add(variant_id)
            variant_request = deepcopy(request)
            if variant.get("revised_cartography"):
                variant_request["revised_cartography"] = deepcopy(variant["revised_cartography"])
            else:
                variant_request.pop("revised_cartography", None)
            if variant.get("output_profile"):
                variant_request["output_profile"] = deepcopy(variant["output_profile"])
            else:
                variant_request.pop("output_profile", None)
            variant_contracts = self._apply_design_overrides(contracts, variant)
            compiled = self.compile(variant_request, intent, plan, bundle, installation,
                                    variant_contracts, font_path)
            candidate = compiled["candidate"]
            candidate["candidate_id"] = "candidate-" + request["run_id"] + "-" + variant_id
            # Re-run preflight so its subject_digest binds the rewritten candidate_id;
            # otherwise the frozen candidate and its report drift apart at G2 replay.
            compiled["preflight"] = self.check_candidate(
                variant_request, candidate, compiled["scene"], variant_contracts, bundle=bundle)
            compiled_by_variant[variant_id] = compiled
            entries.append({
                "variant_id": variant_id,
                "candidate_id": candidate["candidate_id"],
                "resolved_map_digest": sha256_digest(candidate),
                "render_scene_digest": sha256_digest(compiled["scene"]),
                "preflight_status": "passed" if compiled["preflight"]["status"] == "passed" else "failed",
                "preflight_report_digest": sha256_digest(compiled["preflight"]),
            })
        candidate_set = {
            "schema_version": 1,
            "set_id": "candidate-set-" + request["run_id"],
            "run_id": request["run_id"],
            "project_id": request["project_id"],
            "candidates": entries,
            "created_at": utc_now(),
        }
        self.registry.validate("candidate-set", candidate_set)
        return {"candidate_set": candidate_set, "compiled": compiled_by_variant}
