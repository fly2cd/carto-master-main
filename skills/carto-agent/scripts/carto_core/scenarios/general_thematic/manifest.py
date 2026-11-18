"""Self-declared component manifest for the general-thematic scenario package.

CONSTANTS ONLY — no imports of dispatch/raster/vector. The registry loads this module at
import time to build the closed ``_COMPONENTS`` allowlist; importing the heavy strategy
modules here would cycle back into ``scenario_registry``. ``ScenarioCapability.component()``
imports the dispatch module lazily on first use.

A new scenario registers by adding its own package + a manifest like this one + ONE line
in ``scenario_registry._IMPLEMENTATIONS``. ``DEFAULTS`` lets a package inherit another
registered implementation's components (own entries override); completeness is checked as
own + defaults.
"""
from __future__ import annotations

# Module paths are relative to carto_core (resolved by import_module(package="carto_core")).
_DISPATCH = ".scenarios.general_thematic.dispatch"
_REQUEST = ".scenarios.general_thematic.request_contract"
_REVISION = ".scenarios.general_thematic.revision"

COMPONENTS: dict[str, tuple[str, str]] = {
    "data_preparer": (_DISPATCH, "GeneralDataPreparer"),
    "planner": (_DISPATCH, "GeneralPlanner"),
    "candidate_compiler": (_DISPATCH, "GeneralCandidateCompiler"),
    "legend_checker": (_DISPATCH, "legend_checker"),
    "source_contract": (_DISPATCH, "SOURCE_CONTRACT"),
    "request_contract": (_REQUEST, "REQUEST_CONTRACT"),
    "revision_contract": (_REVISION, "REVISION_CONTRACT"),
    "author": (_DISPATCH, "GeneralAuthor"),
    "validation_data_checker": (_DISPATCH, "validation_data_checker"),
    "validation_scene": (_DISPATCH, "validation_scene"),
}

# Other registered implementations whose components this package inherits (own overrides).
DEFAULTS: tuple[str, ...] = ()