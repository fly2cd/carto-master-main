"""Cartographic colour redlines: pure checks over declared colour sequences.

Implements the verifiable part of the project's own target design
(doc/template/map-style.md §8.2): ordered ramps must carry a monotonic L*
gradient (Bertin: ordered data needs a lightness/saturation progression, hue
alone encodes categories), adjacent classes must stay distinguishable, and
dichromatic viewers must still tell classes apart (Machado et al. 2009).

Every numeric parameter and enforcement level comes from
policies/color-redlines-policy.yaml; nothing is hardcoded here. Findings use
the ExpressionValidator shape {severity, code, message}; callers raise on
blocker findings and surface warnings through warnings.warn (the same channel
the expression catalog uses for deprecation notices).

Scope: checks run where instance colours are actually frozen (the generate
chain). Template packages contain no instance colours, so template validate
is intentionally untouched. Contrast (WCAG) primitives live in color_science
but are not wired yet: the current contracts declare no text/background pair.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..color_science import delta_e76, srgb_to_lab, simulate_cvd
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document

_CVD_KINDS = ("protanopia", "deuteranopia")


def default_policy_path() -> Path:
    # Packaged policy, never a path from a business request or doc/.
    return Path(__file__).resolve().parents[3] / "policies/color-redlines-policy.yaml"


@dataclass(frozen=True, slots=True)
class ColorRedlinesPolicy:
    version: str
    confirmation_status: str
    ramp_semantics: str
    adjacent_distinguishability: str
    cvd_safety: str
    lightness_monotonic_tolerance: float
    adjacent_delta_e_min: float
    cvd_delta_e_min: float

    @classmethod
    def load(cls, path: Path | None = None, registry: SchemaRegistry | None = None) -> "ColorRedlinesPolicy":
        registry = registry or SchemaRegistry()
        document = load_document(path or default_policy_path())
        registry.validate("color-redlines-policy", document)
        enforcement = document["enforcement"]
        return cls(
            version=document["version"],
            confirmation_status=document["confirmation_status"],
            ramp_semantics=enforcement["ramp_semantics"],
            adjacent_distinguishability=enforcement["adjacent_distinguishability"],
            cvd_safety=enforcement["cvd_safety"],
            lightness_monotonic_tolerance=float(document["lightness_monotonic_tolerance"]),
            adjacent_delta_e_min=float(document["adjacent_delta_e_min"]),
            cvd_delta_e_min=float(document["cvd_delta_e_min"]),
        )


def _finding(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


def _monotonic(values: list[float], tolerance: float) -> bool:
    diffs = [b - a for a, b in zip(values, values[1:])]
    return all(d >= -tolerance for d in diffs) or all(d <= tolerance for d in diffs)


def check_ramp(colors: list[str], scheme: str, policy: ColorRedlinesPolicy) -> list[dict[str, Any]]:
    """R1+R2+R4 for an ordered ramp with a declared perceptual scheme."""
    findings: list[dict[str, Any]] = []
    if len(colors) < 2:
        return findings
    if policy.ramp_semantics != "off":
        lightness = [srgb_to_lab(c)[0] for c in colors]
        tol = policy.lightness_monotonic_tolerance
        if scheme == "sequential":
            if not _monotonic(lightness, tol):
                findings.append(_finding(policy.ramp_semantics, "COLOR_RAMP_NOT_MONOTONIC",
                                         f"sequential ramp L* must be monotonic; got {[round(v, 2) for v in lightness]}"))
        elif scheme == "diverging":
            # Brewer diverging ramps: two dark arms joined at a LIGHT central
            # critical point — L* rises to a central maximum then falls.
            mid = len(lightness) // 2
            left, right = lightness[:mid + 1], lightness[mid:]
            rising = all(b - a >= -tol for a, b in zip(left, left[1:]))
            falling = all(a - b >= -tol for a, b in zip(right, right[1:]))
            if not (rising and falling and lightness[mid] >= max(lightness[0], lightness[-1]) - tol):
                findings.append(_finding(policy.ramp_semantics, "COLOR_RAMP_DIVERGING_INVALID",
                                         f"diverging ramp L* must rise to a central light maximum then fall; got {[round(v, 2) for v in lightness]}"))
        else:
            raise ProtocolError("COLOR_RAMP_SCHEME_UNKNOWN", scheme)
    findings.extend(check_color_sequence(colors, policy))
    return findings


def check_color_sequence(colors: list[str], policy: ColorRedlinesPolicy) -> list[dict[str, Any]]:
    """R2+R4 for any ordered colour sequence (categorical classes included)."""
    findings: list[dict[str, Any]] = []
    pairs = list(zip(colors, colors[1:]))
    if not pairs:
        return findings
    if policy.adjacent_distinguishability != "off":
        for index, (a, b) in enumerate(pairs):
            distance = delta_e76(a, b)
            if distance < policy.adjacent_delta_e_min:
                findings.append(_finding(policy.adjacent_distinguishability, "COLOR_ADJACENT_INDISTINGUISHABLE",
                                         f"classes {index}/{index + 1} ({a}, {b}) ΔE76={distance:.2f} < {policy.adjacent_delta_e_min}"))
    if policy.cvd_safety != "off":
        for kind in _CVD_KINDS:
            simulated = [simulate_cvd(c, kind) for c in colors]
            for index, (a, b) in enumerate(zip(simulated, simulated[1:])):
                distance = delta_e76(a, b)
                if distance < policy.cvd_delta_e_min:
                    findings.append(_finding(policy.cvd_safety, "COLOR_CVD_UNSAFE",
                                             f"classes {index}/{index + 1} ({colors[index]}, {colors[index + 1]}) "
                                             f"under {kind} ΔE76={distance:.2f} < {policy.cvd_delta_e_min}"))
    return findings


def enforce(findings: list[dict[str, Any]]) -> None:
    """Raise on the first blocker; surface warnings without blocking."""
    for finding in findings:
        if finding["severity"] == "blocker":
            raise ProtocolError(finding["code"], finding["message"])
        if finding["severity"] == "warning":
            warnings.warn(f"{finding['code']}: {finding['message']}", FutureWarning, stacklevel=2)