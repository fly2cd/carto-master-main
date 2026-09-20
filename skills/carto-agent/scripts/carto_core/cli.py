from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .adapters.renderer_probe import RendererCapabilityProbe
from .errors import CartoError, ProtocolError
from .schema_registry import SchemaRegistry, load_document
from .security.approval import ApprovalReceipt, SqliteNonceStore, verify_receipt
from .security.paths import PathGuard
from .workflow.data_preparation import DeterministicDataPreparer
from .workflow.intent import IntentResolver
from .workflow.map_generation import MapGenerationWorkflow
from .workflow.models import ExecutionContext
from .workflow.template_workflow import TemplateCreationWorkflow


def _policy_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "policies" / name


def _add_template_paths(parser: argparse.ArgumentParser, *, request: bool = True) -> None:
    if request:
        parser.add_argument("request")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--allowed-root", action="append", required=True)


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

    create = sub.add_parser("create-template", help="Run the U-P2 template creation workflow")
    create_sub = create.add_subparsers(dest="create_command", required=True)
    analyze = create_sub.add_parser("analyze", help="Register and analyze controlled sources")
    _add_template_paths(analyze)
    brief = create_sub.add_parser("brief", help="Build the independently approved template brief")
    _add_template_paths(brief)
    author = create_sub.add_parser("author", help="Author an approved draft package in staging")
    _add_template_paths(author)
    author.add_argument("--approval", required=True)
    author.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
    author.add_argument("--policy-id", default="carto-security")
    author.add_argument("--issuer", required=True)
    author.add_argument("--nonce-db", required=True)
    validate_template = create_sub.add_parser("validate", help="Validate and render the staged synthetic Fixture")
    _add_template_paths(validate_template)
    validate_template.add_argument("--attestation-key-env", default="CARTO_RENDER_ATTESTATION_KEY")
    validate_template.add_argument("--browser")
    validate_template.add_argument("--font")
    publish = create_sub.add_parser("publish", help="Publish an exactly validated template version")
    _add_template_paths(publish)
    publish.add_argument("--approval", required=True)
    publish.add_argument("--repository-root", required=True)
    publish.add_argument("--repository-scope", required=True)
    publish.add_argument("--idempotency-key", required=True)
    publish.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
    publish.add_argument("--attestation-key-env", default="CARTO_RENDER_ATTESTATION_KEY")
    publish.add_argument("--policy-id", default="carto-security")
    publish.add_argument("--issuer", required=True)
    publish.add_argument("--nonce-db", required=True)
    status = create_sub.add_parser("status", help="Read current template workflow state")
    _add_template_paths(status, request=False)
    retry = create_sub.add_parser("retry", help="Retry the current failed template workflow step")
    _add_template_paths(retry, request=False)
    receipts = create_sub.add_parser("receipts", help="Read immutable template workflow receipts")
    _add_template_paths(receipts, request=False)
    unavailable = create_sub.add_parser("render", help="Standalone rendering is not a template workflow step")
    _add_template_paths(unavailable, request=False)

    generate = sub.add_parser("generate-map", help="Run the U-P2 map generation workflow")
    generate_sub = generate.add_subparsers(dest="generate_command", required=True)
    for name, help_text in (
        ("intake", "Validate and register a map generation request"),
        ("brief", "Create the independently approved map brief"),
        ("compile", "Install the exact template and compile a map candidate"),
        ("preview", "Render and attest the candidate preview"),
        ("freeze", "Verify G2 approval and create an immutable MapSpecLock"),
    ):
        item = generate_sub.add_parser(name, help=help_text)
        item.add_argument("request")
        item.add_argument("--project-root", required=True)
        item.add_argument("--workdir", required=True)
        item.add_argument("--repository-root", required=True)
        item.add_argument("--repository-scope", required=True)
        item.add_argument("--allowed-root", action="append", required=True)
        if name in {"compile", "freeze"}:
            item.add_argument("--approval", required=True)
            item.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
            item.add_argument("--nonce-db", required=True)
            item.add_argument("--policy-id", default="carto-security")
            item.add_argument("--issuer", required=True)
        if name in {"preview", "freeze"}:
            item.add_argument("--attestation-key-env", default="CARTO_RENDER_ATTESTATION_KEY")
            item.add_argument("--browser")
    for name, help_text in (
        ("status", "Read current map generation state"),
        ("retry", "Retry the current failed map generation step"),
        ("receipts", "Read immutable map generation receipts"),
    ):
        item = generate_sub.add_parser(name, help=help_text)
        item.add_argument("--project-root", required=True)
        item.add_argument("--workdir", required=True)
        item.add_argument("--repository-root", required=True)
        item.add_argument("--repository-scope", required=True)
        item.add_argument("--allowed-root", action="append", required=True)
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
        if args.command == "generate-map":
            workflow = MapGenerationWorkflow(
                allowed_roots=args.allowed_root, project_root=args.project_root, workdir=args.workdir,
                repository_root=args.repository_root, repository_scope=args.repository_scope,
            )
            if args.generate_command == "intake":
                return _success(workflow.intake(args.request))
            if args.generate_command == "brief":
                return _success(workflow.brief(args.request))
            if args.generate_command == "compile":
                return _success(workflow.compile(
                    args.request, args.approval,
                    approval_key=os.environ.get(args.key_env, "").encode("utf-8"),
                    nonce_db=args.nonce_db, policy_id=args.policy_id, issuer=args.issuer,
                ))
            if args.generate_command == "preview":
                return _success(workflow.preview(
                    args.request,
                    attestation_key=os.environ.get(args.attestation_key_env, "").encode("utf-8"),
                    browser=args.browser,
                ))
            if args.generate_command == "freeze":
                return _success(workflow.freeze(
                    args.request, args.approval,
                    approval_key=os.environ.get(args.key_env, "").encode("utf-8"),
                    attestation_key=os.environ.get(args.attestation_key_env, "").encode("utf-8"),
                    nonce_db=args.nonce_db, policy_id=args.policy_id, issuer=args.issuer,
                    browser=args.browser,
                ))
            if args.generate_command == "status":
                return _success(workflow.status())
            if args.generate_command == "retry":
                return _success(workflow.retry())
            if args.generate_command == "receipts":
                return _success(workflow.receipts())
        if args.command == "create-template":
            if args.create_command == "render":
                raise ProtocolError(
                    "CAPABILITY_NOT_AVAILABLE",
                    "create-template render is not standalone; Fixture rendering runs inside validate",
                )
            workflow = TemplateCreationWorkflow(
                allowed_roots=args.allowed_root,
                project_root=args.project_root,
                workdir=args.workdir,
            )
            if args.create_command == "analyze":
                return _success(workflow.analyze(args.request))
            if args.create_command == "brief":
                return _success(workflow.brief(args.request))
            if args.create_command == "author":
                key = os.environ.get(args.key_env, "").encode("utf-8")
                return _success(
                    workflow.author(
                        args.request,
                        args.approval,
                        approval_key=key,
                        nonce_db=args.nonce_db,
                        policy_id=args.policy_id,
                        issuer=args.issuer,
                    )
                )
            if args.create_command == "validate":
                key = os.environ.get(args.attestation_key_env, "").encode("utf-8")
                return _success(workflow.validate(
                    args.request, attestation_key=key, browser=args.browser, font_path=args.font,
                ))
            if args.create_command == "publish":
                approval_key = os.environ.get(args.key_env, "").encode("utf-8")
                attestation_key = os.environ.get(args.attestation_key_env, "").encode("utf-8")
                return _success(workflow.publish(
                    args.request, args.approval, repository_root=args.repository_root,
                    repository_scope=args.repository_scope, idempotency_key=args.idempotency_key,
                    approval_key=approval_key, renderer_attestation_key=attestation_key,
                    nonce_db=args.nonce_db, policy_id=args.policy_id, issuer=args.issuer,
                ))
            if args.create_command == "status":
                return _success(workflow.status())
            if args.create_command == "retry":
                return _success(workflow.retry())
            if args.create_command == "receipts":
                return _success(workflow.receipts())
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