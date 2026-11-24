# -*- coding: utf-8 -*-
"""Phase 3 inside-legend generation + finite-domain admission tests (plan §6, design §6.7/§2.3).

Proves the GENERAL parametric mechanism (not a fixed template): independent+inside legends are
mechanically derived from an author declaration, fully enclosed by their own main-map, propagated
with content_role/view_ids/inside_frame, and evaluated satisfied by the phase-1 contained-legend
predicate. Fail-closed: shared+inside unopened, missing declaration, legend too large, out-of-domain
parameters. Admission is policy-driven (inside implemented only when declared). Outside zero-regression.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.grid_layout import case_key, grid_cases, instantiate_grid
from carto_core.compiler.design_requirements import evaluate_predicate, layout_fact_view
from carto_core.compiler.layout import LayoutResolver
from carto_core.compiler.parameter_domain import (
    case_execution_admission, check_parameter_domain, layout_execution_admission)
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.scenarios.general_thematic.raster import layout_contract

INSIDE_DECL = {"anchor": "bottom-right", "offset_mm": 2, "width_mm": 40,
               "height_mm": 50, "padding_mm": 2}
INSIDE_CASE = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "inside"}
OUTSIDE_CASE = {"rows": 1, "columns": 2, "legend_mode": "independent", "legend_placement": "outside"}


def _contract(allowed_cases=None, inside_legend=True):
    contract = deepcopy(layout_contract())
    grid = contract["grid"]
    if allowed_cases is not None:
        grid.pop("allowed_shapes", None)
        grid.pop("legend_modes", None)
        grid["allowed_cases"] = deepcopy(allowed_cases)
    if inside_legend:
        grid["inside_legend"] = deepcopy(INSIDE_DECL)
    return contract


def _enclosed(inner, outer):
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ix >= ox - 1e-9 and iy >= oy - 1e-9 and ix + iw <= ox + ow + 1e-9 and iy + ih <= oy + oh + 1e-9


class InsideLegendGenerationTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.resolver = LayoutResolver(self.registry)

    def test_inside_generation_containment_roles_and_predicate(self):
        contract = _contract(allowed_cases=[INSIDE_CASE])
        resolved = self.resolver.resolve(contract, 300, parameters=INSIDE_CASE)
        self.registry.validate("resolved-layout", resolved)
        frames = {f["id"]: f for f in resolved["contract"]["frames"]}
        maps = [f for f in frames.values() if f.get("content_role") == "main-map"]
        legends = [f for f in frames.values() if f.get("content_role") == "legend-group"]
        self.assertEqual(2, len(maps))
        self.assertEqual(2, len(legends))
        for legend in legends:
            self.assertIn("inside_frame", legend)
            self.assertEqual([frames[legend["inside_frame"]]["content_id"]], legend["view_ids"])
        fact = layout_fact_view(resolved)
        self.assertTrue(fact["roles_complete"])
        status, actual, _ = evaluate_predicate(
            {"kind": "relation", "relation": "contained-legend", "scope": "each-main-map",
             "mode": "independent"}, fact)
        self.assertEqual("satisfied", status)
        self.assertEqual(2, actual)
        status, actual, _ = evaluate_predicate(
            {"kind": "count", "role": "main-map", "op": "eq", "value": 2}, fact)
        self.assertEqual("satisfied", status)

    def test_inside_map_keeps_full_cell_width(self):
        contract = _contract(allowed_cases=[INSIDE_CASE, OUTSIDE_CASE])
        inside = instantiate_grid(contract, INSIDE_CASE, self.registry)
        outside = instantiate_grid(contract, OUTSIDE_CASE, self.registry)
        imap = next(f for f in inside["frames"] if f["id"] == "map-r0-c0")
        omap = next(f for f in outside["frames"] if f["id"] == "map-r0-c0")
        # inside keeps full cell width; outside deducts the outer legend column.
        self.assertGreater(imap["bounds"][2], omap["bounds"][2])
        grid = contract["grid"]
        cw = (grid["panel_area"][2] - grid["column_gap_mm"]) / 2
        self.assertAlmostEqual(cw, imap["bounds"][2])

    def test_inside_legend_bounds_fully_within_map(self):
        contract = _contract(allowed_cases=[INSIDE_CASE])
        result = instantiate_grid(contract, INSIDE_CASE, self.registry)
        frames = {f["id"]: f for f in result["frames"]}
        for key in ("r0-c0", "r0-c1"):
            self.assertTrue(_enclosed(frames["legend-" + key]["bounds"], frames["map-" + key]["bounds"]))

    def test_shared_inside_not_opened(self):
        contract = _contract(allowed_cases=[{**INSIDE_CASE, "legend_mode": "shared"}])
        with self.assertRaisesRegex(ProtocolError, "GRID_PARAMETERS_UNSUPPORTED"):
            instantiate_grid(contract, {**INSIDE_CASE, "legend_mode": "shared"}, self.registry)

    def test_inside_requires_declaration(self):
        contract = _contract(allowed_cases=[INSIDE_CASE], inside_legend=False)
        with self.assertRaisesRegex(ProtocolError, "GRID_PARAMETERS_UNSUPPORTED"):
            instantiate_grid(contract, INSIDE_CASE, self.registry)

    def test_inside_legend_too_large_fails_closed(self):
        contract = _contract(allowed_cases=[INSIDE_CASE])
        contract["grid"]["inside_legend"]["width_mm"] = 500  # cannot fit inside the map
        with self.assertRaisesRegex(ProtocolError, "GRID_CAPACITY_INVALID"):
            instantiate_grid(contract, INSIDE_CASE, self.registry)

    def test_outside_placement_unchanged(self):
        contract = _contract(allowed_cases=[OUTSIDE_CASE])
        result = instantiate_grid(contract, OUTSIDE_CASE, self.registry)
        frames = {f["id"]: f for f in result["frames"]}
        legend = frames["legend-r0-c0"]
        self.assertNotIn("inside_frame", legend)
        # legacy outside legend sits to the right of the map, not enclosed.
        self.assertFalse(_enclosed(legend["bounds"], frames["map-r0-c0"]["bounds"]))

    def test_allowed_cases_single_authority(self):
        contract = _contract(allowed_cases=[INSIDE_CASE])
        # outside combination is not in the declared domain -> rejected (no duplicate authority).
        with self.assertRaisesRegex(ProtocolError, "GRID_PARAMETERS_UNSUPPORTED"):
            instantiate_grid(contract, OUTSIDE_CASE, self.registry)
        self.assertEqual([INSIDE_CASE], grid_cases(contract))


class InsideDomainAdmissionTests(unittest.TestCase):
    def test_parameter_domain_inside_membership(self):
        self.assertEqual("satisfied", check_parameter_domain(INSIDE_CASE, [INSIDE_CASE]))
        self.assertEqual("violated", check_parameter_domain(OUTSIDE_CASE, [INSIDE_CASE]))
        self.assertEqual("satisfied",
                         check_parameter_domain({k: v for k, v in INSIDE_CASE.items() if k != "legend_placement"},
                                                [{k: v for k, v in INSIDE_CASE.items() if k != "legend_placement"}]))

    def test_case_execution_admission_inside(self):
        self.assertEqual("allowed", case_execution_admission(INSIDE_CASE, [INSIDE_CASE]))
        self.assertEqual("not-implemented", case_execution_admission(INSIDE_CASE, [OUTSIDE_CASE]))

    def _fact(self):
        resolved = LayoutResolver().resolve(_contract(allowed_cases=[INSIDE_CASE]), 300, parameters=INSIDE_CASE)
        return layout_fact_view(resolved)

    def _cap(self, placements):
        return {"output_profile": {"width_mm": 297, "height_mm": 210},
                "output_constraints": {"max_width_mm": 420, "max_height_mm": 297},
                "layout_constraints": {"grid": {"legend_placements": placements}}}

    def test_admission_inside_policy_driven(self):
        fact = self._fact()
        self.assertEqual("allowed", layout_execution_admission(fact, self._cap(["outside", "inside"])))
        self.assertEqual("not-implemented", layout_execution_admission(fact, self._cap(["outside"])))
        # default (no field) stays outside-only -> inside not-implemented (backward compatible).
        cap = self._cap(["outside"])
        cap["layout_constraints"]["grid"].pop("legend_placements")
        self.assertEqual("not-implemented", layout_execution_admission(fact, cap))


if __name__ == "__main__":
    unittest.main()