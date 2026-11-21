"""Self-declared component manifest for the leadership-visit scenario package.

CONSTANTS ONLY — no imports of heavy strategy modules. The registry loads this
module at import time to build the closed ``_COMPONENTS`` allowlist; importing
the real component modules here would cycle back into ``scenario_registry``.
``ScenarioCapability.component()`` imports the target modules lazily on first use.

A scenario registers by adding this package + ONE line in
``scenario_registry._IMPLEMENTATIONS``. ``DEFAULTS`` lets a package inherit
another registered implementation's components (own entries override); this
package is standalone — no defaults.
"""
from __future__ import annotations

_SRC = ".scenarios.leadership_visit.source_contract"
_REQ = ".scenarios.leadership_visit.request_contract"
_REV = ".scenarios.leadership_visit.revision"
_PREP = ".scenarios.leadership_visit.data_preparer"
_PLAN = ".scenarios.leadership_visit.planner"
_COMP = ".scenarios.leadership_visit.candidate_compiler"
_CHK = ".scenarios.leadership_visit.legend_checker"
_AUTH = ".scenarios.leadership_visit.route_author"
_VAL = ".scenarios.leadership_visit.route_validation"

COMPONENTS: dict[str, tuple[str, str]] = {
    "data_preparer": (_PREP, "RouteDataPreparer"),
    "planner": (_PLAN, "RoutePlanner"),
    "candidate_compiler": (_COMP, "RouteCandidateCompiler"),
    "legend_checker": (_CHK, "route_legend_checker"),
    "source_contract": (_SRC, "SOURCE_CONTRACT"),
    "request_contract": (_REQ, "REQUEST_CONTRACT"),
    "revision_contract": (_REV, "REVISION_CONTRACT"),
    "author": (_AUTH, "RouteAuthor"),
    "validation_data_checker": (_VAL, "route_validation_data_checker"),
    "validation_scene": (_VAL, "route_validation_scene"),
}

# Standalone — no inherited implementation.
DEFAULTS: tuple[str, ...] = ()