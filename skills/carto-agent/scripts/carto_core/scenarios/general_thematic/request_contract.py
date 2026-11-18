"""general-thematic request_contract: the scenario's understanding of its request body.

The kernel keeps security decisions (scope/approver independence/template kind), digest
gates and the state machine; this component supplies the scenario-specific request-body
semantics the kernel used to inline: geometry discrimination, required fields, derived
capability additions, source-reference cross-checks, brief source-plan construction, and
design-override application. Moved verbatim from workflow.map_generation / compiler.map_candidate
(I-3) so behavior and error codes are preserved.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ...artifacts import file_digest
from ...canonical import sha256_digest
from ...compiler.page_bindings import index_by
from ...errors import ProtocolError
from .dispatch import geometry_of_request


class GeneralRequestContract:
    def geometry(self, request: dict[str, Any]) -> str:
        return geometry_of_request(request)

    def required_fields(self) -> frozenset[str]:
        return frozenset({"run_id", "audience", "scope", "environment", "requested_at",
                          "template", "allowed_capabilities", "font", "intent"})

    def required_capabilities(self, request: dict[str, Any]) -> set[str]:
        # Scenario-derived additions only; the kernel unions the {read, render-preview} baseline
        # and owns the CAPABILITY_NOT_AUTHORIZED security gate.
        extra: set[str] = set()
        if request.get("geometry") == "raster" or any(
                p.get("design", {}).get("kind") == "choropleth" for p in request.get("vector_panels", [])):
            extra.add("classify")
        if any(s.get("attribute_join") for s in request.get("vector_sources", [])):
            extra.add("join")
        if any(item.get("join", {}).get("required") for item in request.get("source_bindings", [])):
            extra.add("join")
        return extra

    def validate_body(self, request: dict[str, Any]) -> None:
        def identity(ref: dict[str, Any]) -> tuple[str, str, str]:
            return ref["id"], ref["version"], ref["digest"]
        if "vector_sources" in request:
            sources = index_by(request["vector_sources"], "source_id")
            roots = index_by(request["sources"], "id")
            if request.get("source_bindings") or set(sources) != set(roots) or any(
                    roots[sid]["version"] != "1.0.0" or roots[sid]["digest"] != sha256_digest(source)
                    for sid, source in sources.items()):
                raise ProtocolError("GENERATE_SOURCE_REF_MISMATCH", "Vector source declarations must match root references")
            return
        if not request.get("source_bindings"):
            raise ProtocolError("GENERATE_REQUEST_INCOMPLETE", "source_bindings")
        if {identity(item) for item in request["sources"]} != {identity(item["source_ref"]) for item in request["source_bindings"]}:
            raise ProtocolError("SOURCE_REFERENCE_SET_MISMATCH", request["request_id"])

    def source_plan(self, request: dict[str, Any], path_guard: Any, project_root: Path) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for binding in sorted(request.get("source_bindings", []), key=lambda item: item["role"]):
            operations = [item for item in ("read", "filter", "join", "classify", "reproject")
                          if item in request["allowed_capabilities"]]
            plan.append({"role": binding["role"], "source_ref": binding["source_ref"],
                         "allowed_operations": operations, "path_digest": file_digest(
                             path_guard.resolve(binding["path"], base_root=project_root, must_exist=True)),
                         "field_bindings": [{"semantic_role": item["semantic_role"],
                                             "source_field": item["source_field"]}
                                            for item in binding.get("field_bindings", [])]})
        if "vector_sources" in request:
            for source in sorted(request["vector_sources"], key=lambda item: item["source_id"]):
                actual = []
                for item in sorted(source["files"], key=lambda item: item["extension"]):
                    path = path_guard.resolve(item["path"], base_root=project_root, must_exist=True)
                    if path.stat().st_size != item["size_bytes"] or file_digest(path) != item["digest"]:
                        raise ProtocolError("VECTOR_SOURCE_CHANGED", "Vector sidecars differ from their declaration")
                    actual.append({"extension": item["extension"], "digest": item["digest"], "size_bytes": item["size_bytes"]})
                fields = sorted({p["design"]["field"] for p in request["vector_panels"]
                                 if p["source_id"] == source["source_id"] and p["design"]["field"] is not None})
                fields = sorted(set(fields) | {p["design"]["normalization"]["denominator_field"]
                                               for p in request["vector_panels"]
                                               if p["source_id"] == source["source_id"] and p["design"].get("normalization")})
                plan.append({"role": source["role"],
                             "source_ref": next(r for r in request["sources"] if r["id"] == source["source_id"]),
                             "allowed_operations": [v for v in ("read", "join", "classify") if v in request["allowed_capabilities"]],
                             "path_digest": sha256_digest({"geometry": actual, "attribute_join": source.get("attribute_join")}),
                             "field_bindings": [{"semantic_role": "thematic-value", "source_field": f} for f in fields]})
        return plan

    def override_keys(self) -> tuple[str, ...]:
        return ("revised_cartography", "output_profile")

    def apply_overrides(self, overrides: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any]:
        # R6: revised_cartography -> embedded cartography; R6b: output_profile -> canvas mm.
        if overrides.get("revised_cartography"):
            contracts.setdefault("scenario", {}).setdefault("embedded", {})
            contracts["scenario"]["embedded"]["cartography"] = deepcopy(overrides["revised_cartography"])
        if overrides.get("output_profile"):
            contracts.setdefault("scenario", {}).setdefault("embedded", {}).setdefault("layout", {}).setdefault("canvas", {})
            op = overrides["output_profile"]
            if "width_mm" in op:
                contracts["scenario"]["embedded"]["layout"]["canvas"]["width"] = op["width_mm"]
            if "height_mm" in op:
                contracts["scenario"]["embedded"]["layout"]["canvas"]["height"] = op["height_mm"]
        return contracts


REQUEST_CONTRACT = GeneralRequestContract()