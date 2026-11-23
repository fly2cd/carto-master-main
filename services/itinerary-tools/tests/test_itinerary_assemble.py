"""itinerary_assemble tests.

The strongest anchor: merging the real E2E draft + geocode + route fixtures
must reproduce the real E2E data/itinerary.json byte-for-byte.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import _SERVICE_ROOT
from itinerary_assemble import itinerary_assemble

FIXTURES = Path(__file__).parent / "fixtures"
CTX = {"allowed_root": _SERVICE_ROOT}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ItineraryAssembleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Build a mini project tree with the golden inputs
        (self.tmp / "data").mkdir()
        shutil.copy(FIXTURES / "draft.json", self.tmp / "data" / "itinerary-draft.json")
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def assemble(self, **overrides):
        args = {
            "draft_path": "data/itinerary-draft.json",
            "geocode_result": load("geocode-result.json"),
            "route_result": load("route-result.json"),
        }
        args.update(overrides)
        return itinerary_assemble(args, self.ctx)

    def test_byte_identical_to_e2e_output(self):
        result = self.assemble()
        self.assertEqual(result["status"], "assembled", result)
        expected = (FIXTURES / "expected-itinerary.json").read_bytes()
        actual = (self.tmp / "data" / "itinerary.json").read_bytes()
        self.assertEqual(actual, expected,
                         "assembled itinerary must match the E2E output byte-for-byte")
        self.assertEqual(result["counts"],
                         {"places": 6, "stops": 7, "travel_legs": 5,
                          "geometry_points": 2768})
        self.assertEqual(len(result["evidence"]), 2)

    def test_missing_place_coordinates(self):
        geo = load("geocode-result.json")
        geo["resolved"] = geo["resolved"][:-1]  # drop one place
        result = self.assemble(geocode_result=geo)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ITINERARY_LOCATION_UNRESOLVED")
        self.assertIn("place-szxz", result["message"])
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_unrouted_leg(self):
        route = load("route-result.json")
        route["results"][0]["status"] = "failed"
        result = self.assemble(route_result=route)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ITINERARY_ROAD_GEOMETRY_REQUIRED")
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_output_collision_refused(self):
        result = self.assemble(output_path="data/itinerary-draft.json")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ITINERARY_OUTPUT_COLLISION")

    def test_geocode_not_complete(self):
        result = self.assemble(geocode_result={"status": "needs_input"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "GEOCODE_INCOMPLETE")

    def test_output_path_outside_root(self):
        result = self.assemble(output_path="C:/Windows/itinerary.json")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_OUTSIDE_ROOT")

    def test_no_partial_file_on_refusal(self):
        geo = load("geocode-result.json")
        geo["resolved"] = []
        result = self.assemble(geocode_result=geo)
        self.assertEqual(result["status"], "error")
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())


class IncrementalRerouteTests(unittest.TestCase):
    """Route-revision reuse (doc/leadership-visit-route-revision-plan.md §四).

    The route-revision channel re-runs plan_route for changed legs only and
    merges the unchanged legs' previous results host-side. These tests pin the
    mechanical guarantees of that merge: only the re-routed leg may differ,
    and a bad merge (dropped leg, degenerate geometry) is refused.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "data").mkdir()
        shutil.copy(FIXTURES / "draft.json", self.tmp / "data" / "itinerary-draft.json")
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def assemble(self, **overrides):
        args = {
            "draft_path": "data/itinerary-draft.json",
            "geocode_result": load("geocode-result.json"),
            "route_result": load("route-result-revised.json"),
        }
        args.update(overrides)
        return itinerary_assemble(args, self.ctx)

    def _legs_by_id(self, data):
        return {leg["leg_id"]: leg for leg in data["legs"] if leg.get("geometry")}

    def test_incremental_merge_only_changed_leg_differs(self):
        result = self.assemble()
        self.assertEqual(result["status"], "assembled", result)
        actual = json.loads(
            (self.tmp / "data" / "itinerary.json").read_text(encoding="utf-8"))
        golden = load("expected-itinerary.json")
        actual_legs, golden_legs = self._legs_by_id(actual), self._legs_by_id(golden)
        self.assertEqual(set(actual_legs), set(golden_legs))
        revised = {r["leg_id"]: r for r in load("route-result-revised.json")["results"]}
        for leg_id in golden_legs:
            if leg_id == "leg-01":
                # the re-routed leg carries exactly the new geometry
                self.assertEqual(actual_legs[leg_id]["geometry"],
                                 revised[leg_id]["geometry"])
                self.assertNotEqual(actual_legs[leg_id]["geometry"],
                                    golden_legs[leg_id]["geometry"])
            else:
                # unchanged legs keep their previous geometry verbatim
                self.assertEqual(actual_legs[leg_id]["geometry"],
                                 golden_legs[leg_id]["geometry"])
        self.assertEqual(result["counts"]["travel_legs"], 5)

    def test_dropped_leg_in_merge_is_rejected(self):
        route = load("route-result-revised.json")
        route["results"] = [r for r in route["results"] if r["leg_id"] != "leg-02"]
        result = self.assemble(route_result=route)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ITINERARY_ROAD_GEOMETRY_REQUIRED")
        self.assertIn("leg-02", result["message"])
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_revised_leg_requires_road_geometry(self):
        route = load("route-result-revised.json")
        for r in route["results"]:
            if r["leg_id"] == "leg-01":
                r["geometry"] = {"type": "LineString", "coordinates": []}
        result = self.assemble(route_result=route)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ITINERARY_ROAD_GEOMETRY_REQUIRED")
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())


class FallbackContractAssembleTests(unittest.TestCase):
    """Degraded-route evidence gates (doc/itinerary-mcp-zero-script-plan.md CS-1).

    A straight-line engine result may only enter evidence when the draft leg
    explicitly declares route_mode=straight_line; a zero/absent distance from
    a real engine is corrupted evidence. Nothing is written on refusal.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "data").mkdir()
        shutil.copy(FIXTURES / "draft.json", self.tmp / "data" / "itinerary-draft.json")
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def assemble(self, **overrides):
        args = {
            "draft_path": "data/itinerary-draft.json",
            "geocode_result": load("geocode-result.json"),
            "route_result": load("route-result.json"),
        }
        args.update(overrides)
        return itinerary_assemble(args, self.ctx)

    def _degraded_route(self):
        route = load("route-result.json")
        for r in route["results"]:
            if r["leg_id"] == "leg-01":
                r["engine"] = "straight_line"
                r["distance_km"] = 0
                r["geometry"]["coordinates"] = [
                    [119.748604, 30.256757], [119.748604, 30.256757]]
        return route

    def test_straight_line_engine_rejected_for_road_network_leg(self):
        result = self.assemble(route_result=self._degraded_route())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ROUTE_ENGINE_DEGRADED")
        self.assertIn("leg-01", result["message"])
        self.assertIn("CARTO_AMAP_KEY", result["message"])
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_straight_line_accepted_when_draft_declares_it(self):
        draft = json.loads((FIXTURES / "draft.json").read_text(encoding="utf-8"))
        for leg in draft["legs"]:
            if leg.get("leg_id") == "leg-01":
                leg["route_mode"] = "straight_line"
        (self.tmp / "data" / "itinerary-draft.json").write_text(
            json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        result = self.assemble(route_result=self._degraded_route())
        self.assertEqual(result["status"], "assembled", result)
        self.assertTrue((self.tmp / "data" / "itinerary.json").exists())

    def test_zero_distance_from_real_engine_rejected(self):
        route = load("route-result.json")
        for r in route["results"]:
            if r["leg_id"] == "leg-01":
                r["distance_km"] = 0
        result = self.assemble(route_result=route)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ROUTE_METRICS_INVALID")
        self.assertIn("leg-01", result["message"])
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())


if __name__ == "__main__":
    unittest.main()
