"""plan_route fallback-contract tests.

The three-tier fallback must honour allow_straight_line end-to-end: no
straight-line engine result may survive as status=complete unless the flag
explicitly allows it, and named Plan-B failures (missing key, refused
request) must surface verbatim instead of silently degrading the route.
Reproduces the 2026-11-21 incident: a shell without CARTO_AMAP_KEY let a
2-point 0 km "straight_line" result reach data/itinerary.json as complete.
"""
import asyncio
import unittest
from unittest import mock

import plan_route
from routing.route_engine import RouteEngine
from routing.router_amap import AmapRoutingError

LEGS = [{"leg_id": "leg-01",
         "origin": {"lon": 120.15, "lat": 30.26},
         "destination": {"lon": 119.74, "lat": 30.25}}]


def _straight_result():
    return {"polyline": [[120.15, 30.26], [119.74, 30.25]],
            "distance": 0, "duration": 0, "engine": "straight_line"}


def _dual_result():
    return {"polyline": [[120.15, 30.26], [120.0, 30.2], [119.74, 30.25]],
            "distance": 42500, "duration": 3400, "engine": "dual_graph"}


class _StubEngine:
    def __init__(self, outcome):
        self._outcome = outcome

    async def reroute_leg(self, origin, destination, via_points=None, strategy="2"):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _run(outcome, **kwargs):
    with mock.patch.object(plan_route, "RouteEngine",
                           lambda *a, **k: _StubEngine(outcome)):
        return plan_route.plan_route({"legs": LEGS, **kwargs})


class PlanRouteFallbackContractTests(unittest.TestCase):
    def test_engine_straight_line_rejected_when_not_allowed(self):
        result = _run(_straight_result())  # allow_straight_line defaults to False
        leg = result["results"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(leg["status"], "failed")
        self.assertIn("straight_line", leg["message"])
        self.assertIn("allow_straight_line", leg["message"])

    def test_engine_straight_line_allowed_when_flag_true(self):
        result = _run(_straight_result(), allow_straight_line=True)
        leg = result["results"][0]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(leg["status"], "complete")
        self.assertEqual(leg["engine"], "straight_line")
        self.assertTrue(leg["degraded"])

    def test_amap_error_surfaces_named_code(self):
        result = _run(AmapRoutingError(
            "AMAP_KEY_MISSING", "CARTO_AMAP_KEY is not set"))
        leg = result["results"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(leg["status"], "failed")
        self.assertIn("AMAP_KEY_MISSING", leg["message"])

    def test_dual_graph_result_passes(self):
        result = _run(_dual_result())
        leg = result["results"][0]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(leg["engine"], "dual_graph")
        self.assertNotIn("degraded", leg)

    def test_empty_polyline_rejected_when_not_allowed(self):
        result = _run({"polyline": [], "distance": 0, "duration": 0,
                       "engine": "unknown"})
        leg = result["results"][0]
        self.assertEqual(leg["status"], "failed")


class _FailingDualGraph:
    def route_leg(self, origin, destination, via_points=None):
        raise RuntimeError("graph disconnected near via segment")


class _RaisingPlanB:
    async def reroute_leg_with_resolve(self, client, origin, destination,
                                       via_points=None, strategy="2",
                                       geocoder=None):
        raise AmapRoutingError("AMAP_REQUEST_FAILED", "status=0 infocode=10001")


class RouteEngineRootCauseChainTests(unittest.TestCase):
    def test_plan_b_error_carries_dual_graph_failure_context(self):
        engine = RouteEngine(enable_dual_graph=True, allow_online=True)
        engine._get_dual_graph_engine = lambda clip_bbox=None: _FailingDualGraph()
        engine._get_plan_b_router = lambda: _RaisingPlanB()
        engine._get_geocoder = lambda: object()
        with self.assertRaises(AmapRoutingError) as ctx:
            asyncio.run(engine.reroute_leg(
                origin={"lon": 120.15, "lat": 30.26},
                destination={"lon": 119.74, "lat": 30.25}))
        self.assertEqual(ctx.exception.code, "AMAP_REQUEST_FAILED")
        self.assertIn("status=0 infocode=10001", ctx.exception.message)
        self.assertIn("dual_graph failed", ctx.exception.message)
        self.assertIn("graph disconnected", ctx.exception.message)

    def test_offline_mode_straight_line_is_marked_degraded(self):
        engine = RouteEngine(enable_dual_graph=False, allow_online=False)
        result = asyncio.run(engine.reroute_leg(
            origin={"lon": 120.15, "lat": 30.26},
            destination={"lon": 119.74, "lat": 30.25}))
        self.assertEqual(result["engine"], "straight_line")
        self.assertTrue(result["degraded"])


if __name__ == "__main__":
    unittest.main()
