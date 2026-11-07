"""Shared raster PreparedDataBundle contract; it does not admit a business scene."""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from .models import ExecutionContext
from .raster_preparation import RasterPreparationService


class RasterBundlePreparer:
    def __init__(self, preparation: RasterPreparationService) -> None:
        self.preparation = preparation

    def build(self, prepared_ref: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        report, evidence = self.preparation.load_verified(prepared_ref)
        context.require_project_scope()
        if report["context"] != {key: getattr(context, key) for key in report["context"]}:
            raise SecurityError("CLASSIFICATION_SCOPE_MISMATCH", "Preparation belongs to another execution context")
        if report["status"] != "ready":
            raise ProtocolError("CLASSIFICATION_CLARIFICATION_REQUIRED", "No open category questions may enter a bundle")
        source, info = report["request"]["source"], evidence["raster_info"]
        task = self.preparation.save_document(report["request"], "raster-classification-request")
        body = {"schema_version": 1, "bundle_id": "raster-bundle-" + prepared_ref["digest"][7:31],
                "task_ref": task.ref(), "datasets": [report["source_snapshot"]["artifact_ref"]],
                "transformations": [], "tool_receipts": [report["gis_result_ref"]],
                "quality_evidence": [prepared_ref], "open_issues": [],
                "role_bindings": [{"data_type": "raster", "role": source["role"],
                    "dataset_ref": report["source_snapshot"]["artifact_ref"], "prepared_ref": prepared_ref,
                    "band": source["band"], "bbox": info["bounds"], "crs": source["crs"],
                    "width": info["width"], "height": info["height"]}],
                "summary": {"combined_bbox": info["bounds"], "data_nature": source["data_nature"]}}
        result = {**deepcopy(body), "digest": sha256_digest(body)}
        self.preparation.registry.validate("prepared-data-bundle", result)
        return result

    def prepare(self, prepared_ref: dict[str, str], context: ExecutionContext):
        return self.preparation.save_document(self.build(prepared_ref, context), "prepared-data-bundle")

    def validate_request(self, request: dict[str, Any], bundle: dict[str, Any], context: ExecutionContext):
        self.preparation.registry.validate("generate-request", request)
        bindings = request.get("prepared_raster_bindings", [])
        sources = request.get("source_bindings", [])
        if len(bindings) != 1 or len(sources) != 1 or sources[0].get("format") != "geotiff":
            raise ProtocolError("RASTER_GENERATE_BINDING_REQUIRED", "Declare one raster source and its resolved preparation")
        binding = bundle["role_bindings"][0]
        if bindings[0] != {"role": binding["role"], "prepared_ref": binding["prepared_ref"]}:
            raise ProtocolError("RASTER_GENERATE_BINDING_MISMATCH", "Generation request must name the exact ready preparation")
        report, _ = self.preparation.load_verified(binding["prepared_ref"])
        if (sources[0] != report["request"]["source"] or request["sources"] != [sources[0]["source_ref"]]
                or request.get("run_id") != context.run_id or request["project_id"] != context.project_id
                or request["subject"]["tenant_id"] != context.tenant_id
                or request["subject"]["subject_id"] != context.subject_id):
            raise SecurityError("RASTER_GENERATE_SOURCE_MISMATCH", "Request source/scope differs from the frozen preparation")

    def prepare_request(self, request: dict[str, Any], context: ExecutionContext):
        """Entry for an admitted scenario's data_preparer, after G1 (not an approval bypass)."""
        self.preparation.registry.validate("generate-request", request)
        bindings = request.get("prepared_raster_bindings", [])
        if len(bindings) != 1:
            raise ProtocolError("RASTER_GENERATE_BINDING_REQUIRED", "One resolved raster preparation is required")
        bundle = self.build(bindings[0]["prepared_ref"], context)
        self.validate_request(request, bundle, context)
        stored = self.preparation.save_document(bundle, "prepared-data-bundle")
        return {"bundle": bundle, "bundle_ref": stored.ref()}

    def load_verified(self, ref: dict[str, str], context: ExecutionContext) -> dict[str, Any]:
        bundle = self.preparation._json_ref(ref, "prepared-data-bundle")
        bindings = bundle.get("role_bindings", [])
        if len(bindings) != 1 or bindings[0].get("data_type") != "raster":
            raise ProtocolError("RASTER_BUNDLE_UNSUPPORTED", "Exactly one frozen raster binding is required")
        if bundle != self.build(bindings[0]["prepared_ref"], context):
            raise ProtocolError("RASTER_BUNDLE_CHANGED", "Prepared bundle differs from its verified preparation")
        return bundle
