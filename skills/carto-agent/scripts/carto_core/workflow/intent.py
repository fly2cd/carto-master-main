from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document


SCENE_TERMS = {
    "government_thematic": ("政务", "专题", "经济发展", "科技创新", "现代产业", "对外开放", "文旅", "交通运输", "行政区划"),
    "emergency_mapping": ("应急", "滑坡", "地质灾害", "洪涝", "洪水", "森林火灾", "灾情", "救援"),
    "leadership_visit": ("领导调研", "调研路线", "行程", "考察点", "调研点"),
}


class IntentResolver:
    def __init__(self, profiles_path: Path, registry: SchemaRegistry | None = None) -> None:
        policy = load_document(profiles_path)
        self.profile_version = str(policy["catalog_version"])
        self._profiles = {item["scene_id"]: item for item in policy["profiles"]}
        self._registry = registry or SchemaRegistry()

    def resolve(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("text", ""))
        fields = dict(request.get("fields", {}))
        explicit_scene = request.get("business_scene")
        matches = [scene for scene, terms in SCENE_TERMS.items() if any(term in text for term in terms)]
        if explicit_scene:
            if explicit_scene not in self._profiles:
                return self._result(request, "government_thematic", [], "unsupported", "missing_information", ["supported_business_scene"])
            if matches and explicit_scene not in matches:
                return self._result(request, explicit_scene, [], "ambiguous", "missing_information", ["business_scene_confirmation"])
            matches = [explicit_scene]
        matches = list(dict.fromkeys(matches))
        if not matches:
            return self._result(request, "government_thematic", [], "unsupported", "missing_information", ["business_scene"])
        if len(matches) > 1:
            return self._result(request, matches[0], [], "ambiguous", "missing_information", ["business_scene_confirmation"])
        scene = matches[0]
        profile = self._profiles[scene]
        unsupported = [action for action in profile.get("unsupported_actions", []) if action in request.get("requested_actions", [])]
        if unsupported:
            return self._result(request, scene, [], "unsupported", "missing_information", unsupported)
        missing = [name for name in profile["required_information"] if not fields.get(name)]
        missing_capabilities = [name for name in request.get("required_capabilities", []) if name not in request.get("available_capabilities", [])]
        if missing_capabilities:
            readiness = "missing_capability"
            missing.extend(f"capability:{name}" for name in missing_capabilities)
        else:
            readiness = "missing_information" if missing else "ready"
        tasks = list(request.get("tasks") or profile["task_ids"][:1])
        unknown_tasks = sorted(set(tasks) - set(profile["task_ids"]))
        if unknown_tasks:
            return self._result(request, scene, [], "unsupported", "missing_information", [f"task:{item}" for item in unknown_tasks])
        return self._result(request, scene, tasks, "resolved", readiness, missing)

    def _result(self, request: dict[str, Any], scene: str, tasks: list[str], intent_status: str, readiness_status: str, missing: list[str]) -> dict[str, Any]:
        evidence_value = {"profile_version": self.profile_version, "scene": scene}
        result = {
            "schema_version": 1,
            "intent_id": str(request.get("intent_id", "resolved-intent")),
            "revision": int(request.get("revision", 1)),
            "profile_version": self.profile_version,
            "business_scene": scene,
            "tasks": tasks or [self._profiles[scene]["task_ids"][0]],
            "intent_status": intent_status,
            "readiness_status": readiness_status,
            "missing_items": missing,
            "evidence_refs": [{"id": "intent-profile", "version": self.profile_version, "digest": sha256_digest(evidence_value)}],
        }
        if request.get("theme"):
            result["theme"] = str(request["theme"])
        self._registry.validate("map-intent", result)
        return result


class TaskDispatcher:
    def dispatch(self, intent: dict[str, Any]) -> list[dict[str, str]]:
        if intent["intent_status"] != "resolved":
            raise ProtocolError("INTENT_NOT_RESOLVED", intent["intent_status"])
        if intent["readiness_status"] != "ready":
            raise ProtocolError("INTENT_NOT_READY", intent["readiness_status"])
        return [{"scene_id": intent["business_scene"], "task_id": task, "handler": f"scene:{intent['business_scene']}:{task}"} for task in intent["tasks"]]
