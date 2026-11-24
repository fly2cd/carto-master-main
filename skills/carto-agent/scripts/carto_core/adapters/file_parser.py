"""Unified data directory parser: file classification and content extraction.

Migrated from the old framework's adapters/file_parser.py. Produces
data-summary.md — a Markdown mirror of the data directory contents
(paragraphs, tables, GeoJSON metadata, raster info). No business semantics:
this is pure format conversion. The host agent reads the output to extract
task-specific facts (itinerary stops, theme indicators, etc.).

Exposed only through the ToolGateway ``data-summary`` capability
(``carto data summarize``); no standalone CLI entry.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File category constants
# ---------------------------------------------------------------------------

CAT_GEO_VECTOR = "geographic-vector"
CAT_GEO_RASTER = "geographic-raster"
CAT_TABULAR = "tabular"
CAT_DOCUMENT = "document"
CAT_IMAGE = "image"
CAT_UNKNOWN = "unknown"

CAT_LABEL = {
    CAT_GEO_VECTOR: "地理矢量（必须上图）",
    CAT_GEO_RASTER: "地理栅格（必须上图）",
    CAT_TABULAR: "表格数据",
    CAT_DOCUMENT: "文档",
    CAT_IMAGE: "图片（照片/图表/资料截图）",
    CAT_UNKNOWN: "未知格式",
}

_SHP_AUX_SUFFIXES = {".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx",
                     ".fbn", ".fbx", ".ain", ".aih", ".ixs", ".mxs", ".atx"}
_NOISE_FILES: set[str] = {"Thumbs.db", "desktop.ini", ".DS_Store", "filelist.xml"}

_SUFFIX_CATEGORY: dict[str, str] = {}
for _s in {".shp", ".geojson", ".kml", ".kmz", ".gpkg", ".gml", ".tab", ".mif", ".dxf"}:
    _SUFFIX_CATEGORY[_s] = CAT_GEO_VECTOR
for _s in {".tif", ".tiff", ".img", ".asc", ".nc", ".dem", ".hgt", ".jp2"}:
    _SUFFIX_CATEGORY[_s] = CAT_GEO_RASTER
for _s in {".csv", ".xlsx", ".xls"}:
    _SUFFIX_CATEGORY[_s] = CAT_TABULAR
for _s in {".txt", ".md", ".docx", ".pdf", ".html", ".htm"}:
    _SUFFIX_CATEGORY[_s] = CAT_DOCUMENT
for _s in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
    _SUFFIX_CATEGORY[_s] = CAT_IMAGE


def classify_suffix(suffix: str) -> str:
    return _SUFFIX_CATEGORY.get(suffix.lower(), CAT_UNKNOWN)


def classify_path(path: Path) -> str:
    return classify_suffix(path.suffix)


def is_shapefile_aux(path: Path) -> bool:
    if path.suffix.lower() not in _SHP_AUX_SUFFIXES:
        return False
    return path.with_suffix(".shp").is_file()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_csv_to_md(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return "*(空 CSV 文件)*\n"
    col_count = max(len(r) for r in rows)
    normalized = [r + [""] * (col_count - len(r)) for r in rows]
    md = "| " + " | ".join(normalized[0]) + " |\n"
    md += "| " + " | ".join(["---"] * col_count) + " |\n"
    for row in normalized[1:]:
        md += "| " + " | ".join(row) + " |\n"
    md += f"\n*（共 {len(rows) - 1} 行数据，{col_count} 列）*\n"
    return md


def _parse_xlsx_to_md(path: Path) -> str:
    try:
        import openpyxl
    except ImportError:
        return "*(需要安装 openpyxl 来解析 .xlsx 文件)*\n"
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        parts.append(f"### Sheet: {sheet_name}\n")
        for row in ws.iter_rows(values_only=True):
            parts.append("| " + " | ".join(str(c) if c is not None else "" for c in row) + " |")
        parts.append("")
    wb.close()
    return "\n".join(parts)


def _parse_docx_to_md(path: Path) -> str:
    """Parse DOCX using python-docx: paragraphs and tables to Markdown."""
    try:
        from docx import Document
        from docx.text.paragraph import Paragraph
    except ImportError:
        return "*(需要安装 python-docx 来解析 .docx 文件)*\n"
    document = Document(path)
    parts = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text)
            continue
        rows = [
            [cell.text.replace("|", r"\|").replace("\n", "<br>") for cell in row.cells]
            for row in block.rows
        ]
        if any(any(cell.strip() for cell in row) for row in rows):
            columns = [f"列 {number}" for number in range(1, max(map(len, rows)) + 1)]
            parts.append(_table_to_md([columns, *rows]))
    return "\n\n".join(parts) if parts else "*(DOCX 中未提取到正文或表格文本)*\n"


def _parse_pdf_to_md(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        return "*(需要安装 pdfplumber 来解析 .pdf 文件)*\n"
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                parts.append(f"### 第 {i + 1} 页\n\n{text}")
            tables = page.extract_tables()
            for j, table in enumerate(tables):
                if table:
                    parts.append(f"#### 表格 {j + 1}\n")
                    parts.append(_table_to_md(table))
    return "\n\n".join(parts) if parts else "*(PDF 中未提取到文本或表格)*\n"


def _table_to_md(table: list[list[str | None]]) -> str:
    if not table:
        return ""
    col_count = max(len(r) for r in table if r)
    md = "| " + " | ".join(str(c) if c is not None else "" for c in table[0]) + " |\n"
    md += "| " + " | ".join(["---"] * col_count) + " |\n"
    for row in table[1:]:
        padded = list(row) + [""] * (col_count - len(row))
        md += "| " + " | ".join(str(c) if c is not None else "" for c in padded) + " |\n"
    return md


def _parse_geojson_meta(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "*(GeoJSON 文件解析失败)*\n"
    if not isinstance(data, dict):
        return "*(不是有效的 GeoJSON 对象)*\n"
    features = data.get("features", [])
    geom_types: set[str] = set()
    attr_fields: set[str] = set()
    for feat in features[:200]:
        g = feat.get("geometry", {})
        if isinstance(g, dict) and g.get("type"):
            geom_types.add(g["type"])
        props = feat.get("properties", {})
        if isinstance(props, dict):
            attr_fields.update(props.keys())
    lines = [
        f"  几何类型: {', '.join(sorted(geom_types)) if geom_types else data.get('type', 'Unknown')}",
        f"  要素数:   {len(features)}",
        f"  属性字段: {', '.join(sorted(attr_fields)) if attr_fields else '(无)'}",
    ]
    return "\n".join(lines) + "\n"


def _parse_image_meta(path: Path) -> str:
    width, height = 0, 0
    try:
        from PIL import Image
        with Image.open(path) as img:
            width, height = img.size
    except Exception:
        pass
    return f"  尺寸: {width}×{height}\n"


def parse_file_to_md(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8")[:100_000]
        except UnicodeDecodeError:
            return "*(文件编码不是 UTF-8)*\n"
    if suffix == ".csv":
        return _parse_csv_to_md(path)
    if suffix == ".xlsx":
        return _parse_xlsx_to_md(path)
    if suffix == ".docx":
        return _parse_docx_to_md(path)
    if suffix == ".pdf":
        return _parse_pdf_to_md(path)
    if suffix in {".geojson", ".json"}:
        return _parse_geojson_meta(path)
    if suffix in {".tif", ".tiff", ".img"}:
        return _parse_image_meta(path)
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
        return _parse_image_meta(path)
    return f"*(不支持的文件格式: {suffix})*\n"


# ---------------------------------------------------------------------------
# Main entry: generate data-summary.md
# ---------------------------------------------------------------------------

def _summary_files(data_dir: Path) -> list[Path]:
    """Visible data files, noise/shapefile sidecars excluded, sorted by category then name."""
    return sorted(
        [p for p in data_dir.iterdir()
         if p.is_file()
         and not p.name.startswith("~")
         and not p.name.startswith(".")
         and not is_shapefile_aux(p)
         and p.name not in _NOISE_FILES],
        key=lambda p: (classify_path(p), p.name),
    )


def summarize_directory(data_dir: Path) -> dict:
    """Structured inventory + Markdown mirror of a data directory.

    Pure format conversion (no business semantics); consumed by the
    data-summary ToolGateway capability, which resolves the directory
    through PathGuard before calling this.
    """
    if not data_dir.is_dir():
        raise ValueError(f"Data directory not found: {data_dir}")
    files = _summary_files(data_dir)
    counts: dict[str, int] = {}
    for path in files:
        category = classify_path(path)
        counts[category] = counts.get(category, 0) + 1
    return {
        "file_count": len(files),
        "categories": [{"category": category, "count": counts[category]}
                       for category in sorted(counts)],
        "summary_md": generate_data_summary_md(data_dir),
    }


def generate_data_summary_md(data_dir: Path) -> str:
    """Parse all files in data_dir, produce a categorized Markdown summary."""
    if not data_dir.is_dir():
        raise ValueError(f"Data directory not found: {data_dir}")

    files = _summary_files(data_dir)

    groups: dict[str, list[Path]] = {cat: [] for cat in CAT_LABEL}
    for f in files:
        groups[classify_path(f)].append(f)

    parts = ["# 数据目录内容\n"]
    parts.append("## 文件分类概览\n")
    for cat, label in CAT_LABEL.items():
        group_files = groups[cat]
        if not group_files:
            continue
        tag = "（必须上图）" if cat in (CAT_GEO_VECTOR, CAT_GEO_RASTER) else ""
        parts.append(f"- **{label}**：{len(group_files)} 个文件 {tag}")
        for f in group_files:
            parts.append(f"  - `{f.name}` ({f.stat().st_size / 1024:.1f} KB)")
    parts.append("")

    for cat, header in [
        (CAT_GEO_VECTOR, "## 地理矢量文件（必须上图）\n"),
        (CAT_GEO_RASTER, "## 地理栅格文件（必须上图）\n"),
        (CAT_TABULAR, "## 表格数据\n"),
        (CAT_DOCUMENT, "## 文档\n"),
        (CAT_IMAGE, "## 图片\n"),
        (CAT_UNKNOWN, "## 未知格式\n"),
    ]:
        group_files = groups[cat]
        if not group_files:
            continue
        parts.append(header)
        for path in group_files:
            parts.append(f"### {path.name}\n")
            try:
                parts.append(parse_file_to_md(path))
            except Exception as exc:
                parts.append(f"*(解析失败: {exc})*\n")
            parts.append("")

    return "\n".join(parts)
