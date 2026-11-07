from __future__ import annotations

from pathlib import Path
from typing import Any

from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard


class MapScenarioAuthor:
    """Route authoring to an explicitly enabled scenario, without embedding a theme."""

    def __init__(self, path_guard: PathGuard, work_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.work_root = path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()

    def _implementation(self, request: dict[str, Any]) -> Any:
        profile = ScenarioRegistry(self.registry).for_create(request)
        return profile.component("author")(self.path_guard, self.work_root, self.registry)

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        return self._implementation(request).author(request, brief)

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        return self._implementation(request).verify_existing(request, brief)
