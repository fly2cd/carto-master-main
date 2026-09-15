from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .errors import CartoError
from .schema_registry import SchemaRegistry, load_document
from .security.approval import ApprovalReceipt, SqliteNonceStore, verify_receipt
from .security.paths import PathGuard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carto", description="Carto Agent controlled CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    schema = sub.add_parser("schema", help="Check schemas or validate a document")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_sub.add_parser("check", help="Validate every registered JSON Schema")
    validate = schema_sub.add_parser("validate", help="Validate JSON/YAML against a named schema")
    validate.add_argument("schema_name")
    validate.add_argument("instance")
    validate.add_argument("--allowed-root", action="append", required=True)

    security = sub.add_parser("security", help="Security boundary utilities")
    security_sub = security.add_subparsers(dest="security_command", required=True)
    check_path = security_sub.add_parser("check-path")
    check_path.add_argument("path")
    check_path.add_argument("--allowed-root", action="append", required=True)
    check_path.add_argument("--must-exist", action="store_true")

    approval = sub.add_parser("approval", help="Verify a trusted approval receipt")
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    verify = approval_sub.add_parser("verify")
    verify.add_argument("receipt")
    verify.add_argument("--allowed-root", action="append", required=True)
    verify.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
    verify.add_argument("--action", required=True)
    verify.add_argument("--object-digest", required=True)
    verify.add_argument("--scope", required=True)
    verify.add_argument("--policy-id", required=True)
    verify.add_argument("--tenant-id", required=True)
    verify.add_argument("--issuer", required=True)
    verify.add_argument("--subject-id", required=True)
    verify.add_argument("--object-type", required=True)
    verify.add_argument("--environment", required=True)
    verify.add_argument("--nonce-db", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "schema" and args.schema_command == "check":
            checked = SchemaRegistry().check_all()
            return _success({"checked": len(checked), "schemas": checked})
        if args.command == "schema" and args.schema_command == "validate":
            path = PathGuard(args.allowed_root).resolve(args.instance, must_exist=True)
            SchemaRegistry().validate(args.schema_name, load_document(path))
            return _success({"schema": args.schema_name, "instance": str(path)})
        if args.command == "security" and args.security_command == "check-path":
            path = PathGuard(args.allowed_root).resolve(args.path, must_exist=args.must_exist)
            return _success({"path": str(path)})
        if args.command == "approval" and args.approval_command == "verify":
            path_guard = PathGuard(args.allowed_root)
            path = path_guard.resolve(args.receipt, must_exist=True)
            nonce_db = path_guard.resolve(args.nonce_db)
            value = load_document(path)
            SchemaRegistry().validate("approval-receipt", value)
            key = os.environ.get(args.key_env, "").encode("utf-8")
            verify_receipt(
                ApprovalReceipt.from_dict(value), key, SqliteNonceStore(str(nonce_db)),
                expected_action=args.action, expected_object_digest=args.object_digest,
                expected_scope=args.scope, expected_policy_id=args.policy_id,
                expected_tenant_id=args.tenant_id,
                expected_issuer=args.issuer, expected_subject_id=args.subject_id,
                expected_object_type=args.object_type, expected_environment=args.environment,
            )
            return _success({"receipt": str(path), "verified": True})
    except (CartoError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, CartoError) else "UNEXPECTED_ERROR"
        print(json.dumps({"ok": False, "code": code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


def _success(payload: dict[str, object]) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
