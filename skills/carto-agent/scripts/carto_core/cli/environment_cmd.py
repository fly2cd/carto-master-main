"""``carto environment`` — host installation and renderer capability probes."""
from __future__ import annotations

from ..adapters.renderer_probe import RendererCapabilityProbe
from ..adapters.host_probe import HermesHostProbe
from ..schema_registry import SchemaRegistry


def register(sub) -> None:
    environment = sub.add_parser("environment", help="Inspect host installation or renderer capabilities")
    environment_sub = environment.add_subparsers(dest="environment_command", required=True)
    environment_sub.add_parser("probe-renderer")
    host = environment_sub.add_parser("probe-host", help="Inspect Hermes; does not approve session tools or production maps")
    host.add_argument("--host", choices=["hermes"], default="hermes")
    host.add_argument("--host-home", required=True)
    host.add_argument("--project-root", required=True)
    host.add_argument("--allowed-root", action="append", required=True)
    host.add_argument("--output", help="New JSON report inside project root; never overwritten")
    host.add_argument("--verify-local-tools", action="store_true", help="Opt in to isolated installed Hermes skill_view calls")
    host.add_argument("--host-python", help="Explicit installed Hermes Python; only used with --verify-local-tools")
    host.add_argument("--timeout", type=float, default=30)


def handle(args) -> dict:
    if args.environment_command == "probe-host":
        probe = HermesHostProbe(allowed_roots=args.allowed_root, project_root=args.project_root, host_home=args.host_home)
        report = probe.run(verify_local_tools=args.verify_local_tools, host_python=args.host_python, timeout=args.timeout)
        output = str(probe.save(report, args.output)) if args.output else None
        return {"host_preflight": report, "report_path": output}
    if args.environment_command == "probe-renderer":
        result = RendererCapabilityProbe().run()
        SchemaRegistry().validate("environment-fingerprint", result)
        return {"environment": result}
    raise ValueError(f"unknown environment command: {args.environment_command}")