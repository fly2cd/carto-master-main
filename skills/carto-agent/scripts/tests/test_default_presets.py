"""Default preset mechanism: explicit preset + confirmed expansion + explicit-wins."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.default_presets import (
    expand_default_request, propose_default,
)
from carto_core.errors import ProtocolError


def _req(geometry="raster", scene="general_thematic_mapping", template=None):
    req = {"schema_version": 1, "request_id": "r", "project_id": "p", "goal": "制作一张专题图",
           "geometry": geometry, "sources": [], "requested_outputs": ["pdf"],
           "subject": {"subject_id": "u", "tenant_id": "t", "namespace": "p"},
           "idempotency_key": "default-preset-00000001",
           "intent": {"business_scene": scene, "theme_tags": ["land-cover"], "tasks": ["thematic-map"]}}
    if template:
        req["template"] = template
    return req


class DefaultPresetTests(unittest.TestCase):
    def test_propose_default_registered(self):
        preset = propose_default("general_thematic_mapping", "raster")
        self.assertIsNotNone(preset)
        self.assertEqual(preset["template"]["id"], "general-thematic-map")
        self.assertEqual(preset["template"]["version"], "3.0.0")
        self.assertIsNone(propose_default("no_such_scene", "raster"))

    def test_expansion_requires_confirmation(self):
        with self.assertRaises(ProtocolError) as r:
            expand_default_request(_req(), confirmed=False)
        self.assertEqual("DEFAULT_EXPANSION_UNCONFIRMED", r.exception.code)

    def test_confirmed_expansion_sets_template_and_provenance(self):
        expanded = expand_default_request(_req(), confirmed=True)
        self.assertEqual(expanded["template"]["id"], "general-thematic-map")
        self.assertTrue(expanded["default_provenance"]["expanded"])
        self.assertEqual(expanded["default_provenance"]["geometry"], "raster")

    def test_explicit_template_wins_no_default(self):
        explicit = {"namespace": "local", "kind": "map-scenario", "id": "my-own", "version": "9.9.9"}
        expanded = expand_default_request(_req(template=explicit), confirmed=True)
        self.assertEqual(expanded["template"]["id"], "my-own")
        self.assertNotIn("default_provenance", expanded)

    def test_unknown_context_confirmed_refused(self):
        with self.assertRaises(ProtocolError) as r:
            expand_default_request(_req(scene="no_such_scene"), confirmed=True)
        self.assertEqual("DEFAULT_PRESET_UNKNOWN", r.exception.code)

    def test_expansion_does_not_mutate_input(self):
        req = _req()
        expand_default_request(req, confirmed=True)
        self.assertNotIn("template", req)  # new request produced, input untouched


if __name__ == "__main__":
    unittest.main()