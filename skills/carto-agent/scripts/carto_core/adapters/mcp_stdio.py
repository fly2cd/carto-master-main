"""Optional official MCP SDK transport. No shell, URL transport, or credential forwarding."""
from __future__ import annotations

import base64
import binascii
import os
from contextlib import asynccontextmanager
from typing import Any

from ..canonical import canonical_json_bytes, sha256_digest
from ..errors import CartoError, ProtocolError
from ..workflow.models import ExecutionContext


class _LocalSchemaValidation:
    """Keep SDK wire decoding, but never compile a service-supplied JSON Schema.

    The adapter validates every accepted payload against the pinned local wire
    contract. This public SDK hook also avoids an implicit tools/list refresh.
    """

    async def validate_tool_result(self, name: str, result: Any) -> None:
        if not isinstance(result.structured_content, dict):
            raise ProtocolError("MCP_STRUCTURED_RESULT_REQUIRED", "Text is not a typed GIS result")


async def _discard_server_message(message: Any) -> None:
    """Do not forward application logging notifications or transport payloads."""


class StdioSession:
    def __init__(self, session: Any, server_info: Any, context: ExecutionContext,
                 limits: dict[str, int]) -> None:
        self.session = session
        self.server_info = server_info
        self.context = context
        self.limits = limits

    def _bounded(self, value: Any) -> None:
        # Acceptance limit after SDK decoding, NOT a hostile-process memory sandbox.
        if len(canonical_json_bytes(value)) > self.limits["max_response_bytes"]:
            raise ProtocolError("MCP_RESPONSE_TOO_LARGE", "Structured MCP response exceeds the acceptance limit")

    async def discover(self, required: set[str]) -> str:
        found: dict[str, dict[str, Any]] = {}
        cursor = None
        cursors: set[str] = set()
        for _ in range(8):
            self.context.budget.consume("tool_calls")
            if cursor is None:
                result = await self.session.list_tools()
            else:
                from mcp.types import PaginatedRequestParams
                result = await self.session.list_tools(params=PaginatedRequestParams(cursor=cursor))
            self._bounded(result.model_dump(mode="json", by_alias=True))
            for tool in result.tools:
                if tool.name in found or len(found) >= 128:
                    raise ProtocolError("MCP_DISCOVERY_INVALID", "Duplicate or excessive discovered tools")
                found[tool.name] = {"name": tool.name, "input": tool.input_schema,
                                    "output": tool.output_schema}
            cursor = result.next_cursor
            if cursor is None:
                break
            if cursor in cursors:
                raise ProtocolError("MCP_DISCOVERY_INVALID", "Repeated discovery cursor")
            cursors.add(cursor)
        else:
            raise ProtocolError("MCP_DISCOVERY_INVALID", "Discovery pagination limit exceeded")
        if not required <= found.keys():
            raise ProtocolError("MCP_CAPABILITY_NOT_AVAILABLE", "Required GIS tools are not advertised")
        # Remote schemas are evidence only. They never authorize capabilities or resolve refs.
        return sha256_digest([found[name] for name in sorted(required)])

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.context.budget.consume("tool_calls")
        result = await self.session.call_tool(name, arguments=arguments,
                                              read_timeout_seconds=self.limits["timeout_seconds"])
        self._bounded(result.model_dump(mode="json", by_alias=True))
        if getattr(result, "is_error", True):
            raise ProtocolError("MCP_TOOL_FAILED", "GIS tool failed; untrusted error text is not forwarded")
        output = getattr(result, "structured_content", None)
        if not isinstance(output, dict):
            raise ProtocolError("MCP_STRUCTURED_RESULT_REQUIRED", "Text is not a typed GIS result")
        return output

    async def read(self, uri: str, size: int) -> bytes:
        if type(size) is not int or not 0 < size <= self.limits["max_artifact_bytes"]:
            raise ProtocolError("MCP_RESOURCE_SIZE_MISMATCH", "Resource exceeds the binary acceptance limit")
        self.context.budget.consume("tool_calls")
        result = await self.session.read_resource(uri)
        contents = getattr(result, "contents", [])
        if len(contents) != 1:
            raise ProtocolError("MCP_RESOURCE_INVALID", "Expected one binary TIFF resource")
        part = contents[0]
        blob = getattr(part, "blob", None)
        if (str(part.uri) != uri or part.mime_type != "image/tiff" or not isinstance(blob, str)
                or len(blob) != 4 * ((size + 2) // 3)):
            raise ProtocolError("MCP_RESOURCE_INVALID", "Resource URI, media type, or encoded length differs")
        try:
            data = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError):
            raise ProtocolError("MCP_RESOURCE_INVALID", "Resource is not strict base64") from None
        if len(data) != size or len(data) > self.limits["max_artifact_bytes"]:
            raise ProtocolError("MCP_RESOURCE_SIZE_MISMATCH", "Resource byte count differs")
        return data


def _find_carto_error(exc: BaseException) -> CartoError | None:
    if isinstance(exc, CartoError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = _find_carto_error(child)
            if found is not None:
                return found
    return None


@asynccontextmanager
async def connect_stdio(*, python: str, cwd: str, env: dict[str, str],
                        context: ExecutionContext, limits: dict[str, int]):
    try:
        import anyio
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError:
        raise ProtocolError("MCP_SDK_UNAVAILABLE", "Install the optional geospatial dependency explicitly") from None
    class PinnedSchemaClientSession(_LocalSchemaValidation, ClientSession):
        pass

    params = StdioServerParameters(command=python, args=["-I", "-B", "-m", "geospatial_mcp.server"],
                                   env=env, cwd=cwd)
    try:
        with anyio.fail_after(limits["timeout_seconds"]):
            # The SDK inherits its safe OS environment whitelist, not the caller's credentials.
            # Server logs and arbitrary failure messages must not enter ordinary Carto logs.
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(params, errlog=errlog) as streams:
                    async with PinnedSchemaClientSession(
                            *streams, message_handler=_discard_server_message,
                            logging_callback=_discard_server_message) as session:
                        context.budget.consume("tool_calls")
                        initialized = await session.initialize()
                        yield StdioSession(session, initialized.server_info, context, limits)
    except Exception as exc:
        known = _find_carto_error(exc)
        if known is not None:
            raise known from None
        # Transport failure after a mutation may have an unknown outcome. Never retry here.
        raise ProtocolError("MCP_TRANSPORT_FAILED", "GIS session failed or timed out; no automatic retry or accepted result") from None
