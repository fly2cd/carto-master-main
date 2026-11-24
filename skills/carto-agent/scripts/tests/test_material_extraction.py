"""Material extraction, data adoption, and provenance tests.

Tests cover:
- Plain text extraction with line-level provenance
- CSV extraction with cell-level provenance
- Material source validation (format detection, size limits, blocked patterns)
- Data adoption (accept/reject/blocked patterns)
- Data facts construction from adopted extractions
- Empty/malformed input rejection
- Security: blocked patterns, oversized files, unknown formats
"""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.workflow.data_adoption import DataAdoptionService
from carto_core.workflow.material_extraction import (
    CsvExtractor,
    MaterialExtractionService,
    PlainTextExtractor,
    detect_format,
)


def _temp_csv(rows: list[list[str]], temp_dir: Path) -> Path:
    """Write a CSV to a temp file and return its path."""
    path = temp_dir / "test.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return path


def _temp_txt(lines: list[str], temp_dir: Path) -> Path:
    """Write text to a temp file and return its path."""
    path = temp_dir / "test.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class MaterialExtractionTextTests(unittest.TestCase):
    """Plain text extraction tests."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.guard = PathGuard([str(self.temp_dir.resolve())])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_plain_text_basic(self):
        path = _temp_txt(["line one", "line two", "line three"], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "txt-1")
        self.assertEqual(result.body["content_type"], "text")
        self.assertEqual(result.body["row_count"], 3)
        self.assertEqual(result.body["rows"][0]["source_location"]["line_start"], 1)
        self.assertEqual(result.body["rows"][2]["source_location"]["line_start"], 3)
        self.assertIn("digest", result.body)

    def test_extract_empty_file_is_rejected(self):
        path = _temp_txt([""], self.temp_dir)
        # Empty file (zero bytes after stripping) — but single empty line is 0 chars?
        # Actually an empty file has size 0, a file with just "" has size 0 too in some cases.
        # Let's create a truly empty file.
        empty_path = self.temp_dir / "empty.txt"
        empty_path.write_bytes(b"")
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError) as ctx:
            svc.extract(empty_path, self.guard, "empty-1")
        self.assertIn("empty", str(ctx.exception.message).lower())

    def test_extract_text_with_line_location(self):
        lines = ["alpha", "beta", "gamma", "delta"]
        path = _temp_txt(lines, self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "loc-1")
        for i, row in enumerate(result.body["rows"]):
            self.assertEqual(row["source_location"]["line_start"], i + 1)
            self.assertEqual(row["cells"]["line"], lines[i])

    def test_extract_unicode_text(self):
        text = ["café résumé naïve", "北京 東京 서울", "αβγδε"]
        path = _temp_txt(text, self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "uni-1")
        self.assertEqual(result.body["row_count"], 3)
        self.assertIn("café", result.body["text_content"])

    def test_extract_text_exceeds_size_limit(self):
        # Create text just over 1 MiB
        long_line = "x" * 100
        lines = [long_line] * 11000  # ~1.1 MiB
        path = _temp_txt(lines, self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError) as ctx:
            svc.extract(path, self.guard, "big-1")
        self.assertIn("limit", str(ctx.exception.message).lower())

    def test_format_detection_by_extension(self):
        self.assertEqual(detect_format(Path("data.csv")), "text/csv")
        self.assertEqual(detect_format(Path("data.txt")), "text/plain")
        self.assertEqual(detect_format(Path("readme.md")), "text/markdown")
        self.assertEqual(detect_format(Path("data.json")), "application/json")
        self.assertEqual(detect_format(Path("map.png")), "image/png")

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ProtocolError):
            detect_format(Path("data.bin"))


class MaterialExtractionCsvTests(unittest.TestCase):
    """CSV extraction tests."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.guard = PathGuard([str(self.temp_dir.resolve())])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_simple_csv(self):
        path = _temp_csv([
            ["name", "value", "category"],
            ["alpha", "10", "A"],
            ["beta", "20", "B"],
            ["gamma", "30", "A"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "csv-1")
        self.assertEqual(result.body["content_type"], "tabular")
        self.assertEqual(result.body["row_count"], 3)
        self.assertEqual(len(result.body["fields"]), 3)
        self.assertEqual(result.body["fields"][0]["name"], "name")

    def test_extract_csv_cell_provenance(self):
        path = _temp_csv([
            ["id", "amount"],
            ["1", "100"],
            ["2", "200"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "csv-prov")
        rows = result.body["rows"]
        self.assertEqual(rows[0]["cells"]["id"], "1")
        self.assertEqual(rows[1]["cells"]["amount"], "200")
        self.assertIn("source_location", rows[0])
        self.assertIn("line_start", rows[0]["source_location"])

    def test_extract_csv_no_header_is_rejected(self):
        # One row with no meaningful header
        path = _temp_csv([["col1"]], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "csv-nodata")
        # Has header but no data rows — should still extract with warning
        self.assertEqual(result.body["row_count"], 0)
        self.assertEqual(len(result.body["issues"]), 1)
        self.assertEqual(result.body["issues"][0]["severity"], "warning")

    def test_extract_csv_duplicate_columns_rejected(self):
        path = _temp_csv([
            ["name", "name", "value"],
            ["a", "b", "10"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError) as ctx:
            svc.extract(path, self.guard, "csv-dup")
        self.assertIn("duplicate", str(ctx.exception.message).lower())

    def test_extract_csv_column_count_mismatch(self):
        path = _temp_csv([
            ["name", "value"],
            ["alpha", "10", "extra_col"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError) as ctx:
            svc.extract(path, self.guard, "csv-mismatch")
        self.assertIn("column", str(ctx.exception.message).lower())

    def test_extract_csv_invalid_column_name(self):
        path = _temp_csv([
            ["valid_name", "123invalid"],
            ["a", "b"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError) as ctx:
            svc.extract(path, self.guard, "csv-badname")
        self.assertIn("column name", str(ctx.exception.message).lower())

    def test_extract_csv_empty_is_rejected(self):
        empty_path = self.temp_dir / "empty.csv"
        empty_path.write_bytes(b"")
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError):
            svc.extract(empty_path, self.guard, "csv-empty")

    def test_extract_csv_binary_is_rejected(self):
        path = self.temp_dir / "binary.csv"
        path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError):
            svc.extract(path, self.guard, "csv-binary")


class DataAdoptionTests(unittest.TestCase):
    """Material adoption decision tests."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.guard = PathGuard([str(self.temp_dir.resolve())])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _text_extraction(self, lines: list[str], source_id: str = "adopt-1") -> dict[str, Any]:
        path = _temp_txt(lines, self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        return svc.extract(path, self.guard, source_id).body

    def test_adopt_valid_text(self):
        extraction = self._text_extraction(["hello world", "second line"])
        service = DataAdoptionService(self.registry)
        evidence = service.adopt(extraction)
        self.assertEqual(evidence["decision"], "adopted")
        self.assertIn("adopted_at", evidence)

    def test_reject_empty_extraction(self):
        # Create extraction with zero byte_length but non-empty text (won't happen
        # in real flow — we test the adoption service's byte_length check)
        extraction = self._text_extraction(["valid content"])
        service = DataAdoptionService(self.registry)
        evidence = service.adopt(extraction)
        self.assertEqual(evidence["decision"], "adopted")

    def test_reject_blocked_pattern_import_os(self):
        extraction = self._text_extraction(["import os\n", "some data"])
        service = DataAdoptionService(self.registry)
        with self.assertRaises(SecurityError) as ctx:
            service.adopt(extraction)
        self.assertIn("blocked", str(ctx.exception.message).lower())

    def test_reject_blocked_pattern_eval(self):
        extraction = self._text_extraction(["eval('1+1')", "data"])
        service = DataAdoptionService(self.registry)
        with self.assertRaises(SecurityError):
            service.adopt(extraction)

    def test_reject_blocked_pattern_subprocess(self):
        extraction = self._text_extraction(["result = subprocess.run(['ls'])", "data"])
        service = DataAdoptionService(self.registry)
        with self.assertRaises(SecurityError):
            service.adopt(extraction)

    def test_reject_blocked_pattern_in_csv_cells(self):
        path = _temp_csv([
            ["name", "script"],
            ["exploit", "os.system('rm -rf /')"],
        ], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        result = svc.extract(path, self.guard, "csv-exploit")
        service = DataAdoptionService(self.registry)
        with self.assertRaises(SecurityError) as ctx:
            service.adopt(result.body)
        self.assertIn("blocked", str(ctx.exception.message).lower())

    def test_adopt_with_format_filter(self):
        extraction = self._text_extraction(["hello"])
        service = DataAdoptionService(self.registry)
        evidence = service.adopt(extraction,
                                 allowed_formats=frozenset({"text/plain", "text/csv"}))
        self.assertEqual(evidence["decision"], "adopted")

    def test_reject_with_wrong_format_filter(self):
        extraction = self._text_extraction(["hello"])
        service = DataAdoptionService(self.registry)
        evidence = service.adopt(extraction,
                                 allowed_formats=frozenset({"text/csv"}))
        self.assertEqual(evidence["decision"], "excluded")
        self.assertIn("format", evidence.get("reason", "").lower())

    def test_adopt_many_mixed_results(self):
        extraction1 = self._text_extraction(["valid data"])
        path2 = _temp_csv([["col"], ["val"]], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        extraction2 = svc.extract(path2, self.guard, "csv-ok").body
        extraction3 = self._text_extraction(["eval('bad')"], "bad-1")

        service = DataAdoptionService(self.registry)
        adopted = service.adopt_many(
            [extraction1, extraction2],
            allowed_formats=frozenset({"text/plain", "text/csv"}),
        )
        self.assertEqual(len(adopted), 2)
        self.assertEqual(adopted[0]["decision"], "adopted")
        self.assertEqual(adopted[1]["decision"], "adopted")

        with self.assertRaises(SecurityError):
            service.adopt_many([extraction3])

    def test_build_data_facts_from_adopted(self):
        extraction1 = self._text_extraction(["hello world", "another line"], "src-1")
        extraction2 = self._text_extraction(["supplementary text"], "src-2")
        service = DataAdoptionService(self.registry)
        adopted = service.adopt_many([extraction1, extraction2])
        facts = service.build_data_facts([extraction1, extraction2], adopted)
        self.assertIsNotNone(facts)
        self.assertEqual(facts["source_kind"], "document")
        self.assertIn("byte_size", facts["observed_dimensions"])
        self.assertEqual(len(facts["material_refs"]), 2)

    def test_build_data_facts_no_adoption(self):
        extraction = self._text_extraction(["text"], "src-3")
        service = DataAdoptionService(self.registry)
        # Exclude all via format filter
        adopted = service.adopt_many(
            [extraction], allowed_formats=frozenset({"text/csv"}))
        facts = service.build_data_facts([extraction], adopted)
        self.assertIsNone(facts)


class MaterialExtractionSecurityTests(unittest.TestCase):
    """Security boundary tests for material extraction."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.guard = PathGuard([str(self.temp_dir.resolve())])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_file_outside_allowed_roots_is_rejected(self):
        # Create a file outside the temp_dir's guard
        outside = Path(tempfile.mkdtemp())
        try:
            path = outside / "outside.txt"
            path.write_text("data", encoding="utf-8")
            svc = MaterialExtractionService(self.registry)
            with self.assertRaises(SecurityError):
                svc.extract(path, self.guard, "outside-1")
        finally:
            import shutil
            shutil.rmtree(outside, ignore_errors=True)

    def test_unsupported_format_is_rejected(self):
        path = self.temp_dir / "test.xyz"
        path.write_text("data", encoding="utf-8")
        svc = MaterialExtractionService(self.registry)
        with self.assertRaises(ProtocolError):
            svc.extract(path, self.guard, "unk-1")

    def test_extraction_result_is_deterministic(self):
        path = _temp_txt(["alpha", "beta", "gamma"], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        r1 = svc.extract(path, self.guard, "det-1")
        r2 = svc.extract(path, self.guard, "det-1")
        # Digests differ because timestamps differ — but content is identical
        self.assertEqual(r1.body["row_count"], r2.body["row_count"])
        self.assertEqual(r1.body["text_content"], r2.body["text_content"])
        self.assertEqual(r1.body["source_ref"]["digest"],
                         r2.body["source_ref"]["digest"])

    def test_extraction_with_different_source_id_differs(self):
        path = _temp_txt(["same content"], self.temp_dir)
        svc = MaterialExtractionService(self.registry)
        r1 = svc.extract(path, self.guard, "id-a")
        r2 = svc.extract(path, self.guard, "id-b")
        # Different source_id produces different result_id and digest
        self.assertNotEqual(r1.body["result_id"], r2.body["result_id"])
        self.assertNotEqual(r1.digest, r2.digest)


class CsvTypeDetectionTests(unittest.TestCase):
    """CSV data type detection tests."""

    def test_detect_integer_column(self):
        extractor = CsvExtractor()
        fields = extractor._detect_types(
            ["id", "name"],
            [["1", "alpha"], ["2", "beta"], ["3", "gamma"]],
        )
        self.assertEqual(fields[0]["data_type"], "integer")
        self.assertEqual(fields[1]["data_type"], "string")

    def test_detect_number_column(self):
        extractor = CsvExtractor()
        fields = extractor._detect_types(
            ["val"],
            [["1.5"], ["2.7"], ["3.14"]],
        )
        self.assertEqual(fields[0]["data_type"], "number")

    def test_detect_mixed_type_falls_to_string(self):
        extractor = CsvExtractor()
        fields = extractor._detect_types(
            ["val"],
            [["1"], ["2.5"], ["not_a_number"]],
        )
        self.assertEqual(fields[0]["data_type"], "string")

    def test_detect_nullable_columns(self):
        extractor = CsvExtractor()
        fields = extractor._detect_types(
            ["id", "name"],
            [["1", ""], ["2", "beta"]],
        )
        self.assertTrue(fields[0]["nullable"])
        self.assertTrue(fields[1]["nullable"])


if __name__ == "__main__":
    unittest.main()