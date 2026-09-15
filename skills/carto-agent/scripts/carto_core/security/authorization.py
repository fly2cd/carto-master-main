from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..errors import SecurityError


class Role(StrEnum):
    VIEWER = "viewer"
    AUTHOR = "author"
    REVIEWER = "reviewer"
    PUBLISHER = "publisher"
    OPERATOR = "operator"
    ADMIN = "admin"


class Action(StrEnum):
    READ = "read"
    CREATE_TEMPLATE = "create_template"
    VALIDATE = "validate"
    APPROVE_BRIEF = "approve_brief"
    APPROVE_FREEZE = "approve_freeze"
    APPROVE_DELIVERY = "approve_delivery"
    PUBLISH_TEMPLATE = "publish_template"
    GENERATE_MAP = "generate_map"
    DELIVER = "deliver"
    MANAGE_POLICY = "manage_policy"


_ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.READ}),
    Role.AUTHOR: frozenset(
        {Action.READ, Action.CREATE_TEMPLATE, Action.VALIDATE, Action.GENERATE_MAP}
    ),
    Role.REVIEWER: frozenset(
        {Action.READ, Action.VALIDATE, Action.APPROVE_BRIEF, Action.APPROVE_FREEZE}
    ),
    Role.PUBLISHER: frozenset(
        {Action.READ, Action.PUBLISH_TEMPLATE, Action.APPROVE_DELIVERY, Action.DELIVER}
    ),
    Role.OPERATOR: frozenset({Action.READ, Action.VALIDATE, Action.GENERATE_MAP, Action.DELIVER}),
    Role.ADMIN: frozenset(Action),
}


@dataclass(frozen=True, slots=True)
class SubjectContext:
    subject_id: str
    roles: frozenset[Role]
    namespaces: frozenset[str]
    tenant_id: str


def authorize(subject: SubjectContext, action: Action, resource_namespace: str) -> None:
    if not subject.subject_id or not subject.tenant_id:
        raise SecurityError("IDENTITY_INVALID", "Authenticated subject and tenant are required")
    if not subject.roles or any(role not in _ROLE_ACTIONS for role in subject.roles):
        raise SecurityError("ROLE_INVALID", "Subject contains an unknown or empty role set")
    if not resource_namespace or (
        resource_namespace not in subject.namespaces and "*" not in subject.namespaces
    ):
        raise SecurityError(
            "RESOURCE_SCOPE_DENIED",
            f"Subject is not authorized for namespace: {resource_namespace}",
        )
    if not any(action in _ROLE_ACTIONS[role] for role in subject.roles):
        raise SecurityError("ACTION_DENIED", f"Action is not granted: {action}")
