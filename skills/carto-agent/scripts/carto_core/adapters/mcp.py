from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..errors import SecurityError
from ..workflow.models import ExecutionContext
from .tool_gateway import ToolGateway, ToolResult


@dataclass(frozen=True, slots=True)
class McpCapabilityDescriptor:
    server_id: str
    capability_id: str
    metadata: dict[str, Any]


class McpAdapter:
    """Weakly coupled MCP discovery facade; execution still goes through ToolGateway."""

    def __init__(self, server_id: str, discovered: Iterable[McpCapabilityDescriptor] = ()) -> None:
        self.server_id = server_id
        self._discovered = {item.capability_id: item for item in discovered}

    def discover(self) -> tuple[McpCapabilityDescriptor, ...]:
        return tuple(self._discovered[key] for key in sorted(self._discovered))

    def bind(self, gateway: ToolGateway, capability_id: str, handler: Callable[[dict[str, Any], ExecutionContext], dict[str, Any]], *, input_schema: str | None = None, output_schema: str | None = None) -> None:
        if capability_id not in self._discovered:
            raise SecurityError("MCP_CAPABILITY_NOT_DISCOVERED", capability_id)
        gateway.register(capability_id, handler, input_schema=input_schema, output_schema=output_schema)

    @staticmethod
    def invoke(gateway: ToolGateway, capability_id: str, typed_input: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return gateway.invoke(capability_id, typed_input, context)
