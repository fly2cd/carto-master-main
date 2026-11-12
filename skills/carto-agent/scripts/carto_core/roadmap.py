"""Capability roadmap: separate 'forbidden' from 'not implemented yet'.

Safety rejects (unknown backend, arbitrary code, symlink escape, unknown fields)
are permanent and carry NO admission_class marker. Scope rejects that are merely
"designed but not built" must be declared in policies/capability-roadmap.yaml and
raise with details.admission_class == "not_implemented" so callers can tell a
queueable gap from a prohibition.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ConfigurationError, ProtocolError
from .schema_registry import SchemaRegistry, load_document

NOT_IMPLEMENTED = "not_implemented"
FORBIDDEN = "forbidden"


class CapabilityRoadmap:
    """Validated, packaged queue of not-yet-implemented capabilities."""

    def __init__(self, registry: SchemaRegistry | None = None, path: Path | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        # Packaged policy, never a path from a business request or doc/.
        path = path or (Path(__file__).resolve().parents[2] / "policies/capability-roadmap.yaml")
        policy = load_document(path)
        self.registry.validate("capability-roadmap", policy)
        self.version = str(policy["version"])
        self._items: dict[str, dict[str, Any]] = {item["id"]: item for item in policy["items"]}

    def item(self, feature: str) -> dict[str, Any]:
        try:
            return self._items[feature]
        except KeyError as exc:
            raise ConfigurationError("ROADMAP_FEATURE_UNDECLARED",
                f"not-implemented guard references undeclared feature: {feature}") from exc

    def require_not_implemented(self, feature: str, code: str, message: str) -> None:
        """Raise a queueable not-implemented error for a declared, undelivered feature."""
        entry = self.item(feature)
        if entry["status"] == "delivered":
            raise ConfigurationError("ROADMAP_FEATURE_DELIVERED",
                f"{feature} is delivered; remove the not-implemented guard")
        raise ProtocolError(code, message, {
            "admission_class": NOT_IMPLEMENTED,
            "feature": feature,
            "status": entry["status"],
            "target": entry.get("target", ""),
            "roadmap_version": self.version,
        })


_roadmap: CapabilityRoadmap | None = None


def roadmap(registry: SchemaRegistry | None = None) -> CapabilityRoadmap:
    global _roadmap
    if _roadmap is None or registry is not None:
        _roadmap = CapabilityRoadmap(registry=registry)
    return _roadmap


def not_implemented(feature: str, code: str, message: str, *, registry: SchemaRegistry | None = None) -> None:
    roadmap(registry).require_not_implemented(feature, code, message)


def admission_class(error: ProtocolError) -> str:
    """Classify a protocol error: declared queueable gap vs permanent prohibition."""
    details = error.details or {}
    return details.get("admission_class", FORBIDDEN)
