from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from .canonical import sha256_digest
from .errors import ProtocolError
from .schema_registry import SchemaRegistry, load_document

# Code identifiers are a closed allowlist, never import paths supplied by a request/policy.
# One bundle per business purpose: geometry (raster | vector) is a strategy branch inside
# the bundle, never a second registration of the same purpose.
_COMPONENTS: dict[str, dict[str, tuple[str, str]]] = {
    "general-thematic": {
        name: (".scenarios.general_dispatch", attribute)
        for name, attribute in (
            ("data_preparer", "GeneralDataPreparer"),
            ("planner", "GeneralPlanner"),
            ("candidate_compiler", "GeneralCandidateCompiler"),
            ("legend_checker", "legend_checker"),
            ("source_contract", "SOURCE_CONTRACT"),
            ("author", "GeneralAuthor"),
            ("validation_data_checker", "validation_data_checker"),
            ("validation_scene", "validation_scene"),
        )
    },
}

REQUIRED_COMPONENTS = {
    # Always required — data admission and safety are universal.
    "admission": ("source_contract",),
    # create-template route (T1 → author → validate → TP).
    "create-template": ("author", "validation_data_checker", "validation_scene"),
    # generate-map route (G1 → data-prep → plan → compile → G2 → render → check → G3).
    "generate-map": ("data_preparer", "planner", "candidate_compiler", "legend_checker"),
}

# Geometries a profile may admit. A bundle registers code; policy admits geometries.
GEOMETRIES = ("raster", "vector")

# Disclosure-only fields: editing them must not invalidate frozen executions.
DISCLOSURE_FIELDS = ("notice", "licenses")


def semantic_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """The digest-relevant subset; disclosure wording is not execution semantics."""
    return {key: value for key, value in definition.items() if key not in DISCLOSURE_FIELDS}


def provided_components(implementation: str) -> set[str]:
    return set(_COMPONENTS.get(implementation, {}))


# The geometry-adaptation fields a variant contributes to the effective definition.
VARIANT_FIELDS = ("template", "authoring_profile", "renderer_id")


def effective_definitions(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten each policy profile into one effective definition per geometry variant.

    ADR-001 §9.5 项④: the versioned policy declares the shared business semantics,
    intent, output and layout envelope exactly once and lists geometry as a
    data-adaptation attribute. Consumers keep reading one flat contract
    (``template`` / ``authoring_profile`` / ``renderer_id`` / ``template_geometry`` /
    ``allowed_geometries``), so the convergence stays in the policy instead of leaking
    a second definition shape into the code.
    """
    flattened: list[dict[str, Any]] = []
    for profile in profiles:
        shared = {key: value for key, value in profile.items() if key != "geometry_variants"}
        for variant in profile["geometry_variants"]:
            definition = deepcopy(shared)
            for field in VARIANT_FIELDS:
                definition[field] = deepcopy(variant[field])
            definition["template_geometry"] = variant["geometry"]
            # The variant list is the geometry admission lever: a geometry is admitted
            # exactly when its variant is declared, so the allowed set is that geometry.
            definition["allowed_geometries"] = [variant["geometry"]]
            flattened.append(definition)
    return flattened


def required_components_for_routes(routes: list[str]) -> set[str]:
    """Union of REQUIRED_COMPONENTS for the given route names plus the admission baseline."""
    required: set[str] = set(REQUIRED_COMPONENTS.get("admission", ()))
    for route in routes:
        required.update(REQUIRED_COMPONENTS.get(route, ()))
    return required


@dataclass(frozen=True)
class ScenarioCapability:
    """A validated, trusted capability definition; not a user-selected executable."""

    _definition: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_definition", deepcopy(self._definition))

    @property
    def definition(self) -> dict[str, Any]:
        return deepcopy(self._definition)

    @property
    def ref(self) -> dict[str, str]:
        return {"id": self.definition["id"], "version": self.definition["version"],
                "digest": sha256_digest(semantic_definition(self._definition))}

    @property
    def notice(self) -> str:
        return self.definition["notice"]

    def component(self, name: str) -> Any:
        entry = _COMPONENTS.get(self.definition["implementation"], {}).get(name)
        if entry is None:
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE", "Scenario component is not registered")
        module, attribute = entry
        return getattr(import_module(module, package=__package__), attribute)

    def require_semantics(self, business_scene: str, tasks: list[str], theme_tags: list[str]) -> None:
        constraints = self.definition["intent_constraints"]
        if (business_scene != constraints["business_scene"]
                or not tasks or not set(tasks).issubset(constraints["allowed_tasks"])
                or not set(theme_tags).issubset(constraints["allowed_theme_tags"])
                or not set(constraints["required_theme_tags"]).issubset(theme_tags)):
            raise ProtocolError("SCENARIO_INTENT_MISMATCH", "Selected template capability does not support the user intent")

    def bind_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        resolver = _intent_resolver()
        resolver.require_current_intent(intent)
        self.require_semantics(intent["business_scene"], intent["tasks"], intent["theme_tags"])
        if len(intent["evidence_refs"]) != 2 or intent["evidence_refs"][1]["id"] != "intent-input":
            raise ProtocolError("INTENT_EVIDENCE_INVALID", "Expected unbound catalog and user-input evidence")
        bound = deepcopy(intent)
        bound["evidence_refs"].append(self.ref)
        return bound

    @staticmethod
    def require_intent_projection(document: dict[str, Any], intent: dict[str, Any], *, kind: str) -> None:
        if (any(document.get(key) != intent[key] for key in ("business_scene", "theme_tags", "tasks"))
                or document.get("intent_ref", {}).get("digest") != sha256_digest(intent)):
            raise ProtocolError(f"{kind}_INTENT_MISMATCH", "Artifact must preserve the resolved user intent")

    def require_contract(self, contract: dict[str, Any]) -> None:
        constraints = self.definition["intent_constraints"]
        if (contract.get("business_scene") != constraints["business_scene"]
                or set(contract.get("tasks", [])) != set(constraints["allowed_tasks"])
                or contract.get("scenario_id") != self.definition["template"]["id"]
                or contract.get("version") != self.definition["template"]["version"]):
            raise ProtocolError("SCENARIO_CONTRACT_MISMATCH", "Template contract differs from its registered capability")

    def require_scene(self, scene: dict[str, Any]) -> None:
        constraints = self.definition.get("output_constraints")
        if constraints is not None:
            # Range-based validation: scene must be within the allowed envelope.
            viewport = scene.get("viewport", {})
            dpi = scene.get("export", {}).get("dpi", 0)
            max_width_px = int(constraints["max_width_mm"] * dpi / 25.4)
            max_height_px = int(constraints["max_height_mm"] * dpi / 25.4)
            if (viewport.get("width_px", 0) > max_width_px
                    or viewport.get("height_px", 0) > max_height_px
                    or dpi < constraints.get("min_dpi", 1)
                    or dpi > constraints.get("max_dpi", 10000)):
                raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                                    "Scene dimensions exceed the scenario output constraints")
            return
        # Legacy exact-match path (removed once all profiles declare output_constraints).
        output = self.definition.get("output_profile", {})
        if output and (any(scene.get("viewport", {}).get(key) != output[key]
                          for key in ("width_px", "height_px"))
                       or scene.get("export", {}).get("dpi") != output["dpi"]):
            raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                                "Scene dimensions differ from the enabled profile")

    def require_manifest(self, manifest: dict[str, Any]) -> None:
        if (manifest.get("licenses") != self.definition["licenses"]
                or manifest.get("limitations") != [self.notice]):
            raise ProtocolError("DELIVERY_SCENARIO_POLICY_MISMATCH", "Delivery disclosure or licenses differ from the frozen scenario")

    def require_intent(self, intent: dict[str, Any]) -> None:
        _intent_resolver().require_current_intent(intent)
        self.require_semantics(intent["business_scene"], intent["tasks"], intent["theme_tags"])
        evidence = intent["evidence_refs"]
        if len(evidence) != 3 or evidence[1]["id"] != "intent-input" or evidence[2] != self.ref:
            raise ProtocolError("SCENARIO_PROFILE_DRIFT", "Intent is not bound to the current capability")


def _intent_resolver(registry: SchemaRegistry | None = None):
    # Local import avoids the workflow package's template-validation import cycle.
    from .workflow.intent import IntentResolver
    return IntentResolver(registry=registry)


class ScenarioRegistry:
    """Separate protocol structure from capability authorization; deny unknown profiles."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        # This is a packaged policy, never a path from a business request or doc/.
        policy = load_document(Path(__file__).resolve().parents[2] / "policies/scenario-capabilities.yaml")
        self.registry.validate("scenario-capabilities", policy)
        self.intent_resolver = _intent_resolver(self.registry)
        self._templates: dict[tuple[str, str, str], ScenarioCapability] = {}
        identities: set[tuple[str, str, str]] = set()
        authoring: set[str] = set()
        for definition in effective_definitions(policy["profiles"]):
            # One profile now yields one identity per geometry variant; the geometry is
            # part of the identity so a duplicated variant stays ambiguous registration.
            identity = (definition["id"], definition["version"], definition["template_geometry"])
            template = definition["template"]
            key = tuple(template[name] for name in ("kind", "id", "version"))
            if key in self._templates or identity in identities or definition["authoring_profile"] in authoring:
                raise ProtocolError("SCENARIO_PROFILE_DUPLICATE", "Ambiguous scenario registration")
            if definition["implementation"] not in _COMPONENTS:
                raise ProtocolError("CAPABILITY_NOT_AVAILABLE", "Scenario implementation is not registered")
            geometries = definition.get("allowed_geometries", list(GEOMETRIES))
            if not geometries or set(geometries) - set(GEOMETRIES):
                raise ProtocolError("SCENARIO_GEOMETRY_CONSTRAINT_INVALID",
                                    "Admitted geometries must be a non-empty subset of the bundle strategies")
            routes = definition.get("routes", ["create-template", "generate-map"])
            missing = sorted(required_components_for_routes(routes) - provided_components(definition["implementation"]))
            if missing:
                raise ProtocolError("CAPABILITY_NOT_AVAILABLE", f"Scenario components incomplete: {missing}")
            if any(name not in self.registry.schemas for name in definition["request_schemas"].values()):
                raise ProtocolError("SCENARIO_PROFILE_SCHEMA_UNKNOWN", "Scenario constraint schema is not registered")
            constraints = definition["intent_constraints"]
            self.intent_resolver.validate_selection(constraints["business_scene"],
                constraints["allowed_tasks"], constraints["allowed_theme_tags"])
            if not set(constraints["required_theme_tags"]).issubset(constraints["allowed_theme_tags"]):
                raise ProtocolError("SCENARIO_THEME_CONSTRAINT_INVALID", "Required topics must also be allowed")
            identities.add(identity)
            authoring.add(definition["authoring_profile"])
            self._templates[key] = ScenarioCapability(deepcopy(definition))

    def for_template(self, template: dict[str, Any]) -> ScenarioCapability:
        key = tuple(template.get(name) for name in ("kind", "id", "version"))
        try:
            return self._templates[key]
        except (KeyError, TypeError) as exc:
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE", "Template has no enabled scenario capability") from exc

    def for_create(self, request: dict[str, Any]) -> ScenarioCapability:
        self.registry.validate("template-create-request", request)
        profile = self.for_template({"kind": request["kind"], "id": request["template_id"],
                                     "version": request["version"]})
        if request["profile"] != profile.definition["authoring_profile"]:
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE", "Authoring profile does not match the template")
        self.registry.validate(profile.definition["request_schemas"]["create-template"], request)
        from .scenarios.general_dispatch import geometry_of_request
        # One geometry gate: a capability's allowed set is exactly the geometry of the
        # variant that registered the requested template asset, so a second
        # template_geometry comparison could never disagree with this one.
        self.require_geometry(profile, geometry_of_request(request))
        return profile

    def resolve_generate(self, request: dict[str, Any]) -> tuple[ScenarioCapability, dict[str, Any]]:
        self.registry.validate("generate-request", request)
        # Understand the user request first; selecting a template never supplies missing semantics.
        intent = self.intent_resolver.resolve({
            "schema_version": 1, "text": request["goal"], "selection": request["intent"],
            "intent_id": f"intent-{request.get('run_id', request['request_id'])}",
        }, available_capabilities=request.get("allowed_capabilities", []))
        self.intent_resolver.require_current_intent(intent)
        profile = self.for_template(request.get("template", {}))
        self.registry.validate(profile.definition["request_schemas"]["generate-map"], request)
        from .scenarios.general_dispatch import geometry_of_request
        self.require_geometry(profile, geometry_of_request(request))
        return profile, profile.bind_intent(intent)

    @staticmethod
    def require_geometry(profile: ScenarioCapability, geometry: str) -> None:
        """Code registers strategies; the profile decides which geometries are admitted."""
        allowed = set(profile.definition.get("allowed_geometries", GEOMETRIES))
        if geometry not in allowed:
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE",
                                f"Geometry '{geometry}' is not admitted by profile {profile.definition['id']}")

    def for_generate(self, request: dict[str, Any]) -> ScenarioCapability:
        return self.resolve_generate(request)[0]

    def generate_intent(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.resolve_generate(request)[1]

    def require_request_intent(self, request: dict[str, Any], intent: dict[str, Any]) -> ScenarioCapability:
        profile, expected = self.resolve_generate(request)
        if intent != expected:
            raise ProtocolError("MAP_INTENT_INPUT_DRIFT", "Persisted intent differs from the user request and current policy")
        return profile

    def for_execution(self, execution: dict[str, Any]) -> ScenarioCapability:
        templates = execution.get("template_refs", [])
        if len(templates) != 1:
            raise ProtocolError("SCENARIO_PROFILE_BINDING_INVALID", "Execution needs exactly one scenario template")
        profile = self.for_template(templates[0])
        if execution.get("profile_refs") != [self.intent_resolver.catalog_ref, profile.ref]:
            raise ProtocolError("SCENARIO_PROFILE_DRIFT", "Frozen execution no longer matches the scenario policy")
        semantics = execution.get("shared_semantics", {})
        tasks = execution.get("map_tasks", [])
        tags = semantics.get("theme_tags", [])
        scene = execution.get("business_scene")
        self.intent_resolver.validate_selection(scene, tasks, tags)
        profile.require_semantics(scene, tasks, tags)
        if "theme_tags" not in semantics or semantics.get("data_nature") != profile.definition["data_nature"]:
            raise ProtocolError("SCENARIO_PROFILE_BINDING_INVALID", "Execution semantics differ from the enabled profile")
        targets = execution.get("targets", {})
        if not targets:
            raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH", "Locked execution has no targets")
        constraints = profile.definition.get("output_constraints")
        if constraints is not None:
            # Range-based validation.
            for target in targets.values():
                if (target.get("width_mm", 0) > constraints["max_width_mm"]
                        or target.get("height_mm", 0) > constraints["max_height_mm"]
                        or target.get("dpi", 0) < constraints.get("min_dpi", 1)
                        or target.get("dpi", 0) > constraints.get("max_dpi", 10000)):
                    raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                                        "Locked targets exceed the scenario output constraints")
            return profile
        # Legacy exact-match path.
        output = profile.definition.get("output_profile", {})
        if output and any(
            any(target.get(key) != output[key] for key in ("width_mm", "height_mm", "dpi"))
            for target in targets.values()
        ):
            raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH",
                                "Locked targets differ from the enabled profile")
        return profile
