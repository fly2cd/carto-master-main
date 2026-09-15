from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .dependencies import DependencyResolver
from .ownership import OwnershipResolver


@dataclass(frozen=True, slots=True)
class CompileRequest:
    contracts: tuple[tuple[str, str, dict[str, Any]], ...]
    dependency_graph: dict[str, list[str]]
    root_contracts: tuple[str, ...]


class ProtocolCompiler:
    """U-P1 compiler skeleton: validates, pins, orders, and checks ownership only."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        self.dependencies = DependencyResolver()
        self.ownership = OwnershipResolver()

    def compile(self, request: CompileRequest) -> dict[str, Any]:
        by_id: dict[str, tuple[str, dict[str, Any]]] = {}
        for contract_id, schema_name, value in request.contracts:
            if contract_id in by_id:
                raise ProtocolError("CONTRACT_DUPLICATE", contract_id)
            self.registry.validate(schema_name, value)
            by_id[contract_id] = (schema_name, value)
        order = self.dependencies.resolve(request.root_contracts, request.dependency_graph)
        missing = [item for item in order if item not in by_id]
        if missing:
            raise ProtocolError("CONTRACT_NOT_SUPPLIED", ",".join(missing))
        snapshot = {item: {"schema": by_id[item][0], "digest": sha256_digest(by_id[item][1])} for item in order}
        return {"schema_version": 1, "order": order, "contracts": snapshot, "digest": sha256_digest(snapshot)}
