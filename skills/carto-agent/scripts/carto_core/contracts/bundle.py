"""Neutral bundle/context helpers shared by preparation and compilation layers.

These are pure functions with no import side effects and no dependency on
``workflow`` / ``compiler`` / ``adapters``. They were relocated here so that the
``compiler`` layer can consume them *downward* through a leaf package instead of
reaching up into ``workflow`` (which triggered the historical import cycle).

* ``bundle_core`` / ``MATERIAL_BUNDLE_KEYS`` moved from
  ``carto_core.workflow.map_data_preparation``.
* ``context_snapshot`` is now the single authoritative definition; it was
  previously duplicated in ``workflow.vector_preparation`` and
  ``compiler.raster_scene``. Both original modules re-export / import it from
  here so the copy-paste fork cannot drift.
"""
from __future__ import annotations

from typing import Any

# Keys MapDataPreparer augments onto the scenario-prepared bundle for material
# (non-GIS) provenance. Scenario candidate compilers re-prepare the GIS bundle
# without these, so bundle-identity comparisons must exclude them; material
# integrity is bound separately via execution.material_facts_refs (P0-1).
MATERIAL_BUNDLE_KEYS = frozenset({"material_sources", "adoption_evidence", "data_facts"})


def bundle_core(bundle: dict[str, Any]) -> dict[str, Any]:
    """GIS-core view of a bundle, excluding MapDataPreparer material augmentation."""
    return {k: v for k, v in bundle.items() if k not in MATERIAL_BUNDLE_KEYS}


def context_snapshot(context) -> dict[str, Any]:
    """Project-scoped identity snapshot of an ExecutionContext.

    Enforces project scope, then projects the four identity fields used to bind
    a preparation/scene to its execution. Single home for what used to be two
    identical copies.
    """
    context.require_project_scope()
    return {key: getattr(context, key) for key in ('run_id', 'tenant_id', 'project_id', 'subject_id')}
