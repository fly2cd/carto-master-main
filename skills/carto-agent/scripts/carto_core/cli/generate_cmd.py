"""``carto generate-map`` — the map generation workflow."""
from __future__ import annotations

from ..workflow.map_generation import MapGenerationWorkflow
from ._shared import approval_key, attestation_key


def register(sub) -> None:
    generate = sub.add_parser("generate-map", help="Run the map generation workflow")
    generate_sub = generate.add_subparsers(dest="generate_command", required=True)
    for name, help_text in (
        ("intake", "Validate and register a map generation request"),
        ("brief", "Create the independently approved map brief"),
        ("compile", "Install the exact template and compile a map candidate"),
        ("preview", "Render and attest the candidate preview"),
        ("freeze", "Verify G2 approval and create an immutable MapSpecLock"),
        ("render", "Render immutable formal PDF/PNG outputs from MapSpecLock"),
        ("check", "Auto final-check: validate rendered outputs, classify failures"),
        ("review", "Production review: approve check results and generate delivery manifest"),
        ("deliver", "Verify G3 and atomically commit the local delivery package"),
        ("revise", "Submit a design revision proposal and prepare for re-compile"),
        ("revision-brief", "Build the exact revised map brief for G1 approval"),
    ):
        item = generate_sub.add_parser(name, help=help_text)
        item.add_argument("request")
        item.add_argument("--project-root", required=True)
        item.add_argument("--workdir", required=True)
        item.add_argument("--repository-root", required=True)
        item.add_argument("--repository-scope", required=True)
        item.add_argument("--allowed-root", action="append", required=True)
        if name in {"compile", "freeze", "deliver", "revise", "review"}:
            item.add_argument("--approval", required=True)
            item.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
        if name in {"revise", "revision-brief"}:
            item.add_argument("--proposal", required=True, help="Path to the design revision proposal YAML")
        if name in {"preview", "freeze", "render", "check", "review"}:
            item.add_argument("--attestation-key-env", default="CARTO_RENDER_ATTESTATION_KEY")
            item.add_argument("--browser")
        if name == "freeze":
            item.add_argument("--design-review",
                              help="Path to an approve-design-review receipt bound to the candidate")
        if name == "review":
            item.add_argument("--recipient-id", required=True)
            item.add_argument("--recipient-type", choices=("project-user", "project-team"), required=True)
            item.add_argument("--destination", required=True)
            item.add_argument("--idempotency-key", required=True)
    for name, help_text in (
        ("status", "Read current map generation state"),
        ("retry", "Retry the current failed map generation step"),
        ("receipts", "Read immutable map generation receipts"),
        ("delivery-status", "Query a delivery transaction by idempotency key"),
    ):
        item = generate_sub.add_parser(name, help=help_text)
        item.add_argument("--project-root", required=True)
        item.add_argument("--workdir", required=True)
        item.add_argument("--repository-root", required=True)
        item.add_argument("--repository-scope", required=True)
        item.add_argument("--allowed-root", action="append", required=True)
        if name == "delivery-status":
            item.add_argument("--idempotency-key", required=True)
    select = generate_sub.add_parser("select-candidate",
                                     help="Promote one compiled candidate to the active design (multi-candidate)")
    select.add_argument("request")
    select.add_argument("--candidate-id", required=True)
    select.add_argument("--project-root", required=True)
    select.add_argument("--workdir", required=True)
    select.add_argument("--repository-root", required=True)
    select.add_argument("--repository-scope", required=True)
    select.add_argument("--allowed-root", action="append", required=True)


def handle(args) -> dict:
    workflow = MapGenerationWorkflow(
        allowed_roots=args.allowed_root, project_root=args.project_root, workdir=args.workdir,
        repository_root=args.repository_root, repository_scope=args.repository_scope,
    )
    command = args.generate_command
    if command == "intake":
        return workflow.intake(args.request)
    if command == "brief":
        return workflow.brief(args.request)
    if command == "compile":
        return workflow.compile(args.request, args.approval, approval_key=approval_key(args))
    if command == "preview":
        return workflow.preview(args.request, attestation_key=attestation_key(args), browser=args.browser)
    if command == "freeze":
        return workflow.freeze(
            args.request, args.approval,
            approval_key=approval_key(args), attestation_key=attestation_key(args),
            browser=args.browser, design_review_approval_path=getattr(args, "design_review", None),
        )
    if command == "render":
        return workflow.render(args.request, attestation_key=attestation_key(args), browser=args.browser)
    if command == "check":
        return workflow.check(args.request, attestation_key=attestation_key(args), browser=args.browser)
    if command == "review":
        return workflow.review(
            args.request, args.approval,
            approval_key=approval_key(args), attestation_key=attestation_key(args), browser=args.browser,
            recipient_id=args.recipient_id, recipient_type=args.recipient_type,
            destination=args.destination, idempotency_key=args.idempotency_key,
        )
    if command == "deliver":
        return workflow.deliver(args.request, args.approval, approval_key=approval_key(args))
    if command == "revision-brief":
        return workflow.revision_brief(args.request, args.proposal)
    if command == "revise":
        return workflow.revise(args.request, args.proposal, args.approval, approval_key=approval_key(args))
    if command == "select-candidate":
        return workflow.select_candidate(args.request, args.candidate_id)
    if command == "delivery-status":
        return workflow.delivery_status(args.idempotency_key)
    if command == "status":
        return workflow.status()
    if command == "retry":
        return workflow.retry()
    if command == "receipts":
        return workflow.receipts()
    raise ValueError(f"unknown generate-map command: {command}")