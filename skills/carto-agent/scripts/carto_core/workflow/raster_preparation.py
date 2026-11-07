"""MCP-backed classification preparation, immutable snapshots, and bound clarifications.

This auxiliary workflow does NOT register a map scenario or issue any business approval.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..adapters.geospatial_mcp import DTYPE_RANGES, TIFF_SIGNATURES, _publish_bytes
from ..canonical import canonical_json_bytes, sha256_digest
from ..compiler.raster_portrayal import algorithm_digest, parse_legend, resolve_classes
from ..errors import ProtocolError, SecurityError
from ..repository.immutable_store import StoredArtifact
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from .models import ExecutionContext


class RasterPreparationService:
    def __init__(self, *, project_root: Path, allowed_roots: list[str], registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        self.guard = PathGuard(allowed_roots)
        self.project = self.guard.resolve(project_root, must_exist=True)
        self.project_guard = PathGuard([self.project])
        self.root = self.project_guard.resolve(self.project / ".carto" / "raster")

    def read_bytes(self, path: Path, limit: int) -> bytes:
        path = self.guard.resolve(path, must_exist=True)
        if not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ProtocolError("RASTER_ASSET_SIZE_INVALID", "Expected a bounded regular file")
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        if not 0 < len(content) <= limit:
            raise ProtocolError("RASTER_ASSET_SIZE_INVALID", "Asset changed or exceeds its size limit")
        return content

    @staticmethod
    def digest_bytes(content: bytes) -> str:
        return "sha256:" + hashlib.sha256(content).hexdigest()

    def _asset(self, content: bytes, kind: str, extension: str) -> dict[str, Any]:
        digest = self.digest_bytes(content)
        path = self.project_guard.resolve(self.root / kind / (digest[7:] + extension))
        _publish_bytes(self.project_guard, path, content)
        return {"artifact_ref": {"id": kind, "version": "1.0.0", "digest": digest, "uri": path.as_posix()},
                "size_bytes": len(content)}

    def save_document(self, value: dict[str, Any], schema: str) -> StoredArtifact:
        self.registry.validate(schema, value)
        digest = sha256_digest(value)
        path = self.project_guard.resolve(self.root / schema / (digest[7:] + ".json"))
        _publish_bytes(self.project_guard, path, canonical_json_bytes(value) + b"\n")
        return StoredArtifact(schema, "1.0.0", digest, path)

    def _json_ref(self, reference: dict[str, str], schema: str) -> dict[str, Any]:
        # Reference identity is checked before indexing, including for direct library callers.
        if (not isinstance(reference, dict) or set(reference) != {"id", "version", "digest", "uri"}
                or reference.get("version") != "1.0.0"
                or not isinstance(reference.get("digest"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", reference["digest"])):
            raise ProtocolError("RASTER_REFERENCE_INVALID", "Expected a typed immutable local reference")
        uri = reference.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ProtocolError("RASTER_REFERENCE_URI_REQUIRED", "A local immutable reference is required")
        path = self.project_guard.resolve(uri, must_exist=True)
        if schema == "geospatial-result":
            expected_id = "tool-gis-raster-statistics"
            expected = self.project / ".carto/geospatial/evidence" / expected_id / "1.0.0" / (reference["digest"][7:] + ".json")
        else:
            expected_id = schema
            expected = self.root / schema / (reference["digest"][7:] + ".json")
        if reference["id"] != expected_id or path != self.project_guard.resolve(expected, must_exist=True):
            raise ProtocolError("RASTER_REFERENCE_SCOPE_INVALID", "Reference is not in its project evidence namespace")
        value = load_document(path)
        if sha256_digest(value) != reference["digest"]:
            raise ProtocolError("RASTER_REFERENCE_CHANGED", "Immutable JSON reference differs from its digest")
        self.registry.validate(schema, value)
        return value

    def snapshot_bytes(self, asset: dict[str, Any], kind: str, extension: str) -> bytes:
        ref = asset["artifact_ref"]
        expected = self.project_guard.resolve(self.root / kind / (ref["digest"][7:] + extension), must_exist=True)
        if self.project_guard.resolve(ref["uri"], must_exist=True) != expected or ref["id"] != kind or ref["version"] != "1.0.0":
            raise ProtocolError("RASTER_SNAPSHOT_SCOPE_INVALID", "Snapshot must belong to this project's content store")
        limit = 268435456 if extension == ".tif" else 1048576 if extension == ".csv" else 67108864
        content = self.read_bytes(expected, limit)
        if len(content) != asset["size_bytes"] or self.digest_bytes(content) != ref["digest"]:
            raise ProtocolError("RASTER_SNAPSHOT_CHANGED", "Immutable raster asset has changed")
        return content

    def _check_result(self, result: dict[str, Any], source: dict[str, Any]) -> None:
        self.registry.validate("geospatial-result", result)
        if (result["operation"] != "statistics" or result["source_ref"] != source["source_ref"]
                or result["dataset_id"] != source["dataset_id"] or result["source_size_bytes"] != source["size_bytes"]):
            raise ProtocolError("CLASSIFICATION_SOURCE_BINDING_MISMATCH", "Statistics do not describe the exact input")
        info, stats = result["raster_info"], result["statistics"]
        crs = None if source["crs"] is None else "EPSG:" + source["crs"]["code"]
        if (info["crs"] != crs or info["crs_type"] != "projected" or info["band_count"] != 1
                or len(info["bands"]) != 1 or info["bands"][0]["dtype"] not in DTYPE_RANGES or info["bands"][0]["band"] != 1
                or info["driver"] != "GTiff"):
            raise ProtocolError("RASTER_RENDER_PROFILE_UNSUPPORTED", "First renderer requires a known projected single integer band")
        a, b, _, d, e, _ = info["transform"]
        if b != 0 or d != 0 or a <= 0 or e >= 0:
            raise ProtocolError("RASTER_RENDER_PROFILE_UNSUPPORTED", "First renderer requires north-up, unrotated pixels")
        counts = stats["classes"]
        values = [item["value"] for item in counts]
        low, high = DTYPE_RANGES[info["bands"][0]["dtype"]]
        if (stats["total_pixels"] != info["width"] * info["height"] or stats["total_pixels"] > 16000000
                or stats["total_pixels"] != stats["valid_pixels"] + stats["masked_pixels"]
                or sum(item["count"] for item in counts) != stats["valid_pixels"]
                or not counts or len(counts) > 256 or values != sorted(set(values))
                or any(not low <= value <= high for value in values)):
            raise ProtocolError("CLASSIFICATION_STATISTICS_INVALID", "Class domain and counts differ from raster totals")

    def _resolve(self, base: dict[str, Any], legend: bytes, result: dict[str, Any],
                 answers: dict[str, Any] | None) -> dict[str, Any]:
        self._check_result(result, base["request"]["source"])
        definitions = parse_legend(legend, base["request"]["legend"])
        rows, questions = resolve_classes(base["request"], definitions, result["statistics"])
        report = {**deepcopy(base), "answers": None, "rows": rows, "questions": questions,
                  "status": "needs-clarification" if questions else "ready"}
        if answers is not None:
            self.registry.validate("raster-classification-answers", answers)
            if answers["based_on_digest"] != sha256_digest(report):
                raise ProtocolError("CLASSIFICATION_ANSWERS_STALE", "Answers must bind this exact baseline analysis")
            rows, questions = resolve_classes(base["request"], definitions, result["statistics"], answers)
            report.update(answers=deepcopy(answers), rows=rows, questions=questions,
                          status="needs-clarification" if questions else "ready")
        self.registry.validate("raster-prepared-data", report)
        return report

    def analyze(self, request: dict[str, Any], context: ExecutionContext, adapter: Any) -> StoredArtifact:
        """Statistics MUST come through the authorized MCP gateway, not a second GIS reader."""
        self.registry.validate("raster-classification-request", request)
        context.require_project_scope()
        source = request["source"]
        path = self.guard.resolve(source["path"], base_root=self.project, must_exist=True)
        for suffix in (".msk", ".aux.xml", ".ovr"):
            if self.guard.resolve(str(path) + suffix).exists():
                raise ProtocolError("RASTER_SIDECAR_UNSUPPORTED", "A self-contained TIFF is required")
        content = self.read_bytes(path, 268435456)
        if (content[:4] not in TIFF_SIGNATURES or self.digest_bytes(content) != source["source_ref"]["digest"]
                or len(content) != source["size_bytes"]):
            raise ProtocolError("RASTER_SOURCE_CHANGED", "Source signature, size or digest does not match")
        spec = request["legend"]
        legend_path = self.guard.resolve(spec["path"], base_root=self.project, must_exist=True)
        legend = self.read_bytes(legend_path, 1048576)
        if self.digest_bytes(legend) != spec["digest"] or len(legend) != spec["size_bytes"]:
            raise ProtocolError("CLASSIFICATION_LEGEND_CHANGED", "Legend bytes differ from the request")
        parse_legend(legend, spec)  # Reject malformed input before launching a service.
        typed = {"schema_version": 1, "operation": "statistics", "source": deepcopy(source)}
        receipt = adapter.make_gateway().invoke("gis-raster-statistics", typed, context)
        if (receipt.status != "succeeded" or receipt.input_digest != sha256_digest(typed)
                or receipt.capability_id != "gis-raster-statistics" or len(receipt.artifact_refs) != 1
                or receipt.artifact_refs[0]["digest"] != receipt.output_digest):
            raise ProtocolError("CLASSIFICATION_EVIDENCE_INVALID", "Statistics gateway evidence is not bound to this request")
        result = self._json_ref(receipt.artifact_refs[0], "geospatial-result")
        self._check_result(result, source)
        # Recheck live inputs before publishing their captured bytes. Later rendering uses ONLY snapshots.
        if (self.read_bytes(path, 268435456) != content or self.read_bytes(legend_path, 1048576) != legend):
            raise ProtocolError("CLASSIFICATION_INPUT_CHANGED", "Source inputs changed during analysis")
        base = {"schema_version": 1, "kind": "raster-classification-preparation", "algorithm_digest": algorithm_digest(),
                "context": {key: getattr(context, key) for key in ("run_id", "tenant_id", "project_id", "subject_id")},
                "request": deepcopy(request), "request_digest": sha256_digest(request),
                "source_snapshot": self._asset(content, "source", ".tif"),
                "legend_snapshot": self._asset(legend, "legend", ".csv"), "gis_result_ref": receipt.artifact_refs[0]}
        return self.save_document(self._resolve(base, legend, result, None), "raster-prepared-data")

    def load_verified(self, reference: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        report = self._json_ref(reference, "raster-prepared-data")
        request = report["request"]
        if report["algorithm_digest"] != algorithm_digest() or report["request_digest"] != sha256_digest(request):
            raise ProtocolError("CLASSIFICATION_ALGORITHM_DRIFT", "Request or classification implementation has changed")
        content = self.snapshot_bytes(report["source_snapshot"], "source", ".tif")
        legend = self.snapshot_bytes(report["legend_snapshot"], "legend", ".csv")
        if (self.digest_bytes(content) != request["source"]["source_ref"]["digest"]
                or len(content) != request["source"]["size_bytes"]
                or self.digest_bytes(legend) != request["legend"]["digest"] or len(legend) != request["legend"]["size_bytes"]):
            raise ProtocolError("CLASSIFICATION_SNAPSHOT_MISMATCH", "Snapshots are not bound to the declared inputs")
        result = self._json_ref(report["gis_result_ref"], "geospatial-result")
        base = {k: v for k, v in report.items() if k not in {"rows", "questions", "status", "answers"}}
        expected = self._resolve(base, legend, result, report["answers"])
        if report != expected:
            raise ProtocolError("CLASSIFICATION_RESOLUTION_MISMATCH", "Resolved rows/questions differ from their frozen inputs")
        return report, result

    def clarify(self, reference: dict[str, str], answers: dict[str, Any], context: ExecutionContext) -> StoredArtifact:
        report, result = self.load_verified(reference)
        context.require_project_scope()
        if report["context"] != {key: getattr(context, key) for key in report["context"]}:
            raise SecurityError("CLASSIFICATION_SCOPE_MISMATCH", "Clarification belongs to a different run or subject")
        base = {k: v for k, v in report.items() if k not in {"rows", "questions", "status", "answers"}}
        legend = self.snapshot_bytes(report["legend_snapshot"], "legend", ".csv")
        return self.save_document(self._resolve(base, legend, result, answers), "raster-prepared-data")
