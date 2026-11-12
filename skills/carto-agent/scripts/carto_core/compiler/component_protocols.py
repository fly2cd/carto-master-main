"""Typing protocols for scenario component interfaces.

These Protocol definitions document the contract between the framework
(``workflow/``, ``compiler/``) and scenario implementations (``scenarios/``).
They are NOT enforced at runtime — the closed ``_COMPONENTS`` allowlist and
the ``ScenarioRegistry`` constructor already guarantee component availability.
They serve as:

* IDE type-checking support for new scenario authors
* A single source of truth for parameter names and return shapes
* A visible diff when the component contract evolves across versions
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class SourceContract(Protocol):
    """Data admission guard — validates that a data source is acceptable."""

    def suggestions(self, profile_definition: dict[str, Any]) -> list[dict[str, Any]]: ...
    def validate_role_bindings(self, request: dict[str, Any],
                               summaries: list[dict[str, Any]]) -> None: ...
    def brief_roles(self, request: dict[str, Any]) -> list[dict[str, Any]]: ...
    @staticmethod
    def validate_source_profile(source: dict[str, Any],
                                 request: dict[str, Any]) -> None: ...


class Author(Protocol):
    """Template authoring — produces a deterministic, closed draft package."""

    def author(self, request: dict[str, Any], template_ref: dict[str, str]) -> dict[str, Any]: ...


class ValidationDataChecker(Protocol):
    """Scenario-level fixture validation — called during template validate."""

    def __call__(self, package_root: Path, snapshot: dict[str, Any],
                 expected: dict[str, Any]) -> None: ...


class ValidationScene(Protocol):
    """Build and freeze a deterministic fixture render scene for template validate."""

    def __call__(self, package_root: Path, snapshot: dict[str, Any],
                 targets: list[str], font: Path, validator_version: str, *,
                 context: Any = None, workspace: Path | None = None,
                 registry: Any = None,
                 layout_parameters: dict[str, Any] | None = None) -> dict[str, Any]: ...


class DataPreparer(Protocol):
    """Production data preparation — validates and bundles real user data."""

    def prepare_request(self, request: dict[str, Any],
                         context: Any) -> dict[str, Any]: ...


class Planner(Protocol):
    """Composition planner — emits a MapPlan from intent + template + data."""

    def plan(self, request: dict[str, Any], intent: dict[str, Any],
             template: dict[str, Any], context: Any,
             registry: Any) -> dict[str, Any]: ...


class CandidateCompiler(Protocol):
    """Compiles a renderable candidate from plan + prepared data."""

    def compile(self, plan: dict[str, Any], prepared: dict[str, Any],
                context: Any, registry: Any) -> dict[str, Any]: ...


class LegendChecker(Protocol):
    """Legend consistency check — called during final quality check."""

    def __call__(self, context: dict[str, Any], candidate: dict[str, Any],
                 resolved_map: dict[str, Any]) -> dict[str, Any]: ...