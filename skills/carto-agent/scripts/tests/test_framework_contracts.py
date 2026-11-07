from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError
from carto_core.repository.delivery_repository import DeliveryRepository
from carto_core.repository.staging_package import StagingPackageWriter
from carto_core.scenario_registry import ScenarioCapability
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.map_final_check import FinalMapCheckService
from carto_core.workflow.template_validation import TemplatePackageValidator
from tests.fixtures.schema_cases import VALID_CASES


class FrameworkContractTests(unittest.TestCase):
    """Isolated framework assertions, not an executable business scenario."""

    def test_expression_metadata_does_not_fabricate_fixture_evidence(self):
        value = deepcopy(VALID_CASES["map-expression"])
        value.pop("fixture_refs")
        registry = SchemaRegistry()
        registry.validate("map-expression", value)
        value["fixture_refs"] = []
        with self.assertRaises(ProtocolError):
            registry.validate("map-expression", value)

    def test_delivery_readme_uses_only_manifest_disclosures(self):
        manifest = {"licenses": ["license-from-manifest"],
                    "limitations": ["limitation-from-manifest"],
                    "recipient": {"recipient_type": "internal", "recipient_id": "unit-recipient"}}
        text = DeliveryRepository._readme(manifest)
        self.assertIn("license-from-manifest", text)
        self.assertIn("limitation-from-manifest", text)
        self.assertTrue(text.rstrip().endswith("- limitation-from-manifest"))

    def test_notice_requires_matching_scene_evidence_receipt_and_artifact(self):
        checker = object.__new__(FinalMapCheckService)
        checker._artifact_path = Mock(return_value=Path("unit-artifact"))
        scene = {"overlays": [{"content": "Required restriction", "coordinate_space": "page"}]}
        context = {"scenario_profile": SimpleNamespace(notice="Required restriction"),
                   "scene": scene, "evidence": {"scenario_notice": "Required restriction"},
                   "receipt": {"scene_digest": sha256_digest(scene)}, "artifacts": [{}]}
        self.assertTrue(checker._scenario_notice(context)[0])
        context["evidence"]["scenario_notice"] = "Wrong restriction"
        self.assertFalse(checker._scenario_notice(context)[0])
        context["evidence"]["scenario_notice"] = "Required restriction"
        context["receipt"]["scene_digest"] = "sha256:" + "0" * 64
        self.assertFalse(checker._scenario_notice(context)[0])
        context["receipt"]["scene_digest"] = sha256_digest(scene)
        checker._artifact_path.return_value = None
        self.assertFalse(checker._scenario_notice(context)[0])

    def test_validation_data_checker_is_required(self):
        validator = object.__new__(TemplatePackageValidator)
        validator.registry = Mock()
        validator.package_root = Path("not-read")
        capability = ScenarioCapability({"implementation": "unregistered-module"})
        with patch("carto_core.workflow.template_validation.ScenarioRegistry") as registry:
            registry.return_value.for_template.return_value = capability
            with self.assertRaises(ProtocolError) as raised:
                validator._check_semantics({"manifest": {"package": {}}, "documents": {}}, {}, [])
        self.assertEqual("CAPABILITY_NOT_AVAILABLE", raised.exception.code)

    def test_staging_reads_declared_prototype_instead_of_a_fixed_name(self):
        # Empty documents and mock validators isolate filename discovery; no real template is authored.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = ["dependencies.lock.yaml", "prototypes/declared-view.yml"]
            contracts = {key: "contracts/" + key + ".yaml" for key in (
                "scenario", "data_schema", "spatial_behavior", "portrayal", "delivery", "quality_gates")}
            files.extend(contracts.values())
            contents = {name: b"{}\n" for name in ["manifest.yaml", "checksums.sha256", *files]}
            contents["prototypes/declared-view.yml"] = b"prototype_id: unit-prototype\n"
            for name, content in contents.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            checksums = {name: "sha256:" + hashlib.sha256(content).hexdigest()
                         for name, content in contents.items() if name != "checksums.sha256"}
            writer = object.__new__(StagingPackageWriter)
            writer.registry = Mock()
            writer.resolver = Mock()
            writer._verify_closed_package(root, {"files": files, "dependency_lock": "dependencies.lock.yaml",
                                                "business_contracts": contracts}, checksums)
            writer.registry.validate.assert_any_call("prototype-description", {"prototype_id": "unit-prototype"})


if __name__ == "__main__":
    unittest.main()
