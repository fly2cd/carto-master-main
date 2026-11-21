"""A1.2 – Design revision, proposal, and persistent budget tests."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import pytest

from carto_core.artifacts import atomic_yaml, sha256_digest
from carto_core.canonical import sha256_digest as _sha256
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.workflow.budget_store import BudgetStore
from carto_core.contracts.execution import ExecutionBudget

# ----- helpers ---------------------------------------------------------------

APPROVAL_KEY = b"test-revision-approval-key-32bytes!"  # >= 32 bytes


def _temp_run_root():
    return Path(tempfile.mkdtemp(prefix="a12-test-"))


# =============================================================================
# BudgetStore
# =============================================================================


class BudgetStoreTests(unittest.TestCase):
    """Persistent budget survives save/load round-trips."""

    def test_fresh_budget_has_defaults(self):
        store = BudgetStore(_temp_run_root())
        budget = store.load()
        assert budget.tool_calls == 0
        assert budget.model_calls == 0
        assert budget.revisions == 0
        assert budget.cost_units == 0.0
        assert budget.context_bytes == 0
        assert budget.max_tool_calls == 20
        assert budget.max_revisions == 2

    def test_save_and_reload_preserves_counters(self):
        root = _temp_run_root()
        store = BudgetStore(root)
        budget = store.load()
        budget.consume("tool_calls", 3)
        budget.consume("model_calls", 1)
        budget.consume("revisions", 1)
        budget.consume("cost_units", 10.5)
        budget.consume("context_bytes", 5000)
        store.save(budget)

        # reload from same path
        store2 = BudgetStore(root)
        restored = store2.load()
        assert restored.tool_calls == 3
        assert restored.model_calls == 1
        assert restored.revisions == 1
        assert restored.cost_units == 10.5
        assert restored.context_bytes == 5000
        # limits unchanged
        assert restored.max_tool_calls == 20
        assert restored.max_revisions == 2

    def test_load_with_defaults_overrides_limits(self):
        root = _temp_run_root()
        store = BudgetStore(root)
        custom = ExecutionBudget(max_revisions=5, max_model_calls=3)
        budget = store.load(defaults=custom)
        assert budget.max_revisions == 5
        assert budget.max_model_calls == 3

    def test_budget_exhaustion_raises(self):
        root = _temp_run_root()
        store = BudgetStore(root)
        budget = store.load()
        budget.consume("revisions", 2)  # hits max_revisions=2
        with pytest.raises(ProtocolError, match="EXECUTION_BUDGET_EXCEEDED"):
            budget.consume("revisions", 1)

    def test_budget_file_validates_schema(self):
        root = _temp_run_root()
        store = BudgetStore(root)
        store.save(store.load())

        # corrupt the file
        path = root / ".budget-state.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["tool_calls"] = -1  # invalid
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(ProtocolError):  # schema validation fails
            store.load()

    def test_budget_store_exists(self):
        root = _temp_run_root()
        store = BudgetStore(root)
        assert not store.exists()
        store.save(store.load())
        assert store.exists()


# =============================================================================
# Design Revision Proposal – schema validation
# =============================================================================


class DesignRevisionProposalTests(unittest.TestCase):
    """Schema validates revision proposals correctly."""

    @staticmethod
    def _valid_proposal(**overrides):
        base = {
            "schema_version": 1,
            "proposal_id": "proposal-test-001",
            "run_id": "run-test-001",
            "parent_revision": 1,
            "changes": {
                "map_title": {"new_value": "Updated Map Title"},
            },
            "justification": "The title should reflect the updated scope.",
        }
        base.update(overrides)
        return base

    def test_valid_proposal_passes(self):
        registry = SchemaRegistry()
        registry.validate("design-revision-proposal", self._valid_proposal())

    def test_proposal_without_changes_is_rejected(self):
        registry = SchemaRegistry()
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal", self._valid_proposal(changes={}))

    def test_proposal_without_justification_is_rejected(self):
        registry = SchemaRegistry()
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal",
                              {k: v for k, v in self._valid_proposal().items() if k != "justification"})

    def test_proposal_with_unknown_field_is_rejected(self):
        registry = SchemaRegistry()
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal",
                              {**self._valid_proposal(), "data_source": "new-source"})

    def test_layout_parameters_change_is_accepted(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "layout_parameters": {"new_value": {"orientation": "landscape", "columns": 2}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_cartography_change_is_accepted(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "cartography": {"new_value": {"typography": {"title_pt": 18}}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_combined_changes_are_accepted(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "map_title": {"new_value": "New Title"},
            "layout_parameters": {"new_value": {"columns": 1}},
            "cartography": {"new_value": {"color_scheme": {"primary": "#FF0000"}}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_annotation_layout_change_is_accepted(self):
        """Phase 0 backfill: the leadership-visit change key passes the shared
        proposal schema (closed shape mirroring the request profile)."""
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "annotation_layout": {"new_value": {"seed": 7, "iterations": 500, "gap_px": 4}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_page_layout_change_is_accepted(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "page_layout": {"new_value": {"model": "fixed-page", "width_mm": 297,
                                          "height_mm": 210, "dpi": 300}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_annotation_layout_invalid_shape_is_rejected(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "annotation_layout": {"new_value": {"seed": 7, "iterations": 0, "gap_px": 4}},
        }
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal", proposal)

    def test_page_layout_invalid_shape_is_rejected(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "page_layout": {"new_value": {"model": "unknown-model"}},
        }
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal", proposal)

    def test_style_overrides_change_is_accepted(self):
        """Phase 2: the leadership-visit style patch is expressible in the shared
        proposal vocabulary (shape delegated to the override schema)."""
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "style_overrides": {"new_value": {"groups": [{"id": "morning", "color": "#228833"}]}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_style_overrides_invalid_patch_is_rejected(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "style_overrides": {"new_value": {"groups": [{"id": "morning", "color": "#2288GG"}]}},
        }
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal", proposal)

    def test_unknown_change_key_is_rejected(self):
        registry = SchemaRegistry()
        with pytest.raises(ProtocolError):
            registry.validate("design-revision-proposal",
                              {**self._valid_proposal(), "changes": {"data_source": {"new_value": "x"}}})


# =============================================================================
# Budget CLI integration (via workflow init)
# =============================================================================


class BudgetWorkflowIntegrationTests(unittest.TestCase):
    """BudgetStore integrates with MapGenerationWorkflow."""

    def test_workflow_creates_budget_store(self):
        from carto_core.workflow.map_generation import MapGenerationWorkflow
        from carto_core.security.paths import PathGuard

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            project.mkdir()
            workdir = root / "work"
            workdir.mkdir()
            repo = root / "repo"
            repo.mkdir()

            wf = MapGenerationWorkflow(
                allowed_roots=[str(root)],
                project_root=str(project),
                workdir=str(workdir),
                repository_root=str(repo),
                repository_scope="test-scope",
            )
            # budget store is created but budget file doesn't exist until saved
            assert not wf._budget_store.exists()

    def test_budget_persists_across_workflow_instances(self):
        from carto_core.workflow.map_generation import MapGenerationWorkflow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            project.mkdir()
            workdir = root / "work"
            workdir.mkdir()
            repo = root / "repo"
            repo.mkdir()

            wf1 = MapGenerationWorkflow(
                allowed_roots=[str(root)],
                project_root=str(project),
                workdir=str(workdir),
                repository_root=str(repo),
                repository_scope="test-scope",
            )
            budget1 = wf1._budget_store.load()
            budget1.consume("revisions", 1)
            wf1._budget_store.save(budget1)

            # new instance on same workdir
            wf2 = MapGenerationWorkflow(
                allowed_roots=[str(root)],
                project_root=str(project),
                workdir=str(workdir),
                repository_root=str(repo),
                repository_scope="test-scope",
            )
            budget2 = wf2._budget_store.load()
            assert budget2.revisions == 1