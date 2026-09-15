from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import ProtocolError


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(self, route_id: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        if route_id in self._routes:
            raise ProtocolError("ROUTE_DUPLICATE", route_id)
        self._routes[route_id] = handler

    def dispatch(self, route_id: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            handler = self._routes[route_id]
        except KeyError as exc:
            raise ProtocolError("ROUTE_NOT_IMPLEMENTED", route_id) from exc
        return handler(request)
