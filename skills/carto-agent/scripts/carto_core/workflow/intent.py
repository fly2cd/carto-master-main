from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document


def default_profiles_path() -> Path:
    return Path(__file__).resolve().parents[3] / "policies/intent-profiles.yaml"


class IntentResolver:
    """Resolve business purpose and topic IDs independently of template capabilities."""

    def __init__(self, profiles_path: Path | None = None, registry: SchemaRegistry | None = None) -> None:
        self._registry = registry or SchemaRegistry()
        policy = load_document(profiles_path or default_profiles_path())
        self._registry.validate("intent-profiles", policy)
        self.profile_version = policy["catalog_version"]
        self._policy = deepcopy(policy)
        self._profiles = {item["business_scene"]: item for item in policy["profiles"]}
        self._themes = {item["id"]: item for item in policy["themes"]}
        if len(self._profiles) != len(policy["profiles"]) or len(self._themes) != len(policy["themes"]):
            raise ProtocolError("INTENT_CATALOG_DUPLICATE", "Business-scene and topic IDs must be unique")

    @property
    def catalog_ref(self) -> dict[str, str]:
        return {"id": "intent-catalog", "version": self.profile_version,
                "digest": sha256_digest(self._policy)}

    def validate_selection(self, business_scene: str, tasks: list[str], theme_tags: list[str]) -> None:
        profile = self._profiles.get(business_scene)
        if profile is None:
            raise ProtocolError("BUSINESS_SCENE_UNKNOWN", str(business_scene))
        if not tasks or set(tasks) - set(profile["task_ids"]):
            raise ProtocolError("INTENT_TASK_UNSUPPORTED", "Tasks are not registered for this business scene")
        if set(theme_tags) - self._themes.keys():
            raise ProtocolError("INTENT_THEME_UNKNOWN", "Topic IDs must belong to the intent catalog")
        if "theme_tags" in profile["required_information"] and not theme_tags:
            raise ProtocolError("INTENT_THEME_REQUIRED", "This business scene requires content topic IDs")

    def require_current_intent(self, intent: dict[str, Any]) -> None:
        self._registry.validate("map-intent", intent)
        if intent["intent_status"] != "resolved":
            raise ProtocolError("INTENT_NOT_RESOLVED", intent["intent_status"])
        if intent["readiness_status"] != "ready":
            raise ProtocolError("INTENT_NOT_READY", intent["readiness_status"])
        if (intent["profile_version"] != self.profile_version
                or intent["evidence_refs"][:1] != [self.catalog_ref]):
            raise ProtocolError("INTENT_CATALOG_DRIFT", "Intent must be resolved against the current catalog")
        self.validate_selection(intent["business_scene"], intent["tasks"], intent["theme_tags"])

    def resolve(self, request: dict[str, Any], *, available_capabilities: Iterable[str] = ()) -> dict[str, Any]:
        self._registry.validate("intent-request", request)
        selection = request["selection"]
        text = request["text"]
        fields = selection["fields"]
        tags = sorted(selection.get("theme_tags", [
            key for key, topic in self._themes.items() if any(term in text for term in topic["terms"])
        ]))
        explicit = selection.get("business_scene")
        matches = [key for key, profile in self._profiles.items()
                   if any(term in text for term in profile["purpose_terms"])]
        if explicit is not None and explicit not in self._profiles:
            return self._result(request, None, [], tags, "unsupported", "missing_information", ["business_scene"])
        if explicit is not None:
            if matches and explicit not in matches:
                return self._result(request, explicit, [], tags, "ambiguous", "missing_information",
                                    ["business_scene_confirmation"])
            scene = explicit
        elif len(matches) != 1:
            status = "ambiguous" if matches else "unsupported"
            return self._result(request, None, [], tags, status, "missing_information", ["business_scene"])
        else:
            scene = matches[0]
        profile = self._profiles[scene]
        unknown_fields = set(fields) - (set(profile["required_information"]) - {"theme_tags"})
        if unknown_fields:
            raise ProtocolError("INTENT_FIELD_UNKNOWN", "Context fields do not belong to the selected business scene")
        tasks = list(selection.get("tasks", []))
        unsupported = ([f"task:{item}" for item in sorted(set(tasks) - set(profile["task_ids"]))]
                       + [f"theme:{item}" for item in sorted(set(tags) - self._themes.keys())]
                       + [action for action in profile["unsupported_actions"]
                          if action in selection.get("requested_actions", [])])
        if unsupported:
            return self._result(request, scene, tasks, tags, "unsupported", "missing_information", unsupported)
        missing = [name for name in profile["required_information"]
                   if not (tags if name == "theme_tags" else fields.get(name))]
        if not tasks:
            missing.append("tasks")
        missing_capabilities = sorted(set(selection.get("required_capabilities", [])) - set(available_capabilities))
        missing.extend(f"capability:{name}" for name in missing_capabilities)
        readiness = "missing_capability" if missing_capabilities else ("missing_information" if missing else "ready")
        return self._result(request, scene, tasks, tags, "resolved" if tasks else "ambiguous", readiness, missing)

    def _result(self, request: dict[str, Any], scene: str | None, tasks: list[str], tags: list[str],
                status: str, readiness: str, missing: list[str]) -> dict[str, Any]:
        result = {
            "schema_version": 1,
            "intent_id": request.get("intent_id", "resolved-intent"),
            "revision": request.get("revision", 1),
            "profile_version": self.profile_version,
            "business_scene": scene,
            "theme_tags": tags,
            "tasks": tasks,
            "intent_status": status,
            "readiness_status": readiness,
            "missing_items": missing,
            "evidence_refs": [self.catalog_ref, {"id": "intent-input", "version": "1.0.0",
                                                "digest": sha256_digest(request)}],
        }
        self._registry.validate("map-intent", result)
        return result


class TaskDispatcher:
    """Return trusted logical task keys; this does not authorize executable components."""

    def dispatch(self, intent: dict[str, Any]) -> list[dict[str, str]]:
        IntentResolver().require_current_intent(intent)
        return [{"business_scene": intent["business_scene"], "task_id": task,
                 "handler": f"business-scene:{intent['business_scene']}:{task}"} for task in intent["tasks"]]
