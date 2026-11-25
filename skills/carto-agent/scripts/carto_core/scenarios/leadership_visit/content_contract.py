"""P6 X08 — leadership-visit business content contract (declared text templates).

The business display text (stop card lines, arrival prefix, travel phrasing, legend
labels) is scenario CONTENT, declared here as an explicit content contract rather than
inline literals scattered in the graphics construction. The shared components
(image_layout / image_page_renderer) carry no business text; they render whatever content
instance they are given. Changing business wording is a content-contract change, not a
change to shared drawing code (field-mapping §X08).

These are the registered baseline wordings; a project adopting different wording does so
through an explicit content selection bound to this contract, not by editing shared code.
"""
from __future__ import annotations

# Card body line templates (business semantics: date + period + stop ordinal).
STOP_LINE_TEMPLATE = "{date}{period}行程点{order}"
ARRIVAL_PREFIX = "到达时间："
DISTANCE_PREFIX = "约"
DURATION_PREFIX = "车程约"
DISTANCE_SUFFIX = "公里"
DURATION_SUFFIX = "分钟"
TRAVEL_JOINER = "，"

# Legend labels derived from the actual expression (business wording).
LEGEND_STOP_LABEL = "行程点"
LEGEND_SUPPORT_LABEL = "起始/折返点"


def stop_line(date: str, period: str, order: int) -> str:
    return STOP_LINE_TEMPLATE.format(date=date, period=period, order=order)


def arrival_line(arrival: str) -> str:
    return ARRIVAL_PREFIX + arrival


def travel_line(role: str, value: float) -> str:
    if role == "distance-km":
        return DISTANCE_PREFIX + f"{value:g}" + DISTANCE_SUFFIX
    return DURATION_PREFIX + f"{value:g}" + DURATION_SUFFIX