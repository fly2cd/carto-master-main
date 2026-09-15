from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry, load_document
from tests.fixtures.schema_cases import INVALID_CASES, VALID_CASES


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def test_every_schema_is_structurally_valid(self) -> None:
        checked = self.registry.check_all()
        self.assertEqual(set(self.registry.schemas), set(checked))

    def test_every_instance_schema_has_valid_and_invalid_fixture(self) -> None:
        expected = set(self.registry.schemas) - {"common"}
        self.assertEqual(expected, set(VALID_CASES))
        self.assertEqual(expected, set(INVALID_CASES))
        for name in sorted(expected):
            with self.subTest(schema=name, fixture="valid"):
                self.registry.validate(name, VALID_CASES[name])
            with self.subTest(schema=name, fixture="invalid"):
                with self.assertRaises(ProtocolError):
                    self.registry.validate(name, INVALID_CASES[name])

    def test_candidate_and_lock_share_identical_execution_contract(self) -> None:
        candidate = VALID_CASES["resolved-map"]
        lock = VALID_CASES["map-spec-lock"]
        self.assertEqual(candidate["execution"], lock["execution"])
        self.assertEqual(candidate["execution_digest"], sha256_digest(candidate["execution"]))
        self.assertEqual(lock["execution_digest"], sha256_digest(lock["execution"]))
        changed = deepcopy(candidate["execution"])
        changed["shared_semantics"]["data_nature"] = "observed"
        self.assertNotEqual(lock["execution_digest"], sha256_digest(changed))

    def test_versioned_intent_profile_policy_matches_schema(self) -> None:
        policy = self.registry.schema_root.parent / "policies" / "intent-profiles.yaml"
        self.registry.validate("intent-profiles", load_document(policy))


if __name__ == "__main__":
    unittest.main()
