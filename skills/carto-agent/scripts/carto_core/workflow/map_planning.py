from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry


class MapPlanner:
    """Plan through the enabled scenario's expression strategy."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self, request: dict[str, Any], intent: dict[str, Any], brief: dict[str, Any],
              bundle: dict[str, Any], installation: dict[str, Any],
              contracts: dict[str, Any]) -> dict[str, Any]:
        profile = ScenarioRegistry(self.registry).require_request_intent(request, intent)
        profile.require_contract(contracts["scenario"])
        self.registry.validate("map-brief", brief)
        profile.require_intent_projection(brief, intent, kind="BRIEF")
        plan = profile.component("planner")(self.registry).build(
            request, intent, brief, bundle, installation, contracts)
        self.registry.validate("map-plan", plan)
        profile.require_intent_projection(plan, intent, kind="PLAN")
        if plan["brief_ref"]["digest"] != sha256_digest(brief):
            raise ProtocolError("PLAN_BRIEF_MISMATCH", "Plan must reference the approved brief")
        return plan

    @staticmethod
    def digest(plan: dict[str, Any]) -> str:
        return sha256_digest(plan)
