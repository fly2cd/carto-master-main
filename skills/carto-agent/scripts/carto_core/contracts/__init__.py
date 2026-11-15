"""Neutral, dependency-leaf contracts shared across kernel layers.

This package is intentionally a LEAF: its modules may depend only on the
true spine (``carto_core.errors`` / ``canonical`` / ``schema_registry``) and
the standard library -- never on ``workflow``, ``compiler`` or ``adapters``.

Keeping the package ``__init__`` empty is load-bearing. Importing a submodule
such as ``carto_core.contracts.execution`` must NOT trigger any parent-package
cascade (unlike ``carto_core.workflow.models``, whose package ``__init__`` pulls
in ``template_validation`` and therefore ``compiler``). That cascade is exactly
what created the historical ``compiler <-> workflow`` import cycle; a leaf
package with an empty initializer lets both layers depend downward on shared
contracts without re-introducing it.
"""
