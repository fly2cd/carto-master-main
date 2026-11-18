"""``carto schema`` — schema self-check and document validation."""
from __future__ import annotations

from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard


def register(sub) -> None:
    schema = sub.add_parser("schema", help="Check schemas or validate a document")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_sub.add_parser("check", help="Validate every registered JSON Schema")
    validate = schema_sub.add_parser("validate", help="Validate JSON/YAML against a named schema")
    validate.add_argument("schema_name")
    validate.add_argument("instance")
    validate.add_argument("--allowed-root", action="append", required=True)


def handle(args) -> dict:
    if args.schema_command == "check":
        checked = SchemaRegistry().check_all()
        return {"checked": len(checked), "schemas": checked}
    if args.schema_command == "validate":
        path = PathGuard(args.allowed_root).resolve(args.instance, must_exist=True)
        SchemaRegistry().validate(args.schema_name, load_document(path))
        return {"schema": args.schema_name, "instance": str(path)}
    raise ValueError(f"unknown schema command: {args.schema_command}")