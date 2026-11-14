"""Explicit thematic semantics and deterministic attribute/encoding execution.

No automatic method selection, unit inference, business-data logging or code evaluation.
"""
from copy import deepcopy
import math
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry


def expression_reference(kind, registry=None):
    from ..repository.map_expression_catalog import MapExpressionCatalog
    choices = {"single":"categorical", "categorical":"categorical",
               "choropleth":"graduated-color", "proportional":"proportional-symbol"}
    if kind not in choices:
        raise ProtocolError("THEMATIC_METHOD_UNSUPPORTED", "An admitted expression method is required")
    catalog=MapExpressionCatalog(registry)
    ref=catalog.reference(choices[kind], "2.0.0")
    if catalog.require(ref)["status"] != "active":
        raise ProtocolError("THEMATIC_METHOD_UNSUPPORTED", "The selected expression is not active")
    return ref


def metric_value(properties, domain):
    field = domain.get("field")
    value = properties.get(field) if field else None
    normalization = domain.get("normalization")
    if normalization is None or value is None:
        return value
    denominator = properties.get(normalization["denominator_field"])
    if not finite(value) or not finite(denominator) or denominator <= 0:
        raise ProtocolError("THEMATIC_DENOMINATOR_INVALID", "Normalization requires finite values and a positive denominator")
    result = value / denominator * normalization["scale"]
    if not finite(result):
        raise ProtocolError("THEMATIC_VALUE_INVALID", "Derived metric is not finite")
    return result


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def equal_interval_edges(low, high, count):
    """Shared equal-interval break computation for raster & vector choropleth (ADR-001 阶段2.3)."""
    if low == high:
        raise ProtocolError("THEMATIC_CONSTANT_DOMAIN", "Equal intervals need a nonconstant domain; select another explicit expression")
    edges = [low + (high - low) * i / count for i in range(count)] + [high]
    labels = [f"Class {i+1}" for i in range(count)]
    return edges, labels


def _domain(design):
    return {"field": design["field"], "measurement": design["measurement"],
            "unit": design["unit"], "normalization": design.get("normalization")}


def _design_to_ir(design, stats):
    """Map a kind-based thematic-design into the geometry-agnostic encoding IR (ADR-001 stage 2)."""
    kind = design["kind"]
    geometry_role = design["geometry"]
    missing = deepcopy(design["missing"])
    domain = _domain(design)
    if kind == "single":
        return {"schema_version": 1, "key_mode": "discrete", "geometry_role": geometry_role, "domain": domain,
                "scale": {"categories": []},
                "channels": {"symbols": [deepcopy(design["symbol"])], "shape": "auto"},
                "missing": missing, "legend": {"policy": "all", "uniform_label": design["label"]}}
    if kind == "categorical":
        return {"schema_version": 1, "key_mode": "discrete", "geometry_role": geometry_role, "domain": domain,
                "scale": {"categories": [{"value": c["value"], "label": c["label"]} for c in design["categories"]]},
                "channels": {"symbols": [deepcopy(c["symbol"]) for c in design["categories"]], "shape": "auto"},
                "missing": missing, "legend": {"policy": design["legend_policy"]}}
    if kind == "choropleth":
        classification = design["classification"]
        if classification["method"] == "equal-interval":
            edges, labels = equal_interval_edges(stats["minimum"], stats["maximum"], classification["class_count"])
        else:
            edges, labels = classification["edges"], classification["labels"]
        return {"schema_version": 1, "key_mode": "interval", "geometry_role": geometry_role, "domain": domain,
                "scale": {"edges": edges, "labels": labels, "interval_policy": "left-closed-last-both", "out_of_range": "reject"},
                "channels": {"symbols": deepcopy(design["symbols"]), "shape": "auto"},
                "missing": missing, "legend": {"policy": "all"}}
    return {"schema_version": 1, "key_mode": "scaling", "geometry_role": geometry_role, "domain": domain,
            "scale": {"domain_max": design["maximum_value"], "range_mm": [design["minimum_radius_mm"], design["maximum_radius_mm"]],
                      "size_scale": "sqrt", "zero_policy": design["zero_policy"], "negative_policy": design["negative_policy"],
                      "out_of_range": design["out_of_range"], "legend_values": design["legend_values"]},
            "channels": {"symbols": [deepcopy(design["symbol"])], "shape": "auto"},
            "missing": missing, "legend": {"policy": "all"}}


def resolve_design(design, report, registry=None):
    registry = registry or SchemaRegistry()
    registry.validate("thematic-design", design)
    if design["geometry"] != report["geometry"]:
        raise ProtocolError("THEMATIC_GEOMETRY_MISMATCH", "Design must match the source geometry")
    kind = design["kind"]
    if kind == "proportional" and design.get("normalization") is not None:
        raise ProtocolError("THEMATIC_MEASUREMENT_INVALID", "Count symbols cannot silently normalize their values")
    domain = _domain(design)
    values = [metric_value(feature["properties"], domain) for feature in report["features"]]
    numeric = [value for value in values if value is not None]
    if kind in {"choropleth", "proportional"} and (not numeric or any(not finite(v) for v in numeric)):
        raise ProtocolError("THEMATIC_VALUE_INVALID", "A numeric expression requires observed finite numeric values")
    stats = {"count": len(numeric), "minimum": min(numeric) if numeric and all(finite(v) for v in numeric) else None,
             "maximum": max(numeric) if numeric and all(finite(v) for v in numeric) else None}
    ir = _design_to_ir(design, stats)
    from ..compiler.vector_portrayal import resolve_features
    # Validate the actual values, all interval coverage, missing policy and symbol domains now.
    resolve_features(report, ir, registry)
    return ir, stats


def vector_views(request, bundle, service, context):
    from ..compiler.portrayal_resolver import ir_to_kind
    bindings = {item["source_id"]: item for item in bundle["role_bindings"]}
    results = []
    for panel in sorted(request["vector_panels"], key=lambda p:p["id"]):
        binding = bindings[panel["source_id"]]
        report = service.load_verified(binding["prepared_ref"], context)
        encoding, statistics = resolve_design(panel["design"], report, service.registry)
        results.append({"view_id":panel["id"], "source_id":panel["source_id"], "data_ref":deepcopy(binding["prepared_ref"]),
                        "design":deepcopy(panel["design"]), "expression_ref":expression_reference(ir_to_kind(encoding),service.registry), "encoding":encoding, "statistics":statistics})
    return results


def raster_views(request, bundle, registry):
    bindings = {item["source_id"]:item for item in bundle["role_bindings"]}
    result = []
    for panel in sorted(request["panels"],key=lambda p:p["id"]):
        registry.validate("thematic-design",panel["design"])
        if panel["design"]["geometry"] != "raster":
            raise ProtocolError("THEMATIC_GEOMETRY_MISMATCH", "Raster panels require an explicit raster design")
        result.append({"view_id":panel["id"], "source_id":panel["source_id"], "data_ref":deepcopy(bindings[panel["source_id"]]["prepared_ref"]),
                       "design":deepcopy(panel["design"]), "expression_ref":expression_reference("categorical",registry), "encoding":None, "statistics":None})
    return result


def join_attributes(service, report, binding, asset=None):
    """Exact string-key join. Uses A2 extraction, snapshots bytes, never guesses keys/types."""
    service.registry.validate("thematic-attribute-join",binding)
    if asset is None:
        path = service.guard.resolve(binding["path"],base_root=service.project,must_exist=True)
        data = service.read_bytes(path,1048576)
        if len(data)!=binding["size_bytes"] or service.digest_bytes(data)!=binding["digest"]:
            raise ProtocolError("THEMATIC_TABLE_DRIFT", "Attribute source differs from its approved bytes")
        asset=service._asset(data,"attribute-table",".csv")
    else:
        data=service.snapshot_bytes(asset,"attribute-table",".csv")
        if service.digest_bytes(data)!=binding["digest"] or len(data)!=binding["size_bytes"]:
            raise ProtocolError("THEMATIC_TABLE_DRIFT", "Frozen table differs from its approved source")
    from .material_extraction import CsvExtractor
    try:
        extraction=CsvExtractor(service.registry).extract(service.project_guard.resolve(asset["artifact_ref"]["uri"],must_exist=True),service.guard,binding["source_id"],"text/csv").body
    except (ProtocolError, SecurityError):
        raise ProtocolError("THEMATIC_TABLE_INVALID","Attribute CSV failed bounded extraction") from None
    fields=binding["fields"]
    if len({f["field"] for f in fields})!=len(fields):
        raise ProtocolError("THEMATIC_FIELD_DUPLICATE","Target attribute fields must be unique")
    required={binding["table_key"], *[f["column"] for f in fields]}
    if not required <= {f["name"] for f in extraction["fields"]}:
        raise ProtocolError("THEMATIC_FIELD_MISSING","Declared table columns are missing")
    rows={}
    for row in extraction["rows"]:
        key=row["cells"][binding["table_key"]]
        if not isinstance(key,str) or not key or key in rows:
            raise ProtocolError("THEMATIC_JOIN_KEY_INVALID","Table keys must be nonempty unique strings")
        rows[key]=row
    seen=set();matches=[]
    for feature in report["features"]:
        props=feature["properties"];key=props.get(binding["geometry_key"])
        if not isinstance(key,str) or not key or key in seen or key not in rows:
            raise ProtocolError("THEMATIC_JOIN_COVERAGE","Geometry keys must be unique and match the table exactly")
        seen.add(key);row=rows[key]
        for field in fields:
            target=field["field"]
            if target in props:
                raise ProtocolError("THEMATIC_FIELD_COLLISION","Join must not overwrite existing attributes")
            cell=row["cells"][field["column"]]
            if cell=="":
                if binding["missing_policy"]=="reject":raise ProtocolError("THEMATIC_VALUE_MISSING","Selected attribute is missing")
                value=None
            elif field["value_type"]=="string":value=cell
            else:
                try:value=float(cell)
                except (TypeError,ValueError):raise ProtocolError("THEMATIC_VALUE_INVALID","Selected attribute is not numeric") from None
                if not finite(value):raise ProtocolError("THEMATIC_VALUE_INVALID","Selected numeric value must be finite")
            props[target]=value
        matches.append({"feature_id":feature["id"],"row_index":row["index"]})
    if seen!=set(rows):raise ProtocolError("THEMATIC_JOIN_COVERAGE","Unmatched table rows are not implicitly discarded")
    return {"asset":asset,"extraction_digest":sha256_digest({"source":binding["digest"],"fields":extraction["fields"],"rows":extraction["rows"]}),
            "matches":matches,"join_digest":sha256_digest(binding)}
