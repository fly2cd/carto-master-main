"""General single-main-map layout presets: schema-valid, publishable as reusable
map-layout segments, and resolvable by the shared LayoutResolver (A3/A4 x orient)."""
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

from carto_core.artifacts import file_digest
from carto_core.compiler.layout import LayoutResolver
from carto_core.repository.general_layout_presets import (
    all_general_layouts, general_single_map_layout,
)
from carto_core.repository.template_repository import TemplateRepository
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from tests.fixtures.schema_cases import D, VALID_CASES


class GeneralLayoutPresetTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.presets = all_general_layouts()

    def test_four_presets_schema_valid(self):
        self.assertEqual(len(self.presets), 4)
        for lid, layout in self.presets.items():
            with self.subTest(layout=lid):
                self.registry.validate("layout", layout)

    def test_paper_sizes_and_orientation(self):
        a4l = self.presets["general-single-map-a4-landscape"]
        a4p = self.presets["general-single-map-a4-portrait"]
        a3l = self.presets["general-single-map-a3-landscape"]
        self.assertEqual((a4l["canvas"]["width"], a4l["canvas"]["height"]), (297, 210))
        self.assertEqual((a4p["canvas"]["width"], a4p["canvas"]["height"]), (210, 297))
        self.assertEqual((a3l["canvas"]["width"], a3l["canvas"]["height"]), (420, 297))
        self.assertEqual(a4p["canvas"]["orientation"], "portrait")

    def test_single_map_frame_and_furniture_present(self):
        for lid, layout in self.presets.items():
            with self.subTest(layout=lid):
                types = [f["type"] for f in layout["frames"]]
                self.assertEqual(types.count("map"), 1)  # single main map
                for needed in ("title", "legend", "scale-bar", "north-arrow", "marginalia"):
                    self.assertIn(needed, types)

    def test_frames_inside_safe_margin(self):
        for lid, layout in self.presets.items():
            c = layout["canvas"]
            m = c["safe_margin"]
            for f in layout["frames"]:
                x, y, w, h = f["bounds"]
                with self.subTest(layout=lid, frame=f["id"]):
                    self.assertGreaterEqual(x, m - 1e-9)
                    self.assertGreaterEqual(y, m - 1e-9)
                    self.assertLessEqual(x + w, c["width"] - m + 1e-9)
                    self.assertLessEqual(y + h, c["height"] - m + 1e-9)

    def test_resolvable_by_shared_layout_resolver(self):
        resolver = LayoutResolver(self.registry)
        for lid, layout in self.presets.items():
            with self.subTest(layout=lid):
                resolved = resolver.resolve(layout, 300)
                frame = LayoutResolver.map_frame(resolved)
                self.assertEqual(frame["type"], "map")
                self.assertEqual(resolved["page"]["width_mm"], layout["canvas"]["width"])

    def test_publishable_as_reusable_map_layout_segment(self):
        """Each preset publishes through the real repository publish path as a
        map-layout segment, then fetches back byte-identical (reusable library item)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            guard = PathGuard([root])
            repo = TemplateRepository(path_guard=guard, root=root / "repo",
                                      repository_scope="local:templates", registry=self.registry)
            for i, (lid, layout) in enumerate(self.presets.items()):
                staging = root / f"staging-{lid}"
                (staging / "contracts").mkdir(parents=True)
                (staging / "contracts/layout.yaml").write_text(json.dumps(layout), encoding="utf-8")
                lock = deepcopy(VALID_CASES["dependency-lock"])
                lock["package"] = {"namespace": "local", "kind": "map-layout", "id": lid,
                                   "version": "1.0.0", "digest": D}
                lock["dependencies"] = []
                (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
                files = ["dependencies.lock.yaml", "contracts/layout.yaml"]
                manifest = {"schema_version": 1,
                            "package": {"namespace": "local", "kind": "map-layout", "id": lid,
                                        "version": "1.0.0", "status": "published",
                                        "summary": f"General {lid} layout"},
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
                pub = repo.publish(package_root=staging, snapshot=snapshot,
                                   evidence={"evidence_digest": D},
                                   approval={"synthetic": "general-layout"},
                                   idempotency_key=f"general-layout-{i:04d}-publish",
                                   publication_object={"schema_version": 1, "run_id": "general-layout-run",
                                                       "request_digest": D,
                                                       "package_ref": {"kind": "map-layout", "id": lid,
                                                                       "version": "1.0.0",
                                                                       "digest": snapshot["package_digest"]},
                                                       "evidence_ref": {"id": "template-validation-evidence",
                                                                        "version": "1.0.0", "digest": D, "uri": "evidence.yaml"},
                                                       "repository_scope": "local:templates",
                                                       "repository_root": (root / "repo").as_posix(),
                                                       "idempotency_key": f"general-layout-{i:04d}-publish"})
                ref = {"kind": "map-layout", "id": lid, "version": "1.0.0",
                       "digest": pub["package_ref"]["digest"]}
                fetched = repo.fetch_segment(ref, namespace="local")
                self.assertEqual(fetched, layout)


if __name__ == "__main__":
    unittest.main()