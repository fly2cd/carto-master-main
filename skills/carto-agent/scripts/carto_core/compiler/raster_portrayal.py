"""Compile categorical display contracts, not GIS classifications or raster reclassifications.

Category names, palette selection and legend inclusion belong to Carto. Source
values, NoData metadata and pixel masks remain unchanged. No raster decoder is
imported here; GIS evidence is verified by the preparation service.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.map_expression_catalog import MapExpressionCatalog

if TYPE_CHECKING:
    from ..repository.immutable_store import StoredArtifact
    from ..workflow.models import ExecutionContext
    from ..workflow.raster_preparation import RasterPreparationService
from ..schema_registry import SchemaRegistry

VERSION = "1.0.0"
# A versioned proposal, not inferred data semantics. Selection is explicit in the request.
PALETTE = ("#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE", "#AA3377",
           "#BBBBBB", "#332288", "#88CCEE", "#44AA99", "#999933", "#882255")
_CODE = re.compile(r"-?(?:0|[1-9][0-9]{0,9})\Z")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def algorithm_digest() -> str:
    root = Path(__file__).resolve().parents[3] / "schemas"
    return sha256_digest({
        "version": VERSION, "code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "preparation": hashlib.sha256((Path(__file__).resolve().parents[1] / "workflow/raster_preparation.py").read_bytes()).hexdigest(),
        "schemas": {name: hashlib.sha256((root / (name + ".schema.json")).read_bytes()).hexdigest()
                    for name in ("raster-classification-request", "raster-classification-answers", "raster-prepared-data")},
    })


def parse_legend(content: bytes, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Consume ONLY explicitly mapped CSV columns; do not infer names from the file name."""
    if not 0 < len(content) <= 1024 * 1024:
        raise ProtocolError("CLASSIFICATION_CSV_SIZE_INVALID", "CSV exceeds the bounded input profile")
    try:
        text = content.decode(spec["encoding"])
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        columns = [spec["value_column"], spec["label_column"]]
        if spec["color_column"] is not None:
            columns.append(spec["color_column"])
        if (not headers or len(headers) != len(set(headers)) or len(headers) > 64
                or len(columns) != len(set(columns)) or not set(columns) <= set(headers)):
            raise ProtocolError("CLASSIFICATION_CSV_COLUMNS_INVALID", "Missing, duplicate, or conflicting mapped columns")
        rows, seen = [], set()
        for record in reader:
            if None in record or any(value is None for value in record.values()):
                raise ProtocolError("CLASSIFICATION_CSV_ROW_INVALID", "CSV row width differs from header")
            if len(rows) >= 256:
                raise ProtocolError("CLASSIFICATION_CLASS_LIMIT", "At most 256 classes are admitted")
            code = record[spec["value_column"]].strip()
            if not _CODE.fullmatch(code) or not -2147483648 <= int(code) <= 4294967295:
                raise ProtocolError("CLASSIFICATION_CODE_INVALID", "Category code must be an exact 32-bit integer")
            value = int(code)
            if value in seen:
                raise ProtocolError("CLASSIFICATION_CODE_DUPLICATE", "CSV category codes must be unique")
            seen.add(value)
            label = record[spec["label_column"]].strip() or None
            color = (record[spec["color_column"]].strip() or None) if spec["color_column"] else None
            if label and (len(label) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in label)):
                raise ProtocolError("CLASSIFICATION_LABEL_INVALID", "Category label violates the text profile")
            if color and not _COLOR.fullmatch(color):
                raise ProtocolError("CLASSIFICATION_COLOR_INVALID", "Expected an explicit six-digit hex color")
            rows.append({"value": value, "label": label, "color": color.upper() if color else None, "order": len(rows)})
    except (UnicodeError, csv.Error) as exc:
        raise ProtocolError("CLASSIFICATION_CSV_INVALID", "CSV must be bounded, well-formed UTF-8") from None
    if not rows:
        raise ProtocolError("CLASSIFICATION_CSV_EMPTY", "CSV has no category definitions")
    return rows


def resolve_classes(request: dict[str, Any], legend: list[dict[str, Any]], statistics: dict[str, Any],
                    answers: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve a DISPLAY classification, never rewrite source NoData or raw statistics."""
    counts = {item["value"]: item["count"] for item in statistics["classes"]}
    if len(counts) != len(statistics["classes"]) or not counts:
        raise ProtocolError("CLASSIFICATION_STATISTICS_INVALID", "Expected unique, nonempty valid-pixel classes")
    definitions = {item["value"]: item for item in legend}
    values = sorted(set(counts) | set(definitions))
    if len(values) > 256:
        raise ProtocolError("CLASSIFICATION_CLASS_LIMIT", "Combined source and legend exceed 256 classes")
    overrides = {}
    if answers is not None:
        SchemaRegistry().validate("raster-classification-answers", answers)
        overrides = {item["value"]: item for item in answers["entries"]}
        if len(overrides) != len(answers["entries"]) or not set(overrides) <= set(values):
            raise ProtocolError("CLASSIFICATION_ANSWERS_INVALID", "Answers contain duplicate or unrelated category codes")
    rows, questions = [], []
    missing_order = len(legend)
    for value in values:
        definition = definitions.get(value)
        observed = counts.get(value, 0)
        if definition is None:
            row = {"value": value, "count": observed, "semantic": None, "display": None, "label": None,
                   "color": None, "order": missing_order, "include_in_legend": False}
            missing_order += 1
        else:
            color = definition["color"]
            if color is None and request["palette"] == "carto-categorical-v1" and definition["order"] < len(PALETTE):
                color = PALETTE[definition["order"]]
            row = {"value": value, "count": observed, "semantic": "class", "display": "color",
                   "label": definition["label"], "color": color, "order": definition["order"],
                   "include_in_legend": bool(observed or request["legend_policy"] == "all")}
        if value in overrides:
            row.update(deepcopy(overrides[value]))
        kinds = []
        if row["semantic"] is None:
            kinds.append("unmapped-value")
        elif row["display"] == "color":
            if row["label"] is None:
                kinds.append("missing-label")
            if row["color"] is None:
                kinds.append("missing-color")
        for kind in kinds:
            messages = {
                "unmapped-value": f"像元值 {value} 未在分类表中定义。请确认其语义、显示方式和是否进入图例；不自动视为 NoData。",
                "missing-label": f"类别值 {value} 缺少名称，请补充用于地图和图例的名称。",
                "missing-color": f"类别值 {value} 缺少颜色，请提供分类颜色。",
            }
            questions.append({"question_id": "class-" + sha256_digest({"request": request, "value": value, "kind": kind})[7:31],
                              "kind": kind, "value": value, "observed_count": observed, "message": messages[kind]})
        rows.append(row)
    orders = [row["order"] for row in rows]
    if len(orders) != len(set(orders)):
        raise ProtocolError("CLASSIFICATION_ORDER_DUPLICATE", "Display order must be unambiguous")
    return sorted(rows, key=lambda row: row["order"]), questions


def legend_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in ("value", "label", "color", "order")}
            for row in rows if row["include_in_legend"] and row["display"] == "color"]


def portrayal_compiler_digest() -> str:
    root = Path(__file__).resolve().parents[3]
    files = [Path(__file__).resolve(),
             root / "scripts/carto_core/repository/map_expression_catalog.py",
             root / "schemas/portrayal.schema.json",
             root / "schemas/resolved-raster-portrayal.schema.json",
             root / "schemas/map-expression.schema.json",
             root / "schemas/map-expression-catalog.schema.json"]
    return sha256_digest({"version": VERSION,
                          "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}})


class RasterPortrayalCompiler:
    """Bind a shared portrayal layer to verified, scoped display definitions.

    Templates contain roles and expression refs, not actual category rows, source
    paths or renderer choices. The project-local result is backend-independent.
    """

    def __init__(self, preparation: RasterPreparationService) -> None:
        self.preparation = preparation

    def _build(self, portrayal: dict[str, Any], layer_id: str,
               prepared_ref: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        # Reload the trusted catalog each time: a stale compiler cannot hide policy drift.
        MapExpressionCatalog(self.preparation.registry).validate_portrayal(portrayal)
        # Current map-body/page adapters render exactly one layer. Do not silently drop
        # extra layers or rules that this compiler has no executor for.
        if len(portrayal["layers"]) != 1 or portrayal["rules"]:
            raise ProtocolError("RASTER_PORTRAYAL_UNSUPPORTED", "Require one raster layer and no unresolved portrayal rules")
        layer = portrayal["layers"][0]
        if layer["id"] != layer_id or layer["geometry"] != "raster":
            raise ProtocolError("RASTER_PORTRAYAL_LAYER_MISMATCH", "Select the declared categorical raster layer")
        report, _ = self.preparation.load_verified(prepared_ref)
        context.require_project_scope()
        if report["context"] != {key: getattr(context, key) for key in report["context"]}:
            raise SecurityError("CLASSIFICATION_SCOPE_MISMATCH", "Display definitions belong to another run or subject")
        if report["status"] != "ready":
            raise ProtocolError("CLASSIFICATION_CLARIFICATION_REQUIRED", "Resolve category questions before compiling portrayal")
        if layer["data_role"] != report["request"]["source"]["role"]:
            raise ProtocolError("RASTER_PORTRAYAL_ROLE_MISMATCH", "Layer must bind the prepared raster's declared role")
        rows = [{key: row[key] for key in ("value", "display", "label", "color", "order", "include_in_legend")}
                for row in report["rows"]]
        # A display-only semantic such as 'nodata' never changes source metadata.
        return {"schema_version": 1, "kind": "resolved-raster-portrayal",
                "compiler_version": VERSION, "compiler_digest": portrayal_compiler_digest(),
                "portrayal": deepcopy(portrayal), "layer_id": layer_id,
                "prepared_ref": deepcopy(prepared_ref), "expression_ref": deepcopy(layer["map_expression_ref"]),
                "source_snapshot": deepcopy(report["source_snapshot"]), "context": deepcopy(report["context"]),
                "lookup_table": rows, "legend_items": legend_items(rows),
                "source_mask_policy": layer["source_mask_policy"], "resampling": layer["resampling"],
                "unknown_value_policy": layer["category_mapping"]["unknown_value_policy"]}

    def compile(self, portrayal: dict[str, Any], layer_id: str,
                prepared_ref: dict[str, str], context: ExecutionContext) -> StoredArtifact:
        result = self._build(portrayal, layer_id, prepared_ref, context)
        return self.preparation.save_document(result, "resolved-raster-portrayal")

    def load_verified(self, reference: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        result = self.preparation._json_ref(reference, "resolved-raster-portrayal")
        expected = self._build(result["portrayal"], result["layer_id"], result["prepared_ref"], context)
        if result != expected:
            raise ProtocolError("RASTER_PORTRAYAL_CHANGED", "Display contract, source, expression or compiler differs from frozen portrayal")
        return result
