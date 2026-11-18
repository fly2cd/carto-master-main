"""Explicit optional geospatial dependencies, resolved on demand.

A leaf module: it imports only ``carto_core.errors``. Relocated from
``workflow.vector_preparation`` (P1 Step C) because ``adapters.formal_renderer``,
``adapters.page_renderer`` and ``scenarios.general_thematic.vector`` all need the reader's
dependency handles, and a dependency accessor is not orchestration -- leaving it in
``workflow`` forced two adapters and one scenario to import the execution layer for it.

Dependencies are explicit and never auto-installed: a missing extra fails closed with
``VECTOR_DEPENDENCY_MISSING`` rather than degrading to a slower or less exact fallback.
"""
from __future__ import annotations

from .errors import ProtocolError


def dependencies():
    """Return ``(fiona, shapely, shape, mapping, orient, CRS)`` or fail closed."""
    try:
        import fiona
        import shapely
        from shapely.geometry import shape, mapping
        from shapely.geometry.polygon import orient
        from fiona.crs import CRS
    except ImportError:
        raise ProtocolError('VECTOR_DEPENDENCY_MISSING',
                            'The explicit vector-rendering extra (Fiona/Shapely) is required') from None
    return fiona, shapely, shape, mapping, orient, CRS
