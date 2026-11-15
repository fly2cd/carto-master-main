"""Candidate quality gates and shared legend semantics over verified frozen inputs."""
from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .registry import CheckerRegistry


def legend_consistency(context):
    if 'vector' in context:
        from ..compiler.vector_portrayal import resolve_features
        valid = all(resolve_features(item['report'], item['portrayal']['encoding']) == {k: item['portrayal'][k] for k in ('feature_styles', 'legend_items', 'counts')} for stack in context['vector']['layers'].values() for item in stack)
        ok, details, disposition = context['scenario_profile'].component('legend_checker')(context)
        return valid and ok, {'vector_encoding_valid': valid, 'business': details}, disposition
    raster=context.get('raster')
    if raster is None:return context['scenario_profile'].component('legend_checker')(context)
    from ..compiler.raster_portrayal import legend_items
    valid=True
    for vid,layer in raster['layers'].items():
        portrayal=layer['portrayal']
        valid=valid and (portrayal['legend_items']==legend_items(portrayal['lookup_table'])
                         and portrayal['source_mask_policy']=='preserve' and portrayal['resampling']=='nearest')
        if 'bodies' in raster:
            body=raster['bodies'].get(vid)
            valid=valid and body is not None and body['legend_items']==portrayal['legend_items'] and body['portrayal_ref']==layer['portrayal_ref']
    ok,details,disposition=context['scenario_profile'].component('legend_checker')(context)
    return valid and ok,{'display_contract_valid':valid,'panel_count':len(raster['layers']),'business':details},disposition


class MapQualityChecks:
    """Uses CheckerRegistry, not a separate scheduler or template-supplied code."""

    def __init__(self, schemas: SchemaRegistry) -> None:
        self.schemas = schemas
        self.checkers = CheckerRegistry(schema_registry=schemas)
        self.checkers.register("protocol.schema-valid", self._schemas)
        self.checkers.register("cartography.legend-consistency", lambda _, ctx: legend_consistency(ctx))
        self.checkers.register("raster.classification-clarified", self._classification)

    def selection(self, gates: dict[str, Any], *, raster: bool = False, vector: bool = False) -> tuple[str, ...]:
        required = ("protocol.schema-valid",)
        if vector:
            required += ("cartography.legend-consistency",)
        if raster:
            required += ("cartography.legend-consistency", "raster.classification-clarified")
        selected = self.checkers.resolve_quality_gates(gates, required=required)
        self.checkers.require_handlers(selected)
        return selected

    def reference(self, gates: dict[str, Any], scene: dict[str, Any]) -> dict[str, str]:
        selected = self.selection(gates, raster=scene["renderer_id"] == "rasterio-matplotlib-page", vector=scene["renderer_id"] == "matplotlib-vector-page")
        return {"id": "map-quality-checks", "version": self.checkers.version,
                "digest": sha256_digest({"registry": self.checkers.policy_digest, "quality_gates": gates,
                    "effective_checks": [self.checkers.definition(check_id) for check_id in selected]})}

    def inspect(self, candidate: dict[str, Any], scene: dict[str, Any], gates: dict[str, Any],
                *, profile: Any, raster: dict[str, Any] | None = None, vector: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = self.selection(gates, raster=scene["renderer_id"] == "rasterio-matplotlib-page", vector=scene["renderer_id"] == "matplotlib-vector-page")
        reference = self.reference(gates, scene)
        frozen = [ref for ref in candidate["execution"].get("policy_refs", []) if ref["id"] == reference["id"]]
        if frozen != [reference]:
            raise ProtocolError("CANDIDATE_CHECKER_SET_DRIFT", "Recompile and approve the current quality gates")
        context = {"scene": scene, "scenario_profile": profile}
        if vector is not None:
            context["vector"] = vector
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
    def _classification(_,context):
        raster=context.get('raster')
        if raster is None:raise ProtocolError('CHECKER_CONTEXT_REQUIRED','Verified raster inputs required')
        from ..compiler.page_bindings import index_by
        bindings=index_by(raster['bundle']['role_bindings'],'source_id');valid=not raster['bundle']['open_issues']
        for layer in raster['layers'].values():
            report,portrayal=layer['report'],layer['portrayal'];sid=report['request']['source']['source_ref']['id']
            valid=valid and report['status']=='ready' and not report['questions'] and portrayal['prepared_ref']==bindings[sid]['prepared_ref'] and portrayal['prepared_ref']['digest']==sha256_digest(report)
        return valid,{'panel_count':len(raster['layers']),'bundle_digest':raster['bundle']['digest']}
