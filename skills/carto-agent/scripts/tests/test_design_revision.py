"""Design revision proposals, persistent budgets and dependency invalidation."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.contracts.execution import ExecutionBudget
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.budget_store import BudgetStore
from carto_core.workflow.revision_graph import bundle_input_digest, compute_invalidation
from carto_core.scenarios.general_thematic.revision import REVISION_CONTRACT

# The generic graph consumes change rules and bundle keys supplied by the scenario.
RULES = REVISION_CONTRACT.rules()
BUNDLE_INPUT_KEYS = REVISION_CONTRACT.bundle_input_keys()


class BudgetStoreTests(unittest.TestCase):
    """Persistent budget survives save/load round-trips."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="carto-budget-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_fresh_budget_has_defaults(self):
        store = BudgetStore(self.root)
        budget = store.load()
        assert budget.tool_calls == 0
        assert budget.model_calls == 0
        assert budget.revisions == 0
        assert budget.cost_units == 0.0
        assert budget.context_bytes == 0
        assert budget.max_tool_calls == 20
        assert budget.max_revisions == 3

    def test_save_and_reload_preserves_counters(self):
        root = self.root
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
        assert restored.max_revisions == 3

    def test_load_with_defaults_overrides_limits(self):
        root = self.root
        store = BudgetStore(root)
        custom = ExecutionBudget(max_revisions=5, max_model_calls=3)
        budget = store.load(defaults=custom)
        assert budget.max_revisions == 5
        assert budget.max_model_calls == 3

    def test_budget_exhaustion_raises(self):
        root = self.root
        store = BudgetStore(root)
        budget = store.load()
        budget.consume("revisions", 3)  # hits max_revisions=3
        with self.assertRaisesRegex(ProtocolError, "EXECUTION_BUDGET_EXCEEDED"):
            budget.consume("revisions", 1)

    def test_budget_file_validates_schema(self):
        root = self.root
        store = BudgetStore(root)
        store.save(store.load())

        # corrupt the file
        path = root / ".budget-state.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["tool_calls"] = -1  # invalid
        path.write_text(json.dumps(raw), encoding="utf-8")

        with self.assertRaises(ProtocolError):  # schema validation fails
            store.load()

    def test_budget_store_exists(self):
        root = self.root
        store = BudgetStore(root)
        assert not store.exists()
        store.save(store.load())
        assert store.exists()


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
        with self.assertRaises(ProtocolError):
            registry.validate("design-revision-proposal", self._valid_proposal(changes={}))

    def test_proposal_without_justification_is_rejected(self):
        registry = SchemaRegistry()
        with self.assertRaises(ProtocolError):
            registry.validate("design-revision-proposal",
                              {k: v for k, v in self._valid_proposal().items() if k != "justification"})

    def test_proposal_with_unknown_field_is_rejected(self):
        registry = SchemaRegistry()
        with self.assertRaises(ProtocolError):
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
            "style": {"new_value": {"typography": {"title_pt": 18}}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_combined_changes_are_accepted(self):
        registry = SchemaRegistry()
        proposal = self._valid_proposal()
        proposal["changes"] = {
            "map_title": {"new_value": "New Title"},
            "layout_parameters": {"new_value": {"columns": 1}},
            "color_scheme": {"new_value": {"scope": "cat-contract",
                                            "colors": [{"value": 1, "color": "#FF0000"}]}},
        }
        registry.validate("design-revision-proposal", proposal)

    def test_unknown_change_key_is_rejected(self):
        registry = SchemaRegistry()
        with self.assertRaises(ProtocolError):
            registry.validate("design-revision-proposal",
                              {**self._valid_proposal(), "changes": {"data_source": {"new_value": "x"}}})


class BudgetWorkflowIntegrationTests(unittest.TestCase):
    """BudgetStore integrates with MapGenerationWorkflow."""

    def test_workflow_creates_budget_store(self):
        from carto_core.workflow.map_generation import MapGenerationWorkflow

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


class ComputeInvalidationTests(unittest.TestCase):
    """Layer-1 rules mirror the revision-impact table (Standard Thematic doc §7)."""

    def test_appearance_changes_invalidate_compilation_only(self) -> None:
        for key in ("style", "layout_parameters", "map_title"):
            with self.subTest(key=key):
                result = compute_invalidation({key: {"new_value": {}}}, RULES)
                self.assertEqual(result["invalidated_nodes"],
                                 ["candidate", "preflight", "preview", "scene"])
                self.assertTrue(result["data_evidence_reusable"])
                self.assertEqual("compile", result["earliest_step"])

    def test_panel_designs_invalidate_plan_too(self) -> None:
        result = compute_invalidation({"panel_designs": {"new_value": {}}}, RULES)
        self.assertIn("plan", result["invalidated_nodes"])
        self.assertEqual(5, len(result["invalidated_nodes"]))

    def test_combined_changes_union(self) -> None:
        result = compute_invalidation({"style": {"new_value": {}},
                                       "panel_designs": {"new_value": {}}}, RULES)
        self.assertEqual(sorted(result["invalidated_nodes"]),
                         ["candidate", "plan", "preflight", "preview", "scene"])

    def test_unknown_change_key_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_UNKNOWN"):
            compute_invalidation({"data_sources": {"new_value": {}}}, RULES)

    def test_empty_changes_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_REQUIRED"):
            compute_invalidation({}, RULES)


class BundleInputDigestTests(unittest.TestCase):
    """The digest gate separates data inputs from design-layer inputs."""

    def test_design_changes_do_not_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r"}], "map_title": "A",
                  "revised_cartography": {"typography": {}}}
        after = {"source_bindings": [{"role": "r"}], "map_title": "B",
                 "revised_cartography": {"typography": {"title_pt": 18}}}
        self.assertEqual(bundle_input_digest(before, BUNDLE_INPUT_KEYS),
                         bundle_input_digest(after, BUNDLE_INPUT_KEYS))

    def test_data_changes_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r", "path": "a.tif"}]}
        after = {"source_bindings": [{"role": "r", "path": "b.tif"}]}
        self.assertNotEqual(bundle_input_digest(before, BUNDLE_INPUT_KEYS),
                            bundle_input_digest(after, BUNDLE_INPUT_KEYS))

    def test_digest_covers_only_bundle_keys(self) -> None:
        request = {key: None for key in BUNDLE_INPUT_KEYS}
        request["unrelated"] = "anything"
        self.assertEqual(bundle_input_digest(request, BUNDLE_INPUT_KEYS),
                         bundle_input_digest({key: None for key in BUNDLE_INPUT_KEYS}, BUNDLE_INPUT_KEYS))


class LeadershipInvalidationTests(unittest.TestCase):
    """Phase 2: the leadership contract's style_overrides vocabulary invalidates
    the compilation nodes only — the frozen data evidence stays reusable and the
    bundle-input digest is untouched by a style patch."""

    def test_style_overrides_invalidate_compilation_only(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        result = compute_invalidation({"style_overrides": {"new_value": {}}}, ROUTE.rules())
        self.assertEqual(result["invalidated_nodes"],
                         ["candidate", "preflight", "preview", "scene"])
        self.assertTrue(result["data_evidence_reusable"])
        self.assertEqual("compile", result["earliest_step"])

    def test_style_patch_never_alters_bundle_inputs(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        keys = ROUTE.bundle_input_keys()
        before = {"source_bindings": [{"role": "r"}],
                  "style_overrides": {"pin": {"radius_px": 9}}}
        after = {"source_bindings": [{"role": "r"}],
                 "style_overrides": {"pin": {"radius_px": 20}}}
        self.assertEqual(bundle_input_digest(before, keys),
                         bundle_input_digest(after, keys))

    def test_page_layout_still_invalidates_plan(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        result = compute_invalidation({"page_layout": {"new_value": {}}}, ROUTE.rules())
        self.assertIn("plan", result["invalidated_nodes"])


class DataRevisionInvalidationTests(unittest.TestCase):
    """Design B: change keys mapped onto the data-evidence node mark the prepared
    bundle non-reusable, so compile re-prepares; design-layer rules are unaffected
    (regression lock — their analysis stays byte-identical)."""

    def setUp(self) -> None:
        from carto_core.scenarios.leadership_visit.data_revision import DATA_REVISION_CONTRACT
        self.rules = DATA_REVISION_CONTRACT.rules()

    def test_route_legs_invalidate_data_evidence(self) -> None:
        result = compute_invalidation(
            {"route_legs": [{"leg_id": "leg-1", "via_points": [{"lon": 1.0, "lat": 2.0}]}]},
            self.rules)
        self.assertIn("data-evidence", result["invalidated_nodes"])
        self.assertFalse(result["data_evidence_reusable"])
        self.assertEqual("compile", result["earliest_step"])

    def test_data_rules_leave_compilation_nodes_intact(self) -> None:
        result = compute_invalidation(
            {"route_legs": [{"leg_id": "leg-1", "via_points": [{"lon": 0.0, "lat": 0.0}]}]},
            self.rules)
        for node in ("candidate", "preview", "preflight", "scene"):
            self.assertIn(node, result["invalidated_nodes"])

    def test_unknown_data_key_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            compute_invalidation({"stops": []}, self.rules)

    def test_design_rules_stay_reusable_regression(self) -> None:
        # The general scenario's design rules never mention the data node, so
        # their reusability verdict must remain True after the generalization.
        result = compute_invalidation({"style": {"new_value": {}}}, RULES)
        self.assertTrue(result["data_evidence_reusable"])
        self.assertNotIn("data-evidence", result["invalidated_nodes"])


if __name__ == "__main__":
    unittest.main()
