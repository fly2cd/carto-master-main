"""``carto template match`` — read-only advisory segment matching (S0).

Exposes the live advisory matching algorithm (rank_segment_candidates over published
segment contracts) as a CLI command. Matching is advisory evidence for authoring review:
it never selects a template for generate-map, never admits a capability, and never writes
repository state. The request segment is validated closed-world against the kind contract
schema (style/layout); an empty library yields an empty candidate list without materialising
an index.
"""
from __future__ import annotations

from ..errors import ProtocolError
from ..repository.template_matching import (
    SEGMENT_CONTRACTS, MatchingPolicy, default_policy_path, rank_segment_candidates,
)
from ..repository.template_repository import TemplateRepository
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard


def register(sub) -> None:
    template = sub.add_parser("template", help="Template library utilities")
    template_sub = template.add_subparsers(dest="template_command", required=True)
    match = template_sub.add_parser(
        "match", help="Read-only advisory segment matching (never selects or writes)")
    match.add_argument("request")
    match.add_argument("--repository-root", required=True)
    match.add_argument("--repository-scope", required=True)
    match.add_argument("--allowed-root", action="append", required=True)
    resolve = template_sub.add_parser(
        "resolve", help="Read-only design-requirement resolution against published candidates")
    resolve.add_argument("requirement")
    resolve.add_argument("--repository-root", required=True)
    resolve.add_argument("--repository-scope", required=True)
    resolve.add_argument("--allowed-root", action="append", required=True)
    orchestrate = template_sub.add_parser(
        "orchestrate", help="Execute the four-branch creation decision (project draft only; never publishes)")
    orchestrate.add_argument("requirement")
    orchestrate.add_argument("--repository-root", required=True)
    orchestrate.add_argument("--repository-scope", required=True)
    orchestrate.add_argument("--allowed-root", action="append", required=True)
    orchestrate.add_argument("--draft-id", required=True)
    orchestrate.add_argument("--revision", type=int, default=1)
    orchestrate.add_argument("--base", help="Base contract file (derive branch)")
    orchestrate.add_argument("--base-ref", help="Published base package templateRef file (derive branch)")
    orchestrate.add_argument("--change-set", help="Restricted change-set file (derive branch)")
    orchestrate.add_argument("--design", help="Confirmed complete design file (create branch)")
    expand = template_sub.add_parser(
        "expand-default", help="Expand a template-less request with the registered default (requires --confirm)")
    expand.add_argument("request")
    expand.add_argument("--allowed-root", action="append", required=True)
    expand.add_argument("--confirm", action="store_true", help="Explicit confirmation of the default choice")
    expand.add_argument("--out", help="Write expanded request to this path (new request, pre-intake)")


def handle(args) -> dict:
    if args.template_command == "orchestrate":
        return _orchestrate(args)
    if args.template_command == "resolve":
        return _resolve(args)
    if args.template_command == "expand-default":
        return _expand_default(args)
    if args.template_command != "match":
        raise ValueError(f"unknown template command: {args.template_command}")
    registry = SchemaRegistry()
    guard = PathGuard(args.allowed_root)
    request = load_document(guard.resolve(args.request, must_exist=True))
    registry.validate("template-match-request", request)
    kind = request["kind"]
    if kind not in SEGMENT_CONTRACTS:
        raise ProtocolError("SEGMENT_KIND_UNSUPPORTED", kind)
    _, schema_name = SEGMENT_CONTRACTS[kind]
    registry.validate(schema_name, request["segment"])
    repository = TemplateRepository(
        path_guard=guard, root=args.repository_root,
        repository_scope=args.repository_scope, registry=registry)
    policy = MatchingPolicy.load(default_policy_path(), registry)
    candidates = repository.segment_candidates(kind=kind)
    ranked = rank_segment_candidates(kind, request["segment"], candidates, policy)
    result = {
        "schema_version": 1,
        "kind": kind,
        "policy_version": policy.version,
        "confirmation_status": policy.confirmation_status,
        "match_threshold": policy.match_threshold,
        "candidates": ranked,
    }
    registry.validate("template-match-result", result)
    return {"match": result}


def _expand_default(args) -> dict:
    """Pre-intake default expansion: produce a NEW request with the registered default
    template, only with explicit --confirm. Never mutates an intake'd request."""
    from ..artifacts import atomic_yaml
    from ..compiler.default_presets import expand_default_request
    registry = SchemaRegistry()
    guard = PathGuard(args.allowed_root)
    request = load_document(guard.resolve(args.request, must_exist=True))
    expanded = expand_default_request(request, confirmed=args.confirm, registry=registry)
    if args.out:
        atomic_yaml(guard.resolve(args.out), expanded)
    return {"expanded_request": expanded}


def _resolve(args) -> dict:
    """Read-only requirement resolution (plan phase 1): retrieve published candidates, build a
    verified fact view per candidate, assess structural satisfaction and decide a branch.

    Execution admission is derived from the scenario capability policy (dimension constraints,
    validated output profile, inside-legend not-implemented); a resolved published candidate
    carries validation evidence (coverage covered), an unresolvable one stays unknown. Never
    writes repository state, creates, or publishes.
    """
    from pathlib import Path
    from ..compiler.design_requirements import (
        assess_candidate, layout_fact_view, resolve_requirement, style_fact_view,
    )
    from ..compiler.layout import LayoutResolver
    from ..compiler.parameter_domain import layout_execution_admission
    from ..errors import CartoError
    from ..scenario_registry import effective_definitions
    registry = SchemaRegistry()
    guard = PathGuard(args.allowed_root)
    requirement = load_document(guard.resolve(args.requirement, must_exist=True))
    registry.validate("design-requirement", requirement)
    seg_kind = {"layout": "map-layout", "style": "map-style"}.get(requirement["object_scope"])
    if seg_kind is None:
        raise ProtocolError("REQUIREMENT_SCOPE_UNSUPPORTED", requirement["object_scope"])
    capability_policy = load_document(
        Path(__file__).resolve().parents[3] / "policies/scenario-capabilities.yaml")
    # P5-1: select the capability by the requirement's trusted business context
    # (business_scene + geometry), never a hardcoded scenario. No context -> no capability
    # (admission unknown -> clarify), not a general-thematic default.
    capability: dict = {}
    context = requirement.get("context")
    if context:
        for definition in effective_definitions(capability_policy["profiles"]):
            constraints = definition.get("intent_constraints", {})
            if (constraints.get("business_scene") == context["business_scene"]
                    and definition.get("template_geometry") == context["geometry"]):
                capability = definition
                break
    repository = TemplateRepository(
        path_guard=guard, root=args.repository_root,
        repository_scope=args.repository_scope, registry=registry)
    candidates = repository.segment_candidates(kind=seg_kind)
    # P5-4: bounded search with completeness record; budget exhaustion -> search-incomplete.
    budget = 50
    examined = candidates[:budget]
    truncated = len(candidates) > budget
    search_metadata = {"search_complete": not truncated, "source_scope": seg_kind,
                       "candidate_budget": budget, "examined": len(examined), "truncated": truncated}
    resolver = LayoutResolver(registry)
    dpi = capability.get("output_profile", {}).get("dpi", 300)
    assessments = []
    for entry, contract in examined:
        ref = {"kind": entry["kind"], "id": entry["id"],
               "version": entry["version"], "digest": entry["digest"]}
        # P5-2: Style requirements evaluate against Style's own facts; Layout against
        # verified resolved-layout facts. Never route Style through LayoutResolver.
        if seg_kind == "map-style":
            fact = style_fact_view(contract)
            coverage = "covered"
            admission = "allowed" if capability else "unknown"
        else:
            try:
                fact = layout_fact_view(resolver.resolve(contract, dpi))
                coverage = "covered"
            except CartoError:
                fact = {"canvas": {}, "frames": [], "roles_complete": False}
                coverage = "unknown"
            admission = layout_execution_admission(fact, capability)
        assessment = assess_candidate(requirement, fact,
                                      execution_admission=admission, validation_coverage=coverage)
        assessment["candidate_ref"] = ref
        assessments.append(assessment)
    result = resolve_requirement(requirement, assessments,
                                 search_complete=not truncated, search_metadata=search_metadata)
    registry.validate("design-resolution-result", result)
    return {"resolution": result}


def _orchestrate(args) -> dict:
    """Four-branch creation orchestration (plan phase 2, design §7): run the read-only resolution
    then execute its branch. reuse/instantiate return a published ref; derive/create produce a
    project-scoped draft from explicit trusted inputs (fail closed when missing); clarify/
    unsupported/search-incomplete stop. Never writes the business index, publishes or approves.
    """
    from ..compiler.creation_orchestration import SEGMENT_DERIVATION_PROFILE, orchestrate_creation
    resolution = _resolve(args)["resolution"]
    registry = SchemaRegistry()
    guard = PathGuard(args.allowed_root)
    requirement = load_document(guard.resolve(args.requirement, must_exist=True))
    seg_kind = {"layout": "map-layout", "style": "map-style"}.get(requirement["object_scope"])
    if seg_kind is None:
        raise ProtocolError("REQUIREMENT_SCOPE_UNSUPPORTED", requirement["object_scope"])
    profile = SEGMENT_DERIVATION_PROFILE[seg_kind]

    def _load_opt(path):
        return None if path is None else load_document(guard.resolve(path, must_exist=True))

    result = orchestrate_creation(
        requirement, resolution, draft_id=args.draft_id, revision=args.revision,
        registry=registry, base=_load_opt(args.base), base_ref=_load_opt(args.base_ref),
        change_set=_load_opt(args.change_set), design=_load_opt(args.design),
        schema=profile["schema"], id_field=profile["id_field"], kind=seg_kind,
        allowed_keys=profile["allowed_keys"])
    registry.validate("design-resolution-result", result)
    return {"orchestration": result}