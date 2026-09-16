from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .adapters.renderer_probe import RendererCapabilityProbe
from .errors import CartoError
from .schema_registry import SchemaRegistry, load_document
from .security.approval import ApprovalReceipt, SqliteNonceStore, verify_receipt
from .security.paths import PathGuard
from .workflow.data_preparation import DeterministicDataPreparer
from .workflow.intent import IntentResolver
from .workflow.models import ExecutionContext


def _policy_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "policies" / name


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

    intent = sub.add_parser("intent", help="Resolve a typed map intent")
    intent_sub = intent.add_subparsers(dest="intent_command", required=True)
    resolve = intent_sub.add_parser("resolve")
    resolve.add_argument("request")
    resolve.add_argument("--allowed-root", action="append", required=True)

    environment = sub.add_parser("environment", help="Probe renderer capabilities")
    environment_sub = environment.add_subparsers(dest="environment_command", required=True)
    environment_sub.add_parser("probe-renderer")

    data = sub.add_parser("data", help="Run deterministic data preparation")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    prepare = data_sub.add_parser("prepare")
    prepare.add_argument("task")
    prepare.add_argument("--allowed-root", action="append", required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--tenant-id", required=True)
    prepare.add_argument("--project-id", required=True)
    prepare.add_argument("--subject-id", required=True)
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
        if args.command == "intent" and args.intent_command == "resolve":
            path = PathGuard(args.allowed_root).resolve(args.request, must_exist=True)
            request = load_document(path)
            if not isinstance(request, dict):
                raise ValueError("Intent request must be an object")
            result = IntentResolver(_policy_path("intent-profiles.yaml")).resolve(request)
            return _success({"intent": result})
        if args.command == "environment" and args.environment_command == "probe-renderer":
            result = RendererCapabilityProbe().run()
            SchemaRegistry().validate("environment-fingerprint", result)
            return _success({"environment": result})
        if args.command == "data" and args.data_command == "prepare":
            path = PathGuard(args.allowed_root).resolve(args.task, must_exist=True)
            task = load_document(path)
            if not isinstance(task, dict):
                raise ValueError("Data preparation task must be an object")
            context = ExecutionContext(
                run_id=args.run_id,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                subject_id=args.subject_id,
                roles=frozenset({"operator"}),
                namespaces=frozenset({args.project_id}),
                authorized_capabilities=frozenset(),
            )
            result = DeterministicDataPreparer(_policy_path("data-preparation-policy.yaml")).prepare_data(task, context)
            return _success({"bundle": result})
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
