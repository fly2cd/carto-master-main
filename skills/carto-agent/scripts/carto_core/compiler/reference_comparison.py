"""Reference round-trip comparison and redline deviation evidence (plan phase 2, MCP-ready).

Pure functions; no workflow / repository / schema_registry imports (validation is injected
at the boundary by the caller). Decomposes the total round-trip divergence into three
attributable parts so a TP approver can see WHERE it comes from:
  * recovery_error: reference image -> extracted proposal (inverse-extraction fidelity);
  * authorized_deviation: proposal -> effective colors (a user-authorized change, e.g. a
    redline-driven recolor; this is NOT an error and must be explicitly approved);
  * implementation_error: effective colors -> rendered output (forward-render fidelity).

A faithful extraction is NOT a redline exemption: blocker findings require an explicit
authorized recolor recorded as a deviation, never a silent pass.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import color_science
from .reference_extraction import round_trip_palette


def round_trip_report(reference_png: bytes, rendered_png: bytes, *,
                      proposed_colors: list[str],
                      effective_colors: Optional[list[str]] = None,
                      k: int | None = None) -> dict[str, float]:
    """Three-way round-trip decomposition (all max ΔE2000, lower = better)."""
    recovery = round_trip_palette(reference_png, proposed_colors, k)
    effective = effective_colors if effective_colors is not None else proposed_colors
    implementation = round_trip_palette(rendered_png, effective, k)
    deviation = 0.0
    if effective_colors is not None:
        deviation = max(min(color_science.delta_e2000(p, e) for p in proposed_colors)
                        for e in effective_colors)
    return {
        "recovery_error_delta_e2000": recovery,
        "authorized_deviation_delta_e2000": deviation,
        "implementation_error_delta_e2000": implementation,
    }


def redline_deviation(colors: list[str], *, registry: Any = None) -> dict[str, Any]:
    """Detect redline blockers that require an explicit authorized recolor (deviation).

    Returns requires_authorization=True when any blocker is present; the caller must record
    an authorized color change (deviation) rather than silently passing a faithful extract.
    """
    from .color_checks import ColorRedlinesPolicy, check_color_sequence
    findings = check_color_sequence(colors, ColorRedlinesPolicy.load(registry=registry))
    blockers = [f for f in findings if f["severity"] == "blocker"]
    return {
        "requires_authorization": bool(blockers),
        "blockers": blockers,
        "findings": findings,
    }