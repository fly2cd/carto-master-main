"""Trusted expression definitions, independent of business intents and renderer backends."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document


class MapExpressionCatalog:
    """Read the single versioned repository catalog; never resolve request-supplied code."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        path = Path(__file__).resolve().parents[3] / "policies/map-expression-catalog.yaml"
        document = load_document(path)
        self.registry.validate("map-expression-catalog", document)
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in document["entries"]:
            key = (entry["expression_id"], entry["version"])
            if key in self._entries:
                raise ProtocolError("MAP_EXPRESSION_CATALOG_DUPLICATE", "Expression identities must be unique")
            self._entries[key] = deepcopy(entry)

    def reference(self, identifier: str, version: str) -> dict[str, str]:
        entry = self._get(identifier, version)
        return {"id": identifier, "version": version, "digest": sha256_digest(entry)}

    def _get(self, identifier: str, version: str) -> dict[str, Any]:
        entry = self._entries.get((identifier, version))
        if entry is None or entry["status"] != "active":
            raise ProtocolError("MAP_EXPRESSION_NOT_AVAILABLE", "An active, explicitly pinned expression is required")
        return entry

    def require(self, reference: dict[str, str]) -> dict[str, Any]:
        if not isinstance(reference, dict) or set(reference) != {"id", "version", "digest"}:
            raise ProtocolError("MAP_EXPRESSION_REFERENCE_INVALID", "Expected an exact expression reference")
        if not all(isinstance(value, str) for value in reference.values()):
            raise ProtocolError("MAP_EXPRESSION_REFERENCE_INVALID", "Expression reference values must be strings")
        entry = self._get(reference["id"], reference["version"])
        if sha256_digest(entry) != reference["digest"]:
            raise ProtocolError("MAP_EXPRESSION_CATALOG_MISMATCH", "Expression differs from its trusted catalog definition")
        return deepcopy(entry)

    def validate_portrayal(self, portrayal: dict[str, Any]) -> None:
        self.registry.validate("portrayal", portrayal)
        identifiers = [layer["id"] for layer in portrayal["layers"]]
        if len(identifiers) != len(set(identifiers)):
            raise ProtocolError("PORTRAYAL_LAYER_DUPLICATE", "Layer IDs must be unambiguous")
        for layer in portrayal["layers"]:
            entry = self.require(layer["map_expression_ref"])
            if layer["geometry"] not in entry["geometry_types"]:
                raise ProtocolError("MAP_EXPRESSION_GEOMETRY_MISMATCH", "Layer is not supported by the expression")
