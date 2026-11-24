from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..errors import ProtocolError
from .dependencies import DependencyResolver


class OwnershipResolver:
    OWNERS = {"platform", "map-style", "map-layout", "map-scenario", "project"}
    KIND_TO_SEGMENT = {
        "map-style": "style",
        "map-layout": "layout",
    }
    SEGMENT_TO_KIND = {segment: kind for kind, segment in KIND_TO_SEGMENT.items()}

    def merge(self, segments: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        """Preserve the U-P1 flat merge contract for existing compiler callers."""
        result: dict[str, Any] = {}
        owners: dict[str, str] = {}
        for owner, values in segments:
            if owner not in self.OWNERS:
                raise ProtocolError("OWNERSHIP_OWNER_UNKNOWN", owner)
            for key, value in values.items():
                if key in result and result[key] != value:
                    raise ProtocolError("OWNERSHIP_CONFLICT", f"{key}: {owners[key]} vs {owner}")
                result[key] = value
                owners[key] = owner
        return {"values": result, "ownership": owners}

    def compose_scenario(
        self,
        scenario: dict[str, Any],
        templates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace scenario-owned template segments without performing field-level merges."""
        embedded = scenario.get("embedded")
        if not isinstance(embedded, dict):
            raise ProtocolError("SCENARIO_EMBEDDED_MISSING", "scenario.embedded must be an object")

        required_segments = set(self.KIND_TO_SEGMENT.values())
        if set(embedded) != required_segments or not all(isinstance(value, dict) for value in embedded.values()):
            raise ProtocolError(
                "SCENARIO_EMBEDDED_INVALID",
                "scenario.embedded must contain exactly the style and layout segment objects",
            )

        replaceable = scenario.get("replaceable_segments", [])
        if not isinstance(replaceable, list) or any(item not in required_segments for item in replaceable):
            raise ProtocolError("SCENARIO_REPLACEABLE_INVALID", "replaceable_segments contains an invalid segment")

        composed = deepcopy(embedded)
        ownership = {segment: "map-scenario" for segment in required_segments}
        seen_kinds = {"map-scenario"}

        for template in templates:
            if not isinstance(template, dict):
                raise ProtocolError("TEMPLATE_KIND_UNKNOWN", "template descriptor must be an object")
            kind = template.get("kind")
            if kind == "map-scenario" or kind in seen_kinds:
                raise ProtocolError("TEMPLATE_KIND_DUPLICATE", str(kind))
            if kind not in self.KIND_TO_SEGMENT:
                raise ProtocolError("TEMPLATE_KIND_UNKNOWN", str(kind))
            seen_kinds.add(kind)

            expected_segment = self.KIND_TO_SEGMENT[kind]
            actual_segment = template.get("segment")
            if actual_segment != expected_segment:
                raise ProtocolError(
                    "KIND_BOUNDARY_VIOLATION",
                    f"{kind} must own the complete {expected_segment} segment, not {actual_segment}",
                )
            if expected_segment not in replaceable:
                raise ProtocolError("SEGMENT_NOT_REPLACEABLE", expected_segment)
            value = template.get("value")
            if not isinstance(value, dict):
                raise ProtocolError("KIND_BOUNDARY_VIOLATION", f"{kind}.value must be a complete object")

            self._require_compatible(scenario, template)
            composed[expected_segment] = deepcopy(value)
            ownership[expected_segment] = kind

        return {"segments": composed, "ownership": ownership}

    def validate_segment_refs(self, scenario: dict[str, Any]) -> dict[str, str]:
        """S1 semantic rules for referenced segments; returns the derived ownership map.

        Rules: a segment is sourced exactly once (embedded XOR segment_refs);
        referenced segments must be replaceable and kind-bound; every reference
        is exactly pinned. Pure protocol check consumed by the validate/publish
        and generate admission boundaries (S2).
        """
        embedded = scenario.get("embedded")
        if not isinstance(embedded, dict):
            raise ProtocolError("SCENARIO_EMBEDDED_MISSING", "scenario.embedded must be an object")
        refs = scenario.get("segment_refs", {})
        if not isinstance(refs, dict):
            raise ProtocolError("SEGMENT_REFS_INVALID", "segment_refs must be an object")
        replaceable = scenario.get("replaceable_segments", [])
        if not isinstance(replaceable, list):
            raise ProtocolError("SCENARIO_REPLACEABLE_INVALID", "replaceable_segments must be an array")
        ownership: dict[str, str] = {}
        for segment in self.KIND_TO_SEGMENT.values():
            in_embedded = segment in embedded
            in_refs = segment in refs
            if in_embedded and in_refs:
                raise ProtocolError("SEGMENT_DOUBLE_SOURCED", segment)
            if not in_embedded and not in_refs:
                raise ProtocolError("SEGMENT_SOURCE_MISSING", segment)
            if in_embedded:
                if not isinstance(embedded[segment], dict):
                    raise ProtocolError("SCENARIO_EMBEDDED_INVALID", segment)
                ownership[segment] = "map-scenario"
                continue
            reference = refs[segment]
            if segment not in replaceable:
                raise ProtocolError("SEGMENT_NOT_REPLACEABLE", segment)
            expected_kind = self.SEGMENT_TO_KIND[segment]
            if not isinstance(reference, dict) or reference.get("kind") != expected_kind:
                raise ProtocolError("KIND_BOUNDARY_VIOLATION", f"{segment} must reference {expected_kind}")
            DependencyResolver.require_pinned(reference)
            ownership[segment] = expected_kind
        return ownership

    def validate_segment_lock(self, scenario: dict[str, Any], lock: dict[str, Any]) -> None:
        """S1 lock rule: segment_refs must equal the segment-kind entries pinned in
        dependency-lock.dependencies (which must also equal manifest.dependencies).
        No floating or extra segment dependency is accepted."""
        refs = scenario.get("segment_refs", {})
        if not isinstance(refs, dict):
            raise ProtocolError("SEGMENT_REFS_INVALID", "segment_refs must be an object")
        expected = sorted(refs.values(), key=lambda item: (item["kind"], item["id"], item["version"], item["digest"]))
        actual = sorted((item for item in lock.get("dependencies", [])
                         if item.get("kind") in self.KIND_TO_SEGMENT),
                        key=lambda item: (item["kind"], item["id"], item["version"], item["digest"]))
        if expected != actual:
            raise ProtocolError("SEGMENT_LOCK_MISMATCH", str(scenario.get("scenario_id", "")))

    @staticmethod
    def _require_compatible(scenario: dict[str, Any], template: dict[str, Any]) -> None:
        requirements = template.get("compatibility", {})
        if not isinstance(requirements, dict):
            raise ProtocolError("TEMPLATE_INCOMPATIBLE", "template compatibility must be an object")
        allowed_keys = {"scenario_ids", "target_profiles", "data_roles", "placeholders"}
        if set(requirements) - allowed_keys:
            raise ProtocolError("TEMPLATE_INCOMPATIBLE", "unknown compatibility requirement")

        scenario_id = scenario.get("scenario_id")
        scenario_compatibility = scenario.get("compatibility", {})
        available = {
            "target_profiles": set(scenario_compatibility.get("target_profiles", [])),
            "data_roles": set(scenario.get("data_role_refs", [])),
            "placeholders": set(scenario_compatibility.get("placeholders", [])),
        }

        scenario_ids = requirements.get("scenario_ids", [])
        if scenario_ids and scenario_id not in scenario_ids:
            raise ProtocolError("TEMPLATE_INCOMPATIBLE", f"scenario {scenario_id} is not supported")

        for key in ("target_profiles", "data_roles", "placeholders"):
            required = requirements.get(key, [])
            if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
                raise ProtocolError("TEMPLATE_INCOMPATIBLE", f"{key} must be a string array")
            missing = sorted(set(required) - available[key])
            if missing:
                raise ProtocolError("TEMPLATE_INCOMPATIBLE", f"missing {key}: {', '.join(missing)}")
