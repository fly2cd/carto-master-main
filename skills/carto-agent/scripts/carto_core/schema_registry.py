from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from .errors import ProtocolError, SecurityError

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_DEPTH = 64
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def default_schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas"


def load_document(path: Path) -> Any:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise SecurityError("DOCUMENT_TOO_LARGE", f"Document exceeds {MAX_DOCUMENT_BYTES} bytes")
    suffix = path.suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise ProtocolError("DOCUMENT_TYPE_UNSUPPORTED", f"Unsupported document type: {suffix}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("DOCUMENT_ENCODING_INVALID", "Document must be UTF-8") from exc
    try:
        value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ProtocolError("DOCUMENT_PARSE_FAILED", str(exc)) from exc
    _check_depth(value)
    return value


def _check_depth(value: Any, depth: int = 0, active: set[int] | None = None) -> None:
    if depth > MAX_DOCUMENT_DEPTH:
        raise SecurityError("DOCUMENT_TOO_DEEP", f"Document depth exceeds {MAX_DOCUMENT_DEPTH}")
    active = active if active is not None else set()
    if isinstance(value, (dict, list)):
        identity = id(value)
        if identity in active:
            raise SecurityError("DOCUMENT_CYCLIC", "Document contains a cyclic YAML alias")
        active.add(identity)
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError("DOCUMENT_KEY_INVALID", "Mapping keys must be strings")
            _check_depth(item, depth + 1, active)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1, active)
    if isinstance(value, (dict, list)):
        active.remove(id(value))


class SchemaRegistry:
    def __init__(self, schema_root: Path | None = None) -> None:
        self.schema_root = (schema_root or default_schema_root()).resolve(strict=True)
        self.schemas: dict[str, dict[str, Any]] = {}
        resources: list[tuple[str, Resource[Any]]] = []
        for path in sorted(self.schema_root.glob("*.schema.json")):
            schema = load_document(path)
            if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
                raise ProtocolError("SCHEMA_ID_MISSING", f"Schema has no $id: {path.name}")
            if schema.get("$schema") != SCHEMA_DIALECT:
                raise ProtocolError(
                    "SCHEMA_DIALECT_INVALID",
                    f"Schema must use JSON Schema Draft 2020-12: {path.name}",
                )
            name = path.name.removesuffix(".schema.json")
            if name in self.schemas:
                raise ProtocolError("SCHEMA_NAME_DUPLICATE", f"Duplicate schema name: {name}")
            if any(uri == schema["$id"] for uri, _ in resources):
                raise ProtocolError("SCHEMA_ID_DUPLICATE", f"Duplicate schema $id: {schema['$id']}")
            self.schemas[name] = schema
            resources.append((schema["$id"], Resource.from_contents(schema)))
        if not self.schemas:
            raise ProtocolError("SCHEMA_REGISTRY_EMPTY", f"No schemas found in: {self.schema_root}")
        self.registry = Registry().with_resources(resources)

    def check_all(self) -> list[str]:
        checked: list[str] = []
        for name, schema in self.schemas.items():
            validator_class = validator_for(schema)
            validator_class.check_schema(schema)
            validator_class(schema, registry=self.registry, format_checker=FormatChecker())
            checked.append(name)
        return checked

    def validate(self, schema_name: str, instance: Any) -> None:
        try:
            schema = self.schemas[schema_name]
        except KeyError as exc:
            raise ProtocolError("SCHEMA_NOT_FOUND", f"Unknown schema: {schema_name}") from exc
        validator_class = validator_for(schema)
        validator = validator_class(
            schema,
            registry=self.registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
        if errors:
            first = errors[0]
            path = "/" + "/".join(str(part) for part in first.absolute_path)
            raise ProtocolError(
                "SCHEMA_VALIDATION_FAILED",
                f"{schema_name}{path}: {first.message}",
                {"schema": schema_name, "path": path, "error_count": len(errors)},
            )
