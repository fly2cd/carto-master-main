"""Single source of truth for render-backend identity, family and dispatch.

ADR-001 阶段1：此前 renderer_id 字面量与“静态页 vs 浏览器”家族知识散落在
render_backend.create_render_backend、template_validation._is_static_backend、
map_generation（``renderer_id in {...}``）与 map_candidate 等多处硬编码。本模块把它们
收敛为唯一权威表——新增一个后端只需在此登记一条 BackendDescriptor。

本模块是零内部依赖的叶子（仅依赖 carto_core.errors），因此 workflow / compiler /
adapters 均可安全导入而不触发循环 import（compiler.*_scene 对本包的模块级导入历来
敏感，故这些模块保留各自的自我 id 常量，由测试锚定与此处一致，见 test_backend_registry）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..errors import ProtocolError

# 后端家族：进程内静态页渲染（matplotlib 系） vs 浏览器/WebGL 渲染（maplibre）。
STATIC_PAGE = "static-page"
BROWSER = "browser"

# 后端实现标签，供 create_render_backend 分派到具体适配器类。
IMPL_FORMAL = "formal"
IMPL_BROWSER = "browser"


@dataclass(frozen=True)
class BackendDescriptor:
    """一个渲染后端的不可变身份与能力声明。"""

    renderer_id: str
    family: str
    geometry: str
    export_formats: frozenset[str]
    impl: str


RASTER_PAGE = BackendDescriptor(
    renderer_id="rasterio-matplotlib-page", family=STATIC_PAGE, geometry="raster",
    export_formats=frozenset({"pdf", "png"}), impl=IMPL_FORMAL)
VECTOR_PAGE = BackendDescriptor(
    renderer_id="matplotlib-vector-page", family=STATIC_PAGE, geometry="vector",
    export_formats=frozenset({"pdf", "png"}), impl=IMPL_FORMAL)
MAPLIBRE_WEB = BackendDescriptor(
    renderer_id="maplibre-web", family=BROWSER, geometry="vector",
    export_formats=frozenset({"svg", "png", "pdf"}), impl=IMPL_BROWSER)

_BACKENDS: dict[str, BackendDescriptor] = {
    descriptor.renderer_id: descriptor
    for descriptor in (RASTER_PAGE, VECTOR_PAGE, MAPLIBRE_WEB)
}


def resolve(renderer_id: str) -> BackendDescriptor:
    """返回后端描述符；未知 id 是配置错误，明确拒绝（不静默回退）。"""
    try:
        return _BACKENDS[renderer_id]
    except KeyError:
        raise ProtocolError("RENDER_BACKEND_NOT_AVAILABLE", str(renderer_id)) from None


def is_known(renderer_id: str) -> bool:
    return renderer_id in _BACKENDS


def is_static(renderer_id: str) -> bool:
    """是否进程内静态页后端（matplotlib 系）。

    未知 id 返回 False，与历史 ``renderer_id in {"rasterio-matplotlib-page",
    "matplotlib-vector-page"}`` 判断逐字等价（保持行为不变）。
    """
    backend = _BACKENDS.get(renderer_id)
    return backend is not None and backend.family == STATIC_PAGE


def is_browser(renderer_id: str) -> bool:
    """是否浏览器/WebGL 后端。未知 id 返回 False。"""
    backend = _BACKENDS.get(renderer_id)
    return backend is not None and backend.family == BROWSER


def renderer_ids() -> frozenset[str]:
    return frozenset(_BACKENDS)
