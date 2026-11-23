# -*- coding: utf-8 -*-
"""
router_amap.py — Plan B: 高德在线驾车路径规划

统一 Router 接口：输入 WGS-84，输出统一格式 Dict。
内部自动完成 WGS-84 → GCJ-02 → Amap API → WGS-84 转换。
"""

from __future__ import annotations
import logging
import os
from typing import List, Dict, Tuple, Any, Optional

import httpx

from amap_client.coord_converter import CoordConverter
from amap_client.amap_rate_limit import wait_for_amap_slot


class AmapRoutingError(RuntimeError):
    """Named Plan-B failure (never silently degrades to a straight line).

    ``code`` is a stable machine identifier (AMAP_KEY_MISSING /
    AMAP_REQUEST_FAILED); ``message`` carries the diagnostic detail.
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class AmapRouter:
    """高德驾车路径规划器（Plan B 兜底）"""

    DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"

    def __init__(self, amap_key: str = ""):
        self.amap_key = amap_key or os.environ.get("CARTO_AMAP_KEY", "")

    def _require_key(self) -> None:
        if not self.amap_key:
            raise AmapRoutingError(
                "AMAP_KEY_MISSING",
                "CARTO_AMAP_KEY is not set; Plan B (Amap online routing) is "
                "unavailable — fix the environment instead of degrading the route",
            )

    # -----------------------------------------------------------------
    async def route_leg(
        self,
        client: httpx.AsyncClient,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        via_points: Optional[List[Tuple[float, float]]] = None,
        strategy: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """
        统一 Router 接口：单段路径规划。

        Args:
            client: httpx AsyncClient
            origin: (lon, lat) WGS-84
            destination: (lon, lat) WGS-84
            via_points: [(lon, lat), ...] 途经点 WGS-84
            strategy: 高德路线策略（0-6，默认 2）

        Returns:
            {
                "polyline": [[lon, lat], ...],   # WGS-84
                "distance": int,                  # 米
                "duration": int,                  # 秒
                "engine": "amap",
            }
            or None if routing fails
        """
        self._require_key()
        # WGS-84 → GCJ-02
        gcj_origin = CoordConverter.wgs84_to_gcj02(*origin)
        gcj_dest = CoordConverter.wgs84_to_gcj02(*destination)

        params: Dict[str, Any] = {
            "key": self.amap_key,
            "origin": f"{gcj_origin[0]:.6f},{gcj_origin[1]:.6f}",
            "destination": f"{gcj_dest[0]:.6f},{gcj_dest[1]:.6f}",
            "strategy": strategy,
            "extensions": "base",
        }

        if via_points:
            via_strs = []
            for vp in via_points:
                gcj_vp = CoordConverter.wgs84_to_gcj02(*vp)
                via_strs.append(f"{gcj_vp[0]:.6f},{gcj_vp[1]:.6f}")
            params["waypoints"] = ";".join(via_strs)

        await wait_for_amap_slot()
        resp = await client.get(self.DRIVING_URL, params=params, timeout=15.0)
        data = resp.json()

        if data.get("status") != "1" or not data.get("route", {}).get("paths"):
            logging.getLogger(__name__).debug("router_amap.route_leg.event")
            return None

        path = data["route"]["paths"][0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))
        steps = path.get("steps", [])

        # 提取折线并转为 WGS-84
        polyline: List[List[float]] = []
        for step in steps:
            for c_str in step.get("polyline", "").split(";"):
                if not c_str:
                    continue
                parts = c_str.split(",")
                if len(parts) == 2:
                    gcj_lon, gcj_lat = float(parts[0]), float(parts[1])
                    wgs_lon, wgs_lat = CoordConverter.gcj02_to_wgs84(gcj_lon, gcj_lat)
                    pt = [wgs_lon, wgs_lat]
                    if not polyline or polyline[-1] != pt:
                        polyline.append(pt)

        # 闭环缝合：确保首尾点与输入一致
        if not polyline or polyline[0] != [origin[0], origin[1]]:
            polyline.insert(0, [origin[0], origin[1]])
        if polyline[-1] != [destination[0], destination[1]]:
            polyline.append([destination[0], destination[1]])

        # 若 API 未返回耗时，按市区平均车速 40km/h 估算
        if duration <= 0 and distance > 0:
            duration = int(distance / (40 * 1000 / 3600))

        return {
            "polyline": polyline,
            "distance": distance,
            "duration": duration,
            "engine": "amap",
        }

    # -----------------------------------------------------------------
    async def reroute_leg_with_resolve(
        self,
        client: httpx.AsyncClient,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        via_points: Optional[List[Dict[str, Any]]] = None,
        strategy: str = "2",
        geocoder=None,
    ) -> Dict[str, Any]:
        """
        重规划单段：支持地名→坐标自动解析。

        Args:
            client: httpx AsyncClient
            origin: {"lon": 120.1, "lat": 30.2} 或 {"name": "地点", "city": "城市"}
            destination: 同上
            via_points: 途经点列表，同上格式
            strategy: 路线策略
            geocoder: AmapGeocoder 实例（用于解析地名）

        Returns:
            {
                "fromName": str, "toName": str,
                "polyline": [[lon, lat], ...], "distance": int, "duration": int,
                "viaPoints": [...]
            }
        """
        self._require_key()

        async def _resolve_coord(item: Dict[str, Any]) -> Tuple[float, float, str]:
            name = item.get("name", "")
            if "lon" in item and "lat" in item:
                lon, lat = float(item["lon"]), float(item["lat"])
                # 传入坐标是 WGS-84，回算 GCJ-02 给高德 API
                lon, lat = CoordConverter.wgs84_to_gcj02(lon, lat)
                return lon, lat, name or f"{lon},{lat}"

            # 只有地名则现场 GeoCoding
            if geocoder is None:
                raise ValueError(f"无法解析地名 {name}：未提供 geocoder 实例")
            raw_lon, raw_lat, formatted_addr = await geocoder.geocode_single(
                client, name, item.get("city", "")
            )
            return raw_lon, raw_lat, formatted_addr or name

        # 解析起终点
        orig_lon, orig_lat, orig_name = await _resolve_coord(origin)
        dest_lon, dest_lat, dest_name = await _resolve_coord(destination)

        # 解析途经点
        resolved_via_points = []
        via_coords = []
        if via_points:
            for vp in via_points:
                v_lon, v_lat, v_name = await _resolve_coord(vp)
                via_coords.append(f"{v_lon:.6f},{v_lat:.6f}")
                resolved_via_points.append({"name": v_name, "lon": v_lon, "lat": v_lat})

        # 构造高德 API 参数
        params: Dict[str, Any] = {
            "key": self.amap_key,
            "origin": f"{orig_lon:.6f},{orig_lat:.6f}",
            "destination": f"{dest_lon:.6f},{dest_lat:.6f}",
            "strategy": int(strategy),
            "extensions": "base",
        }
        if via_coords:
            params["waypoints"] = ";".join(via_coords)

        await wait_for_amap_slot()
        resp = await client.get(self.DRIVING_URL, params=params, timeout=15.0)
        data = resp.json()

        if data.get("status") != "1" or not data.get("route", {}).get("paths"):
            raise AmapRoutingError(
                "AMAP_REQUEST_FAILED",
                f"amap driving API refused the request: status={data.get('status')} "
                f"infocode={data.get('infocode')} info={data.get('info')}",
            )

        path = data["route"]["paths"][0]
        leg_dist = int(path.get("distance", 0))
        leg_dur = int(path.get("duration", 0))
        steps = path.get("steps", [])

        # 提取折线并转为 WGS-84
        leg_poly: List[List[float]] = []
        for step in steps:
            for c_str in step.get("polyline", "").split(";"):
                if not c_str:
                    continue
                parts = c_str.split(",")
                if len(parts) == 2:
                    gcj_lon, gcj_lat = float(parts[0]), float(parts[1])
                    wgs_lon, wgs_lat = CoordConverter.gcj02_to_wgs84(gcj_lon, gcj_lat)
                    pt = [wgs_lon, wgs_lat]
                    if not leg_poly or leg_poly[-1] != pt:
                        leg_poly.append(pt)

        # 闭环缝合
        start_pt = list(CoordConverter.gcj02_to_wgs84(orig_lon, orig_lat))
        end_pt = list(CoordConverter.gcj02_to_wgs84(dest_lon, dest_lat))
        if not leg_poly or leg_poly[0] != start_pt:
            leg_poly.insert(0, start_pt)
        if leg_poly[-1] != end_pt:
            leg_poly.append(end_pt)

        if leg_dur <= 0 and leg_dist > 0:
            leg_dur = int(leg_dist / (40 * 1000 / 3600))

        return {
            "fromName": orig_name,
            "toName": dest_name,
            "polyline": leg_poly,
            "engine": "amap",
            "distance": leg_dist,
            "duration": leg_dur,
            "viaPoints": resolved_via_points,
        }
