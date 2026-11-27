"""leadership-visit request_contract: scenario understanding of its request body (I-3).

The kernel keeps security gates, digest gates and the state machine; this component
supplies geometry discrimination, required fields, derived capability additions,
source-reference cross-checks, brief source-plan construction and design overrides.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ...artifacts import file_digest
from ...canonical import sha256_digest
from ...errors import ProtocolError

_GEOMETRY = "vector"
_REQUIRED_FIELDS = frozenset({
    "run_id", "audience", "scope", "environment", "requested_at",
    "template", "allowed_capabilities", "font", "intent",
    "itinerary_structure", "basemap",
})
_SCENARIO_CAPABILITIES = frozenset({
    "read", "render-preview",
    "geo-to-image-pixels",
    "image-display-bounds",
})


def _merge_style_override(base: dict[str, Any],
                          patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a style_overrides patch onto the template's image_itinerary contract.

    Semantics: ``groups`` entries patch the declared group by id (present fields
    replace, the id itself never changes); ``default_group`` / ``numbering`` /
    ``white_threshold`` replace; ``route`` / ``pin`` / ``callout`` /
    ``support_label`` merge key-wise; ``page_furniture`` merges key-wise with its
    ``frame_border`` also merging key-wise. The template remains the default
    authority: fields the patch does not mention are preserved byte-for-byte. The
    merged contract is validated against image-itinerary-style at compile (the
    scenario candidate compiler's existing formal gate).
    """
    merged = deepcopy(base)
    groups = {group["id"]: group for group in merged.get("groups", [])}
    for entry in patch.get("groups", []):
        target = groups.get(entry["id"])
        if target is None:
            raise ProtocolError("LEADERSHIP_STYLE_GROUP_UNKNOWN",
                                f"style_overrides references undeclared group '{entry['id']}'")
        for key, value in entry.items():
            if key != "id":
                target[key] = deepcopy(value)
    if "default_group" in patch:
        merged["default_group"] = deepcopy(patch["default_group"])
        if merged["default_group"] not in groups:
            raise ProtocolError("LEADERSHIP_STYLE_GROUP_UNKNOWN",
                                f"style_overrides sets unknown default_group '{merged['default_group']}'")
    for key in ("numbering", "white_threshold"):
        if key in patch:
            merged[key] = deepcopy(patch[key])
    for section in ("route", "pin", "callout", "support_label"):
        if section in patch:
            merged.setdefault(section, {}).update(deepcopy(patch[section]))
    if "page_furniture" in patch:
        furniture_patch = deepcopy(patch["page_furniture"])
        border_patch = furniture_patch.pop("frame_border", None)
        merged.setdefault("page_furniture", {}).update(furniture_patch)
        if border_patch:
            merged["page_furniture"].setdefault("frame_border", {}).update(border_patch)
    return merged


class RouteRequestContract:
    """Scenario understanding of the leadership visit request body."""

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------

    def geometry(self, request: dict[str, Any]) -> str:
        return _GEOMETRY

    # ------------------------------------------------------------------
    # required_fields
    # ------------------------------------------------------------------

    def required_fields(self) -> frozenset[str]:
        return _REQUIRED_FIELDS

    # ------------------------------------------------------------------
    # required_capabilities
    # ------------------------------------------------------------------

    def required_capabilities(self, request: dict[str, Any]) -> set[str]:
        # Scenario-derived additions only; the kernel unions the {read, render-preview}
        # baseline and owns the CAPABILITY_NOT_AUTHORIZED security gate.
        capabilities = set(_SCENARIO_CAPABILITIES)
        if request.get("annotation_layout"):
            # The callout layout solver runs only when annotations are requested;
            # its capability is required exactly then (precise-to-usage), and the
            # ToolGateway enforces the grant again at invoke time.
            capabilities.add("annotation-layout")
        return capabilities

    # ------------------------------------------------------------------
    # validate_body
    # ------------------------------------------------------------------

    def validate_body(self, request: dict[str, Any]) -> None:
        # P6/S8: the running visual (style) authority is portrayal.design_instances (the
        # private image_itinerary contract has been retired). Style segment replacement is
        # refused (design_instances owns style). Layout segment replacement IS admitted so a
        # general shared Layout can be reused cross-scene (A18); the compiler consumes the
        # resolved layout, so the selection is effective, not ignored.
        segment_refs = request.get("segment_refs") or {}
        if segment_refs.get("style"):
            raise ProtocolError("SEGMENT_SELECTION_UNSUPPORTED",
                                "leadership_visit style authority is design_instances; "
                                "style segment replacement is not admitted")
        if set(segment_refs) - {"layout"}:
            raise ProtocolError("SEGMENT_SELECTION_UNSUPPORTED",
                                "leadership_visit admits only layout segment replacement")
        # Single-candidate boundary: leadership visit maps use one candidate plus direct
        # style/layout overrides (style_overrides). Multi-variant open design / comparison
        # is reserved for government thematic mapping (general scenario); the shared-plan
        # multi-variant path is not admitted here. Refuse explicitly (forbidden boundary).
        if request.get("design_variants"):
            raise ProtocolError("LEADERSHIP_VARIANTS_UNSUPPORTED",
                                "leadership_visit is single-candidate; use style_overrides for "
                                "direct style/layout changes. Multi-variant comparison is reserved "
                                "for the general thematic scenario.")
        # itinerary_structure — source and normalized refs must be present
        itin = request.get("itinerary_structure")
        if not itin:
            raise ProtocolError("LEADERSHIP_REQUEST_INCOMPLETE",
                                "itinerary_structure is required")
        if not itin.get("source_ref"):
            raise ProtocolError("LEADERSHIP_REQUEST_INCOMPLETE",
                                "itinerary_structure.source_ref is required")
        # basemap — image_ref and parameters_ref must be present
        basemap = request.get("basemap")
        if not basemap:
            raise ProtocolError("LEADERSHIP_REQUEST_INCOMPLETE",
                                "basemap is required")
        if not basemap.get("image_ref"):
            raise ProtocolError("LEADERSHIP_REQUEST_INCOMPLETE",
                                "basemap.image_ref is required")
        if basemap.get("mode") != "registered-transform":
            raise ProtocolError("LEADERSHIP_BASEMAP_MODE_INVALID",
                                "basemap.mode must be 'registered-transform'")
        # online_basemap — optional online tile binding (display layer only)
        online = request.get("online_basemap")
        if online is not None:
            if online.get("provider") != "Tianditu":
                raise ProtocolError(
                    "LEADERSHIP_BASEMAP_PROVIDER_UNSUPPORTED",
                    "online_basemap.provider must be 'Tianditu' (CGCS2000 ~= WGS84); "
                    "other providers are not admitted")
            if online.get("layer") not in {"vec_w", "img_w", "cia_w"}:
                raise ProtocolError("LEADERSHIP_BASEMAP_PROVIDER_UNSUPPORTED",
                                    "online_basemap.layer must be a Tianditu raster layer")
        # source_bindings — route-stops must be present
        roles = {b["role"] for b in request.get("source_bindings", [])}
        if "route-stops" not in roles:
            raise ProtocolError("LEADERSHIP_REQUEST_INCOMPLETE",
                                "source_bindings must include role 'route-stops'")
        # pending mode — when the itinerary file will be produced after G1
        # (MCP tool chain), the source_ref URI may not resolve yet; this is
        # legal only if at least one binding declares pending preparation.
        bindings = request.get("source_bindings", [])
        pending = any(b.get("pending") for b in bindings)
        if not pending:
            # Non-pending: the itinerary file must exist now.
            return

    # ------------------------------------------------------------------
    # source_plan
    # ------------------------------------------------------------------

    def source_plan(self, request: dict[str, Any], path_guard: Any,
                    project_root: Path) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for binding in sorted(request.get("source_bindings", []), key=lambda b: b["role"]):
            operations = [op for op in ("read", "filter", "reproject")
                          if op in request["allowed_capabilities"]]
            entry: dict[str, Any] = {
                "role": binding["role"],
                "source_ref": binding["source_ref"],
                "allowed_operations": operations,
                "field_bindings": [
                    {"semantic_role": fb["semantic_role"], "source_field": fb["source_field"]}
                    for fb in binding.get("field_bindings", [])
                ],
            }
            if binding.get("pending"):
                # G1 前声明"将要处理"：itinerary 文件由 MCP 工具链在 G1 后产出，
                # 此时不要求文件存在、不绑定 path_digest。brief 展示的是"计划"
                # 而不是"已就绪的数据"。G1 后宿主完成 MCP 调用并更新
                # source_ref.digest，compile 时内核校验实际文件。
                entry["preparation"] = binding.get("preparation", "mcp-itinerary-chain")
            else:
                # 现有模式：文件已存在，计算摘要绑定。
                entry["path_digest"] = file_digest(
                    path_guard.resolve(binding["path"], base_root=project_root, must_exist=True))
            plan.append(entry)
        # basemap resource — always verify image exists (user-provided material)
        basemap = request["basemap"]
        image_path = path_guard.resolve(basemap["image_ref"]["uri"],
                                        base_root=project_root, must_exist=True)
        plan.append({
            "role": "basemap",
            "source_ref": basemap["image_ref"],
            "path_digest": file_digest(image_path),
            "allowed_operations": ["read"],
        })
        # online basemap declaration — an outbound face, not a local byte resource:
        # the frontend fetches Tianditu tiles for the declared view, so the tile
        # requests belong on the G1 approval face even when the PDF renders from
        # the registered image. Encoded as a declaration ref (digest binds the
        # declared provider/layer/zoom options); nothing resolves it as a path.
        online = request.get("online_basemap")
        if online is not None:
            plan.append({
                "role": "online-basemap",
                "source_ref": {
                    "id": "online-basemap",
                    "version": "1.0.0",
                    "digest": sha256_digest(online),
                },
                "allowed_operations": [],
            })
        return plan

    # ------------------------------------------------------------------
    # override_keys / apply_overrides
    # ------------------------------------------------------------------

    def override_keys(self) -> tuple[str, ...]:
        return ("map_title", "style_overrides")

    def apply_overrides(self, overrides: dict[str, Any],
                        contracts: dict[str, Any]) -> dict[str, Any]:
        # map_title is consumed from the request by the compiler/planner; the
        # scenario contract has no title field, so it stays byte-identical to the
        # installed template.
        patch = overrides.get("style_overrides")
        if patch:
            contracts.setdefault("portrayal", {})
            # P6 S8: the adopted design instances are the authority. Resolve the effective
            # style, apply the patch, and re-adopt the instances. The private image_itinerary
            # contract is no longer stored or consulted.
            instances = contracts["portrayal"].get("design_instances")
            if not instances:
                raise ProtocolError(
                    "LEADERSHIP_STYLE_CONTRACT_MISSING",
                    "style_overrides requires the template portrayal contract's "
                    "design_instances section")
            from .contract_migration import migrate_image_itinerary, resolve_effective_style
            base = resolve_effective_style(instances)
            patched = _merge_style_override(base, patch)
            rule_ref = instances["style_roles"]["route"]["stroke"]["width"]["rule_ref"]
            contracts["portrayal"]["design_instances"] = migrate_image_itinerary(patched, rule_ref=rule_ref)
        return contracts


REQUEST_CONTRACT = RouteRequestContract()