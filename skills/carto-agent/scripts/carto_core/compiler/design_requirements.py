"""Deterministic design-requirement predicate evaluator (plan phase 1, design §6.5).

Pure module: no repository / workflow / scenario imports. It evaluates a closed minimal
predicate vocabulary (measure / enum / count / relation) over a VERIFIED fact view of a
candidate contract plus parameters, producing satisfied / violated / unknown per condition
and an AND aggregate over hard conditions. It never reads arbitrary paths, executes
expressions, or lets similarity / model confidence override a result.

Key invariants (design §6.5):
  * unknown is never silently treated as satisfied;
  * count uses DISTINCT content_id of an explicit content_role, never "all type=map";
    an incomplete role list yields unknown, not a guessed count;
  * contained-legend over zero main-maps is violated (no vacuous empty-set truth);
  * invalid protocol / non-finite facts fail closed before evaluation, not via unknown.

The fact view is supplied by the caller from a verified contract + registered instantiator;
this module does not access the repository or mutate the candidate.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProtocolError

_OPS = {
    "eq": lambda a, b: a == b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
}


def _enclosed(inner: list[float], outer: list[float]) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return (ix >= ox - 1e-9 and iy >= oy - 1e-9
            and ix + iw <= ox + ow + 1e-9 and iy + ih <= oy + oh + 1e-9)


def _measure(pred: dict[str, Any], fact: dict[str, Any]) -> tuple[str, Any, str]:
    key = "width_mm" if pred["path"] == "/canvas/width" else "height_mm"
    actual = fact.get("canvas", {}).get(key)
    if actual is None:
        return "unknown", None, f"{pred['path']} not measured"
    if not math.isfinite(actual):
        raise ProtocolError("REQUIREMENT_FACT_INVALID", f"non-finite {key}")
    ok = _OPS[pred["op"]](actual, pred["value"])
    return ("satisfied" if ok else "violated"), actual, f"{pred['path']} {pred['op']} {pred['value']} mm"


def _enum(pred: dict[str, Any], fact: dict[str, Any]) -> tuple[str, Any, str]:
    actual = fact.get("canvas", {}).get("orientation")
    if actual is None:
        return "unknown", None, "orientation not declared (not inferred from width/height)"
    ok = actual == pred["value"]
    return ("satisfied" if ok else "violated"), actual, f"orientation eq {pred['value']}"


def _count(pred: dict[str, Any], fact: dict[str, Any]) -> tuple[str, Any, str]:
    if not fact.get("roles_complete"):
        return "unknown", None, "content role list incomplete; count not exact"
    role = pred["role"]
    ids = {f["content_id"] for f in fact.get("frames", []) if f.get("content_role") == role}
    actual = len(ids)
    ok = _OPS[pred["op"]](actual, pred["value"])
    return ("satisfied" if ok else "violated"), actual, f"count({role}) {pred['op']} {pred['value']}"


def _contained_legend(pred: dict[str, Any], fact: dict[str, Any]) -> tuple[str, Any, str]:
    if not fact.get("roles_complete"):
        return "unknown", None, "content role list incomplete; relation undecidable"
    frames = fact.get("frames", [])
    mains = [f for f in frames if f.get("content_role") == "main-map"]
    if not mains:
        return "violated", 0, "no main-map: contained-legend cannot be vacuously true"
    for main in mains:
        legends = [f for f in frames if f.get("content_role") == "legend-group"
                   and f.get("inside_frame") == main["id"]
                   and f.get("view_ids") == [main["content_id"]]]
        if len(legends) != 1:
            return "violated", None, (f"main-map {main['id']} requires exactly one independent "
                                      f"inside legend bound to its view; found {len(legends)}")
        legend = legends[0]
        if legend.get("bounds") is None or main.get("bounds") is None:
            return "unknown", None, "legend/map bounds missing; enclosure undecidable"
        if not _enclosed(legend["bounds"], main["bounds"]):
            return "violated", None, f"legend {legend['id']} not fully inside main-map {main['id']}"
    return "satisfied", len(mains), "each main-map has exactly one independent fully-inside legend"


_EVALUATORS = {
    "measure": _measure,
    "enum": _enum,
    "count": _count,
    "relation": _contained_legend,
}


def evaluate_predicate(predicate: dict[str, Any], fact: dict[str, Any]) -> tuple[str, Any, str]:
    kind = predicate.get("kind")
    evaluator = _EVALUATORS.get(kind)
    if evaluator is None:
        raise ProtocolError("REQUIREMENT_PREDICATE_UNSUPPORTED", str(kind))
    if kind == "relation" and predicate.get("relation") != "contained-legend":
        raise ProtocolError("REQUIREMENT_PREDICATE_UNSUPPORTED", str(predicate.get("relation")))
    return evaluator(predicate, fact)


def evaluate_requirement(requirement: dict[str, Any], fact: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every condition; AND-aggregate hard conditions into a three-state result.

    Returns {requirement_id, revision, conditions:[{id,strength,status,actual,reason}],
    aggregate, hard_count}. aggregate is satisfied/violated/unknown, or ``browse`` when there
    are no hard conditions (candidate browsing only — never "unique fully satisfied").
    """
    seen: set[str] = set()
    results = []
    for condition in requirement["conditions"]:
        cid = condition["id"]
        if cid in seen:
            raise ProtocolError("REQUIREMENT_CONDITION_DUPLICATE", cid)
        seen.add(cid)
        status, actual, reason = evaluate_predicate(condition["predicate"], fact)
        results.append({"id": cid, "strength": condition["strength"],
                        "status": status, "actual": actual, "reason": reason})
    hard = [r for r in results if r["strength"] == "hard"]
    if not hard:
        aggregate = "browse"
    elif any(r["status"] == "violated" for r in hard):
        aggregate = "violated"
    elif any(r["status"] == "unknown" for r in hard):
        aggregate = "unknown"
    else:
        aggregate = "satisfied"
    return {"requirement_id": requirement["requirement_id"], "revision": requirement["revision"],
            "conditions": results, "aggregate": aggregate, "hard_count": len(hard)}


def layout_fact_view(resolved: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic fact view from a verified resolved layout (design §6.5/§6.6).

    Reads content_role/view_ids/inside_frame from the contract frames and bounds_px from the
    resolved frames. roles_complete is True only when every map/legend/inset frame carries an
    explicit content_role; otherwise role counts/relations stay unknown (old contracts are
    never auto-assumed main-map). Pure: does not mutate the layout or access the repository.
    """
    contract = resolved["contract"]
    page = resolved["page"]
    resolved_by_id = {f["id"]: f for f in resolved["frames"]}
    frames = []
    roles_complete = True
    for frame in contract["frames"]:
        role = frame.get("content_role")
        if frame["type"] in ("map", "legend", "inset") and role is None:
            roles_complete = False
        rf = resolved_by_id.get(frame["id"], {})
        frames.append({"id": frame["id"], "content_id": frame["content_id"],
                       "type": frame["type"], "content_role": role,
                       "view_ids": frame.get("view_ids"), "inside_frame": frame.get("inside_frame"),
                       "bounds": rf.get("bounds_px")})
    return {"canvas": {"width_mm": page["width_mm"], "height_mm": page["height_mm"],
                       "orientation": contract["canvas"].get("orientation")},
            "frames": frames, "roles_complete": roles_complete}


def assess_candidate(requirement: dict[str, Any], fact: dict[str, Any], *,
                     parameter_status: str = "not-applicable",
                     execution_admission: str = "unknown",
                     validation_coverage: str = "unknown") -> dict[str, Any]:
    """Combine structural satisfaction, parameter domain, execution admission and coverage.

    Design §6.5 '能力与事实分开': ``usable`` (directly usable) requires ALL of structural
    satisfied, parameter domain satisfied/not-applicable, execution allowed, and validation
    covered. A structurally satisfied candidate whose backend is not-implemented is NOT
    usable; similarity or model confidence never overrides any dimension. The caller supplies
    parameter_status (parameter_domain.check_parameter_domain), execution_admission and
    validation_coverage from the capability policy / evidence; this pure composition does not
    access the repository.
    """
    structural = evaluate_requirement(requirement, fact)
    usable = (structural["aggregate"] == "satisfied"
              and parameter_status in ("satisfied", "not-applicable")
              and execution_admission == "allowed"
              and validation_coverage == "covered")
    return {"requirement_id": requirement["requirement_id"], "revision": requirement["revision"],
            "structural": structural, "parameter_domain": parameter_status,
            "execution_admission": execution_admission, "validation_coverage": validation_coverage,
            "usable": usable}


_RESOLUTION_BRANCHES = ("reuse", "instantiate", "derive", "create", "clarify",
                        "unsupported", "search-incomplete")


def resolve_requirement(requirement: dict[str, Any],
                        assessments: list[dict[str, Any]], *,
                        search_complete: bool = True) -> dict[str, Any]:
    """Deterministic resolution decision over candidate assessments (design §7/§12).

    Each assessment is an ``assess_candidate`` result plus a ``candidate_ref``. Branch priority:
    a usable candidate -> reuse (instantiate when parameterized); incomplete search ->
    search-incomplete; no candidates -> create; structural satisfied but backend
    not-implemented -> unsupported (never auto-downgrade); pending unknown -> clarify;
    otherwise approximate candidates -> derive (a suggestion; phase 2 executes). This pure
    composition never creates, publishes, or lets similarity override a hard result.
    """
    usable = [a for a in assessments if a["usable"]]
    if usable:
        branch = "instantiate" if any(a["parameter_domain"] == "satisfied" for a in usable) else "reuse"
    elif not search_complete:
        branch = "search-incomplete"
    elif not assessments:
        branch = "create"
    elif any(a["structural"]["aggregate"] == "satisfied"
             and a["execution_admission"] == "not-implemented" for a in assessments):
        branch = "unsupported"
    elif any(a["structural"]["aggregate"] == "satisfied"
             and a["execution_admission"] != "allowed" for a in assessments):
        branch = "clarify"
    elif any(a["structural"]["aggregate"] in ("unknown", "browse") for a in assessments):
        branch = "clarify"
    else:
        branch = "derive"
    flattened = [{
        "candidate_ref": a["candidate_ref"],
        "usable": a["usable"],
        "structural_aggregate": a["structural"]["aggregate"],
        "parameter_domain": a["parameter_domain"],
        "execution_admission": a["execution_admission"],
        "validation_coverage": a["validation_coverage"],
    } for a in assessments]
    return {"schema_version": 1, "requirement_id": requirement["requirement_id"],
            "revision": requirement["revision"], "branch": branch, "assessments": flattened}