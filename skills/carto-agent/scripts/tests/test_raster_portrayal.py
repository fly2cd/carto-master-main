"""Shared expression tests using synthetic evidence, without a GIS or rendering runtime."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from carto_core.compiler.raster_portrayal import RasterPortrayalCompiler
from carto_core.errors import CartoError
from carto_core.repository.map_expression_catalog import MapExpressionCatalog
from carto_core.schema_registry import SchemaRegistry, load_document
from tests.test_raster_classification import PreparationFixture
from tests.fixtures.schema_cases import VALID_CASES

FIXTURES = Path(__file__).parent / "fixtures"
SKILL = Path(__file__).resolve().parents[2]


def raster_contract(role="land-cover"):
    result = load_document(FIXTURES / "portrayal-raster.valid.json")
    result["layers"][0]["data_role"] = role
    result["layers"][0]["map_expression_ref"] = MapExpressionCatalog().reference("raster/categorical", "1.0.0")
    return result


class MapExpressionCatalogTests(unittest.TestCase):
    def test_alternate_valid_and_invalid_schema_examples(self):
        registry = SchemaRegistry()
        for stem, schema in (("portrayal-raster", "portrayal"), ("map-expression-raster", "map-expression")):
            with self.subTest(stem=stem):
                registry.validate(schema, load_document(FIXTURES / f"{stem}.valid.json"))
                with self.assertRaises(CartoError):
                    registry.validate(schema, load_document(FIXTURES / f"{stem}.invalid.json"))

    def test_catalog_resolves_existing_and_raster_expressions(self):
        catalog = MapExpressionCatalog()
        document = load_document(SKILL / "policies/map-expression-catalog.yaml")
        self.assertEqual(3, len(document["entries"]))
        for entry in document["entries"]:
            self.assertEqual(entry, catalog.require(catalog.reference(entry["expression_id"], entry["version"])))
        # Retrieval returns copies, not mutable catalog state.
        ref = catalog.reference("raster/categorical", "1.0.0")
        entry = catalog.require(ref); entry["title"] = "mutated"
        self.assertNotEqual(entry, catalog.require(ref))

    def test_invalid_unknown_and_changed_references_are_rejected(self):
        catalog = MapExpressionCatalog()
        reference = catalog.reference("raster/categorical", "1.0.0")
        for change in ({"digest": "sha256:" + "0"*64}, {"id": "raster/unknown"},
                       {"version": "2.0.0"}, {"uri": "https://untrusted.invalid/code.py"}, {"id": []}):
            with self.subTest(change=change), self.assertRaises(CartoError):
                catalog.require({**reference, **change})

    def test_duplicate_deprecated_and_unknown_catalog_fields_are_rejected(self):
        original = load_document(SKILL / "policies/map-expression-catalog.yaml")
        duplicate = deepcopy(original); duplicate["entries"].append(deepcopy(duplicate["entries"][-1]))
        with patch("carto_core.repository.map_expression_catalog.load_document", return_value=duplicate), \
                self.assertRaisesRegex(CartoError, "CATALOG_DUPLICATE"):
            MapExpressionCatalog()
        deprecated = deepcopy(original); deprecated["entries"][-1]["status"] = "deprecated"
        with patch("carto_core.repository.map_expression_catalog.load_document", return_value=deprecated), \
                self.assertRaisesRegex(CartoError, "NOT_AVAILABLE"):
            MapExpressionCatalog().reference("raster/categorical", "1.0.0")
        unknown = deepcopy(original); unknown["backend"] = "external-program"
        with patch("carto_core.repository.map_expression_catalog.load_document", return_value=unknown), self.assertRaises(CartoError):
            MapExpressionCatalog()

    def test_duplicate_layers_and_wrong_expression_geometry_fail_closed(self):
        contract = raster_contract(); contract["layers"].append(deepcopy(contract["layers"][0]))
        with self.assertRaisesRegex(CartoError, "LAYER_DUPLICATE"):
            MapExpressionCatalog().validate_portrayal(contract)
        contract = deepcopy(VALID_CASES["portrayal"])
        contract["layers"][0]["map_expression_ref"] = MapExpressionCatalog().reference("raster/categorical", "1.0.0")
        with self.assertRaises(CartoError):
            MapExpressionCatalog().validate_portrayal(contract)

    def test_categorical_expression_fields_are_a_consistent_combination(self):
        registry = SchemaRegistry()
        original = load_document(FIXTURES / "map-expression-raster.valid.json")
        for kind in ("geometry", "algorithm", "legend", "labels", "role", "parameters", "id"):
            entry = deepcopy(original)
            if kind == "geometry": entry["geometry_types"] = ["polygon"]
            if kind == "algorithm": entry["visual_variables"][0]["algorithm_id"] = "sequential-classification"
            if kind == "legend": entry["legend"]["type"] = "classed-color"
            if kind == "labels": entry["legend"]["label_source"] = "class-breaks"
            if kind == "role": entry["field_requirements"][0]["semantic_role"] = "amount"
            if kind == "parameters": entry["parameter_definitions"] = [{"name": "k", "type": "integer", "required": True}]
            if kind == "id": entry["expression_id"] = "polygon/classed"
            with self.subTest(kind=kind), self.assertRaises(CartoError): registry.validate("map-expression", entry)

    def test_expression_does_not_authorize_business_scenario(self):
        from carto_core import scenario_registry
        # A valid raster expression still authorizes nothing by itself: the only registered
        # profile is the purpose-named general_thematic_mapping scene, admitted through the
        # versioned policy plus the closed code allowlist.
        policy = load_document(SKILL / "policies/scenario-capabilities.yaml")
        self.assertEqual(["general-thematic-mapping"], [item["id"] for item in policy["profiles"]])
        self.assertEqual(["general_thematic_mapping"],
                         [item["intent_constraints"]["business_scene"] for item in policy["profiles"]])
        self.assertEqual({"general-thematic-raster"}, set(scenario_registry._COMPONENTS))
        for key in ("business_scene", "backend", "source_path", "lookup_table"):
            contract = raster_contract(); contract[key] = "not-a-template-expression-field"
            with self.subTest(key=key), self.assertRaises(CartoError):
                SchemaRegistry().validate("portrayal", contract)


class RasterPortrayalCompilerTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.compiler = RasterPortrayalCompiler(self.service)
        self.contract = raster_contract(self.request["source"]["role"])

    def compile(self, prepared=None, contract=None, layer_id="raster-layer"):
        return self.compiler.compile(contract or self.contract, layer_id, (prepared or self.ready()).ref(), self.context)

    def test_candidate_compiler_checks_trusted_expression_even_if_lock_matches(self):
        from carto_core.compiler.map_candidate import MapCandidateCompiler
        compiler = MapCandidateCompiler(self.service.project_guard)
        reference = deepcopy(self.contract["layers"][0]["map_expression_ref"])
        compiler._validate_expression_bindings(self.contract, {"resources": [reference]})
        with self.assertRaisesRegex(CartoError, "LOCK_MISMATCH"):
            compiler._validate_expression_bindings(self.contract, {"resources": []})
        forged = deepcopy(self.contract)
        reference["digest"] = "sha256:" + "0"*64
        forged["layers"][0]["map_expression_ref"] = reference
        with self.assertRaisesRegex(CartoError, "CATALOG_MISMATCH"):
            compiler._validate_expression_bindings(forged, {"resources": [reference]})

    def test_template_validator_checks_trusted_expression_even_if_lock_matches(self):
        import os
        from carto_core.canonical import sha256_digest
        from carto_core.workflow.template_validation import TemplatePackageValidator
        validator = TemplatePackageValidator(path_guard=self.service.project_guard,
            package_root=self.root, evidence_root=self.root/"validation", attestation_key=os.urandom(32))
        manifest = deepcopy(VALID_CASES["manifest"])
        identity = {key: manifest["package"][key] for key in ("namespace", "kind", "id", "version")}
        lock = deepcopy(VALID_CASES["dependency-lock"])
        lock.update(package={**identity, "digest": sha256_digest(identity)},
                    dependencies=manifest.get("dependencies", []),
                    resources=[deepcopy(self.contract["layers"][0]["map_expression_ref"])])
        snapshot = {"manifest": manifest, "documents": {"portrayal": deepcopy(self.contract), "dependency_lock": lock}}
        validator._check_dependencies(snapshot)
        snapshot["documents"]["portrayal"]["layers"][0]["map_expression_ref"]["digest"] = "sha256:" + "0"*64
        lock["resources"][0]["digest"] = "sha256:" + "0"*64
        with self.assertRaisesRegex(CartoError, "CATALOG_MISMATCH"):
            validator._check_dependencies(snapshot)

    def test_freezes_display_only_contract_with_single_legend(self):
        prepared = self.ready(); before = len(self.calls)
        first = self.compile(prepared); result = self.compiler.load_verified(first.ref(), self.context)
        second = self.compile(prepared)
        self.assertEqual(first.ref(), second.ref())
        self.assertEqual(before, len(self.calls))
        self.assertEqual(prepared.ref(), result["prepared_ref"])
        self.assertEqual([1,255], [row["value"] for row in result["legend_items"]])
        self.assertEqual("nearest", result["resampling"])
        self.assertEqual("preserve", result["source_mask_policy"])
        for row in result["lookup_table"]:
            self.assertNotIn("semantic", row)
            self.assertNotIn("count", row)
        self.assertNotIn("backend", result)
        self.assertNotIn("business_scene", result)
        self.assertNotIn("path", json.dumps(result["portrayal"]))

    def test_compilation_does_not_import_raster_processing_or_rendering_libraries(self):
        import builtins
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name.split(".")[0] in {"numpy", "rasterio", "matplotlib", "PIL"}:
                raise AssertionError("Display compilation must not decode or render pixels")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded):
            artifact = self.compile()
            self.compiler.load_verified(artifact.ref(), self.context)

    def test_pending_clarifications_cannot_be_compiled(self):
        with self.assertRaisesRegex(CartoError, "CLARIFICATION_REQUIRED"):
            self.compile(self.analyze())

    def test_explicit_role_and_layer_selection_required(self):
        prepared = self.ready()
        wrong_role = deepcopy(self.contract); wrong_role["layers"][0]["data_role"] = "other-role"
        with self.assertRaisesRegex(CartoError, "ROLE_MISMATCH"):
            self.compile(prepared, wrong_role)
        with self.assertRaisesRegex(CartoError, "LAYER_MISMATCH"):
            self.compile(prepared, layer_id="wrong-layer")

    def test_foreign_scope_cannot_compile_or_consume(self):
        prepared = self.ready(); artifact = self.compile(prepared)
        for key in ("run_id", "tenant_id", "project_id", "subject_id"):
            original = getattr(self.context, key)
            setattr(self.context, key, "other-scope")
            try:
                with self.subTest(key=key), self.assertRaises(CartoError): self.compile(prepared)
                with self.subTest(key=key), self.assertRaises(CartoError): self.compiler.load_verified(artifact.ref(), self.context)
            finally:
                setattr(self.context, key, original)

    def test_original_files_not_needed_but_snapshot_tamper_is_rejected(self):
        artifact = self.compile(); result = self.compiler.load_verified(artifact.ref(), self.context)
        self.source_path.unlink(); self.legend_path.unlink()
        self.assertEqual(result, self.compiler.load_verified(artifact.ref(), self.context))
        Path(result["source_snapshot"]["artifact_ref"]["uri"]).write_bytes(b"changed frozen TIFF")
        with self.assertRaises(CartoError): self.compiler.load_verified(artifact.ref(), self.context)

    def test_resolved_lookup_legend_and_provenance_are_recomputed(self):
        artifact = self.compile(); original = self.compiler.load_verified(artifact.ref(), self.context)
        for kind in ("color", "label", "legend", "hide", "compiler", "source", "expression"):
            result = deepcopy(original)
            row = next(row for row in result["lookup_table"] if row["display"] == "color")
            if kind == "color": row["color"] = "#ABCDEF"
            if kind == "label": row["label"] = "Forged label"
            if kind == "legend": result["legend_items"] = []
            if kind == "hide": row.update(display="hidden", color=None, include_in_legend=False)
            if kind == "compiler": result["compiler_digest"] = "sha256:" + "0"*64
            if kind == "source": result["source_snapshot"]["artifact_ref"]["digest"] = "sha256:" + "0"*64
            if kind == "expression": result["expression_ref"]["digest"] = "sha256:" + "0"*64
            bad = self.service.save_document(result, "resolved-raster-portrayal")
            with self.subTest(kind=kind), self.assertRaisesRegex(CartoError, "PORTRAYAL_CHANGED"):
                self.compiler.load_verified(bad.ref(), self.context)

    def test_existing_compiler_rechecks_trusted_expression_catalog(self):
        artifact = self.compile()
        catalog = load_document(SKILL / "policies/map-expression-catalog.yaml")
        catalog["entries"][-1]["title"] += " changed"
        with patch("carto_core.repository.map_expression_catalog.load_document", return_value=catalog), \
                self.assertRaisesRegex(CartoError, "CATALOG_MISMATCH"):
            self.compiler.load_verified(artifact.ref(), self.context)

    def test_display_nodata_semantics_do_not_rewrite_source_metadata(self):
        baseline = self.analyze(); answers = self.answers(baseline)
        answers["entries"][0]["semantic"] = "nodata"
        prepared = self.service.clarify(baseline.ref(), answers, self.context)
        result = self.compiler.load_verified(self.compile(prepared).ref(), self.context)
        report, evidence = self.service.load_verified(prepared.ref())
        self.assertEqual(6, evidence["statistics"]["valid_pixels"])
        self.assertEqual(report["source_snapshot"], result["source_snapshot"])
        row = next(row for row in result["lookup_table"] if row["value"] == 0)
        self.assertEqual("hidden", row["display"])
        self.assertNotIn("semantic", row)

    def test_unsupported_mapping_resampling_and_legend_policies_rejected(self):
        prepared = self.ready()
        mutations = [("resampling", "bilinear"), ("no_data", "zero"),
                     ("source_mask_policy", "ignore"), ("symbol", {"fill": "#ABCDEF"}),
                     ("classification", {"method": "jenks"})]
        for key, value in mutations:
            contract = deepcopy(self.contract); contract["layers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(CartoError): self.compile(prepared, contract)
        for key, value in (("generated_from_layers", False), ("show_no_data", True), ("overflow_policy", "truncate")):
            contract = deepcopy(self.contract); contract["legend"][key] = value
            with self.subTest(key=key), self.assertRaises(CartoError): self.compile(prepared, contract)

    def test_unimplemented_multi_layer_and_rules_are_not_silently_ignored(self):
        prepared = self.ready()
        contract = deepcopy(self.contract); extra = deepcopy(contract["layers"][0]); extra["id"] = "another-layer"
        contract["layers"].append(extra)
        with self.assertRaisesRegex(CartoError, "PORTRAYAL_UNSUPPORTED"): self.compile(prepared, contract)
        contract = deepcopy(self.contract)
        contract["rules"] = [{"id": "unsupported-rule", "strength": "mandatory",
                              "path": "/layers/0", "description": "Synthetic unhandled rule", "value": True}]
        SchemaRegistry().validate("portrayal", contract)
        with self.assertRaisesRegex(CartoError, "PORTRAYAL_UNSUPPORTED"): self.compile(prepared, contract)


if __name__ == "__main__":
    unittest.main()
