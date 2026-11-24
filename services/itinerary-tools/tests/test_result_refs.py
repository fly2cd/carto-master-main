"""Result reference protocol tests (doc/itinerary-mcp-zero-script-plan.md CS-2).

Golden anchors:
- inline vs referenced route results must assemble byte-identical
  data/itinerary.json (protocol equivalence);
- base_result_ref merge reroutes only the changed legs and carries the
  others verbatim ("only what should change, changed");
- tampered/misleading references are refused by name (digest binding).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import plan_route
from _service_utils import raw_file_digest
from itinerary_assemble import itinerary_assemble

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _StubEngine:
    def __init__(self, outcome):
        self._outcome = outcome

    async def reroute_leg(self, origin, destination, via_points=None, strategy="2"):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _dual_raw():
    return {"polyline": [[120.15, 30.26], [120.0, 30.2], [119.74, 30.25]],
            "distance": 42500, "duration": 3400, "engine": "dual_graph"}


def _revised_leg01_raw():
    """Raw engine values that plan_route turns into the revised leg-01
    of route-result-revised.json (amap reroute via Zijingang)."""
    revised = {r["leg_id"]: r for r in load("route-result-revised.json")["results"]}
    leg = revised["leg-01"]
    return {"polyline": leg["geometry"]["coordinates"],
            "distance": int(round(leg["distance_km"] * 1000)),
            "duration": int(round(leg["duration_min"] * 60)),
            "engine": leg["engine"]}


class PlanRoutePersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.ctx = {"allowed_root": self.tmp}
        self.leg = {"leg_id": "leg-01",
                    "origin": {"lon": 120.15, "lat": 30.26},
                    "destination": {"lon": 119.74, "lat": 30.25}}

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, outcome, **kwargs):
        with mock.patch.object(plan_route, "RouteEngine",
                               lambda *a, **k: _StubEngine(outcome)):
            return plan_route.plan_route({"legs": [self.leg], **kwargs}, self.ctx)

    def test_persists_result_and_returns_ref(self):
        result = self._run(_dual_raw())
        self.assertEqual(result["status"], "complete")
        ref = result["result_ref"]
        self.assertTrue(ref["uri"].startswith("route-results/"))
        self.assertTrue(ref["uri"].endswith(".json"))
        persisted = (self.tmp / ref["uri"]).resolve()
        self.assertTrue(persisted.is_file())
        self.assertEqual(raw_file_digest(persisted), ref["digest"])
        document = json.loads(persisted.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["results"], result["results"])

    def test_no_ctx_no_persistence(self):
        # Backward compatibility: direct function calls without ctx keep the
        # inline-only contract and touch no files.
        with mock.patch.object(plan_route, "RouteEngine",
                               lambda *a, **k: _StubEngine(_dual_raw())):
            result = plan_route.plan_route({"legs": [self.leg]})
        self.assertEqual(result["status"], "complete")
        self.assertNotIn("result_ref", result)
        self.assertFalse((self.tmp / "route-results").exists())


class IncrementalMergeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "route-results").mkdir()
        self.ctx = {"allowed_root": self.tmp}
        self.base = load("route-result.json")
        base_bytes = json.dumps(self.base, ensure_ascii=False, indent=2)
        self.base_path = self.tmp / "route-results" / "plan-base.json"
        self.base_path.write_text(base_bytes, encoding="utf-8")
        self.base_ref = {"uri": "route-results/plan-base.json",
                         "digest": raw_file_digest(self.base_path)}
        self.changed_leg = {
            "leg_id": "leg-01",
            "origin": {"lon": 120.150018, "lat": 30.266874},
            "destination": {"lon": 119.748121, "lat": 30.257323},
            "via_points": [{"lon": 120.077143, "lat": 30.305034}],
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _run_merge(self, outcome):
        with mock.patch.object(plan_route, "RouteEngine",
                               lambda *a, **k: _StubEngine(outcome)):
            return plan_route.plan_route(
                {"legs": [self.changed_leg],
                 "base_result_ref": self.base_ref},
                self.ctx)

    def test_merge_reroutes_only_changed_leg(self):
        result = self._run_merge(_revised_leg01_raw())
        self.assertEqual(result["status"], "complete", result)
        merged = {r["leg_id"]: r for r in result["results"]}
        revised = {r["leg_id"]: r for r in load("route-result-revised.json")["results"]}
        self.assertEqual(set(merged), set(revised))
        self.assertEqual(merged["leg-01"], revised["leg-01"])
        for leg_id in ("leg-02", "leg-04", "leg-05", "leg-06"):
            # unchanged legs carried verbatim from the persisted base
            self.assertEqual(merged[leg_id], revised[leg_id])
        # the merged result is itself persisted and referenced
        ref = result["result_ref"]
        self.assertTrue((self.tmp / ref["uri"]).is_file())
        self.assertEqual(raw_file_digest(self.tmp / ref["uri"]), ref["digest"])

    def test_base_ref_digest_tamper_refused(self):
        self.base_path.write_text(
            self.base_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        result = self._run_merge(_revised_leg01_raw())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ROUTE_RESULT_DIGEST_MISMATCH")

    def test_base_ref_missing_file_refused(self):
        ref = dict(self.base_ref, uri="route-results/does-not-exist.json")
        with mock.patch.object(plan_route, "RouteEngine",
                               lambda *a, **k: _StubEngine(_dual_raw())):
            result = plan_route.plan_route(
                {"legs": [self.changed_leg], "base_result_ref": ref}, self.ctx)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_NOT_FOUND")

    def test_base_ref_outside_root_refused(self):
        ref = dict(self.base_ref, uri="C:/Windows/plan-base.json")
        with mock.patch.object(plan_route, "RouteEngine",
                               lambda *a, **k: _StubEngine(_dual_raw())):
            result = plan_route.plan_route(
                {"legs": [self.changed_leg], "base_result_ref": ref}, self.ctx)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_OUTSIDE_ROOT")


class AssembleReferenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "data").mkdir()
        shutil.copy(FIXTURES / "draft.json", self.tmp / "data" / "itinerary-draft.json")
        (self.tmp / "route-results").mkdir()
        self.route_path = self.tmp / "route-results" / "plan-golden.json"
        self.route_path.write_text(
            (FIXTURES / "route-result.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        self.ref = {"uri": "route-results/plan-golden.json",
                    "digest": raw_file_digest(self.route_path)}
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def _assemble(self, **overrides):
        args = {
            "draft_path": "data/itinerary-draft.json",
            "geocode_result": load("geocode-result.json"),
            "route_result_ref": self.ref,
        }
        args.update(overrides)
        return itinerary_assemble(args, self.ctx)

    def test_reference_assembly_matches_e2e_golden_bytes(self):
        result = self._assemble()
        self.assertEqual(result["status"], "assembled", result)
        expected = (FIXTURES / "expected-itinerary.json").read_bytes()
        actual = (self.tmp / "data" / "itinerary.json").read_bytes()
        self.assertEqual(actual, expected,
                         "referenced assembly must match the inline golden "
                         "byte-for-byte (protocol equivalence)")

    def test_reference_digest_tamper_refused(self):
        self.route_path.write_text(
            self.route_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        result = self._assemble()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "ROUTE_RESULT_DIGEST_MISMATCH")
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_inline_and_ref_conflict_refused(self):
        result = self._assemble(route_result=load("route-result.json"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "INPUT_CONFLICT")
        self.assertFalse((self.tmp / "data" / "itinerary.json").exists())

    def test_ref_outside_root_refused(self):
        result = self._assemble(
            route_result_ref={"uri": "C:/Windows/plan-golden.json",
                              "digest": self.ref["digest"]})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_OUTSIDE_ROOT")


if __name__ == "__main__":
    unittest.main()
