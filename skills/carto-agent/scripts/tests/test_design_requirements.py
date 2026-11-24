# -*- coding: utf-8 -*-
"""Phase 1 design-requirement predicate evaluator tests (design §6.5, N02/N03/F01-F05)."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.design_requirements import (
    evaluate_predicate, evaluate_requirement, layout_fact_view)
from carto_core.compiler.layout import LayoutResolver
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES


def _cond(cid, predicate, strength="hard"):
    return {"id": cid, "strength": strength, "predicate": predicate, "source_ref": "user:msg-1"}


def _req(conditions, rid="req-1"):
    return {"schema_version": 1, "requirement_id": rid, "revision": 1,
            "object_scope": "layout", "conditions": conditions}


FACT_A3_DUAL = {
    "canvas": {"width_mm": 420.0, "height_mm": 297.0, "orientation": "landscape"},
    "roles_complete": True,
    "frames": [
        {"id": "map1", "content_id": "view-1", "type": "map", "content_role": "main-map",
         "bounds": [10, 25, 190, 175]},
        {"id": "map2", "content_id": "view-2", "type": "map", "content_role": "main-map",
         "bounds": [210, 25, 190, 175]},
        {"id": "leg1", "content_id": "leg-1", "type": "legend", "content_role": "legend-group",
         "view_ids": ["view-1"], "inside_frame": "map1", "bounds": [15, 30, 60, 50]},
        {"id": "leg2", "content_id": "leg-2", "type": "legend", "content_role": "legend-group",
         "view_ids": ["view-2"], "inside_frame": "map2", "bounds": [215, 30, 60, 50]},
    ],
}

REQ_A3_DUAL = _req([
    _cond("c-width", {"kind": "measure", "path": "/canvas/width", "op": "eq", "value": 420, "unit": "mm"}),
    _cond("c-height", {"kind": "measure", "path": "/canvas/height", "op": "eq", "value": 297, "unit": "mm"}),
    _cond("c-orient", {"kind": "enum", "path": "/canvas/orientation", "op": "eq", "value": "landscape"}),
    _cond("c-count", {"kind": "count", "role": "main-map", "op": "eq", "value": 2}),
    _cond("c-legend", {"kind": "relation", "relation": "contained-legend",
                       "scope": "each-main-map", "mode": "independent"}),
])


class PredicateTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()

    def test_a3_dual_inside_legend_fully_satisfied(self):
        self.registry.validate("design-requirement", REQ_A3_DUAL)
        result = evaluate_requirement(REQ_A3_DUAL, FACT_A3_DUAL)
        self.assertEqual("satisfied", result["aggregate"])
        self.assertEqual(5, result["hard_count"])
        self.assertTrue(all(c["status"] == "satisfied" for c in result["conditions"]))

    def test_measure_unknown_when_not_measured(self):
        fact = {"canvas": {}, "roles_complete": True, "frames": []}
        status, _, _ = evaluate_predicate(
            {"kind": "measure", "path": "/canvas/width", "op": "eq", "value": 420, "unit": "mm"}, fact)
        self.assertEqual("unknown", status)

    def test_enum_unknown_not_inferred_from_dimensions(self):
        fact = {"canvas": {"width_mm": 420, "height_mm": 297}, "roles_complete": True, "frames": []}
        status, _, _ = evaluate_predicate(
            {"kind": "enum", "path": "/canvas/orientation", "op": "eq", "value": "landscape"}, fact)
        self.assertEqual("unknown", status)

    def test_non_finite_fact_fails_closed(self):
        fact = {"canvas": {"width_mm": float("inf")}, "roles_complete": True, "frames": []}
        with self.assertRaisesRegex(ProtocolError, "REQUIREMENT_FACT_INVALID"):
            evaluate_predicate({"kind": "measure", "path": "/canvas/width", "op": "eq",
                                "value": 420, "unit": "mm"}, fact)

    def test_count_unknown_when_roles_incomplete_F02(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["roles_complete"] = False  # candidate only declares type=map, no content_role
        status, _, _ = evaluate_predicate({"kind": "count", "role": "main-map", "op": "eq", "value": 2}, fact)
        self.assertEqual("unknown", status)

    def test_count_distinct_content_id_N03(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"][1]["content_id"] = "view-1"  # two main-map frames share one view slot
        status, actual, _ = evaluate_predicate({"kind": "count", "role": "main-map", "op": "eq", "value": 2}, fact)
        self.assertEqual("violated", status)
        self.assertEqual(1, actual)

    def test_single_main_map_violates_count_N02(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]
        result = evaluate_requirement(REQ_A3_DUAL, fact)
        self.assertEqual("violated", result["aggregate"])

    def test_contained_legend_no_main_map_is_violated_F03(self):
        fact = {"canvas": {}, "roles_complete": True,
                "frames": [{"id": "leg", "content_id": "l", "type": "legend",
                            "content_role": "legend-group", "view_ids": ["v"], "bounds": [0, 0, 10, 10]}]}
        status, _, _ = evaluate_predicate({"kind": "relation", "relation": "contained-legend",
                                           "scope": "each-main-map", "mode": "independent"}, fact)
        self.assertEqual("violated", status)

    def test_contained_legend_out_of_bounds_violated_F04(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"][2]["bounds"] = [15, 30, 300, 50]  # legend exceeds map1 right edge
        status, _, _ = evaluate_predicate({"kind": "relation", "relation": "contained-legend",
                                           "scope": "each-main-map", "mode": "independent"}, fact)
        self.assertEqual("violated", status)

    def test_contained_legend_bound_to_other_view_violated(self):
        fact = deepcopy(FACT_A3_DUAL)
        fact["frames"][2]["view_ids"] = ["view-2"]  # leg1 inside map1 but bound to view-2
        status, _, _ = evaluate_predicate({"kind": "relation", "relation": "contained-legend",
                                           "scope": "each-main-map", "mode": "independent"}, fact)
        self.assertEqual("violated", status)


class AggregationTests(unittest.TestCase):
    def test_violated_dominates_unknown_F05(self):
        req = _req([
            _cond("c-count", {"kind": "count", "role": "main-map", "op": "eq", "value": 2}),
            _cond("c-width", {"kind": "measure", "path": "/canvas/width", "op": "eq", "value": 420, "unit": "mm"}),
        ])
        fact = deepcopy(FACT_A3_DUAL)
        fact["canvas"] = {}  # width unknown
        fact["frames"] = [f for f in fact["frames"] if f["id"] != "map2"]  # count violated
        result = evaluate_requirement(req, fact)
        self.assertEqual("violated", result["aggregate"])

    def test_unknown_when_no_violation_but_pending(self):
        req = _req([_cond("c-count", {"kind": "count", "role": "main-map", "op": "eq", "value": 2})])
        fact = deepcopy(FACT_A3_DUAL)
        fact["roles_complete"] = False
        self.assertEqual("unknown", evaluate_requirement(req, fact)["aggregate"])

    def test_empty_hard_set_is_browse_not_satisfied(self):
        req = _req([_cond("s", {"kind": "count", "role": "main-map", "op": "gte", "value": 1}, strength="soft")])
        result = evaluate_requirement(req, FACT_A3_DUAL)
        self.assertEqual("browse", result["aggregate"])
        self.assertEqual(0, result["hard_count"])

    def test_duplicate_condition_id_rejected(self):
        req = _req([_cond("dup", {"kind": "count", "role": "main-map", "op": "eq", "value": 2}),
                    _cond("dup", {"kind": "count", "role": "legend-group", "op": "eq", "value": 2})])
        with self.assertRaisesRegex(ProtocolError, "REQUIREMENT_CONDITION_DUPLICATE"):
            evaluate_requirement(req, FACT_A3_DUAL)

    def test_unsupported_predicate_rejected_F01(self):
        with self.assertRaisesRegex(ProtocolError, "REQUIREMENT_PREDICATE_UNSUPPORTED"):
            evaluate_predicate({"kind": "script", "path": "/x"}, FACT_A3_DUAL)

    def test_schema_rejects_arbitrary_path_F01(self):
        bad = _req([_cond("c", {"kind": "measure", "path": "/frames/0/bounds", "op": "eq",
                                "value": 1, "unit": "mm"})])
        with self.assertRaises(ProtocolError):
            SchemaRegistry().validate("design-requirement", bad)


class FactViewTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
        self.contract.update(layout_id="synthetic-role-layout")
        self.contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
        self.contract["frames"] = [
            {"id": "map", "content_id": "main-view", "type": "map", "content_role": "main-map",
             "bounds": [10, 25, 215, 175], "coordinate_space": "page", "overflow_policy": "clip"},
            {"id": "legend", "content_id": "legend-view", "type": "legend", "content_role": "legend-group",
             "bounds": [15, 30, 60, 50], "coordinate_space": "page", "overflow_policy": "reject",
             "inside_frame": "map", "view_ids": ["main-view"]},
            {"id": "title", "content_id": "title", "type": "title", "content_role": "title",
             "bounds": [10, 10, 277, 15], "coordinate_space": "page", "overflow_policy": "reject"},
        ]

    def test_fact_view_from_resolved_layout_roles_complete(self):
        resolved = LayoutResolver(self.registry).resolve(self.contract, 300)
        fact = layout_fact_view(resolved)
        self.assertTrue(fact["roles_complete"])
        self.assertEqual("landscape", fact["canvas"]["orientation"])
        self.assertEqual(297, fact["canvas"]["width_mm"])
        count = evaluate_predicate({"kind": "count", "role": "main-map", "op": "eq", "value": 1}, fact)
        self.assertEqual("satisfied", count[0])
        rel = evaluate_predicate({"kind": "relation", "relation": "contained-legend",
                                  "scope": "each-main-map", "mode": "independent"}, fact)
        self.assertEqual("satisfied", rel[0])

    def test_old_contract_without_roles_is_unknown(self):
        for frame in self.contract["frames"]:
            frame.pop("content_role", None)
        resolved = LayoutResolver(self.registry).resolve(self.contract, 300)
        fact = layout_fact_view(resolved)
        self.assertFalse(fact["roles_complete"])
        count = evaluate_predicate({"kind": "count", "role": "main-map", "op": "eq", "value": 1}, fact)
        self.assertEqual("unknown", count[0])


if __name__ == "__main__":
    unittest.main()