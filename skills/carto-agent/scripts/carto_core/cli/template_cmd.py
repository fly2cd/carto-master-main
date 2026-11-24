"""``carto create-template`` — the U-P2 template creation workflow."""
from __future__ import annotations

from ..errors import ProtocolError
from ..workflow.template_workflow import TemplateCreationWorkflow
from ..workflow.segment_workflow import create_workflow_for_request
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
    import_draft = create_sub.add_parser(
        "import-draft",
        help="A->B deferred publication: import a finished creation run's draft/evidence into a new publication run")
    _add_template_paths(import_draft)
    brief = create_sub.add_parser("brief", help="Build the template brief (design intent record, not an approval object)")
    _add_template_paths(brief)
    author = create_sub.add_parser("author", help="Author a deterministic draft package in staging (no approval required)")
    _add_template_paths(author)
    validate_template = create_sub.add_parser("validate", help="Validate and render the staged scenario validation input")
    _add_template_paths(validate_template)
    validate_template.add_argument("--attestation-key-env", default="CARTO_RENDER_ATTESTATION_KEY")
    validate_template.add_argument("--browser")
    validate_template.add_argument("--font")
    validate_template.add_argument("--repository-root")
    validate_template.add_argument("--repository-scope")
    validate_template.add_argument("--publication-request",
                                   help="Trusted ready publication-request; without it validate ends at validated-draft")
    prepare = create_sub.add_parser("prepare-publish", help="Freeze the operator-approved publication object (machine step, no nonce)")
    _add_template_paths(prepare)
    prepare.add_argument("--repository-root", required=True)
    prepare.add_argument("--repository-scope", required=True)
    prepare.add_argument("--idempotency-key", required=True)
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
    ref_prepare = create_sub.add_parser(
        "reference-prepare",
        help="Prepare a NON-authoritative draft segment request from a reference image (intake->extract->assemble)")
    ref_prepare.add_argument("config", help="YAML config: image, base_design and segment-create-request metadata")
    ref_prepare.add_argument("--project-root", required=True)
    ref_prepare.add_argument("--workdir", required=True)
    ref_prepare.add_argument("--allowed-root", action="append", required=True)
    ref_prepare.add_argument("--output", default="segment-request.yaml",
                             help="Draft request output path relative to project-root")


def handle(args) -> dict:
    if args.create_command == "render":
        raise ProtocolError(
            "CAPABILITY_NOT_AVAILABLE",
            "create-template render is not standalone; Fixture rendering runs inside validate",
        )
    if args.create_command == "reference-prepare":
        return _reference_prepare(args)
    if args.create_command in {"status", "retry", "receipts"}:
        workflow = TemplateCreationWorkflow(
            allowed_roots=args.allowed_root,
            project_root=args.project_root,
            workdir=args.workdir,
        )
    else:
        workflow = create_workflow_for_request(
            args.request, allowed_roots=args.allowed_root,
            project_root=args.project_root, workdir=args.workdir,
        )
    if args.create_command == "analyze":
        return workflow.analyze(args.request)
    if args.create_command == "import-draft":
        from ..workflow.segment_workflow import SegmentCreationWorkflow
        if not isinstance(workflow, SegmentCreationWorkflow):
            raise ProtocolError("TEMPLATE_KIND_UNSUPPORTED", "import-draft is a segment publication entry")
        return workflow.import_draft(args.request)
    if args.create_command == "brief":
        return workflow.brief(args.request)
    if args.create_command == "author":
        return workflow.author(args.request)
    if args.create_command == "validate":
        validate_kwargs = dict(attestation_key=attestation_key(args), browser=args.browser,
                               font_path=args.font, repository_root=args.repository_root,
                               repository_scope=args.repository_scope)
        if args.publication_request is not None:
            validate_kwargs["publication_request"] = args.publication_request
        return workflow.validate(args.request, **validate_kwargs)
    if args.create_command == "prepare-publish":
        return workflow.prepare_publication(
            args.request, repository_root=args.repository_root,
            repository_scope=args.repository_scope, idempotency_key=args.idempotency_key,
        )
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


def _reference_prepare(args) -> dict:
    """Reference-image pre-entry: produce a draft segment request for human confirmation.

    Reads a YAML config (image + base_design + request metadata), runs the safe intake ->
    extraction -> assembly orchestration, freezes reference evidence under workdir/reference
    and writes the draft request. The draft is NOT auto-ingested; the user confirms it and
    runs the ordinary create-template analyze/brief/author/validate/publish chain.
    """
    from pathlib import Path
    from ..artifacts import atomic_yaml
    from ..schema_registry import load_document
    from ..security.paths import PathGuard
    from ..workflow.reference_segment import prepare_reference_segment_request
    guard = PathGuard(args.allowed_root)
    proj = guard.resolve(args.project_root, must_exist=True)
    config = load_document(guard.resolve(args.config, must_exist=True))
    if not isinstance(config, dict):
        raise ProtocolError("REFERENCE_CONFIG_INVALID", "config must be an object")
    config = dict(config)
    image = config.pop("image")
    base_design = config.pop("base_design")
    image_path = Path(image)
    if not image_path.is_absolute():
        image_path = proj / image_path
    work = guard.resolve(proj / args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    result = prepare_reference_segment_request(
        guard, image_path, work_root=work, base_design=base_design, **config)
    out_path = guard.resolve(proj / args.output)
    atomic_yaml(out_path, result["request"])
    return {
        "request_path": str(out_path),
        "proposal_id": result["proposal"]["proposal_id"],
        "recovery_error_delta_e2000": result["recovery_error_delta_e2000"],
        "intake_digest": result["intake"]["source_image"]["digest"],
        "unrecoverable": result["proposal"]["unrecoverable"],
    }