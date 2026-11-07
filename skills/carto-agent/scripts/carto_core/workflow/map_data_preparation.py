from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard


class MapDataPreparer:
    """Select the registered data adapter; common workflow code has no business roles."""

    def __init__(self, path_guard: PathGuard, project_root: Path, output_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = path_guard.resolve(project_root, must_exist=True)
        self.output_root = path_guard.resolve(output_root)
        self.registry = registry or SchemaRegistry()

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        from ..scenario_registry import ScenarioRegistry

        profile = ScenarioRegistry(self.registry).for_generate(request)
        adapter = profile.component("data_preparer")(
            self.path_guard, self.project_root, self.output_root, self.registry)
        return adapter.prepare(request, request_ref)
