"""Single general-thematic bundle: geometry is a strategy branch, not a scenario split.

The eight component hooks keep one signature each; the geometry (raster | vector) is
decided from an explicit request/template discriminator and delegated to the matching
strategy module. Registering a geometry here is NOT admission: the ``geometry_variants``
list in ``policies/scenario-capabilities.yaml`` remains the policy lever that withholds a
geometry from production routes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from ..workflow.models import ExecutionContext
from . import general_thematic as raster
from . import general_vector as vector

GEOMETRIES = ("raster", "vector")


def geometry_of_request(request: dict[str, Any]) -> str:
    geometry = request.get("geometry")
    if geometry not in GEOMETRIES:
        raise ProtocolError("SCENARIO_GEOMETRY_REQUIRED", "Declare an admitted geometry explicitly")
    return geometry


def geometry_of_profile(definition: dict[str, Any]) -> str:
    geometry = definition.get("template_geometry")
    if geometry not in GEOMETRIES:
        raise ProtocolError("SCENARIO_GEOMETRY_REQUIRED", "Template capability must declare geometry")
    return geometry


def geometry_of_snapshot(snapshot: dict[str, Any]) -> str:
    layers = snapshot.get("documents", {}).get("portrayal", {}).get("layers", [])
    geometries = {layer.get("geometry") for layer in layers}
    if len(geometries) != 1 or not geometries <= set(GEOMETRIES):
        raise ProtocolError("SCENARIO_GEOMETRY_AMBIGUOUS", "Template portrayal must declare one geometry family")
    return geometries.pop()


def _contract(request: dict[str, Any]):
    return vector.SOURCE_CONTRACT if geometry_of_request(request) == "vector" else raster.SOURCE_CONTRACT


class UnifiedSourceContract:
    """One admission guard; per-geometry rules stay inside the strategy modules."""

    def suggestions(self, profile_definition: dict[str, Any]) -> list[dict[str, Any]]:
        impl = (vector.SOURCE_CONTRACT
                if geometry_of_profile(profile_definition) == "vector"
                else raster.SOURCE_CONTRACT)
        return impl.suggestions(profile_definition)

    def validate_role_bindings(self, request: dict[str, Any], summaries: list[dict[str, Any]]) -> None:
        _contract(request).validate_role_bindings(request, summaries)

    def brief_roles(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return _contract(request).brief_roles(request)

    @staticmethod
    def validate_source_profile(source: dict[str, Any], request: dict[str, Any]) -> None:
        _contract(request).validate_source_profile(source, request)


SOURCE_CONTRACT = UnifiedSourceContract()


class GeneralDataPreparer:
    def __init__(self, path_guard: PathGuard, project_root: Path, output_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self._args = (path_guard, project_root, output_root, registry)

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        impl = (vector.GeneralVectorDataPreparer if geometry_of_request(request) == "vector"
                else raster.GeneralThematicDataPreparer)
        return impl(*self._args).prepare(request, request_ref)


class GeneralPlanner:
    def __init__(self, registry: SchemaRegistry | None = None, *, project_root=None) -> None:
        self._registry = registry
        self._project_root = project_root

    def build(self, request: dict[str, Any], intent: dict[str, Any], brief: dict[str, Any],
              bundle: dict[str, Any], installation: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any]:
        impl = (vector.GeneralVectorPlanner if geometry_of_request(request) == "vector"
                else raster.GeneralThematicPlanner)
        planner = impl(self._registry, project_root=self._project_root) if geometry_of_request(request)=="vector" else impl(self._registry)
        return planner.build(request, intent, brief, bundle, installation, contracts)


class GeneralCandidateCompiler:
    def __init__(self, path_guard: PathGuard, registry: SchemaRegistry | None = None, *,
                 project_root: Path | None = None, context: ExecutionContext | None = None) -> None:
        self._args = (path_guard, registry, project_root, context)

    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any], contracts: dict[str, Any],
                font_path: Path) -> dict[str, Any]:
        guard, registry, project, context = self._args
        impl = (vector.GeneralVectorCandidateCompiler if geometry_of_request(request) == "vector"
                else raster.GeneralThematicCandidateCompiler)
        return impl(guard, registry, project_root=project, context=context).compile(
            request, intent, plan, bundle, installation, contracts, font_path)


class GeneralAuthor:
    def __init__(self, path_guard: PathGuard, work_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self._args = (path_guard, work_root, registry)

    def _impl(self, request: dict[str, Any]):
        impl = (vector.GeneralVectorAuthor if geometry_of_request(request) == "vector"
                else raster.GeneralThematicAuthor)
        return impl(*self._args)

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        return self._impl(request).author(request, brief)

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        return self._impl(request).verify_existing(request, brief)


# Geometry-agnostic content check; the vector strategy reused it before the merge, so the
# raster implementation stays the single shared component (identity preserved for tests).
validation_data_checker = raster.validation_data_checker


def validation_scene(package_root: Path, snapshot: dict[str, Any], targets: list[str],
                     font: Path, validator_version: str, *,
                     context: ExecutionContext | None = None,
                     workspace: Path | None = None,
                     registry: SchemaRegistry | None = None,
                     layout_parameters: dict[str, Any] | None = None,
                     validation_expression: str | None = None) -> dict[str, Any]:
    kwargs = {"context": context, "workspace": workspace, "registry": registry,
              "layout_parameters": layout_parameters}
    if geometry_of_snapshot(snapshot) == "vector":
        if validation_expression is not None:
            kwargs["validation_expression"] = validation_expression
        return vector.validation_scene(package_root, snapshot, targets, font, validator_version, **kwargs)
    return raster.validation_scene(package_root, snapshot, targets, font, validator_version, **kwargs)


def legend_checker(context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
    if context.get("vector") is not None:
        return vector.legend_checker(context)
    return raster.legend_checker(context)
