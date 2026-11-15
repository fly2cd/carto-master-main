"""Persistent cumulative budget that survives CLI restarts."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..artifacts import atomic_json, utc_now
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..contracts.execution import ExecutionBudget


class BudgetStore:
    """Read/write a persistent ExecutionBudget for a single run.

    Budget counters (tool_calls, model_calls, revisions, cost_units, context_bytes)
    accumulate across CLI invocations.  Exhaustion is enforced by
    :meth:`ExecutionBudget.consume` — the store only persists the latest counters.
    """

    def __init__(self, run_root: Path, registry: SchemaRegistry | None = None) -> None:
        self._path = run_root / ".budget-state.json"
        self._registry = registry or SchemaRegistry()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def load(self, *, defaults: ExecutionBudget | None = None) -> ExecutionBudget:
        """Return the persisted budget, or *defaults* (or a fresh budget)."""
        if not self._path.exists():
            return replace(defaults) if defaults is not None else ExecutionBudget()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProtocolError("BUDGET_STATE_INVALID", str(self._path)) from exc
        self._registry.validate("budget-state", raw)
        return ExecutionBudget(
            max_tool_calls=raw["max_tool_calls"],
            max_model_calls=raw["max_model_calls"],
            max_revisions=raw["max_revisions"],
            max_elapsed_seconds=raw["max_elapsed_seconds"],
            max_cost_units=raw["max_cost_units"],
            max_context_bytes=raw["max_context_bytes"],
            tool_calls=raw["tool_calls"],
            model_calls=raw["model_calls"],
            revisions=raw["revisions"],
            cost_units=raw["cost_units"],
            context_bytes=raw["context_bytes"],
            started_at=raw["started_at"],
        )

    def save(self, budget: ExecutionBudget) -> None:
        """Persist the current budget counters atomically."""
        value = {
            "schema_version": 1,
            "saved_at": utc_now(),
            "max_tool_calls": budget.max_tool_calls,
            "max_model_calls": budget.max_model_calls,
            "max_revisions": budget.max_revisions,
            "max_elapsed_seconds": budget.max_elapsed_seconds,
            "max_cost_units": budget.max_cost_units,
            "max_context_bytes": budget.max_context_bytes,
            "tool_calls": budget.tool_calls,
            "model_calls": budget.model_calls,
            "revisions": budget.revisions,
            "cost_units": budget.cost_units,
            "context_bytes": budget.context_bytes,
            "started_at": budget.started_at,
        }
        self._registry.validate("budget-state", value)
        atomic_json(self._path, value, create_once=False)

    def exists(self) -> bool:
        return self._path.exists()