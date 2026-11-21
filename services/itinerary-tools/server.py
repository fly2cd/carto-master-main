"""Itinerary tools MCP server: geocode + plan_route via stdio.

Two tools, zero old-framework dependencies. The server is deliberately thin:
it registers the tools and dispatches calls. All domain logic lives in
geocode.py and plan_route.py which use the copied AmapClient/Routing modules.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from geocode import geocode
from plan_route import plan_route
from itinerary_check import itinerary_check
from itinerary_assemble import itinerary_assemble
from request_scaffold import request_scaffold
from _service_utils import ServiceError, service_error_result

# Tool descriptions for MCP discovery
TOOL_DESCRIPTIONS = {
    "geocode": (
        "Geocode place names to WGS-84 coordinates using the Amap API. "
        "Returns status=complete with resolved coordinates, or status=needs_input "
        "with ambiguous candidates when multiple matches exist. "
        "For ambiguous results, call again with confirmations parameter. "
        "Input: {places: [{place_id, name, city}], confirmations?: [...]}"
    ),
    "plan_route": (
        "Plan road routes between origin and destination. "
        "Three-tier fallback: Plan A (offline dual-graph, local road network) "
        "→ Plan B (Amap online routing) → Plan C (straight-line, if allowed). "
        "Input: {legs: [{leg_id, origin: {lon,lat}, destination: {lon,lat}, "
        "via_points?: [...], strategy?: '0'-'6'}], allow_straight_line?: bool}"
    ),
    "itinerary_check": (
        "Validate the host's itinerary-draft.json against the itinerary contract "
        "BEFORE request assembly and geocoding. Advisory layer: the kernel remains "
        "the authority; this gives the host field-level errors to fix. "
        "Input: {draft_path, expected_digest?}"
    ),
    "itinerary_assemble": (
        "Merge the user-confirmed geocode result and the plan_route result into the "
        "draft, validate completeness (every place geocoded, every travel leg routed), "
        "and atomically write data/itinerary.json. Run AFTER G1 approval, BEFORE "
        "generate-map compile. Input: {draft_path, geocode_result, route_result, "
        "output_path?}"
    ),
    "request_scaffold": (
        "Build the pending generate-request.yaml mechanically: computes the digest "
        "bindings (draft / basemap / registration / template from the template "
        "repository index) and writes the request in the verified pending shape. "
        "Advisory: the kernel's closed schema at intake is the authority. "
        "Input: {draft_path, project_id, tenant_id, subject_id, approver_subject_id, "
        "request_id?, run_id?, idempotency_key?, basemap_path?, registration_path?, "
        "font_path?, font_family?, template_repo_path?, goal?, requested_at?}"
    ),
}

# Typed input schemas. Declaring property types is REQUIRED for host-client
# compatibility: when the schema is a bare {"type": "object"}, some MCP host
# clients serialize array/object parameters as JSON strings, which the tool
# entry points then reject ("string indices must be integers"). Verified on
# Claude Code (VS Code extension) against mcp SDK 1.30.
_GEOCODE_SCHEMA = {
    "type": "object",
    "properties": {
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "place_id": {"type": "string"},
                    "name": {"type": "string"},
                    "city": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "confirmations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "place_id": {"type": "string"},
                    "location": {
                        "type": "object",
                        "properties": {
                            "lon": {"type": "number"},
                            "lat": {"type": "number"},
                        },
                        "required": ["lon", "lat"],
                    },
                    "user_confirmed": {"type": "boolean"},
                },
                "required": ["place_id", "location"],
            },
        },
    },
    "required": ["places"],
}

_PLAN_ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "legs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "leg_id": {"type": "string"},
                    "origin": {
                        "type": "object",
                        "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
                        "required": ["lon", "lat"],
                    },
                    "destination": {
                        "type": "object",
                        "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
                        "required": ["lon", "lat"],
                    },
                    "via_points": {"type": "array"},
                    "strategy": {"type": "string"},
                },
                "required": ["origin", "destination"],
            },
        },
        "allow_straight_line": {"type": "boolean"},
    },
    "required": ["legs"],
}

_ITINERARY_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "draft_path": {"type": "string", "minLength": 1},
        "expected_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    },
    "required": ["draft_path"],
}

_ITINERARY_ASSEMBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "draft_path": {"type": "string", "minLength": 1},
        "geocode_result": {"type": "object"},
        "route_result": {"type": "object"},
        "output_path": {"type": "string", "minLength": 1},
    },
    "required": ["draft_path", "geocode_result", "route_result"],
}

_REQUEST_SCAFFOLD_SCHEMA = {
    "type": "object",
    "properties": {
        "draft_path": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "tenant_id": {"type": "string", "minLength": 1},
        "subject_id": {"type": "string", "minLength": 1},
        "approver_subject_id": {"type": "string", "minLength": 1},
        "request_id": {"type": "string"},
        "run_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
        "basemap_path": {"type": "string"},
        "registration_path": {"type": "string"},
        "font_path": {"type": "string"},
        "font_family": {"type": "string"},
        "template_repo_path": {"type": "string"},
        "goal": {"type": "string"},
        "requested_at": {"type": "string"},
    },
    "required": ["draft_path", "project_id", "tenant_id",
                 "subject_id", "approver_subject_id"],
}


def _normalize_arguments(arguments):
    """Accept both native dict args and host clients that stringify them.

    Some MCP host clients serialize the whole arguments object (or its
    array/object values) as JSON strings. Parse defensively; leave anything
    that is not parseable JSON untouched so the tool entry points report a
    clean schema error.
    """
    import json

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {"_unparsed": arguments}
    if not isinstance(arguments, dict):
        return arguments
    for key, value in list(arguments.items()):
        if isinstance(value, str) and value[:1] in ("[", "{"):
            try:
                arguments[key] = json.loads(value)
            except ValueError:
                pass
    return arguments


async def run(allowed_root: str, allow_online: bool = True, network_path: str | None = None):
    """Run the MCP server via stdio protocol."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        print("ERROR: MCP SDK not installed. Run: pip install 'mcp>=1.26,<2'", file=sys.stderr)
        sys.exit(1)

    server = Server("itinerary-tools")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="geocode", description=TOOL_DESCRIPTIONS["geocode"], inputSchema=_GEOCODE_SCHEMA),
            Tool(name="plan_route", description=TOOL_DESCRIPTIONS["plan_route"], inputSchema=_PLAN_ROUTE_SCHEMA),
            Tool(name="itinerary_check", description=TOOL_DESCRIPTIONS["itinerary_check"], inputSchema=_ITINERARY_CHECK_SCHEMA),
            Tool(name="itinerary_assemble", description=TOOL_DESCRIPTIONS["itinerary_assemble"], inputSchema=_ITINERARY_ASSEMBLE_SCHEMA),
            Tool(name="request_scaffold", description=TOOL_DESCRIPTIONS["request_scaffold"], inputSchema=_REQUEST_SCAFFOLD_SCHEMA),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        import json
        import sys as _sys
        import time as _time
        # The tool entry points are synchronous and call asyncio.run() internally
        # (httpx/route_engine are async). Dispatch to a worker thread so
        # asyncio.run() gets a fresh loop instead of colliding with the server's.
        print(f"[server] dispatch {name}", file=_sys.stderr, flush=True)
        t0 = _time.perf_counter()
        arguments = _normalize_arguments(arguments)
        # File-touching preparation tools get the allowed-root context: the
        # --allowed-root CLI argument becomes a real path boundary for them.
        ctx = {"allowed_root": Path(allowed_root)}
        try:
            if name == "geocode":
                result = await asyncio.to_thread(geocode, arguments)
            elif name == "plan_route":
                result = await asyncio.to_thread(plan_route, arguments)
            elif name == "itinerary_check":
                result = await asyncio.to_thread(itinerary_check, arguments, ctx)
            elif name == "itinerary_assemble":
                result = await asyncio.to_thread(itinerary_assemble, arguments, ctx)
            elif name == "request_scaffold":
                result = await asyncio.to_thread(request_scaffold, arguments, ctx)
            else:
                result = {"status": "error", "message": f"Unknown tool: {name}"}
        except ServiceError as exc:
            result = service_error_result(exc)
        except Exception as exc:  # tool-level failures must not kill the server
            result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"[:400]}
        print(f"[server] {name} done in {_time.perf_counter() - t0:.1f}s, "
              f"response {len(json.dumps(result, ensure_ascii=False)):,} bytes",
              file=_sys.stderr, flush=True)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Itinerary tools MCP server (geocode + plan_route)")
    parser.add_argument("--allowed-root", action="append", required=True,
                        help="Existing absolute root granted by the operator")
    parser.add_argument("--allow-online", action="store_true", default=True,
                        help="Enable Amap providers using CARTO_AMAP_KEY (default: true)")
    parser.add_argument("--offline", action="store_true",
                        help="Force offline mode (dual-graph only, no Amap calls)")
    parser.add_argument("--network", help="Explicit local GeoJSON road network path")
    args = parser.parse_args()

    allow_online = not args.offline

    # Heavy C-extension deps (numpy/osmnx/geopandas, pulled in by
    # dual_graph_router) MUST be imported here in the MAIN thread, before the
    # event loop starts. Importing them lazily from a tool worker thread
    # (asyncio.to_thread) deadlocks on the Windows loader lock while the
    # Proactor loop polls — verified via py-spy stack dumps and a minimal
    # 20-line reproduction. The eager import costs ~2.6s at startup and makes
    # the first plan_route call fast (the 48MB road network still loads
    # lazily on first use, in the worker thread, which is safe — pure data).
    from routing import router_dual_graph  # noqa: F401

    asyncio.run(run(args.allowed_root[0], allow_online, args.network))


if __name__ == "__main__":
    main()
