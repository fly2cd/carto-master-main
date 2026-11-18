"""Evidenced exact CSV attribute join (mechanical vector-data infrastructure).

Moved verbatim from ``workflow/thematic.py`` (I-5 dissolution). This is execution-layer
data-type work, not scenario orchestration: it joins a frozen attribute table to vector
features by exact string key, snapshots bytes, and never guesses keys/types. The scenario
request-body view assembly (vector_views/raster_views) moved into the scenario package.
"""
from __future__ import annotations

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..compiler.portrayal_resolver import finite


def join_attributes(service, report, binding, asset=None):
    """Exact string-key join. Uses A2 extraction, snapshots bytes, never guesses keys/types."""
    service.registry.validate("thematic-attribute-join",binding)
    if asset is None:
        path = service.guard.resolve(binding["path"],base_root=service.project,must_exist=True)
        data = service.read_bytes(path,1048576)
        if len(data)!=binding["size_bytes"] or service.digest_bytes(data)!=binding["digest"]:
            raise ProtocolError("THEMATIC_TABLE_DRIFT", "Attribute source differs from its approved bytes")
        asset=service.store_asset(data,"attribute-table",".csv")
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