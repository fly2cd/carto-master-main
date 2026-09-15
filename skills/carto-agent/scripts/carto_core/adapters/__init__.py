"""Controlled external capability adapters."""

from .qgis_probe import QgisEnvironmentProbe
from .mcp import McpAdapter, McpCapabilityDescriptor
from .tool_gateway import ToolGateway, ToolResult

__all__ = ["McpAdapter", "McpCapabilityDescriptor", "QgisEnvironmentProbe", "ToolGateway", "ToolResult"]
