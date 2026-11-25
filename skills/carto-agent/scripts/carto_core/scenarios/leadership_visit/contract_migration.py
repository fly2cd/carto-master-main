"""P6 S4 — explicit, auditable author migration of the private image_itinerary contract.

Field-mapping M01–M46: each baseline leaf field is relocated to its confirmed logical
address (S business definition / I instance selection / A Style role appearance /
J component internal parameter / N annotation placement / V basemap display). This is
the offline author migration the mapping §9.3 permits: source values are preserved with
their meaning, transformations are explicit (no silent guessing), and the result is
validated against the closed contracts before adoption.

This module produces the new instances; it does NOT delete the old authority (S8) nor
wire consumers (S5). The old image_itinerary remains the running authority until the
consumers are switched and equivalence is verified.

Key explicit transformations (mapping §4):
  M18  section_gap = 2 x old line_gap (divider at midpoint)
  M05/M09  per-group route offset normalized to one effective value (group wins, else default)
  M06  fallback rule split from legend color (no covert color from a fallback field)
  M25  arrival-time display is an explicit content selection (baseline False), not a
       renderer default-True
  M30/M32  support text color/size merged to a single text role (no mirrored duplicates)
  M39  display-order rule distinct from the visit_order fact
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...errors import ProtocolError


def _q(value: float, rule_ref: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "reference-design-px", "value": value, "rule_ref": deepcopy(rule_ref)}


def _pt(value: float) -> dict[str, Any]:
    return {"kind": "physical-pt", "value": value}


def _mm(value: float) -> dict[str, Any]:
    return {"kind": "physical-mm", "value": value}


def migrate_image_itinerary(style: dict[str, Any], *, rule_ref: dict[str, Any]) -> dict[str, Any]:
    """Relocate the 46 baseline fields into the new contract instances.

    ``rule_ref`` pins the adopted measurement rule (U). The baseline reference-design
    values keep their reference-design-px unit (mapping §1.7: not converted to permanent
    mm/pt by a fixed DPI). Physical page furniture keeps pt/mm.
    """
    if not isinstance(style, dict) or not isinstance(rule_ref, dict):
        raise ProtocolError("MIGRATION_INPUT_INVALID", "style and rule_ref are required")
    groups = style.get("groups", [])
    route = style.get("route", {})
    pin = style.get("pin", {})
    callout = style.get("callout", {})
    support = style.get("support_label")
    furniture = style.get("page_furniture", {})
    border = furniture.get("frame_border", {})

    # --- S business definitions + I group bindings / labels / resolution (M02/M03/M04/M06)
    group_definitions = [{"id": g["id"], "display_label": g["label"]} for g in groups]
    group_bindings = [{"semantic_group": g["id"], "visual_role": f"group-{g['id']}"} for g in groups]
    legend_labels = {g["id"]: g["label"] for g in groups}
    group_resolution = {"fallback_group": style["default_group"]}

    # --- A Style role appearance
    style_roles: dict[str, Any] = {}
    default_route_offset = route.get("right_offset_px", 0)
    for g in groups:
        style_roles[f"group-{g['id']}"] = {"color": g["color"]}  # M04
        # M05/M09: one effective route offset per group (group value wins, else default).
        offset = g.get("right_offset_px", default_route_offset)
        style_roles[f"route-{g['id']}"] = {"display_offset": {"distance": _q(offset, rule_ref)}}
    style_roles["route"] = {"stroke": {"width": _q(route["width_px"], rule_ref)}}  # M07
    style_roles["route-halo"] = {"stroke": {"width": _q(route["halo_width_px"], rule_ref)},
                                 "color": "#FFFFFF"}  # M08 + X07 halo color role
    style_roles["numbered-stop-marker"] = {"radius": _q(pin["radius_px"], rule_ref),
                                           "stroke": {"width": _q(1, rule_ref), "color": "#FFFFFF"}}  # M12 + X07 edge
    style_roles["visit-order-text"] = {"font": {"size": _q(pin["font_size_px"], rule_ref)},
                                       "color": "#FFFFFF"}  # M13 + X07 number text color
    style_roles["card-title"] = {  # M15/M23/M27
        "font": {"size": _q(callout["title_font_px"], rule_ref), "weight": callout["font_weight"]},
        "color": callout.get("title_color", "#FFFFFF"),
    }
    style_roles["card-body"] = {  # M16/M28
        "font": {"size": _q(callout["body_font_px"], rule_ref)},
        "color": callout.get("body_color", "#FFFFFF"),
    }
    style_roles["card-background"] = {"opacity": callout["opacity"]}  # M19
    style_roles["card-leader"] = {"stroke": {"width": _q(callout["leader_width_px"], rule_ref)}}  # M20
    if support is not None:
        style_roles["support-accent"] = {"color": support["color"]}  # M29
        style_roles["support-label-text"] = {  # M30/M32/M38 merged single text role
            "font": {"size": _q(support["font_size_px"], rule_ref), "weight": support.get("font_weight", 400)},
            "color": support["text_color"],
        }
        style_roles["support-marker"] = {"radius": _q(support["point_radius_px"], rule_ref)}  # M31
        style_roles["support-label-background"] = {"opacity": support["opacity"]}  # M34
        style_roles["support-label-leader"] = {"stroke": {"width": _q(support["leader_width_px"], rule_ref)}}  # M35
    if furniture.get("title_font_pt") is not None:
        style_roles["page-title"] = {"font": {"size": _pt(furniture["title_font_pt"])},
                                     "color": "#1A3A5C"}  # M41 + X07 page title color
    if furniture.get("body_font_pt") is not None:
        style_roles["source-notice"] = {"font": {"size": _pt(furniture["body_font_pt"])}}  # M42
    if border.get("color") is not None:
        style_roles["map-border"] = {"color": border["color"]}  # M43

    # --- J component internal parameters
    arrows = route.get("arrows", {})
    components: dict[str, Any] = {
        "route": {"type": "classified-route", "parameters": {"arrows": {  # M10/M11
            "head_size": _q(arrows["size_px"], rule_ref),
            "repeat_spacing": _q(arrows["spacing_px"], rule_ref),
        }}},
        "card": {"type": "information-card", "parameters": {  # M14/M17/M18/M24/M26
            "sizing": {"width": {
                "mode": "fit-content-up-to-limit" if callout.get("fit_content", False) else "fixed",
                "limit": _q(callout["width_px"], rule_ref),
            }},
            "inset": _q(callout["padding_px"], rule_ref),
            "sections": {"gap": _q(2 * callout["line_gap_px"], rule_ref)},  # M18: full gap = 2 x old
            "title": {"wrap_mode": "wrap-by-character" if callout.get("title_wrap", False)
                      else "single-line-reject-overflow"},
            "structure": {"section_order": ["body", "divider", "title"],  # X05 registered preset
                          "divider_position": "gap-midpoint", "empty_body": "center"},
        }},
    }
    if border.get("inner_width_mm") is not None:
        components["map-border"] = {"type": "double-outline", "parameters": {  # M44/M45/M46
            "inner_stroke_width": _mm(border["inner_width_mm"]),
            "stroke_gap": _mm(border["gap_mm"]),
            "outer_stroke_width": _mm(border["outer_width_mm"]),
        }}
    if support is not None:
        components["support-label"] = {"type": "linked-label", "parameters": {  # M33
            "inset": _q(support["padding_px"], rule_ref),
        }}

    # --- N annotation placement selections (M21/M22/M36/M37)
    annotations: dict[str, Any] = {
        "card": {"placement": {"mode": "preferred", "offset": {
            "x": _q(callout["offset_x_px"], rule_ref),
            "y": _q(callout["offset_y_px"], rule_ref),
        }}},
    }
    if support is not None:
        annotations["support-label"] = {"placement": {"mode": "preferred", "offset": {
            "x": _q(support["offset_x_px"], rule_ref),
            "y": _q(support["offset_y_px"], rule_ref),
        }}}

    # --- I content selections (M25/M39)
    card_fields = ["stop-label", "visit-date", "visit-period", "distance-km", "duration-min"]
    if callout.get("show_arrival_time", False):  # baseline False; explicit, not renderer default
        card_fields.append("arrival-time")
    content = {
        "card": {"fields": card_fields},
        "numbering": {"display_order": style.get("numbering", "global")},
    }

    # --- V basemap display (M40)
    basemap_display = {"crop": {"parameters": {"white_threshold": style["white_threshold"]}}}

    return {
        "group_definitions": group_definitions,
        "group_bindings": group_bindings,
        "legend_labels": legend_labels,
        "group_resolution": group_resolution,
        "style_roles": style_roles,
        "components": components,
        "annotations": annotations,
        "content": content,
        "basemap_display": basemap_display,
    }


def _value(measurement: dict[str, Any]) -> float:
    """Extract the numeric value from a discriminated measurement (derived copy)."""
    return measurement["value"]


def resolve_effective_style(migrated: dict[str, Any]) -> dict[str, Any]:
    """S5 consumer path: derive the effective style the graphics construction consumes
    FROM the new contract instances (mapping §5.2).

    The backend drawing functions may keep their shape, but their input is now a derived
    copy resolved from the adopted Style roles / component parameters / annotation
    placements / content selections — not the private image_itinerary defaults. This is
    the resolution direction; migrate_image_itinerary is the authoring direction. Round
    trips must preserve the visible design (verified by equivalence tests).
    """
    roles = migrated["style_roles"]
    components = migrated["components"]
    annotations = migrated["annotations"]
    content = migrated["content"]
    card = components["card"]["parameters"]
    route_comp = components["route"]["parameters"]
    border = components.get("map-border", {}).get("parameters")

    groups = []
    for definition in migrated["group_definitions"]:
        gid = definition["id"]
        group = {"id": gid, "label": migrated["legend_labels"][gid],
                 "color": roles[f"group-{gid}"]["color"]}
        offset = _value(roles[f"route-{gid}"]["display_offset"]["distance"])
        if offset != 0:
            group["right_offset_px"] = offset
        groups.append(group)

    callout = {
        "width_px": _value(card["sizing"]["width"]["limit"]),
        "title_font_px": _value(roles["card-title"]["font"]["size"]),
        "body_font_px": _value(roles["card-body"]["font"]["size"]),
        "padding_px": _value(card["inset"]),
        "line_gap_px": _value(card["sections"]["gap"]) / 2,  # reverse M18
        "opacity": roles["card-background"]["opacity"],
        "leader_width_px": _value(roles["card-leader"]["stroke"]["width"]),
        "offset_x_px": _value(annotations["card"]["placement"]["offset"]["x"]),
        "offset_y_px": _value(annotations["card"]["placement"]["offset"]["y"]),
        "font_weight": roles["card-title"]["font"]["weight"],
        "title_wrap": card["title"]["wrap_mode"] == "wrap-by-character",
        "show_arrival_time": "arrival-time" in content["card"]["fields"],
        "fit_content": card["sizing"]["width"]["mode"] == "fit-content-up-to-limit",
        "title_color": roles["card-title"]["color"],
        "body_color": roles["card-body"]["color"],
    }

    style: dict[str, Any] = {
        "schema_version": 1,
        "groups": groups,
        "default_group": migrated["group_resolution"]["fallback_group"],
        "route": {
            "width_px": _value(roles["route"]["stroke"]["width"]),
            "halo_width_px": _value(roles["route-halo"]["stroke"]["width"]),
            "arrows": {"size_px": _value(route_comp["arrows"]["head_size"]),
                       "spacing_px": _value(route_comp["arrows"]["repeat_spacing"])},
        },
        "pin": {"radius_px": _value(roles["numbered-stop-marker"]["radius"]),
                "font_size_px": _value(roles["visit-order-text"]["font"]["size"])},
        "callout": callout,
        "numbering": content["numbering"]["display_order"],
        "white_threshold": migrated["basemap_display"]["crop"]["parameters"]["white_threshold"],
    }
    if "page-title" in roles or "source-notice" in roles or border is not None:
        furniture: dict[str, Any] = {}
        if "page-title" in roles:
            furniture["title_font_pt"] = _value(roles["page-title"]["font"]["size"])
        if "source-notice" in roles:
            furniture["body_font_pt"] = _value(roles["source-notice"]["font"]["size"])
        if border is not None:
            furniture["frame_border"] = {"color": roles["map-border"]["color"],
                                         "inner_width_mm": _value(border["inner_stroke_width"]),
                                         "gap_mm": _value(border["stroke_gap"]),
                                         "outer_width_mm": _value(border["outer_stroke_width"])}
        style["page_furniture"] = furniture
    if "support-label" in components:
        support = components["support-label"]["parameters"]
        style["support_label"] = {
            "color": roles["support-accent"]["color"],
            "text_color": roles["support-label-text"]["color"],
            "point_radius_px": _value(roles["support-marker"]["radius"]),
            "font_size_px": _value(roles["support-label-text"]["font"]["size"]),
            "padding_px": _value(support["inset"]),
            "opacity": roles["support-label-background"]["opacity"],
            "leader_width_px": _value(roles["support-label-leader"]["stroke"]["width"]),
            "offset_x_px": _value(annotations["support-label"]["placement"]["offset"]["x"]),
            "offset_y_px": _value(annotations["support-label"]["placement"]["offset"]["y"]),
            "font_weight": roles["support-label-text"]["font"]["weight"],
        }
    return style