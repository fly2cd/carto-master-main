"""Candidate quality gates and shared legend semantics over verified frozen inputs."""
from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .registry import CheckerRegistry


def legend_consistency(context: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
    """One lookup table drives the legend; output evidence is checked when present."""
    raster = context.get("raster")
    if raster is None:
        return context["scenario_profile"].component("legend_checker")(context)
    from ..compiler.raster_portrayal import legend_items
    portrayal = raster["portrayal"]
    valid = (portrayal["legend_items"] == legend_items(portrayal["lookup_table"])
             and portrayal["source_mask_policy"] == "preserve"
             and portrayal["resampling"] == "nearest")
    if "body" in raster:
        valid = (valid and raster["body"]["legend_items"] == portrayal["legend_items"]
                 and raster["body"]["portrayal_ref"] == raster["page"]["portrayal_ref"])
    business_ok, details, disposition = context["scenario_profile"].component("legend_checker")(context)
    return valid and business_ok, {"display_contract_valid": valid,
        "legend_count": len(portrayal["legend_items"]), "business": details}, disposition


class MapQualityChecks:
    """Uses CheckerRegistry, not a separate scheduler or template-supplied code."""

    def __init__(self, schemas: SchemaRegistry) -> None:
        self.schemas = schemas
        self.checkers = CheckerRegistry(schema_registry=schemas)
        self.checkers.register("protocol.schema-valid", self._schemas)
        self.checkers.register("cartography.legend-consistency", lambda _, ctx: legend_consistency(ctx))
        self.checkers.register("raster.classification-clarified", self._classification)

    def selection(self, gates: dict[str, Any], *, raster: bool = False) -> tuple[str, ...]:
        required = ("protocol.schema-valid",)
        if raster:
            required += ("cartography.legend-consistency", "raster.classification-clarified")
        selected = self.checkers.resolve_quality_gates(gates, required=required)
        self.checkers.require_handlers(selected)
        return selected

    def reference(self, gates: dict[str, Any], scene: dict[str, Any]) -> dict[str, str]:
        selected = self.selection(gates, raster=scene["renderer_id"] == "rasterio-matplotlib-page")
        return {"id": "map-quality-checks", "version": self.checkers.version,
                "digest": sha256_digest({"registry": self.checkers.policy_digest, "quality_gates": gates,
                    "effective_checks": [self.checkers.definition(check_id) for check_id in selected]})}

    def inspect(self, candidate: dict[str, Any], scene: dict[str, Any], gates: dict[str, Any],
                *, profile: Any, raster: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = self.selection(gates, raster=scene["renderer_id"] == "rasterio-matplotlib-page")
        reference = self.reference(gates, scene)
        frozen = [ref for ref in candidate["execution"].get("policy_refs", []) if ref["id"] == reference["id"]]
        if frozen != [reference]:
            raise ProtocolError("CANDIDATE_CHECKER_SET_DRIFT", "Recompile and approve the current quality gates")
        context = {"scene": scene, "scenario_profile": profile}
        if raster is not None:
            context["raster"] = raster
        results = [self.checkers.evaluate(check_id, candidate, context).to_dict() for check_id in selected]
        report = {
            "schema_version": 1, "report_id": f"preflight-{candidate['run_id']}",
            "phase": "validate", "subject_digest": sha256_digest(candidate),
            "checker_set_digest": reference["digest"],
            "status": "failed" if self.checkers.has_blocking_failure(results) else "passed",
            "results": results, "created_at": candidate["created_at"],
        }
        self.schemas.validate("validation-report", report)
        return report

    def _schemas(self, candidate, context):
        self.schemas.validate("resolved-map", candidate)
        self.schemas.validate("render-scene", context["scene"])
        return True, {"schemas": ["resolved-map", "render-scene"]}

    @staticmethod
    def _classification(_, context):
        raster = context.get("raster")
        if raster is None:
            raise ProtocolError("CHECKER_CONTEXT_REQUIRED", "Classification checks require verified raster inputs")
        report, portrayal, bundle = raster["report"], raster["portrayal"], raster["bundle"]
        valid = (report["status"] == "ready" and not report["questions"] and not bundle["open_issues"]
                 and portrayal["prepared_ref"] == bundle["role_bindings"][0]["prepared_ref"]
                 and portrayal["prepared_ref"]["digest"] == sha256_digest(report))
        return valid, {"ready": report["status"] == "ready", "open_question_count": len(report["questions"]),
                       "prepared_ref_digest": portrayal["prepared_ref"]["digest"],
                       "bundle_digest": sha256_digest(bundle)}
