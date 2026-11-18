"""``carto create-template`` — the U-P2 template creation workflow."""
from __future__ import annotations

from ..errors import ProtocolError
from ..workflow.template_workflow import TemplateCreationWorkflow
from ._shared import approval_key, attestation_key


def _add_template_paths(parser, *, request: bool = True) -> None:
    if request:
        parser.add_argument("request")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--allowed-root", action="append", required=True)


def register(sub) -> None:
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
    validate_template = create_sub.add_parser("validate", help="Validate and render the staged scenario validation input")
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
    status = create_sub.add_parser("status", help="Read current template workflow state")
    _add_template_paths(status, request=False)
    retry = create_sub.add_parser("retry", help="Retry the current failed template workflow step")
    _add_template_paths(retry, request=False)
    receipts = create_sub.add_parser("receipts", help="Read immutable template workflow receipts")
    _add_template_paths(receipts, request=False)
    unavailable = create_sub.add_parser("render", help="Standalone rendering is not a template workflow step")
    _add_template_paths(unavailable, request=False)


def handle(args) -> dict:
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
        return workflow.analyze(args.request)
    if args.create_command == "brief":
        return workflow.brief(args.request)
    if args.create_command == "author":
        return workflow.author(args.request, args.approval, approval_key=approval_key(args))
    if args.create_command == "validate":
        return workflow.validate(args.request, attestation_key=attestation_key(args),
                                 browser=args.browser, font_path=args.font)
    if args.create_command == "publish":
        return workflow.publish(
            args.request, args.approval, repository_root=args.repository_root,
            repository_scope=args.repository_scope, idempotency_key=args.idempotency_key,
            approval_key=approval_key(args), renderer_attestation_key=attestation_key(args),
        )
    if args.create_command == "status":
        return workflow.status()
    if args.create_command == "retry":
        return workflow.retry()
    if args.create_command == "receipts":
        return workflow.receipts()
    raise ValueError(f"unknown create-template command: {args.create_command}")