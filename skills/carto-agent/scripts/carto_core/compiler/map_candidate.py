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

    def load_contracts(self, installation: dict[str, Any], *,
                       repository=None, segment_refs: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if contracts["scenario"].get("segment_refs"):
            # S2: resolve referenced segments from the published repository at the
            # load boundary; the installed package stays byte-identical to the
            # published one. Legacy fully embedded packages never need a repository.
            if repository is None:
                raise ProtocolError("SEGMENT_REPOSITORY_REQUIRED",
                                    "Referenced segments require the published template repository")
            contracts["scenario"] = repository.resolve_scenario_segments(
                contracts["scenario"], namespace=manifest["package"]["namespace"], lock=lock)
            self.registry.validate("scenario", contracts["scenario"])
        # P4: project-level composition. A request segment reference supersedes the
        # author baseline for segments the scenario declares replaceable. Resolution
        # uses the same trusted repository fetch (exact identity + digest + package
        # integrity) as author refs — one ownership model, no second override engine.
        # The installed package is never rewritten; the effective selection is
        # recorded separately so execution can bind the exact replacing refs.
        if segment_refs:
            if repository is None:
                raise ProtocolError("SEGMENT_REPOSITORY_REQUIRED",
                                    "Referenced segments require the published template repository")
            from .ownership import OwnershipResolver
            resolver = OwnershipResolver()
            selection_ownership = resolver.validate_request_segment_refs(contracts["scenario"], segment_refs)
            resolved = deepcopy(contracts["scenario"])
            superseded: dict[str, Any] = {}
            for segment, reference in sorted(segment_refs.items()):
                author_refs = contracts["scenario"].get("segment_refs", {})
                superseded[segment] = deepcopy(author_refs.get(segment)) if segment in author_refs else "embedded"
                resolved["embedded"][segment] = repository.fetch_segment(
                    reference, namespace=manifest["package"]["namespace"])
            self.registry.validate("scenario", resolved)
            contracts["scenario"] = resolved
            contracts["segment_selection"] = {
                "refs": deepcopy(segment_refs),
                "ownership": selection_ownership,
                "superseded": superseded,
            }
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
        profile = ScenarioRegistry(self.registry).for_execution(candidate["execution"])
        request_contract = profile.component("request_contract")
        if any(request.get(key) for key in request_contract.override_keys()):
            contracts = request_contract.apply_overrides(request, deepcopy(contracts))
        profile.require_contract(contracts["scenario"])
        profile.require_scene(scene)
        self.registry.validate("resolved-map", candidate)
        self.registry.validate("render-scene", scene)
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        # P4: the frozen component binding must equal the selection authorized by the
        # fingerprint-locked request and the trusted installed package. Content checks
        # below verify the page; this verifies the *identity* of every component ref,
        # so a smuggled / missing / drifted segment ref cannot ride a passing page into
        # G2 and the lock. Shared by preflight, preview, freeze and lock re-verification.
        self._require_selection_binding(request, candidate, contracts)
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
                pages=self._require_port("pages"), environment=self._require_port("environment")).validate_execution(
                scene, candidate["execution"], self.context)
            profile.component("candidate_compiler")(self.path_guard, self.registry,
                project_root=self.project_root, context=self.context).verify_request(request, scene, inputs)
            template_style = contracts["scenario"].get("embedded", {}).get("style")
            if scene['resolved_layout']['template_contract'] != contracts['scenario']['embedded']['layout']:
                raise ProtocolError('LAYOUT_TEMPLATE_MISMATCH','Layout differs from installed template')
            if any(layer['portrayal']['portrayal'] != contracts['portrayal'] for layer in inputs['layers'].values()):
                raise ProtocolError('PORTRAYAL_TEMPLATE_MISMATCH','Expression differs from installed template')
            if inputs["page"]["appearance"]["style"] != template_style:
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
                pages=self._require_port("pages"), environment=self._require_port("environment")).validate_execution(scene, candidate["execution"], self.context)
            profile.component("candidate_compiler")(self.path_guard, self.registry,
                project_root=self.project_root, context=self.context).verify_request(request, scene, vector)
            if (scene["resolved_layout"]["template_contract"] != contracts["scenario"]["embedded"]["layout"]
                    or vector["page"]["style"] != contracts["scenario"]["embedded"]["style"]):
                raise ProtocolError("VECTOR_TEMPLATE_MISMATCH", "Page layout or appearance differs from the installed template")
            if bundle is not None and _bundle_core(bundle) != _bundle_core(vector["bundle"]):
                raise ProtocolError("VECTOR_BUNDLE_MISMATCH", "Page does not preserve the prepared bundle")
        return MapQualityChecks(self.registry).inspect(
            candidate, scene, contracts["quality_gates"], profile=profile, raster=inputs, vector=vector)

    def _require_selection_binding(self, request: dict[str, Any], candidate: dict[str, Any],
                                   contracts: dict[str, Any]) -> None:
        """P4: the frozen component binding must equal the request-authorized selection.

        Derives the expected segment binding from the fingerprint-locked request and
        compares ``execution.template_refs`` segment refs and ``ownership`` exactly.
        Missing, extra, or id/version/digest-drifted segment refs are refused, so a
        component declaration inconsistent with the G1 request cannot reach G2 or the
        lock even when the rendered page content still matches. This is the identity
        counterpart to the page-content checks in ``check_candidate``.

        The scenario component's identity is bound transitively by for_execution
        (registered capability) + require_contract (installed scenario contract) +
        load_contracts package-integrity verification, so this gate focuses on the
        project-level segment selection that those gates do not compare to the request.
        """
        execution = candidate["execution"]
        refs = execution.get("template_refs", [])
        scenario_refs = [r for r in refs if r.get("kind") == "map-scenario"]
        if len(scenario_refs) != 1:
            raise ProtocolError("CANDIDATE_COMPONENT_SELECTION_MISMATCH",
                                "Execution must bind exactly one scenario component")
        expected_segments = request.get("segment_refs") or {}
        expected_by_kind = {ref["kind"]: ref for ref in expected_segments.values()}
        actual_segments = {r["kind"]: r for r in refs if r.get("kind") in ("map-style", "map-layout")}
        if set(actual_segments) != set(expected_by_kind):
            raise ProtocolError("CANDIDATE_COMPONENT_SELECTION_MISMATCH",
                                "Execution segment refs differ from the request selection")
        for kind, ref in expected_by_kind.items():
            actual = actual_segments[kind]
            if any(actual.get(key) != ref.get(key) for key in ("id", "version", "digest")):
                raise ProtocolError("CANDIDATE_COMPONENT_SELECTION_MISMATCH",
                                    f"{kind} ref identity/digest differs from the request selection")
        ownership = execution.get("ownership", {})
        if ownership.get("scenario") != "map-scenario":
            raise ProtocolError("CANDIDATE_COMPONENT_OWNERSHIP_MISMATCH",
                                "Execution must record scenario ownership")
        for segment in ("style", "layout"):
            if segment in expected_segments:
                if ownership.get(segment) != expected_segments[segment]["kind"]:
                    raise ProtocolError("CANDIDATE_COMPONENT_OWNERSHIP_MISMATCH",
                                        f"{segment} ownership differs from the selection")
            elif segment in ownership:
                raise ProtocolError("CANDIDATE_COMPONENT_OWNERSHIP_MISMATCH",
                                    f"Unselected {segment} ownership is present")

    @staticmethod
    def require_execution_intent(execution: dict[str, Any], intent: dict[str, Any]) -> None:
        if (execution.get("business_scene") != intent["business_scene"]
                or execution.get("map_tasks") != intent["tasks"]
                or execution.get("shared_semantics", {}).get("theme_tags") != intent["theme_tags"]
                or execution.get("intent_ref", {}).get("digest") != sha256_digest(intent)
                or execution.get("profile_refs") != [intent["evidence_refs"][0], intent["evidence_refs"][-1]]):
            raise ProtocolError("CANDIDATE_INTENT_MISMATCH", "Execution must preserve the resolved user intent")

    def compile_variants(self, request, intent, plan, bundle, installation, contracts,
                         font_path, variants, plan_factory=None):
        # Deterministically compile each externally supplied design variant into its own
        # candidate and assemble a candidate-set. The program compiles, formally validates
        # (preflight) and presents the comparison only; it never ranks or selects among
        # variants -- creative choice stays with the LLM/human (design-principles).
        # P5-6: when a plan_factory is injected (by the workflow), each variant gets its OWN
        # plan built from its variant_request + variant_contracts, so a variant that changes
        # plan-affecting fields (e.g. output_profile) is not bound to a stale shared plan.
        # Without a factory the legacy shared plan is used (single-plan path).
        if not isinstance(variants, list) or not variants:
            raise ProtocolError("CANDIDATE_VARIANTS_REQUIRED", "At least one design variant is required")
        if len(variants) > 8:
            raise ProtocolError("CANDIDATE_VARIANTS_LIMIT", "At most 8 variants per candidate set")
        seen = set()
        entries = []
        compiled_by_variant = {}
        request_contract = ScenarioRegistry(self.registry).for_template(request["template"]).component("request_contract")
        override_keys = request_contract.override_keys()
        for variant in variants:
            variant_id = variant.get("variant_id")
            if not isinstance(variant_id, str) or variant_id in seen:
                raise ProtocolError("CANDIDATE_VARIANT_DUPLICATE", "Variant ids must be unique strings")
            seen.add(variant_id)
            variant_request = deepcopy(request)
            for key in override_keys:
                if variant.get(key):
                    variant_request[key] = deepcopy(variant[key])
                else:
                    variant_request.pop(key, None)
            variant_contracts = request_contract.apply_overrides(variant, deepcopy(contracts))
            variant_plan = (plan_factory(variant_request, variant_contracts)
                            if plan_factory is not None else plan)
            compiled = self.compile(variant_request, intent, variant_plan, bundle, installation,
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
