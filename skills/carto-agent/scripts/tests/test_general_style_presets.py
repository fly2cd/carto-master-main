"""General Style presets: schema-valid, publishable as reusable map-style segments,
and pair with general layouts via the shared appearance resolver."""
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
from carto_core.compiler.appearance import resolve_appearance
from carto_core.repository.general_layout_presets import general_single_map_layout
from carto_core.repository.general_style_presets import all_general_styles, general_style
from carto_core.repository.template_repository import TemplateRepository
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from tests.fixtures.schema_cases import D, VALID_CASES


class GeneralStylePresetTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.presets = all_general_styles()

    def test_four_presets_schema_valid(self):
        self.assertEqual(len(self.presets), 4)
        for sid, style in self.presets.items():
            with self.subTest(style=sid):
                self.registry.validate("style", style)

    def test_visual_language_and_color_system(self):
        self.assertEqual(self.presets["general-style-statistical"]["symbolization"]["color_system"], "sequential")
        self.assertEqual(self.presets["general-style-technical"]["symbolization"]["color_system"], "qualitative")
        self.assertEqual(self.presets["general-style-technical"]["visual_language"], "technical")
        self.assertEqual(self.presets["general-style-editorial"]["typography"]["title_pt"], 22)

    def test_publishable_as_reusable_map_style_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            guard = PathGuard([root])
            repo = TemplateRepository(path_guard=guard, root=root / "repo",
                                      repository_scope="local:templates", registry=self.registry)
            for i, (sid, style) in enumerate(self.presets.items()):
                staging = root / f"staging-{sid}"
                (staging / "contracts").mkdir(parents=True)
                (staging / "contracts/cartography.yaml").write_text(json.dumps(style), encoding="utf-8")
                lock = deepcopy(VALID_CASES["dependency-lock"])
                lock["package"] = {"namespace": "local", "kind": "map-style", "id": sid,
                                   "version": "1.0.0", "digest": D}
                lock["dependencies"] = []
                (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
                files = ["dependencies.lock.yaml", "contracts/cartography.yaml"]
                manifest = {"schema_version": 1,
                            "package": {"namespace": "local", "kind": "map-style", "id": sid,
                                        "version": "1.0.0", "status": "published",
                                        "summary": f"General {sid} style"},
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
                                   approval={"synthetic": "general-style"},
                                   idempotency_key=f"general-style-{i:04d}-publish",
                                   publication_object={"schema_version": 1, "run_id": "general-style-run",
                                                       "request_digest": D,
                                                       "package_ref": {"kind": "map-style", "id": sid,
                                                                       "version": "1.0.0",
                                                                       "digest": snapshot["package_digest"]},
                                                       "evidence_ref": {"id": "template-validation-evidence",
                                                                        "version": "1.0.0", "digest": D, "uri": "evidence.yaml"},
                                                       "repository_scope": "local:templates",
                                                       "repository_root": (root / "repo").as_posix(),
                                                       "idempotency_key": f"general-style-{i:04d}-publish"})
                ref = {"kind": "map-style", "id": sid, "version": "1.0.0",
                       "digest": pub["package_ref"]["digest"]}
                self.assertEqual(repo.fetch_segment(ref, namespace="local"), style)

    def test_pairs_with_general_layout_via_appearance_resolver(self):
        layout = general_single_map_layout("A4", "landscape")
        color_sources = [{"view_id": "main-view",
                          "ref": {"id": "color-source", "version": "1.0.0", "digest": "sha256:" + "0" * 64}}]
        for sid, style in self.presets.items():
            with self.subTest(style=sid):
                appearance = resolve_appearance(style, layout, color_sources, self.registry)
                self.assertEqual(appearance["style"], style)
                self.assertEqual(appearance["typography"]["title_pt"], style["typography"]["title_pt"])
                self.assertEqual(appearance["typography"]["padding_mm"], layout["content_padding_mm"])


if __name__ == "__main__":
    unittest.main()