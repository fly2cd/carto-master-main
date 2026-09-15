from __future__ import annotations

from typing import Any, Protocol

from ..workflow.models import ExecutionContext


class CapabilityHandler(Protocol):
    def __call__(self, typed_input: dict[str, Any], execution_context: ExecutionContext) -> dict[str, Any]: ...


class MapAdapter(Protocol):
    def capabilities(self) -> set[str]: ...
    def compile(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def render(self, request: dict[str, Any]) -> dict[str, Any]: ...
