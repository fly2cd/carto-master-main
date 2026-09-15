from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..errors import ProtocolError


class DependencyResolver:
    """Resolves an explicitly supplied dependency graph; no dynamic discovery."""

    def resolve(self, roots: Iterable[str], graph: dict[str, list[str]]) -> list[str]:
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ProtocolError("DEPENDENCY_CYCLE", node)
            if node in visited:
                return
            if node not in graph:
                raise ProtocolError("DEPENDENCY_NOT_PINNED", node)
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)
            ordered.append(node)

        for root in roots:
            visit(root)
        return ordered

    @staticmethod
    def require_pinned(reference: dict[str, Any]) -> None:
        missing = [key for key in ("id", "version", "digest") if not reference.get(key)]
        if missing:
            raise ProtocolError("DEPENDENCY_NOT_PINNED", ",".join(missing))
