"""General library bootstrap publication: 8 presets publish idempotently and fetch back."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.repository.general_library import publish_general_library
from carto_core.repository.template_repository import TemplateRepository
from carto_core.security.paths import PathGuard


class GeneralLibraryPublicationTests(unittest.TestCase):
    def test_publish_eight_presets_idempotent_and_fetchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            refs = publish_general_library(root)
            self.assertEqual(len(refs), 8)
            kinds = {r["kind"] for r in refs}
            self.assertEqual(kinds, {"map-layout", "map-style"})
            self.assertEqual(sum(r["kind"] == "map-layout" for r in refs), 4)
            self.assertEqual(sum(r["kind"] == "map-style" for r in refs), 4)
            # re-publish is idempotent (same idempotency keys -> same receipts, no dup)
            refs2 = publish_general_library(root)
            self.assertEqual(refs, refs2)
            guard = PathGuard([root])
            repo = TemplateRepository(path_guard=guard, root=root,
                                      repository_scope="local:templates")
            self.assertEqual(len(repo._load_index()["entries"]), 8)
            for r in refs:
                self.assertIsNotNone(repo.fetch_segment(r, namespace="local"))


if __name__ == "__main__":
    unittest.main()