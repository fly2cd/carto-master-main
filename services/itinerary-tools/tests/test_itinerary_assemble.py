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


if __name__ == "__main__":
    unittest.main()
