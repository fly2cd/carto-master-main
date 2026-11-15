"""Geometry -> preparation service: the composition root's factory port.

``compiler.map_candidate`` revalidates a candidate against the frozen preparation
of whichever geometry the scene declares, but the compiler layer must not import
the execution layer -- that runtime edge is what kept the historical
``compiler <-> workflow`` cycle alive (Tier-2 去环 Step6). This module is the
single place that maps a geometry identifier onto a concrete service class, so
composition roots (``workflow.map_generation`` and the tests that drive the same
path) can inject it as the ``contracts.protocols.PreparationServiceFactory`` port.

Both services share the same keyword-only construction signature
(``project_root`` / ``allowed_roots`` / ``registry``) even though their runtime
APIs deliberately differ per geometry, which is why one factory is sufficient and
no signature unification is implied.

Unknown geometry fails closed; there is no default geometry.
"""
from __future__ import annotations

from pathlib import Path

from ..contracts.protocols import GEOMETRIES
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .raster_preparation import RasterPreparationService
from .vector_preparation import VectorPreparationService

SERVICES = {"raster": RasterPreparationService, "vector": VectorPreparationService}


def preparation_service(geometry: str, *, project_root: Path, allowed_roots: list[str],
                        registry: SchemaRegistry | None = None):
    """Construct the preparation service for ``geometry`` (one of :data:`GEOMETRIES`)."""
    try:
        service = SERVICES[geometry]
    except KeyError:
        raise ProtocolError("PREPARATION_GEOMETRY_UNKNOWN",
                            f"Geometry must be one of {GEOMETRIES}") from None
    return service(project_root=project_root, allowed_roots=allowed_roots, registry=registry)
