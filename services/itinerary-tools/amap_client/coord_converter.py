# -*- coding: utf-8 -*-
"""
coord_converter.py — GCJ-02（火星坐标系）与 WGS-84 互转
"""

from __future__ import annotations
import math
from typing import Tuple


class CoordConverter:
    PI = 3.1415926535897932384626
    A = 6378245.0
    EE = 0.00669342162296594323

    @staticmethod
    def is_valid_china_coord(lon: float, lat: float) -> bool:
        return 73.66 <= lon <= 135.05 and 3.86 <= lat <= 53.55

    @classmethod
    def gcj02_to_wgs84(cls, lon: float, lat: float) -> Tuple[float, float]:
        """高德(GCJ-02) 坐标转 GPS/OSM 标准坐标(WGS-84)"""
        dlat = cls._transform_lat(lon - 105.0, lat - 35.0)
        dlon = cls._transform_lon(lon - 105.0, lat - 35.0)
        radlat = (lat / 180.0) * cls.PI
        magic = math.sin(radlat)
        magic = 1 - cls.EE * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / (((cls.A * (1 - cls.EE)) / (magic * sqrtmagic)) * cls.PI)
        dlon = (dlon * 180.0) / ((cls.A / sqrtmagic) * math.cos(radlat) * cls.PI)
        return round(lon - dlon, 6), round(lat - dlat, 6)

    @classmethod
    def wgs84_to_gcj02(cls, lon: float, lat: float) -> Tuple[float, float]:
        """GPS标准坐标(WGS-84) 转 火星坐标(GCJ-02) —— 用于将 WGS-84 坐标回算为 GCJ-02 后重新调高德/DataV Routing"""
        dlat = cls._transform_lat(lon - 105.0, lat - 35.0)
        dlon = cls._transform_lon(lon - 105.0, lat - 35.0)
        radlat = (lat / 180.0) * cls.PI
        magic = math.sin(radlat)
        magic = 1 - cls.EE * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / (((cls.A * (1 - cls.EE)) / (magic * sqrtmagic)) * cls.PI)
        dlon = (dlon * 180.0) / ((cls.A / sqrtmagic) * math.cos(radlat) * cls.PI)
        return round(lon + dlon, 6), round(lat + dlat, 6)

    @classmethod
    def _transform_lat(cls, x: float, y: float) -> float:
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += ((20.0 * math.sin(6.0 * x * cls.PI) + 20.0 * math.sin(2.0 * x * cls.PI)) * 2.0) / 3.0
        ret += ((20.0 * math.sin(y * cls.PI) + 40.0 * math.sin((y / 3.0) * cls.PI)) * 2.0) / 3.0
        ret += ((160.0 * math.sin((y / 12.0) * cls.PI) + 320 * math.sin((y * cls.PI) / 30.0)) * 2.0) / 3.0
        return ret

    @classmethod
    def _transform_lon(cls, x: float, y: float) -> float:
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += ((20.0 * math.sin(6.0 * x * cls.PI) + 20.0 * math.sin(2.0 * x * cls.PI)) * 2.0) / 3.0
        ret += ((20.0 * math.sin(x * cls.PI) + 40.0 * math.sin((x / 3.0) * cls.PI)) * 2.0) / 3.0
        ret += ((150.0 * math.sin((x / 12.0) * cls.PI) + 300.0 * math.sin((x / 30.0) * cls.PI)) * 2.0) / 3.0
        return ret