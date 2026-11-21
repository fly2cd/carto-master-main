# -*- coding: utf-8 -*-
"""
router_dual_graph.py — Plan A: 对偶图离线路线规划

封装 dual_graph_router.DualGraphRouter，实现统一 Router 接口。
输入/输出均为 WGS-84。距离沿折线累加 haversine，耗时按 45km/h 估算。
"""

from __future__ import annotations
import logging
import math
from typing import Dict, List, Tuple, Optional, Any

from .dual_graph_router import DualGraphRouter, create_dual_graph_router, network_cache_identity


def _haversine_meters(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Haversine 球面距离（米）"""
    lon1, lat1 = p1
    lon2, lat2 = p2
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 6371000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class DualGraphRouterAdapter:
    """对偶图最少换路寻路引擎的 Router 接口适配器（Plan A 优先）"""

    ESTIMATED_SPEED_KMH = 45.0  # 主干道/高架平均车速

    def __init__(self, engine: DualGraphRouter):
        self._engine = engine

    def route_leg(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        via_points: Optional[List[Tuple[float, float]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        统一 Router 接口。

        Args:
            origin: (lon, lat) WGS-84
            destination: (lon, lat) WGS-84
            via_points: [(lon, lat), ...] 途经点 WGS-84

        Returns:
            {
                "polyline": [[lon, lat], ...],   # WGS-84
                "distance": int,                  # 米
                "duration": int,                  # 秒（估算）
                "engine": "dual_graph",
            }
            or None if routing fails
        """
        polyline = self._engine.route(origin, destination, via_points=via_points)

        if not polyline or len(polyline) < 2:
            return None

        # 沿折线累加 haversine 距离
        total_dist = 0.0
        for i in range(len(polyline) - 1):
            p1 = (polyline[i][0], polyline[i][1])
            p2 = (polyline[i + 1][0], polyline[i + 1][1])
            total_dist += _haversine_meters(p1, p2)

        # 按主干道平均车速估算耗时
        speed_mps = self.ESTIMATED_SPEED_KMH * 1000.0 / 3600.0
        duration = int(total_dist / speed_mps)

        return {
            "polyline": polyline,
            "distance": int(total_dist),
            "duration": duration,
            "engine": "dual_graph",
        }


_engine_cache: Dict[str, Optional[DualGraphRouterAdapter]] = {}


def create_dual_graph_engine(
    city_name: str = "Zhejiang",
    switch_penalty: float = 1000.0,
    geojson_path: Optional[str] = None,
    clip_bbox: Optional[Tuple[float, float, float, float]] = None,
    force_reload: bool = False,
    cache_dir: Optional[str] = None,
) -> Optional[DualGraphRouterAdapter]:
    """
    创建对偶图规划引擎适配器（带缓存）。

    首次创建需要加载路网数据（5-30 秒），后续调用直接返回缓存实例。

    Returns:
        DualGraphRouterAdapter 实例，或 None（数据源加载失败）
    """
    cache_key = network_cache_identity(city_name, switch_penalty, cache_dir=cache_dir, geojson_path=geojson_path, clip_bbox=clip_bbox)
    if cache_key in _engine_cache and not force_reload:
        return _engine_cache[cache_key]

    try:
        router = create_dual_graph_router(
            city_name=city_name,
            switch_penalty=switch_penalty,
            geojson_path=geojson_path,
            clip_bbox=clip_bbox,
            force_reload=force_reload,
            cache_dir=cache_dir,
        )
        if router is None:
            _engine_cache[cache_key] = None
            return None

        adapter = DualGraphRouterAdapter(router)
        _engine_cache[cache_key] = adapter
        return adapter
    except Exception as e:
        logging.getLogger(__name__).debug("router_dual_graph.create_dual_graph_engine.event")
        # Provider failures must not print request data or paths to ordinary logs.
        _engine_cache[cache_key] = None
        return None