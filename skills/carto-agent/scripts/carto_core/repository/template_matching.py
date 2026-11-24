"""Read-only segment similarity scoring for the template library (S0).

Algorithms migrated from the 2026Oct prototype ``workflow/template_matcher.py``
and adapted to the main repository's contract schemas:

    style   — visual_language + color_system: exact (disqualifier),
              symbol_catalogs: Jaccard, labeling: exact, defaults: deviation.
              The prototype's ``symbol_definitions`` component is dropped because
              the main ``cartography`` contract has no such field; remaining
              weights are renormalised to sum to 1.
    layout  — canvas: exact (disqualifier), category: exact (disqualifier),
              frames: type+IoU with count penalty, placeholders: Jaccard,
              capacity: deviation.

The prototype's brand scorer was removed together with the map-brand segment
(2026-11-18, user-authorized): the identity contract had no rendering consumer.

Boundary: this module is advisory only. It never selects a template for
generate-map, never writes repository state, and never issues approvals.
Every numeric decision parameter comes from ``policies/template-matching-policy.yaml``
(``confirmation_status: pending-business-review`` — prototype values without
business justification yet). Weights below are algorithm structure, not policy.
Scoring functions are pure: no I/O, no globals, deterministic output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..color_science import delta_e76, hex_to_rgb  # noqa: F401 — public re-export (S0 API)
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document

# kind → (package-relative contract path, contract schema name).
# Non-map-scenario manifests forbid business_contracts (manifest.schema.json),
# so segment packages use this fixed convention inherited from the prototype.
SEGMENT_CONTRACTS: dict[str, tuple[str, str]] = {
    "map-style": ("contracts/cartography.yaml", "style"),
    "map-layout": ("contracts/layout.yaml", "layout"),
}


def default_policy_path() -> Path:
    # Packaged policy, never a path from a business request or doc/.
    return Path(__file__).resolve().parents[3] / "policies/template-matching-policy.yaml"


@dataclass(frozen=True, slots=True)
class MatchingPolicy:
    version: str
    confirmation_status: str
    match_threshold: float
    color_delta_e_max: float
    defaults_relative_deviation_max: float
    capacity_relative_deviation_max: float

    @classmethod
    def load(cls, path: Path | None = None, registry: SchemaRegistry | None = None) -> "MatchingPolicy":
        registry = registry or SchemaRegistry()
        document = load_document(path or default_policy_path())
        registry.validate("template-matching-policy", document)
        return cls(
            version=document["version"],
            confirmation_status=document["confirmation_status"],
            match_threshold=float(document["match_threshold"]),
            color_delta_e_max=float(document["color_delta_e_max"]),
            defaults_relative_deviation_max=float(document["defaults_relative_deviation_max"]),
            capacity_relative_deviation_max=float(document["capacity_relative_deviation_max"]),
        )


# ═══════════════════════════════════════════════════════════════════════
#  Pure similarity primitives
# ═══════════════════════════════════════════════════════════════════════


# Colour primitives (hex_to_rgb, delta_e76) are re-exported from the
# zero-dependency leaf carto_core.color_science — single source shared with
# compiler/color_checks. The S0 public API and all import sites stay unchanged.


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Normalised Levenshtein similarity (0.0 … 1.0)."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    n, m = len(s1), len(s2)
    if n > m:
        s1, s2 = s2, s1
        n, m = m, n
    prev = list(range(m + 1))
    for i, c1 in enumerate(s1, 1):
        curr = [i]
        for j, c2 in enumerate(s2, 1):
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if c1 == c2 else 1),
            ))
        prev = curr
    return 1.0 - prev[-1] / max(n, m)


def jaccard(set1: set[str], set2: set[str]) -> float:
    if not set1 and not set2:
        return 1.0
    union = set1 | set2
    if not union:
        return 0.0
    return len(set1 & set2) / len(union)


def bounds_iou(b1: list[float], b2: list[float]) -> float:
    """IoU for axis-aligned bounding boxes [x, y, w, h]."""
    x1, y1, w1, h1 = float(b1[0]), float(b1[1]), float(b1[2]), float(b1[3])
    x2, y2, w2, h2 = float(b2[0]), float(b2[1]), float(b2[2]), float(b2[3])
    ix = max(x1, x2)
    iy = max(y1, y2)
    iw = min(x1 + w1, x2 + w2) - ix
    ih = min(y1 + h1, y2 + h2) - iy
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Segment scorers (pure; None = disqualified)
# ═══════════════════════════════════════════════════════════════════════


def score_style(hint: dict[str, Any], contract: dict[str, Any], policy: MatchingPolicy) -> float | None:
    # ── disqualifiers ──
    if hint.get("visual_language") != contract.get("visual_language"):
        return None
    hint_sym = hint.get("symbolization", {})
    tmpl_sym = contract.get("symbolization", {})
    if hint_sym.get("color_system") != tmpl_sym.get("color_system"):
        return None

    # Prototype weights minus symbol_definitions (absent from the main
    # cartography contract), renormalised: 0.20/0.15/0.15/0.20/0.20 over 0.90.
    weights = {"catalogs": 2 / 9, "labeling": 1 / 6, "defaults": 1 / 6,
               "vis_lang": 2 / 9, "color_sys": 2 / 9}
    score = weights["vis_lang"] + weights["color_sys"]  # disqualifiers passed

    # ── symbol_catalogs ──
    h_cats = set(hint_sym.get("symbol_catalogs", []))
    t_cats = set(tmpl_sym.get("symbol_catalogs", []))
    score += weights["catalogs"] * jaccard(h_cats, t_cats)

    # ── labeling ──
    hint_lbl = hint.get("labeling", {})
    tmpl_lbl = contract.get("labeling", {})
    lbl_hits = 0
    for f in ("density", "collision_policy", "font_role"):
        if hint_lbl.get(f) == tmpl_lbl.get(f):
            lbl_hits += 1
    score += weights["labeling"] * (lbl_hits / 3)

    # ── defaults ──
    hint_def = hint.get("defaults", {})
    tmpl_def = contract.get("defaults", {})
    def_hits = 0
    for f in ("line_width_mm", "point_size_mm", "opacity"):
        hv = hint_def.get(f)
        tv = tmpl_def.get(f)
        if hv is not None and tv is not None and tv != 0:
            dev = abs(hv - tv) / abs(tv)
            if dev <= policy.defaults_relative_deviation_max:
                def_hits += 1
        elif hv is None and tv is None:
            def_hits += 1
    score += weights["defaults"] * (def_hits / 3) if def_hits > 0 else 0.0

    return score


def score_layout(hint: dict[str, Any], contract: dict[str, Any], policy: MatchingPolicy) -> float | None:
    # ── disqualifier: canvas ──
    hint_canvas = hint.get("canvas", {})
    tmpl_canvas = contract.get("canvas", {})
    for f in ("width", "height", "unit", "orientation"):
        if hint_canvas.get(f) != tmpl_canvas.get(f):
            return None

    # ── disqualifier: category ──
    if hint.get("category") != contract.get("category"):
        return None

    weights = {"canvas": 0.30, "category": 0.15, "frames": 0.40,
               "placeholders": 0.10, "capacity": 0.05}
    score = weights["canvas"] + weights["category"]  # disqualifiers passed

    # ── frames ──
    hint_frames = hint.get("frames", [])
    tmpl_frames = contract.get("frames", [])
    if hint_frames and tmpl_frames:
        ious: list[float] = []
        for hf in hint_frames:
            best_iou = 0.0
            for tf in tmpl_frames:
                if hf.get("type") != tf.get("type"):
                    continue
                iou = bounds_iou(hf["bounds"], tf["bounds"])
                if iou > best_iou:
                    best_iou = iou
            ious.append(best_iou)
        avg_iou = sum(ious) / len(ious) if ious else 0.0
        # also penalise count mismatch
        count_penalty = min(len(hint_frames), len(tmpl_frames)) / max(len(hint_frames), len(tmpl_frames))
        score += weights["frames"] * avg_iou * count_penalty
    elif not hint_frames and not tmpl_frames:
        score += weights["frames"]

    # ── placeholders ──
    h_ph = set(hint.get("placeholders", []))
    t_ph = set(contract.get("placeholders", []))
    score += weights["placeholders"] * jaccard(h_ph, t_ph)

    # ── capacity ──
    hint_cap = hint.get("capacity", {})
    tmpl_cap = contract.get("capacity", {})
    cap_hits = 0
    for f in ("legend_items", "title_characters"):
        hv = hint_cap.get(f)
        tv = tmpl_cap.get(f)
        if hv is not None and tv is not None and tv != 0:
            if abs(hv - tv) / tv <= policy.capacity_relative_deviation_max:
                cap_hits += 1
        elif hv is None and tv is None:
            cap_hits += 1
    score += weights["capacity"] * (cap_hits / 2) if cap_hits > 0 else 0.0

    return score


_SCORERS = {"map-style": score_style, "map-layout": score_layout}


def rank_segment_candidates(
    kind: str,
    segment: dict[str, Any],
    candidates: list[tuple[dict[str, Any], dict[str, Any]]],
    policy: MatchingPolicy,
) -> list[dict[str, Any]]:
    """Score (index entry, contract) pairs; return ranked advisory candidates.

    Disqualified candidates are excluded. Ordering is deterministic:
    descending score, then namespace/id/version. ``matched`` only reports
    score >= policy.match_threshold; it is not a selection decision.
    """
    scorer = _SCORERS.get(kind)
    if scorer is None:
        raise ProtocolError("SEGMENT_KIND_UNSUPPORTED", kind)
    ranked: list[dict[str, Any]] = []
    for entry, contract in candidates:
        score = scorer(segment, contract, policy)
        if score is None:
            continue
        ranked.append({
            "template_ref": {"kind": entry["kind"], "id": entry["id"],
                             "version": entry["version"], "digest": entry["digest"]},
            "score": score,
            "matched": score >= policy.match_threshold,
            "_sort": (entry["namespace"], entry["id"], entry["version"]),
        })
    ranked.sort(key=lambda item: (-item["score"], item["_sort"]))
    for item in ranked:
        item.pop("_sort")
    return ranked