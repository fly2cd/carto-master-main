from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.compiler.dependencies import DependencyResolver
from carto_core.compiler.ownership import OwnershipResolver
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry, load_document
from tests.fixtures.schema_cases import A, D, INVALID_CASES, SEMANTIC_INVALID_CASES, VALID_CASES


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()
        cls.policies_root = cls.registry.schema_root.parent / "policies"

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

    def test_semantic_invalid_fixtures_are_rejected(self) -> None:
        for fixture_name, (schema_name, instance) in SEMANTIC_INVALID_CASES.items():
            with self.subTest(fixture=fixture_name, schema=schema_name):
                with self.assertRaises(ProtocolError):
                    self.registry.validate(schema_name, instance)

    def test_final_check_report_requires_complete_frozen_evidence(self) -> None:
        report = deepcopy(VALID_CASES["validation-report"])
        report.update({
            "report_id": "final-check-one",
            "phase": "final-check",
            "subject_ref": A,
            "checker_set_digest": D,
            "checked_artifacts": [
                {"target": "pdf", "artifact_ref": A, "size_bytes": 1024, "media_type": "application/pdf"},
                {"target": "png", "artifact_ref": A, "size_bytes": 2048, "media_type": "image/png"},
            ],
            "counts": {
                "blocker": 1, "error": 0, "warning": 1, "info": 0,
                "failed_blocker": 0, "failed_error": 0, "failed_warning": 0,
            },
            "results": [
                {"check_id": "final.artifact-integrity", "version": "1.0.0", "status": "passed", "severity": "blocker", "details": {}},
                {"check_id": "final.renderer-warnings", "version": "1.0.0", "status": "passed", "severity": "warning", "disposition": "accepted", "details": {}},
            ],
        })
        self.registry.validate("validation-report", report)
        for field in ("subject_ref", "checker_set_digest", "checked_artifacts", "counts"):
            with self.subTest(missing=field):
                invalid = deepcopy(report)
                invalid.pop(field)
                with self.assertRaises(ProtocolError):
                    self.registry.validate("validation-report", invalid)
        warning_without_disposition = deepcopy(report)
        warning_without_disposition["results"][1].pop("disposition")
        with self.assertRaises(ProtocolError):
            self.registry.validate("validation-report", warning_without_disposition)
        unknown = deepcopy(report)
        unknown["unexpected"] = True
        with self.assertRaises(ProtocolError):
            self.registry.validate("validation-report", unknown)

    def test_delivery_manifest_requires_tenant_and_licenses(self) -> None:
        manifest = VALID_CASES["delivery-manifest"]
        self.registry.validate("delivery-manifest", manifest)
        for field in ("tenant_id", "licenses"):
            with self.subTest(missing=field):
                invalid = deepcopy(manifest)
                invalid.pop(field)
                with self.assertRaises(ProtocolError):
                    self.registry.validate("delivery-manifest", invalid)
        unknown = deepcopy(manifest)
        unknown["unexpected"] = True
        with self.assertRaises(ProtocolError):
            self.registry.validate("delivery-manifest", unknown)
    def test_delivery_transaction_and_receipt_require_commit_bindings(self) -> None:
        transaction = VALID_CASES["delivery-transaction"]
        receipt = VALID_CASES["delivery-receipt"]
        self.registry.validate("delivery-transaction", transaction)
        self.registry.validate("delivery-receipt", receipt)
        for schema_name, fixture, fields in (
            ("delivery-transaction", transaction, ("manifest_ref", "approval_ref", "final_path")),
            ("delivery-receipt", receipt, ("manifest_ref", "g3_approval_ref", "final_path", "artifacts")),
        ):
            for field in fields:
                with self.subTest(schema=schema_name, missing=field):
                    invalid = deepcopy(fixture)
                    invalid.pop(field)
                    with self.assertRaises(ProtocolError):
                        self.registry.validate(schema_name, invalid)
            with self.subTest(schema=schema_name, unknown="unexpected"):
                invalid = deepcopy(fixture)
                invalid["unexpected"] = True
                with self.assertRaises(ProtocolError):
                    self.registry.validate(schema_name, invalid)
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
        policy = self.policies_root / "intent-profiles.yaml"
        self.registry.validate("intent-profiles", load_document(policy))

    def test_map_expression_catalog_contains_only_the_up2_slice(self) -> None:
        catalog = load_document(self.policies_root / "map-expression-catalog.yaml")
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["version"], "1.0.0")
        entries = catalog["entries"]
        self.assertEqual(
            {(entry["expression_id"], entry["version"]) for entry in entries},
            {("choropleth/sequential", "1.0.0"), ("proportional-symbol/count", "1.0.0")},
        )
        for entry in entries:
            self.registry.validate("map-expression", entry)

        template_ref = deepcopy(VALID_CASES["publication-receipt"]["package_ref"])
        template_ref["kind"] = "map-expression"
        invalid_receipt = deepcopy(VALID_CASES["publication-receipt"])
        invalid_receipt["package_ref"] = template_ref
        with self.assertRaises(ProtocolError):
            self.registry.validate("publication-receipt", invalid_receipt)

    def test_map_expression_catalog_is_declarative_only(self) -> None:
        executable = deepcopy(VALID_CASES["map-expression"])
        executable["visual_variables"][0]["algorithm_id"] = "javascript-eval"
        with self.assertRaises(ProtocolError):
            self.registry.validate("map-expression", executable)
        executable = deepcopy(VALID_CASES["map-expression"])
        executable["parameter_definitions"][0]["command"] = "python task.py"
        with self.assertRaises(ProtocolError):
            self.registry.validate("map-expression", executable)

    def test_manifest_declares_six_contracts_and_closes_file_sets(self) -> None:
        resolver = DependencyResolver()
        manifest = VALID_CASES["manifest"]
        resolver.validate_manifest(manifest, manifest["files"])
        self.assertEqual(manifest["business_contracts"], resolver.MAP_SCENARIO_CONTRACTS)
        self.assertEqual(len(manifest["business_contracts"]), 6)

        missing_checksum = deepcopy(manifest)
        missing_checksum["checksums"].pop("contracts/delivery.yaml")
        with self.assertRaises(ProtocolError) as raised:
            resolver.validate_manifest(missing_checksum)
        self.assertEqual(raised.exception.code, "MANIFEST_CHECKSUM_MISMATCH")

        hidden_file = [*manifest["files"], "assets/undeclared.svg"]
        with self.assertRaises(ProtocolError) as raised:
            resolver.validate_manifest(manifest, hidden_file)
        self.assertEqual(raised.exception.code, "MANIFEST_FILE_SET_MISMATCH")

        missing_contract = deepcopy(manifest)
        missing_contract["business_contracts"].pop("delivery")
        with self.assertRaises(ProtocolError) as raised:
            resolver.validate_manifest(missing_contract)
        self.assertEqual(raised.exception.code, "MANIFEST_BUSINESS_CONTRACTS_INVALID")

    def test_dependency_lock_requires_exact_versions_and_unique_identities(self) -> None:
        resolver = DependencyResolver()
        resolver.validate_lock(VALID_CASES["dependency-lock"])

        floating = deepcopy(VALID_CASES["dependency-lock"])
        floating["resources"][0]["version"] = "latest"
        with self.assertRaises(ProtocolError) as raised:
            resolver.validate_lock(floating)
        self.assertEqual(raised.exception.code, "DEPENDENCY_VERSION_NOT_EXACT")

        duplicate = deepcopy(VALID_CASES["dependency-lock"])
        duplicate["resources"].append(deepcopy(duplicate["resources"][0]))
        with self.assertRaises(ProtocolError) as raised:
            resolver.validate_lock(duplicate)
        self.assertEqual(raised.exception.code, "DEPENDENCY_DUPLICATE")

    def test_scenario_ownership_replaces_whole_segments(self) -> None:
        resolver = OwnershipResolver()
        scenario = VALID_CASES["scenario"]
        replacement = {
            "kind": "map-style",
            "segment": "cartography",
            "value": {"style_id": "replacement-only"},
            "compatibility": {
                "scenario_ids": ["urban-flood-risk"],
                "target_profiles": ["a3-landscape"],
                "data_roles": ["risk-area"],
                "placeholders": ["{{MAP_FRAME}}"],
            },
        }
        result = resolver.compose_scenario(scenario, [replacement])
        self.assertEqual(result["segments"]["cartography"], {"style_id": "replacement-only"})
        self.assertNotIn("symbolization", result["segments"]["cartography"])
        self.assertEqual(result["ownership"]["cartography"], "map-style")
        self.assertEqual(result["ownership"]["identity"], "map-scenario")

    def test_scenario_ownership_rejects_duplicate_kind_and_boundary_violation(self) -> None:
        resolver = OwnershipResolver()
        scenario = VALID_CASES["scenario"]
        replacement = {"kind": "map-style", "segment": "cartography", "value": {"style_id": "one"}}
        with self.assertRaises(ProtocolError) as raised:
            resolver.compose_scenario(scenario, [replacement, deepcopy(replacement)])
        self.assertEqual(raised.exception.code, "TEMPLATE_KIND_DUPLICATE")

        wrong_segment = {"kind": "map-style", "segment": "layout", "value": {"layout_id": "wrong"}}
        with self.assertRaises(ProtocolError) as raised:
            resolver.compose_scenario(scenario, [wrong_segment])
        self.assertEqual(raised.exception.code, "KIND_BOUNDARY_VIOLATION")

    def test_scenario_ownership_rejects_non_replaceable_and_incompatible_templates(self) -> None:
        resolver = OwnershipResolver()
        locked_scenario = deepcopy(VALID_CASES["scenario"])
        locked_scenario["replaceable_segments"].remove("layout")
        layout = {"kind": "map-layout", "segment": "layout", "value": {"layout_id": "external"}}
        with self.assertRaises(ProtocolError) as raised:
            resolver.compose_scenario(locked_scenario, [layout])
        self.assertEqual(raised.exception.code, "SEGMENT_NOT_REPLACEABLE")

        incompatible = {
            "kind": "map-style",
            "segment": "cartography",
            "value": {"style_id": "external"},
            "compatibility": {"data_roles": ["population-density"]},
        }
        with self.assertRaises(ProtocolError) as raised:
            resolver.compose_scenario(VALID_CASES["scenario"], [incompatible])
        self.assertEqual(raised.exception.code, "TEMPLATE_INCOMPATIBLE")


if __name__ == "__main__":
    unittest.main()
