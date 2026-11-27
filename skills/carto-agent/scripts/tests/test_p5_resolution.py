"""P5-1/2 acceptance: trusted business context + typed Style fact adaptation (fix B08).

A14: Style retrieval evaluates against Style's own facts and the correct capability
context, not a hardcoded general-thematic / 300dpi Layout path. No context -> clarify,
never a general default.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.design_requirements import (
    evaluate_predicate, style_fact_view,
)
from carto_core.repository.general_style_presets import general_style
from carto_core.schema_registry import SchemaRegistry


class StyleFactAdaptationTests(unittest.TestCase):
    """P5-2: Style predicates read Style's own facts (not LayoutResolver)."""

    def setUp(self):
        self.fact = style_fact_view(general_style("statistical"))

    def test_style_fact_view_reads_own_facts(self):
        self.assertEqual(self.fact["visual_language"], "statistical")
        self.assertEqual(self.fact["color_system"], "sequential")
        self.assertEqual(self.fact["typography"]["title_pt"], 20)

    def test_style_enum_satisfied_and_violated(self):
        ok = evaluate_predicate({"kind": "style-enum", "path": "/symbolization/color_system",
                                 "op": "eq", "value": "sequential"}, self.fact)
        self.assertEqual(ok[0], "satisfied")
        bad = evaluate_predicate({"kind": "style-enum", "path": "/symbolization/color_system",
                                  "op": "eq", "value": "qualitative"}, self.fact)
        self.assertEqual(bad[0], "violated")

    def test_style_measure_pt(self):
        ok = evaluate_predicate({"kind": "style-measure", "path": "/typography/title_pt",
                                 "op": "gte", "value": 18, "unit": "pt"}, self.fact)
        self.assertEqual(ok[0], "satisfied")
        bad = evaluate_predicate({"kind": "style-measure", "path": "/typography/title_pt",
                                  "op": "gte", "value": 24, "unit": "pt"}, self.fact)
        self.assertEqual(bad[0], "violated")

    def test_missing_style_fact_unknown_not_satisfied(self):
        empty = style_fact_view({})
        res = evaluate_predicate({"kind": "style-enum", "path": "/visual_language",
                                  "op": "eq", "value": "technical"}, empty)
        self.assertEqual(res[0], "unknown")


class ContextSelectionTests(unittest.TestCase):
    """P5-1: resolve selects capability by context; no context -> not a general default."""

    def _setup_repo(self, root):
        from carto_core.artifacts import file_digest
        from carto_core.repository.template_repository import TemplateRepository
        from carto_core.security.paths import PathGuard
        from tests.fixtures.schema_cases import D, VALID_CASES
        guard = PathGuard([root])
        repo = TemplateRepository(path_guard=guard, root=root / "repo",
                                  repository_scope="local:templates")
        style = general_style("statistical")
        staging = root / "staging-style"
        (staging / "contracts").mkdir(parents=True)
        (staging / "contracts/cartography.yaml").write_text(json.dumps(style), encoding="utf-8")
        lock = deepcopy(VALID_CASES["dependency-lock"])
        lock["package"] = {"namespace": "local", "kind": "map-style", "id": "stat-style",
                           "version": "1.0.0", "digest": D}
        lock["dependencies"] = []
        (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
        files = ["dependencies.lock.yaml", "contracts/cartography.yaml"]
        manifest = {"schema_version": 1,
                    "package": {"namespace": "local", "kind": "map-style", "id": "stat-style",
                                "version": "1.0.0", "status": "published", "summary": "stat style"},
                    "dependency_lock": "dependencies.lock.yaml", "files": files,
                    "checksums": {rel: file_digest(staging / rel) for rel in files}}
        (staging / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
        md = file_digest(staging / "manifest.yaml")
        lines = [f"{manifest['checksums'][rel][7:]}  {rel}" for rel in files]
        lines.append(f"{md[7:]}  manifest.yaml")
        (staging / "checksums.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
        snapshot = {"package_digest": file_digest(staging / "checksums.sha256"),
                    "manifest_digest": md, "manifest": manifest,
                    "dependency_lock_digest": file_digest(staging / "dependencies.lock.yaml")}
        repo.publish(package_root=staging, snapshot=snapshot, evidence={"evidence_digest": D},
                     approval={"synthetic": "p5"}, idempotency_key="p5-style-00000001",
                     publication_object={"schema_version": 1, "run_id": "p5-run", "request_digest": D,
                                         "package_ref": {"kind": "map-style", "id": "stat-style",
                                                         "version": "1.0.0", "digest": snapshot["package_digest"]},
                                         "evidence_ref": {"id": "template-validation-evidence", "version": "1.0.0",
                                                          "digest": D, "uri": "evidence.yaml"},
                                         "repository_scope": "local:templates",
                                         "repository_root": (root / "repo").as_posix(),
                                         "idempotency_key": "p5-style-00000001"})
        return repo

    def _resolve(self, root, req):
        from carto_core.cli import match_cmd
        from types import SimpleNamespace
        req_path = root / "req.json"
        req_path.write_text(json.dumps(req), encoding="utf-8")
        args = SimpleNamespace(template_command="resolve", requirement=str(req_path),
                               repository_root=str(root / "repo"), repository_scope="local:templates",
                               allowed_root=[str(root)])
        return match_cmd.handle(args)["resolution"]

    def test_style_resolve_with_context_uses_style_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self._setup_repo(root)
            req = {"schema_version": 1, "requirement_id": "req-style", "revision": 1,
                   "object_scope": "style",
                   "context": {"business_scene": "general_thematic_mapping", "geometry": "raster"},
                   "conditions": [
                       {"id": "cs", "strength": "hard", "source_ref": "u",
                        "predicate": {"kind": "style-enum", "path": "/symbolization/color_system",
                                      "op": "eq", "value": "sequential"}}]}
            result = self._resolve(root, req)
            self.assertEqual(result["assessments"][0]["structural_aggregate"], "satisfied")
            self.assertEqual(result["assessments"][0]["execution_admission"], "allowed")
            self.assertIn(result["branch"], ("reuse", "instantiate"))

    def test_no_context_does_not_default_to_general(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self._setup_repo(root)
            req = {"schema_version": 1, "requirement_id": "req-noctx", "revision": 1,
                   "object_scope": "style",
                   "conditions": [
                       {"id": "cs", "strength": "hard", "source_ref": "u",
                        "predicate": {"kind": "style-enum", "path": "/symbolization/color_system",
                                      "op": "eq", "value": "sequential"}}]}
            result = self._resolve(root, req)
            # without context, admission is unknown -> not usable -> clarify (not reuse)
            self.assertNotIn(result["branch"], ("reuse", "instantiate"))
            self.assertEqual(result["assessments"][0]["execution_admission"], "unknown")


class GenerationConnectionTests(unittest.TestCase):
    """P5-5: explicit selection -> generate-request segment_refs; resolution as evidence."""

    def _sel(self, kind, sid):
        return {"kind": kind, "id": sid, "version": "1.0.0", "digest": "sha256:" + "0" * 64}

    def test_assemble_style_and_layout(self):
        from carto_core.compiler.generation_connection import assemble_segment_refs
        refs = assemble_segment_refs([self._sel("map-style", "s"), self._sel("map-layout", "l")])
        self.assertEqual(set(refs), {"style", "layout"})
        self.assertEqual(refs["layout"]["id"], "l")

    def test_duplicate_segment_refused(self):
        from carto_core.compiler.generation_connection import assemble_segment_refs
        from carto_core.errors import ProtocolError
        with self.assertRaises(ProtocolError) as r:
            assemble_segment_refs([self._sel("map-layout", "a"), self._sel("map-layout", "b")])
        self.assertEqual("SEGMENT_DOUBLE_SOURCED", r.exception.code)

    def test_unpinned_refused(self):
        from carto_core.compiler.generation_connection import assemble_segment_refs
        from carto_core.errors import ProtocolError
        bad = self._sel("map-style", "s")
        del bad["digest"]
        with self.assertRaises(ProtocolError):
            assemble_segment_refs([bad])

    def test_attach_evidence_within_retrieval(self):
        from carto_core.compiler.generation_connection import attach_resolution_evidence
        sel = self._sel("map-layout", "l")
        resolution = {"requirement_id": "req", "revision": 1, "branch": "reuse",
                      "assessments": [{"candidate_ref": sel, "usable": True}]}
        req = attach_resolution_evidence({"run_id": "r"}, resolution, [sel])
        self.assertEqual(req["segment_refs"]["layout"]["id"], "l")
        self.assertEqual(req["retrieval_evidence"]["branch"], "reuse")

    def test_selection_outside_retrieval_refused(self):
        from carto_core.compiler.generation_connection import attach_resolution_evidence
        from carto_core.errors import ProtocolError
        resolution = {"requirement_id": "req", "revision": 1, "branch": "reuse",
                      "assessments": [{"candidate_ref": self._sel("map-layout", "l"), "usable": True}]}
        with self.assertRaises(ProtocolError) as r:
            attach_resolution_evidence({}, resolution, [self._sel("map-layout", "other")])
        self.assertEqual("SELECTION_OUTSIDE_RETRIEVAL", r.exception.code)


class CompositionCheckTests(unittest.TestCase):
    """P5-3: joint style+layout compatibility with locatable conflicts."""

    def test_compatible_composition(self):
        from carto_core.compiler.composition_check import check_composition
        from carto_core.repository.general_layout_presets import general_single_map_layout
        from carto_core.repository.general_style_presets import general_style
        result = check_composition(general_style("technical"),
                                   general_single_map_layout("A4", "landscape"),
                                   {"renderer_id": "rasterio-matplotlib-page"})
        self.assertTrue(result["compatible"])
        self.assertEqual(result["conflicts"], [])

    def test_missing_legend_conflict_locatable(self):
        from carto_core.compiler.composition_check import check_composition
        from carto_core.repository.general_layout_presets import general_single_map_layout
        from carto_core.repository.general_style_presets import general_style
        layout = general_single_map_layout("A4", "landscape")
        layout["frames"] = [f for f in layout["frames"] if f["type"] != "legend"]
        result = check_composition(general_style("technical"), layout, {"renderer_id": "x"})
        self.assertFalse(result["compatible"])
        self.assertTrue(any(c["component"] == "layout" and "legend" in c["reason"]
                            for c in result["conflicts"]))

    def test_no_renderer_conflict(self):
        from carto_core.compiler.composition_check import check_composition
        from carto_core.repository.general_layout_presets import general_single_map_layout
        from carto_core.repository.general_style_presets import general_style
        result = check_composition(general_style("technical"),
                                   general_single_map_layout("A4", "landscape"), {})
        self.assertFalse(result["compatible"])
        self.assertTrue(any(c["component"] == "capability" for c in result["conflicts"]))


class SearchCompletenessTests(unittest.TestCase):
    """P5-4: resolve records search metadata; complete search flagged."""

    def test_resolve_records_search_metadata(self):
        from carto_core.cli import match_cmd
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ContextSelectionTests()._setup_repo(root)
            req = {"schema_version": 1, "requirement_id": "req-sm", "revision": 1,
                   "object_scope": "style",
                   "context": {"business_scene": "general_thematic_mapping", "geometry": "raster"},
                   "conditions": [{"id": "cs", "strength": "hard", "source_ref": "u",
                                   "predicate": {"kind": "style-enum", "path": "/symbolization/color_system",
                                                 "op": "eq", "value": "sequential"}}]}
            rp = root / "req.json"
            rp.write_text(json.dumps(req), encoding="utf-8")
            args = SimpleNamespace(template_command="resolve", requirement=str(rp),
                                   repository_root=str(root / "repo"), repository_scope="local:templates",
                                   allowed_root=[str(root)])
            result = match_cmd.handle(args)["resolution"]
            sm = result["search_metadata"]
            self.assertTrue(sm["search_complete"])
            self.assertFalse(sm["truncated"])
            self.assertEqual(sm["examined"], 1)
            self.assertEqual(sm["candidate_budget"], 50)


if __name__ == "__main__":
    unittest.main()