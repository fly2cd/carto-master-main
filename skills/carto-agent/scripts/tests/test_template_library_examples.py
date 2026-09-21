from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.security.paths import PathGuard
from carto_core.workflow.template_author import MapScenarioAuthor
from carto_core.workflow.template_validation import TemplatePackageValidator


ATTESTATION_KEY = b"template-library-test-key-at-least-32-bytes"
CARTO_AGENT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CARTO_AGENT_ROOT.parents[1]
EXAMPLE_PACKAGE = (
    CARTO_AGENT_ROOT
    / "templates"
    / "map-scenario"
    / "urban-flood-risk"
    / "1.0.0"
)
EXPECTED_IDENTITY = {
    "namespace": "local",
    "kind": "map-scenario",
    "id": "urban-flood-risk",
    "version": "1.0.0",
    "source_crs": {"authority": "EPSG", "code": "4326"},
    "display_crs": {"authority": "EPSG", "code": "3857"},
}
EXPECTED_TARGETS = ["svg", "pdf", "png"]
EXPECTED_FILES = {
    "manifest.yaml",
    "checksums.sha256",
    "dependencies.lock.yaml",
    "templates/design_spec.md",
    "contracts/scenario.yaml",
    "contracts/data.schema.yaml",
    "contracts/spatial-behavior.yaml",
    "contracts/portrayal.yaml",
    "contracts/delivery.yaml",
    "contracts/quality-gates.yaml",
    "fixtures/flood-risk.synthetic.geojson",
    "prototypes/risk-overview.yaml",
}


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validator(package_root: Path, evidence_root: Path, *allowed_roots: Path) -> TemplatePackageValidator:
    return TemplatePackageValidator(
        path_guard=PathGuard(allowed_roots),
        package_root=package_root,
        evidence_root=evidence_root,
        attestation_key=ATTESTATION_KEY,
    )


def _refresh_checksums(package_root: Path) -> None:
    """Re-close a copied package so a schema mutation reaches schema validation."""
    manifest_path = package_root / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["checksums"] = {
        relative: _digest((package_root / relative).read_bytes())
        for relative in sorted(manifest["files"])
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    recorded = {
        "manifest.yaml": _digest(manifest_path.read_bytes()),
        **manifest["checksums"],
    }
    checksum_lines = [
        f"{recorded[relative].removeprefix('sha256:')}  {relative}"
        for relative in sorted(recorded)
    ]
    (package_root / "checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class TemplateLibraryExampleTests(unittest.TestCase):
    def test_example_is_closed_schema_valid_and_explicitly_non_production(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temporary_root = Path(temp)
            snapshot = _validator(
                EXAMPLE_PACKAGE,
                temporary_root / "evidence",
                REPOSITORY_ROOT,
                temporary_root,
            ).inspect(EXPECTED_IDENTITY, EXPECTED_TARGETS)

        actual_files = {
            path.relative_to(EXAMPLE_PACKAGE).as_posix()
            for path in EXAMPLE_PACKAGE.rglob("*")
            if path.is_file()
        }
        self.assertEqual(EXPECTED_FILES, actual_files)
        self.assertEqual("draft", snapshot["manifest"]["package"]["status"])
        self.assertEqual(EXPECTED_TARGETS, snapshot["manifest"]["targets"])

        documents = snapshot["documents"]
        self.assertEqual(
            {
                "data_nature": "synthetic",
                "contains_production_data": False,
                "contains_sensitive_coordinates": False,
                "source_crs": "EPSG:4326",
            },
            documents["fixture"]["carto_metadata"],
        )
        self.assertEqual("not-run", documents["prototype"]["renderer_execution"])
        self.assertTrue(all(not target["production_ready"] for target in documents["delivery"]["targets"]))
        self.assertEqual(
            {"navigation", "formal-delivery"},
            set(documents["scenario"]["application"]["excluded_uses"]),
        )

    def test_checksum_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temporary_root = Path(temp)
            copied_package = temporary_root / "package"
            shutil.copytree(EXAMPLE_PACKAGE, copied_package)
            scenario_path = copied_package / "contracts" / "scenario.yaml"
            scenario_path.write_text(
                scenario_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
                newline="\n",
            )

            with self.assertRaises(ProtocolError) as raised:
                _validator(
                    copied_package,
                    temporary_root / "evidence",
                    temporary_root,
                ).inspect(EXPECTED_IDENTITY, EXPECTED_TARGETS)
            self.assertEqual("PACKAGE_CHECKSUM_MISMATCH", raised.exception.code)

    def test_unknown_contract_field_is_rejected_after_package_is_reclosed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temporary_root = Path(temp)
            copied_package = temporary_root / "package"
            shutil.copytree(EXAMPLE_PACKAGE, copied_package)
            scenario_path = copied_package / "contracts" / "scenario.yaml"
            scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
            scenario["unexpected_field"] = "must be rejected"
            scenario_path.write_text(
                yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
                newline="\n",
            )
            _refresh_checksums(copied_package)

            with self.assertRaises(ProtocolError) as raised:
                _validator(
                    copied_package,
                    temporary_root / "evidence",
                    temporary_root,
                ).inspect(EXPECTED_IDENTITY, EXPECTED_TARGETS)
            self.assertEqual("SCHEMA_VALIDATION_FAILED", raised.exception.code)

    def test_committed_example_matches_current_author_output_byte_for_byte(self) -> None:
        request = {
            "namespace": "local",
            "kind": "map-scenario",
            "template_id": "urban-flood-risk",
            "version": "1.0.0",
            "profile": "flood-risk-overview",
            "purpose": "Synthetic urban flood-risk engineering preview",
            "reuse_intent": "Reuse with approved synthetic role-compatible inputs",
            "supported_uses": ["engineering-preview"],
            "excluded_uses": ["navigation", "formal-delivery"],
            "targets": EXPECTED_TARGETS,
            "source_crs": {"authority": "EPSG", "code": "4326"},
            "display_crs": {"authority": "EPSG", "code": "3857"},
            "requested_at": "2026-09-21T00:00:00Z",
        }
        brief = {"brief_id": "urban-flood-risk-brief", "revision": 1}

        with tempfile.TemporaryDirectory() as temp:
            temporary_root = Path(temp)
            generated = MapScenarioAuthor(
                PathGuard([REPOSITORY_ROOT, temporary_root]),
                temporary_root,
            ).author(request, brief)
            generated_package = Path(generated["package_path"])
            generated_files = {
                path.relative_to(generated_package).as_posix(): path.read_bytes()
                for path in generated_package.rglob("*")
                if path.is_file()
            }

        committed_files = {
            path.relative_to(EXAMPLE_PACKAGE).as_posix(): path.read_bytes()
            for path in EXAMPLE_PACKAGE.rglob("*")
            if path.is_file()
        }
        self.assertEqual(committed_files, generated_files)


if __name__ == "__main__":
    unittest.main()
