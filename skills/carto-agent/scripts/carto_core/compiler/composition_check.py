"""P5-3 joint composition compatibility check across selected components.

After single-component conditions pass, check the style+layout combination for cross-
component conflicts: required content slots, typography vs container capacity, legend
capacity, backend capability. Conflicts carry a locatable source + responsible component
(plan §12.3); the program reports conflicts, never silently shrinks/deletes/overrides.
"""
from __future__ import annotations

from typing import Any


def check_composition(style: dict[str, Any], layout: dict[str, Any],
                      capability: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {compatible, conflicts:[{component, source, reason}]}.

    Pure check over verified contracts; does not mutate or execute. A conflict names the
    responsible component and the decision source so a designer can revise explicitly.
    """
    conflicts: list[dict[str, Any]] = []
    frames = layout.get("frames", [])
    types = [f.get("type") for f in frames]

    # Required content slots: a single main map + title + legend must exist.
    if types.count("map") != 1:
        conflicts.append({"component": "layout", "source": "frames",
                          "reason": f"expected exactly one main map, found {types.count('map')}"})
    for needed in ("title", "legend"):
        if needed not in types:
            conflicts.append({"component": "layout", "source": "frames",
                              "reason": f"missing required {needed} frame"})

    # Typography vs title container capacity (nominal fit, not silent shrink).
    typo = style.get("typography", {})
    cap = layout.get("capacity", {})
    title_pt = typo.get("title_pt")
    title_chars = cap.get("title_characters")
    if title_pt is not None and title_chars is not None and title_pt > 0:
        # a nominal title must be readable within the declared character capacity;
        # oversized nominal font against a small capacity is a conflict to revise.
        if title_chars < 8 and title_pt > 24:
            conflicts.append({"component": "style+layout", "source": "typography/capacity",
                              "reason": f"title_pt {title_pt} too large for title_characters {title_chars}"})

    # Legend capacity must be declared and positive.
    if not cap.get("legend_items"):
        conflicts.append({"component": "layout", "source": "capacity",
                          "reason": "legend_items capacity not declared"})

    # Backend capability: the capability's renderer must be present for execution.
    if capability is not None and not capability.get("renderer_id"):
        conflicts.append({"component": "capability", "source": "renderer_id",
                          "reason": "no admitted renderer for the composition"})

    return {"compatible": not conflicts, "conflicts": conflicts}