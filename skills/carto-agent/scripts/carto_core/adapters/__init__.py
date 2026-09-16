"""Controlled external capability adapters."""

from .mcp import McpAdapter, McpCapabilityDescriptor
from .renderer_probe import RendererCapabilityProbe
from .svg_compositor import SvgCompositor
from .tool_gateway import ToolGateway, ToolResult
from .webmap_renderer import (
    RenderReceiptValidator,
    RenderSceneSemanticValidator,
    RenderSessionGateway,
    RendererCapabilityProfile,
    RendererCapabilityRegistry,
    WebMapRendererAdapter,
    compute_renderer_attestation,
)

__all__ = [
    "McpAdapter",
    "McpCapabilityDescriptor",
    "RendererCapabilityProbe",
    "RenderReceiptValidator",
    "RenderSceneSemanticValidator",
    "RenderSessionGateway",
    "RendererCapabilityProfile",
    "RendererCapabilityRegistry",
    "SvgCompositor",
    "ToolGateway",
    "ToolResult",
    "WebMapRendererAdapter",
    "compute_renderer_attestation",
]
