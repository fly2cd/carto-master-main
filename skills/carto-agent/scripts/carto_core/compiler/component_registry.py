"""P6 事项1.3 — trusted expression/content component definition registry.

Component definitions are registered in code (closed allowlist, like scenario_registry);
a request/instance cannot supply an arbitrary definition. Each definition declares its
strict parameter schema, admitted structure modes and required backend capabilities.

The compile entry validates every adopted component instance against its definition:
parameters validate against the closed parameter schema (unknown parameters refused, not
accepted-then-dropped), structure_mode must be admitted, and the type must match. This is
consumer validation, not merely Schema legality of the instance container.
"""
from __future__ import annotations

from typing import Any

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry

# Trusted component definitions: type -> (parameter_schema, structure_modes, backend_capabilities).
_COMPONENT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "information-card": {"parameter_schema": "card-parameters",
                         "structure_modes": ["atomic-card"],
                         "backend_capabilities": ["image-overlay"]},
    "classified-route": {"parameter_schema": "route-parameters",
                         "structure_modes": ["grouped-line"],
                         "backend_capabilities": ["image-overlay"]},
    "linked-label": {"parameter_schema": "linked-label-parameters",
                     "structure_modes": ["single-line"],
                     "backend_capabilities": ["image-overlay"]},
    "double-outline": {"parameter_schema": "double-outline-parameters",
                       "structure_modes": ["placed-map-content"],
                       "backend_capabilities": ["image-overlay"]},
    "numbered-stop-marker": {"parameter_schema": "card-parameters",
                             "structure_modes": ["pin"],
                             "backend_capabilities": ["image-overlay"]},
    "chart": {"parameter_schema": "chart-parameters",
              "structure_modes": ["bar-vertical", "bar-horizontal", "pie", "line"],
              "backend_capabilities": ["image-overlay"]},
}


def component_definition(component_type: str) -> dict[str, Any]:
    definition = _COMPONENT_DEFINITIONS.get(component_type)
    if definition is None:
        raise ProtocolError("COMPONENT_DEFINITION_UNKNOWN", component_type)
    return definition


def validate_component_instance(instance: dict[str, Any], registry: SchemaRegistry) -> None:
    """Validate one adopted component instance against its trusted definition.

    Refuses unknown types, unknown parameters (closed parameter schema), and unadmitted
    structure modes. A parameter accepted by the container but absent from the definition's
    schema is rejected here, never silently dropped.
    """
    component_type = instance.get("type")
    definition = component_definition(component_type)
    parameters = instance.get("parameters")
    if not isinstance(parameters, dict):
        raise ProtocolError("COMPONENT_PARAMETERS_INVALID", component_type)
    registry.validate(definition["parameter_schema"], parameters)
    structure_mode = instance.get("structure_mode")
    if structure_mode is not None and structure_mode not in definition["structure_modes"]:
        raise ProtocolError("COMPONENT_STRUCTURE_MODE_UNSUPPORTED",
                            f"{component_type}:{structure_mode}")


def validate_design_components(design_instances: dict[str, Any], registry: SchemaRegistry) -> None:
    """Validate every component instance in adopted design instances (事项1.3)."""
    for cid, instance in design_instances.get("components", {}).items():
        try:
            validate_component_instance(instance, registry)
        except ProtocolError as exc:
            raise ProtocolError(exc.code, f"{cid}: {exc.message}") from exc