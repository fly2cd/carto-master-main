"""Trusted expression definitions, independent of business intents and renderer backends."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import warnings

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
        if entry is None:
            raise ProtocolError("MAP_EXPRESSION_NOT_AVAILABLE", "An explicitly pinned expression is required")
        if entry["status"] not in ("active", "deprecated"):
            raise ProtocolError("MAP_EXPRESSION_NOT_AVAILABLE", "Expression status is not available")
        if entry["status"] == "deprecated":
            superseded = entry.get("superseded_by")
            hint = f"; superseded by '{superseded}'" if superseded else ""
            warnings.warn(f"Expression '{identifier}@{version}' is deprecated{hint}", FutureWarning, stacklevel=2)
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

    # -- geometry / adapter resolution -----------------------------------------

    @staticmethod
    def _supported_geometries(entry: dict[str, Any]) -> list[str]:
        """Return the list of supported geometries for an entry.

        New entries use ``applicable_geometry``; legacy entries use ``geometry_types``.
        """
        return entry.get("applicable_geometry") or entry.get("geometry_types", [])

    def adapter_for(self, reference: dict[str, str], geometry: str) -> dict[str, Any]:
        """Return the adapter configuration for rendering this expression on *geometry*.

        Returns a dict with at least ``algorithm_id`` and ``fixture_kind``.
        """
        entry = self.require(reference)
        adapters = entry.get("adapters", {})
        if geometry in adapters:
            return deepcopy(adapters[geometry])
        # Fallback for entries without explicit adapter declarations: derive from
        # the entry-level visual_variables and fixture declarations.
        algorithm_id = entry["visual_variables"][0]["algorithm_id"]
        fixture_kind = entry.get("fixture", {}).get("kind", "none")
        return {"algorithm_id": algorithm_id, "fixture_kind": fixture_kind}

    def is_deprecated(self, reference: dict[str, str]) -> bool:
        """Return True if the referenced expression is deprecated."""
        entry = self.require(reference)
        return entry.get("status") == "deprecated"

    def superseded_by(self, reference: dict[str, str]) -> str | None:
        """Return the expression_id that supersedes this one, or None."""
        entry = self.require(reference)
        return entry.get("superseded_by")

    # -- portrayal validation ---------------------------------------------------

    def validate_portrayal(self, portrayal: dict[str, Any]) -> None:
        self.registry.validate("portrayal", portrayal)
        identifiers = [layer["id"] for layer in portrayal["layers"]]
        if len(identifiers) != len(set(identifiers)):
            raise ProtocolError("PORTRAYAL_LAYER_DUPLICATE", "Layer IDs must be unambiguous")
        for layer in portrayal["layers"]:
            for ref in [layer["map_expression_ref"], *layer.get("expression_options", [])]:
                entry = self.require(ref)
                supported = set(self._supported_geometries(entry))
                matches_family = (layer["geometry"] == "vector"
                                  and layer.get("encoding_policy") == "explicit-per-panel"
                                  and bool(supported & {"vector", "point", "line", "polygon"}))
                if layer["geometry"] not in supported and not matches_family:
                    raise ProtocolError("MAP_EXPRESSION_GEOMETRY_MISMATCH", "Layer is not supported by the expression")

    def references(self, portrayal: dict[str, Any]) -> list[dict[str, str]]:
        """The exact union of base and selectable expressions, shared by both workflows."""
        self.validate_portrayal(portrayal)
        refs = {}
        for layer in portrayal["layers"]:
            for ref in [layer["map_expression_ref"], *layer.get("expression_options", [])]:
                refs[(ref["id"], ref["version"], ref["digest"])] = deepcopy(ref)
        return [refs[key] for key in sorted(refs)]
