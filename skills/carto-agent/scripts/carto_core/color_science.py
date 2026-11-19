"""Colour-science primitives: zero-dependency leaf shared by matching and redline checks.

Formulas are implemented from published sources, not third-party libraries:
- sRGB -> CIELAB (D65): CIE 15 (gamma decode, XYZ matrix, cube-root f).
- CIE76 ΔE: Euclidean distance in CIELAB (perceptual space).
- Contrast ratio: WCAG 2.2 relative luminance.
- CVD simulation: Machado, Oliveira & Fernandes 2009, severity-1.0 matrices
  (protanopia/deuteranopia), applied in linear RGB.

Single source of truth: repository/template_matching re-exports delta_e76 and
hex_to_rgb from here; compiler/color_checks consumes the same primitives.
"""
from __future__ import annotations

import math


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"invalid hex colour: {hex_str!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _linearize(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _srgb_to_linear(hex_str: str) -> tuple[float, float, float]:
    return tuple(_linearize(v / 255) for v in hex_to_rgb(hex_str))  # type: ignore[return-value]


def srgb_to_lab(hex_str: str) -> tuple[float, float, float]:
    """sRGB -> CIELAB (D65) per CIE 15."""
    r, g, b = _srgb_to_linear(hex_str)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e76(hex1: str, hex2: str) -> float:
    """CIE76 ΔE — Euclidean distance in CIELAB (perceptual), converted from sRGB."""
    l1, a1, b1 = srgb_to_lab(hex1)
    l2, a2, b2 = srgb_to_lab(hex2)
    return math.sqrt((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)


def relative_luminance(hex_str: str) -> float:
    """WCAG 2.2 relative luminance (linearised sRGB, Rec.709 coefficients)."""
    r, g, b = _srgb_to_linear(hex_str)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG 2.2 contrast ratio in [1, 21]; black/white = 21."""
    l1, l2 = sorted((relative_luminance(hex1), relative_luminance(hex2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# Machado et al. 2009, severity 1.0 (dichromacy). Rows sum to 1, so white and
# any neutral grey are preserved exactly — a mechanical invariant of the model.
_CVD_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
}


def simulate_cvd(hex_str: str, kind: str) -> str:
    """Simulate dichromatic vision; returns the perceived colour as uppercase hex.

    The matrix acts on linear RGB; out-of-gamut results are clamped before
    re-encoding (the standard approximation for display-referred simulation).
    """
    matrix = _CVD_MATRICES[kind]
    r, g, b = _srgb_to_linear(hex_str)
    out = []
    for row in matrix:
        v = row[0] * r + row[1] * g + row[2] * b
        v = min(1.0, max(0.0, v))
        encoded = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(round(min(1.0, max(0.0, encoded)) * 255))
    return "#{:02X}{:02X}{:02X}".format(*out)