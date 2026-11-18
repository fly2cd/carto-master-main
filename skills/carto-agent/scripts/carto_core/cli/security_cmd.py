"""``carto security`` and ``carto approval`` — security boundary utilities."""
from __future__ import annotations

import os

from ..schema_registry import SchemaRegistry, load_document
from ..security.approval import ApprovalReceipt, verify_receipt
from ..security.paths import PathGuard


def register(sub) -> None:
    security = sub.add_parser("security", help="Security boundary utilities")
    security_sub = security.add_subparsers(dest="security_command", required=True)
    check_path = security_sub.add_parser("check-path")
    check_path.add_argument("path")
    check_path.add_argument("--allowed-root", action="append", required=True)
    check_path.add_argument("--must-exist", action="store_true")

    approval = sub.add_parser("approval", help="Verify a signed approval receipt")
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    verify = approval_sub.add_parser("verify")
    verify.add_argument("receipt")
    verify.add_argument("--allowed-root", action="append", required=True)
    verify.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
    verify.add_argument("--action", required=True)
    verify.add_argument("--object-type", required=True)
    verify.add_argument("--object-digest", required=True)
    verify.add_argument("--subject-id")
    verify.add_argument("--tenant-id")
    verify.add_argument("--scope")


def handle(args) -> dict:
    if args.command == "security":
        path = PathGuard(args.allowed_root).resolve(args.path, must_exist=args.must_exist)
        return {"path": str(path)}
    if args.command == "approval":
        path_guard = PathGuard(args.allowed_root)
        path = path_guard.resolve(args.receipt, must_exist=True)
        value = load_document(path)
        SchemaRegistry().validate("approval-receipt", value)
        key = os.environ.get(args.key_env, "").encode("utf-8")
        verify_receipt(
            ApprovalReceipt.from_dict(value), key,
            expected_action=args.action,
            expected_object_type=args.object_type,
            expected_object_digest=args.object_digest,
            expected_subject_id=args.subject_id,
            expected_tenant_id=args.tenant_id,
            expected_scope=args.scope,
        )
        return {"receipt": str(path), "verified": True}
    raise ValueError(f"unknown security/approval command: {args.command}")