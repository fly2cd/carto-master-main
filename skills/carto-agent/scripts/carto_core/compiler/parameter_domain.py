"""Finite parameter-domain evaluation (plan phase 1, design §6.7). Pure module.

Recognizes the legacy template-owned grid domain (``grid_cases()`` = allowed_shapes x
legend_modes, placement implicitly outside) and evaluates a candidate parameter tuple
against a declared ``allowed_cases`` domain by FULL-TUPLE membership — never field-wise
(each field legal does not imply the combination is allowed). A case is admitted for
execution only when an implemented consumer exists; ``inside`` placement stays
not-implemented until phase 3 delivers it. No arbitrary parameter language or solver.
"""
from __future__ import annotations

from typing import Any

from .grid_layout import case_key, grid_cases


def legacy_grid_allowed_cases(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Recognize the template-owned finite grid domain as explicit cases (placement-aware).

    Legacy contracts (allowed_shapes x legend_modes) yield outside cases; a reviewed
    ``allowed_cases`` domain is returned as declared (single authority, plan phase 3).
    """
    return grid_cases(contract)


def check_parameter_domain(parameters: dict[str, Any] | None,
                           allowed_cases: list[dict[str, Any]] | None) -> str:
    """Full-tuple domain membership: satisfied / violated / unknown.

    No declared domain or no chosen parameters yields unknown (clarify / browse), never a
    guessed pass. Parameters must exactly equal one allowed case.
    """
    if not allowed_cases:
        return "unknown"
    if parameters is None:
        return "unknown"
    keys = {case_key(c) for c in allowed_cases}
    return "satisfied" if case_key(parameters) in keys else "violated"


def case_execution_admission(case: dict[str, Any],
                             implemented_cases: list[dict[str, Any]]) -> str:
    """allowed only when an implemented consumer exists for the exact case; else not-implemented."""
    if case_key(case) in {case_key(c) for c in implemented_cases}:
        return "allowed"
    return "not-implemented"


def layout_execution_admission(fact: dict[str, Any], capability: dict[str, Any]) -> str:
    """Derive execution admission from the scenario capability policy (design §6.5).

    Mechanical and policy-driven: dimensions beyond output_constraints are forbidden; an
    inside legend (legend-group contained in a main-map) is admitted only when the capability
    policy declares the inside placement implemented (plan phase 3), else not-implemented;
    a dimension within the constraint upper bound but different from the validated
    output_profile is not-implemented (an A3 upper bound is NOT full-chain A3 admission);
    otherwise allowed. Unknown canvas dimensions yield unknown, never a guessed pass.
    """
    canvas = fact.get("canvas", {})
    width, height = canvas.get("width_mm"), canvas.get("height_mm")
    if width is None or height is None:
        return "unknown"
    constraints = capability.get("output_constraints", {})
    if width > constraints.get("max_width_mm", width) or height > constraints.get("max_height_mm", height):
        return "forbidden"
    frames = fact.get("frames", [])
    map_ids = {f["id"] for f in frames if f.get("content_role") == "main-map"}
    has_inside = any(f.get("content_role") == "legend-group" and f.get("inside_frame") in map_ids
                     for f in frames)
    if has_inside:
        grid_policy = capability.get("layout_constraints", {}).get("grid", {})
        if "inside" not in grid_policy.get("legend_placements", ["outside"]):
            return "not-implemented"
    profile = capability.get("output_profile", {})
    if (width, height) != (profile.get("width_mm"), profile.get("height_mm")):
        return "not-implemented"
    return "allowed"