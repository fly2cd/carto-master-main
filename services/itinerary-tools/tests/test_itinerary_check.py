"""itinerary_check tests: legal golden draft + illegal mutations (paired).

The legal fixture is the real draft from the 2026-11-20 end-to-end run.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import _SERVICE_ROOT
from itinerary_check import itinerary_check

FIXTURES = Path(__file__).parent / "fixtures"
CTX = {"allowed_root": _SERVICE_ROOT}


def load_golden() -> dict:
    return json.loads((FIXTURES / "draft.json").read_text(encoding="utf-8"))


class ItineraryCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Mutated drafts live in a temp project: root must be that project
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def draft_path(self, document: dict) -> str:
        path = self.tmp / "itinerary-draft.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return str(path)

    def errors(self, result) -> list:
        return result["report"]["errors"]

    def test_golden_draft_passes(self):
        result = itinerary_check(
            {"draft_path": str(FIXTURES / "draft.json")}, CTX)
        self.assertEqual(result["status"], "complete", self.errors(result))
        self.assertEqual(result["report"]["summary"],
                         {"places": 6, "stops": 7, "legs": 6})
        self.assertTrue(result["draft_digest"].startswith("sha256:"))

    def test_duplicate_stop_id(self):
        draft = load_golden()
        draft["stops"][1]["stop_id"] = draft["stops"][0]["stop_id"]
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(e["code"] == "ITINERARY_STOP_DUPLICATE"
                            for e in self.errors(result)))

    def test_unknown_place_id(self):
        draft = load_golden()
        draft["stops"][1]["place_id"] = "place-nowhere"
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_PLACE_UNKNOWN"
                            for e in self.errors(result)))

    def test_bad_activity_type(self):
        draft = load_golden()
        draft["stops"][1]["activities"][0]["type"] = "sightseeing"
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_ACTIVITY_INVALID"
                            and "/type" in e["path"]
                            for e in self.errors(result)))

    def test_bad_period(self):
        draft = load_golden()
        draft["stops"][1]["activities"][0]["period"] = "evening"
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_ACTIVITY_INVALID"
                            and "/period" in e["path"]
                            for e in self.errors(result)))

    def test_stay_leg_across_places(self):
        draft = load_golden()
        draft["legs"][2]["to_stop_id"] = "stop-04"  # stay leg to a different place
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_LEG_INVALID"
                            for e in self.errors(result)))

    def test_bad_metric_source(self):
        draft = load_golden()
        draft["legs"][0]["metric_source"] = "guess"
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_METRIC_INVALID"
                            for e in self.errors(result)))

    def test_missing_geocoding_query(self):
        draft = load_golden()
        draft["places"][0]["geocoding_query"] = "临安"
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(e["code"] == "ITINERARY_PLACE_INVALID"
                            and "geocoding_query" in e["path"]
                            for e in self.errors(result)))

    def test_input_drift(self):
        result = itinerary_check(
            {"draft_path": str(FIXTURES / "draft.json"),
             "expected_digest": "sha256:" + "0" * 64}, CTX)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(e["code"] == "ITINERARY_INPUT_DRIFT"
                            for e in self.errors(result)))

    def test_unparseable_draft(self):
        path = self.tmp / "itinerary-draft.json"
        path.write_text("{broken json", encoding="utf-8")
        result = itinerary_check({"draft_path": str(path)}, self.ctx)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(e["code"] == "ITINERARY_DRAFT_UNPARSEABLE"
                            for e in self.errors(result)))

    def test_path_outside_root(self):
        result = itinerary_check({"draft_path": "C:/Windows/win.ini"}, CTX)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_OUTSIDE_ROOT")

    def test_prefilled_location_warns(self):
        draft = load_golden()
        draft["places"][0]["location"] = {"lon": 1.0, "lat": 2.0}
        result = itinerary_check({"draft_path": self.draft_path(draft)}, self.ctx)
        self.assertTrue(any(w["code"] == "ITINERARY_LOCATION_PREFILLED"
                            for w in result["report"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
