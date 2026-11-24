"""Guard tests for the migrated 2026Oct segment assets (template-assets/).

Every adapted contract must stay valid under the main schemas, every asset must
carry its untouched original plus a migration record whose source digest still
matches the original bytes. Runtime consumption of these assets goes through the
repository publish/fetch path only; this guard never reads them as protocols.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.schema_registry import SchemaRegistry, load_document

ASSETS_ROOT = SCRIPTS_ROOT.parent / "template-assets"
CONTRACTS = {"map-style": ("cartography.yaml", "style"),
             "map-layout": ("layout.yaml", "layout")}


class MigratedAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()
        cls.record = load_document(ASSETS_ROOT / "MIGRATION.yaml")
        cls.assets = {(item["kind"], item["id"], item["version"]): item
                      for item in cls.record["assets"]}

    def test_migration_record_covers_exactly_the_asset_directories(self) -> None:
        found = set()
        for kind in CONTRACTS:
            for version_dir in (ASSETS_ROOT / kind).glob("*/*"):
                found.add((kind, version_dir.parent.name, version_dir.name))
        self.assertEqual(found, set(self.assets))
        self.assertTrue(found, "No template assets found; integrity checks would be vacuous")

    def test_every_adapted_contract_validates_under_main_schemas(self) -> None:
        for (kind, template_id, version) in sorted(self.assets):
            filename, schema = CONTRACTS[kind]
            with self.subTest(asset=f"{kind}/{template_id}@{version}"):
                contract = load_document(ASSETS_ROOT / kind / template_id / version / filename)
                self.registry.validate(schema, contract)

    def test_originals_are_preserved_and_match_recorded_source_digests(self) -> None:
        for (kind, template_id, version), item in sorted(self.assets.items()):
            with self.subTest(asset=f"{kind}/{template_id}@{version}"):
                original = (ASSETS_ROOT / kind / template_id / version / "original.yaml").read_bytes()
                digest = "sha256:" + hashlib.sha256(original).hexdigest()
                self.assertEqual(digest, item["source_digest"])
                self.assertTrue(item["adaptations"])


if __name__ == "__main__":
    unittest.main()