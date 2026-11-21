"""``carto data`` — deterministic data preparation and read-only raster inspection."""
from __future__ import annotations

from pathlib import Path

from ..contracts.execution import ExecutionContext
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..workflow.data_preparation import DeterministicDataPreparer
from ._shared import policy_path


def register(sub) -> None:
    data = sub.add_parser("data", help="Run deterministic data preparation")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    prepare = data_sub.add_parser("prepare")
    prepare.add_argument("task")
    prepare.add_argument("--allowed-root", action="append", required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--tenant-id", required=True)
    prepare.add_argument("--project-id", required=True)
    prepare.add_argument("--subject-id", required=True)

    inspect_raster = data_sub.add_parser("inspect-raster", help="Read a registered categorical TIFF through MCP; no map or transformation")
    inspect_raster.add_argument("request", help="geospatial-request with operation info or statistics")
    inspect_raster.add_argument("--mcp-config", required=True, help="Explicit operator-controlled geospatial-mcp-config")
    inspect_raster.add_argument("--project-root", required=True)
    inspect_raster.add_argument("--allowed-root", action="append", required=True)
    inspect_raster.add_argument("--run-id", required=True)
    inspect_raster.add_argument("--tenant-id", required=True)
    inspect_raster.add_argument("--project-id", required=True)
    inspect_raster.add_argument("--subject-id", required=True)

    summarize = data_sub.add_parser("summarize", help="Inventory a project data directory into a Markdown mirror through the data-summary capability; read-only, no map")
    summarize.add_argument("request", help="data-summary-request document (data_dir within the project root)")
    summarize.add_argument("--project-root", required=True)
    summarize.add_argument("--allowed-root", action="append", required=True)
    summarize.add_argument("--run-id", required=True)
    summarize.add_argument("--tenant-id", required=True)
    summarize.add_argument("--project-id", required=True)
    summarize.add_argument("--subject-id", required=True)

    for command in ("analyze-classification", "clarify-classification"):
        classification = data_sub.add_parser(command, help="Prepare/clarify a frozen raster classification; no map or approval")
        classification.add_argument("request", help="Classification request, or prepared artifact-ref JSON for clarification")
        if command == "analyze-classification":
            classification.add_argument("--mcp-config", required=True)
        else:
            classification.add_argument("--answers", required=True)
        classification.add_argument("--project-root", required=True)
        classification.add_argument("--allowed-root", action="append", required=True)
        classification.add_argument("--run-id", required=True)
        classification.add_argument("--tenant-id", required=True)
        classification.add_argument("--project-id", required=True)
        classification.add_argument("--subject-id", required=True)


def _operator_context(args, capabilities=frozenset()) -> ExecutionContext:
    return ExecutionContext(
        run_id=args.run_id, tenant_id=args.tenant_id, project_id=args.project_id,
        subject_id=args.subject_id, roles=frozenset({"operator"}),
        namespaces=frozenset({args.project_id}), authorized_capabilities=capabilities,
    )


def handle(args) -> dict:
    if args.data_command == "inspect-raster":
        from ..adapters.geospatial_mcp import CAPABILITIES, GeospatialMcpAdapter

        guard = PathGuard(args.allowed_root)
        project = guard.resolve(args.project_root, must_exist=True)
        path = guard.resolve(args.request, base_root=project, must_exist=True)
        request = load_document(path)
        SchemaRegistry().validate("geospatial-request", request)
        if request["operation"] not in {"info", "statistics"}:
            raise ProtocolError("MCP_MUTATION_REQUIRES_WORKFLOW", "Read-only inspection cannot authorize a transformation")
        adapter = GeospatialMcpAdapter(config_path=Path(args.mcp_config), project_root=project,
                                       allowed_roots=args.allowed_root)
        capability = CAPABILITIES[request["operation"]]
        context = _operator_context(args, frozenset({capability}))
        receipt = adapter.make_gateway().invoke(capability, request, context)
        # Structured details are in the project-scoped evidence artifact, not ordinary stdout logs.
        return {"tool_result": receipt.to_dict()}
    if args.data_command == "summarize":
        # The old standalone scripts/data_summary.py entry, folded into the single
        # CLI as an authorized read-only capability: PathGuard-resolved data
        # directory, typed I/O schemas, ToolResult evidence artifact.
        from ..adapters.image_tools import DATA_SUMMARY_CAPABILITY, make_data_summary_gateway
        from ..repository.immutable_store import ImmutableArtifactStore

        guard = PathGuard(args.allowed_root)
        project = guard.resolve(args.project_root, must_exist=True)
        path = guard.resolve(args.request, base_root=project, must_exist=True)
        request = load_document(path)
        registry = SchemaRegistry()
        registry.validate("data-summary-request", request)
        store = ImmutableArtifactStore(project / ".carto" / "data" / "evidence",
                                       path_guard=PathGuard([project]))
        gateway = make_data_summary_gateway(store, registry, guard=guard, project_root=project)
        context = _operator_context(args, frozenset({DATA_SUMMARY_CAPABILITY}))
        receipt = gateway.invoke(DATA_SUMMARY_CAPABILITY, request, context)
        # The Markdown mirror lives in the project-scoped evidence artifact.
        return {"tool_result": receipt.to_dict()}
    if args.data_command in {"analyze-classification", "clarify-classification"}:
        from ..workflow.raster_preparation import RasterPreparationService

        service = RasterPreparationService(project_root=Path(args.project_root), allowed_roots=args.allowed_root)
        path = service.guard.resolve(args.request, base_root=service.project, must_exist=True)
        request = load_document(path)
        capabilities = frozenset({"gis-raster-statistics"}) if args.data_command == "analyze-classification" else frozenset()
        context = _operator_context(args, capabilities)
        if args.data_command == "analyze-classification":
            from ..adapters.geospatial_mcp import GeospatialMcpAdapter
            service.registry.validate("raster-classification-request", request)
            adapter = GeospatialMcpAdapter(config_path=Path(args.mcp_config), project_root=service.project,
                                           allowed_roots=args.allowed_root)
            artifact = service.analyze(request, context, adapter)
        else:
            answer_path = service.guard.resolve(args.answers, base_root=service.project, must_exist=True)
            artifact = service.clarify(request, load_document(answer_path), context)
        report, _ = service.load_verified(artifact.ref())
        # Questions and category rows live ONLY in the project-scoped artifact, not ordinary logs.
        return {"prepared_ref": artifact.ref(), "status": report["status"],
                "class_count": len(report["rows"]), "question_count": len(report["questions"])}
    if args.data_command == "prepare":
        path = PathGuard(args.allowed_root).resolve(args.task, must_exist=True)
        task = load_document(path)
        if not isinstance(task, dict):
            raise ValueError("Data preparation task must be an object")
        context = _operator_context(args)
        result = DeterministicDataPreparer(policy_path("data-preparation-policy.yaml")).prepare_data(task, context)
        return {"bundle": result}
    raise ValueError(f"unknown data command: {args.data_command}")