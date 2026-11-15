"""Scenario component contracts, enforced by tests/test_component_protocols.py.

These Protocol definitions are the contract between the framework (``workflow/``,
``compiler/``) and scenario implementations (``scenarios/``). The closed
``scenario_registry._COMPONENTS`` allowlist guarantees *which* objects a bundle
provides; this module states *what shape* those objects must have.

Two halves of the contract
--------------------------
1. Instance protocols (``DataPreparer``, ``Planner``, ...) describe the methods the
   framework calls on a component.
2. Factory protocols (``DataPreparerFactory``, ...) describe how the framework
   *constructs* the class-valued components. A component with correct methods but a
   drifted constructor still breaks the framework at the call site, so both halves
   are declared and both are checked.

Enforcement
-----------
``tests/test_component_protocols.py`` walks every bundle registered in
``scenario_registry._COMPONENTS`` and asserts, for each component: membership in
``COMPONENT_PROTOCOLS``, structural conformance (``isinstance`` against the
``runtime_checkable`` protocol) and **exact parameter-name/kind/default parity**
between the declared and the actual signature. Runtime ``isinstance`` alone only
proves a method of that name exists -- it would not catch ``compile(plan, prepared)``
drifting to ``compile(request, intent, plan, ...)`` -- which is why the signature
comparison is part of the guard.

History: this module used to be documentation only ("NOT enforced at runtime"). Measured
against the real components, 6 of the 8 protocols had drifted (wrong method name, wrong
parameter list, or a missing method), which is the failure mode the guard now prevents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Instance contracts: what the framework calls ON a component
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceContract(Protocol):
    """Data admission guard — validates that a data source is acceptable."""

    def suggestions(self, profile_definition: dict[str, Any]) -> list[dict[str, Any]]: ...
    def validate_role_bindings(self, request: dict[str, Any],
                               summaries: list[dict[str, Any]]) -> None: ...
    def brief_roles(self, request: dict[str, Any]) -> list[dict[str, Any]]: ...
    @staticmethod
    def validate_source_profile(source: dict[str, Any],
                                request: dict[str, Any]) -> None: ...


@runtime_checkable
class Author(Protocol):
    """Template authoring — produces a deterministic, closed draft package.

    ``verify_existing`` is part of the contract: ``workflow.template_author`` exposes it
    and ``workflow.template_workflow`` calls it when a template package already exists.
    """

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]: ...
    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]: ...


@runtime_checkable
class ValidationDataChecker(Protocol):
    """Scenario-level fixture validation — called during template validate."""

    def __call__(self, package_root: Path, snapshot: dict[str, Any],
                 expected: dict[str, Any]) -> None: ...


@runtime_checkable
class ValidationScene(Protocol):
    """Build and freeze a deterministic fixture render scene for template validate."""

    def __call__(self, package_root: Path, snapshot: dict[str, Any],
                 targets: list[str], font: Path, validator_version: str, *,
                 context: Any = None, workspace: Path | None = None,
                 registry: Any = None,
                 layout_parameters: dict[str, Any] | None = None,
                 validation_expression: str | None = None) -> dict[str, Any]: ...


@runtime_checkable
class DataPreparer(Protocol):
    """Production data preparation — validates and bundles real user data.

    ``prepare`` (not ``prepare_request``) is the framework entry point; it is called by
    ``workflow.map_data_preparation`` with the frozen request and its artifact ref.
    """

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]: ...


@runtime_checkable
class Planner(Protocol):
    """Composition planner — emits a MapPlan from intent + template + data."""

    def build(self, request: dict[str, Any], intent: dict[str, Any], brief: dict[str, Any],
              bundle: dict[str, Any], installation: dict[str, Any],
              contracts: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class CandidateCompiler(Protocol):
    """Compiles a renderable candidate from request + intent + plan + prepared data."""

    def compile(self, request: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any],
                bundle: dict[str, Any], installation: dict[str, Any],
                contracts: dict[str, Any], font_path: Path) -> dict[str, Any]: ...


@runtime_checkable
class LegendChecker(Protocol):
    """Legend/display consistency check — called by ``validation.map_checks``.

    Returns the checker triple ``(ok, details, disposition)``, not a report dict; the
    caller folds it into a ``ValidationReport`` result.
    """

    def __call__(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]: ...


# ---------------------------------------------------------------------------
# Construction contracts: how the framework builds the class-valued components
# ---------------------------------------------------------------------------


@runtime_checkable
class DataPreparerFactory(Protocol):
    """``workflow.map_data_preparation`` builds the preparer with these arguments."""

    def __call__(self, path_guard: Any, project_root: Path, output_root: Path,
                 registry: Any = None) -> DataPreparer: ...


@runtime_checkable
class PlannerFactory(Protocol):
    """``workflow.map_planning`` builds the planner with these arguments."""

    def __call__(self, registry: Any = None, *, project_root: Any = None) -> Planner: ...


@runtime_checkable
class CandidateCompilerFactory(Protocol):
    """``compiler.map_candidate`` builds the candidate compiler with these arguments."""

    def __call__(self, path_guard: Any, registry: Any = None, *,
                 project_root: Path | None = None, context: Any = None) -> CandidateCompiler: ...


@runtime_checkable
class AuthorFactory(Protocol):
    """``workflow.template_author`` builds the author with these arguments."""

    def __call__(self, path_guard: Any, work_root: Path, registry: Any = None) -> Author: ...


# ---------------------------------------------------------------------------
# Registries consumed by the guard test
# ---------------------------------------------------------------------------

#: Component name (as used in ``scenario_registry._COMPONENTS`` and
#: ``ScenarioCapability.component``) -> the instance contract it must satisfy.
COMPONENT_PROTOCOLS: dict[str, Any] = {
    "data_preparer": DataPreparer,
    "planner": Planner,
    "candidate_compiler": CandidateCompiler,
    "legend_checker": LegendChecker,
    "source_contract": SourceContract,
    "author": Author,
    "validation_data_checker": ValidationDataChecker,
    "validation_scene": ValidationScene,
}

#: Components the framework *constructs*, mapped to their construction contract.
#: The remaining components are registered as ready-made instances or functions and are
#: used as-is, so they have no construction half.
COMPONENT_CONSTRUCTORS: dict[str, Any] = {
    "data_preparer": DataPreparerFactory,
    "planner": PlannerFactory,
    "candidate_compiler": CandidateCompilerFactory,
    "author": AuthorFactory,
}
