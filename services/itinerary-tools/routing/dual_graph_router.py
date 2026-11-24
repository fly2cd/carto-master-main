import logging
# -*- coding: utf-8 -*-
"""
dual_graph_router.py — 基于 OSM 骨干路网的对偶图最少换路寻路引擎

核心思想：
  传统导航以「交叉口为节点」，优化目标是「时间最短」，因此频繁穿插小路。
  本模块以「道路（Stroke）为节点」，综合优化四条准则：
    ① 物理距离最短（不走冤枉路）
    ② 快速路/高架优先（motorway/trunk 成本折扣 0.85×）
    ③ 换路次数最少（归一化道路名 + link 感知惩罚：匝道上下高架几乎无惩罚）
    ④ 转弯平顺（>60° 转弯角度惩罚抑制蛇形折角）
  算法自然产出「走大路、大开大合、流畅平顺」的示意路线。

算法：
  Edge-Expanded State A*（边扩展状态 A*）
  - 状态空间：(node_id, road_name)  # 不仅知道在哪个路口，还知道在哪条路上
  - 转移代价：length×expressway_discount + switch_penalty + turn_penalty
  - 换路判定基于归一化道路名（"文一西路"≈"文一路"）
  - link 匝道过渡几乎无惩罚，保证高架桥/快速路可达
  - 启发式：Haversine 直线距离（admissible，保证最优解）

依赖：
  osmnx, networkx, shapely — 可选。未安装时自动降级，返回 None 触发高德回退。

用法：
  from .dual_graph_router import DualGraphRouter, create_dual_graph_router

  router = create_dual_graph_router("Hangzhou")
  if router:
      polyline = router.route((120.15, 30.27), (120.20, 30.19))
"""

import os
import math
import heapq
import hashlib
import json
import re
import time
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
MAX_ROUTE_SNAP_DISTANCE_M = 1000.0  # meters; hard-coded from old contracts

# ---------------------------------------------------------------------------
# 可选依赖检测
# ---------------------------------------------------------------------------
_HAS_OSMNX = False
_HAS_SHAPELY = False

try:
    import osmnx as ox
    import networkx as nx
    _HAS_OSMNX = True
except ImportError:
    ox = None
    nx = None

try:
    from shapely.geometry import Point, LineString, box
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    Point = None
    LineString = None
    box = None
    unary_union = None


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
DEFAULT_SWITCH_PENALTY = 1000.0       # 主路→主路换路惩罚（米），平衡"少换路"与"不走冤枉路"
LINK_SWITCH_PENALTY = 100.0           # 匝道（link）换路惩罚（米），极低——上下高架不应受罚
TURN_PENALTY_FACTOR = 400.0           # 转弯惩罚系数（米），90°直角转弯 ≈ 400m 额外代价
EXPRESSWAY_DISCOUNT = 0.85            # 快速路/高速成本折扣系数（<1 表示偏好走大路）
DEFAULT_HIGHWAY_FILTER = {
    "motorway", "trunk", "primary", "secondary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
}
MIN_SEGMENT_LENGTH = 50.0             # 最短保留路段（米）
MAX_NEAREST_NODE_DIST = 500.0         # 优先查找附近节点的半径（米）
MAX_EXPANDED_STATES = 200000          # A* 最大展开状态数（安全阀）
CACHE_VERSION = 4                      # v4: 绑定数据源内容、路径与构图选项
A_STAR_TIME_BUDGET = 5.0              # 单次 A* 时间预算（秒）


DEFAULT_NETWORK_FILENAME = "highway_zhejiang_planar261109.geojson"


def network_cache_identity(city_name, switch_penalty, cache_dir=None,
                           geojson_path=None, clip_bbox=None):
    """Bind graph caches to source bytes, canonical paths and build options."""
    directory = os.path.realpath(cache_dir or os.path.join(os.path.dirname(__file__), "data"))
    source = os.path.realpath(geojson_path or os.path.join(directory, DEFAULT_NETWORK_FILENAME))
    digest = None
    if os.path.isfile(source):
        with open(source, "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    payload = [CACHE_VERSION, city_name, switch_penalty, directory, source,
               digest, clip_bbox, sorted(DEFAULT_HIGHWAY_FILTER)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def _haversine_meters(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Haversine 球面距离（米），用于启发式和节点查找。"""
    lon1, lat1 = p1
    lon2, lat2 = p2
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 6371000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _equirectangular_meters(p1, p2):
    """等角投影距离（米），适用于城区尺度（误差 < 0.5%）。"""
    mid_lat = (p1[1] + p2[1]) / 2.0 * math.pi / 180.0
    dx = (p2[0] - p1[0]) * math.pi / 180.0 * 6378137.0 * math.cos(mid_lat)
    dy = (p2[1] - p1[1]) * math.pi / 180.0 * 6378137.0
    return math.hypot(dx, dy)


def _closest_point_on_segment(px, py, ax, ay, bx, by):
    """点到线段最近投影参数 t ∈ [0, 1] 和距离（度）。"""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return 0.0, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    cx, cy = ax + t * dx, ay + t * dy
    return t, math.hypot(px - cx, py - cy)


def _normalize_road_name(name: str) -> str:
    """提取道路根名称，使 '文一西路' 与 '文一路' 识别为同一走廊。

    策略：逐层剥离后缀（路/街/大道 → 方位 → 快速/高架），保留核心专名。
    返回空字符串表示无法归一化（无名道路）。
    """
    if not name or name == "未命名道路":
        return ""

    # 第一层：去除通用道路类型后缀
    cleaned = re.sub(
        r"(快速路|高架路|高架|大道|道路|路|街|巷|辅道|辅路|支路|线|干线)$",
        "", name
    )

    # 第二层：去除末尾方位词 + 可选数字后缀
    cleaned = re.sub(
        r"[东西南北中](?:[0-9一二三四五六七八九十]+(?:号?线|期|段|匝道)?)?$",
        "", cleaned
    )

    # 第三层：再剥离一次可能残留的类型词（如 "德胜快速" → "德胜"）
    cleaned = re.sub(r"(快速|高架|大道|道路|路|街|巷)$", "", cleaned)

    result = cleaned.strip()
    return result if len(result) >= 2 else name  # 归一化后太短则保留原名


def _calculate_turn_angle(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
) -> float:
    """计算 p1→p2→p3 的转弯角度（0°=直行，180°=掉头）。"""
    dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
    dx2, dy2 = p3[0] - p2[0], p3[1] - p2[1]
    dot = dx1 * dx2 + dy1 * dy2
    mag1 = math.hypot(dx1, dy1)
    mag2 = math.hypot(dx2, dy2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    cos_val = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_val))


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class RoadEdge:
    """路网中的一条边（两个交叉口之间的路段）。"""
    edge_id: int
    from_node: int
    to_node: int
    road_name: str           # 道路名称（如"余杭塘路"）
    length_m: float          # 路段长度（米）
    coords: List[Tuple[float, float]]  # 几何折线 [(lon, lat), ...]


@dataclass
class AStarState:
    """Edge-Expanded A* 状态。"""
    node_id: int
    road_name: str
    norm_name: str = ""     # 归一化道路名，用于换路判定（不参与 hash/eq）
    highway: str = ""       # highway 类型（motorway/trunk/.../link），用于代价计算

    def __hash__(self):
        return hash((self.node_id, self.road_name))

    def __eq__(self, other):
        return (self.node_id == other.node_id and
                self.road_name == other.road_name)


# ---------------------------------------------------------------------------
# 主类：DualGraphRouter
# ---------------------------------------------------------------------------

class DualGraphRouter:
    """基于 OSM 骨干路网的对偶图最少换路寻路引擎。

    支持两种数据源（按优先级）：
      1. 本地 GeoJSON 文件（QGIS QuickOSM 导出）—— 无需联网，无需 osmnx
      2. osmnx 在线下载 —— 需要 osmnx 和 Overpass API 访问

    属性:
        city_name:      目标城市名
        switch_penalty: 换路惩罚当量（米）
        nodes:          {node_id: (lon, lat)}
        adjacency:      {node_id: [(neighbor, road_name, norm_name, highway, length_m, coords), ...]}
    """

    def __init__(
        self,
        city_name: str = "Zhejiang",
        switch_penalty: float = DEFAULT_SWITCH_PENALTY,
        cache_dir: Optional[str] = None,
        geojson_path: Optional[str] = None,
        clip_bbox: Optional[Tuple[float, float, float, float]] = None,
        force_reload: bool = False,
    ):
        """初始化对偶图寻路引擎。

        Args:
            city_name: 城市名
            switch_penalty: 主路间换路惩罚（米）
            cache_dir: 缓存目录
            geojson_path: GeoJSON 路径
            clip_bbox: 路网裁剪范围 (min_lon, min_lat, max_lon, max_lat)，
                       只加载此范围内的道路。None = 加载全部。
                       建议设为 POI 外扩 5~10km，大幅加速平面化。
        """
        self._force_reload = force_reload
        self.city_name = city_name
        self.switch_penalty = switch_penalty
        self.clip_bbox = clip_bbox
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data"
        )

        # 图数据
        self.nodes: Dict[int, Tuple[float, float]] = {}
        self.adjacency: Dict[int, List[Tuple[int, str, float, List[Tuple[float, float]]]]] = {}
        self.contracted = False

        # 节点坐标反向索引（用于 A* 启发式）
        self._node_coords: Dict[int, Tuple[float, float]] = {}

        self._cache_identity = network_cache_identity(
            city_name, switch_penalty, self.cache_dir, geojson_path, clip_bbox)

        # 初始化
        t0 = time.time()
        self._load_or_download(geojson_path)
        logging.getLogger(__name__).debug("dual_graph_router.__init__.event")

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _cache_path(self) -> str:
        """生成与数据源摘要及构图选项绑定的缓存路径。"""
        os.makedirs(self.cache_dir, exist_ok=True)
        return os.path.join(self.cache_dir, f"backbone_{self._cache_identity}.json")

    def _default_geojson_path(self) -> str:
        """Bundled Zhejiang planar network; no implicit legacy-city fallback."""
        return os.path.join(self.cache_dir, DEFAULT_NETWORK_FILENAME)

    def _load_or_download(self, geojson_path: Optional[str] = None):
        """
        按优先级加载路网数据：
          1. 如果提供了 geojson_path，从本地 GeoJSON 加载
          2. 如果默认路径存在 GeoJSON，自动加载
          3. 如果缓存 JSON 存在，加载缓存
          4. 通过 osmnx 在线下载
        """
        # 优先级 1 & 2：本地 GeoJSON
        gj_path = geojson_path or self._default_geojson_path()
        if geojson_path and not os.path.isfile(gj_path):
            raise RuntimeError('Configured local road network is missing')
        if os.path.exists(gj_path):
            logging.getLogger(__name__).debug("dual_graph_router._load_or_download.event")
            cache_path = self._cache_path()
            if os.path.exists(cache_path) and not self._force_reload:
                try:
                    self._load_from_cache(cache_path)
                    return
                except (ValueError, KeyError, TypeError):
                    self.nodes.clear()
                    self.adjacency.clear()
                    self._node_coords.clear()
            self._load_from_geojson(gj_path)
            self._save_to_cache(cache_path)
            return

        # 优先级 3：缓存 JSON
        cache_path = self._cache_path()
        if os.path.exists(cache_path):
            logging.getLogger(__name__).debug("dual_graph_router._load_or_download.event")
            self._load_from_cache(cache_path)
            return

        # 优先级 4：osmnx 在线下载
        if _HAS_OSMNX:
            logging.getLogger(__name__).debug("dual_graph_router._load_or_download.event")
            self._download_backbone()
            self._save_to_cache(cache_path)
        else:
            raise RuntimeError(
                "无可用数据源。请通过以下方式之一提供路网数据：\n"
                f"  1. 放置 GeoJSON 文件到: {self._default_geojson_path()}\n"
                "  2. 安装 osmnx 进行在线下载: pip install osmnx"
            )

    # ------------------------------------------------------------------
    # GeoJSON 加载（QGIS QuickOSM 导出）
    # ------------------------------------------------------------------

    # 骨干道路 highway 类型（含 link 匝道——无匝道则高架/快速路悬空不可达）
    _BACKBONE_HIGHWAY = {
        "motorway", "trunk", "primary", "secondary",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
    }

    # 排除的道路名关键词（内部路、无名路等）
    _NOISE_NAME_KEYWORDS = ["内部", "专用", "便道", "无名", "小区"]

    def _load_from_geojson(self, geojson_path: str):
        """从 QGIS QuickOSM 导出的 GeoJSON 构建路网图。

        处理步骤：
          1. 读取 GeoJSON FeatureCollection
          2. 过滤 highway ∈ motorway/trunk/primary/secondary + link 匝道
          3. 无名主路丢弃，无名匝道保留（生成唯一名）
          4. 为每条 LineString 构建节点和边
          5. 基于空间容差合并重复节点
        """
        logging.getLogger(__name__).debug("dual_graph_router._load_from_geojson.event")
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        if not features:
            raise ValueError("GeoJSON 文件不包含任何 feature")

        # bbox 预裁剪：大幅削减数据量，加速后续平面化
        skip_bbox = 0
        if self.clip_bbox is not None:
            min_lon, min_lat, max_lon, max_lat = self.clip_bbox
            logging.getLogger(__name__).debug("dual_graph_router._load_from_geojson.event")

            def _geom_intersects_bbox(geom: dict) -> bool:
                """判断几何是否与 bbox 有交集（保守：用外包矩形粗筛）。"""
                coords = geom.get("coordinates", [])
                if not coords:
                    return False
                # 计算 LineString 的外包矩形
                g_min_lon = min(c[0] for c in coords)
                g_max_lon = max(c[0] for c in coords)
                g_min_lat = min(c[1] for c in coords)
                g_max_lat = max(c[1] for c in coords)
                # 矩形相交检测
                return not (g_max_lon < min_lon or g_min_lon > max_lon or
                           g_max_lat < min_lat or g_min_lat > max_lat)

            features = [f for f in features
                       if _geom_intersects_bbox(f.get("geometry", {}))]
            skip_bbox = len(data.get("features", [])) - len(features)
            logging.getLogger(__name__).debug("dual_graph_router._load_from_geojson.event")

        # 过滤：只保留骨干道路
        backbone_features = []
        skip_no_geom = 0
        skip_highway = 0
        skip_noise_name = 0
        skip_no_name = 0
        for feat in features:
            geom = feat.get("geometry", {})
            if geom.get("type") != "LineString":
                skip_no_geom += 1
                continue

            props = feat.get("properties", {})
            hw = str(props.get("highway", "")).strip()

            if hw not in self._BACKBONE_HIGHWAY:
                skip_highway += 1
                continue

            # 道路名称：无名主路过滤，但无名匝道保留（link 通常无独立名称）
            name = str(props.get("name", "")).strip()
            is_link = "_link" in hw
            coords = geom.get("coordinates", [])
            if not name or name.lower() in ("null", "none", "未命名道路"):
                if is_link:
                    # 无名匝道：用 highway 类型 + 坐标哈希生成唯一名，避免合并
                    name = f"[匝道]_{hw}_{coords[0][0]:.4f}_{coords[0][1]:.4f}" if coords else hw
                else:
                    skip_no_name += 1
                    continue

            # 排除内部路等噪声
            if any(kw in name for kw in self._NOISE_NAME_KEYWORDS):
                skip_noise_name += 1
                continue

            if len(coords) < 2:
                continue

            backbone_features.append({
                "name": name,
                "highway": hw,
                "coords": [(round(c[0], 6), round(c[1], 6)) for c in coords],
            })

        logging.getLogger(__name__).debug("dual_graph_router._load_from_geojson.event")

        # 构建图
        self._build_from_features(backbone_features)

    def _build_from_features(self, features: List[Dict]):
        """从 GeoJSON 路段列表构建邻接表。

        对每个路段：将连续坐标对转化为边，通过空间哈希合并重复节点。
        """
        # 节点坐标 → node_id 的映射（使用坐标字符串作为 key）
        coord_to_node: Dict[str, int] = {}
        next_node_id = 0
        edges_seen: Set[Tuple[int, int, str]] = set()

        for feat in features:
            name = feat["name"]
            highway = feat["highway"]
            norm_name = _normalize_road_name(name)
            coords = feat["coords"]

            if len(coords) < 2:
                continue

            # 为每个坐标点分配 node_id
            node_ids = []
            for pt in coords:
                key = f"{pt[0]:.5f},{pt[1]:.5f}"
                if key not in coord_to_node:
                    coord_to_node[key] = next_node_id
                    self._node_coords[next_node_id] = pt
                    self.nodes[next_node_id] = pt
                    self.adjacency.setdefault(next_node_id, [])
                    next_node_id += 1
                node_ids.append(coord_to_node[key])

            # 在连续 node 之间建立边
            for i in range(len(node_ids) - 1):
                u = node_ids[i]
                v = node_ids[i + 1]
                edge_coords = [coords[i], coords[i + 1]]

                # 计算边长
                length_m = _equirectangular_meters(coords[i], coords[i + 1])

                # 去重
                dedup_key = (min(u, v), max(u, v), name)
                if dedup_key in edges_seen:
                    continue
                edges_seen.add(dedup_key)

                # 双向添加（邻接表格式: neighbor, road_name, norm_name, highway, length_m, coords）
                self.adjacency[u].append((v, name, norm_name, highway, length_m, edge_coords))
                self.adjacency[v].append((u, name, norm_name, highway, length_m, list(reversed(edge_coords))))

        logging.getLogger(__name__).debug("dual_graph_router._build_from_features.event")

    def _download_backbone(self):
        """通过 osmnx 下载城市骨干路网（含 link 匝道）并构图为邻接表。"""
        # 构建 OSM highway filter 字符串（包含 link 类型）
        tags = "|".join(sorted(DEFAULT_HIGHWAY_FILTER))
        custom_filter = f'["highway"~"{tags}"]'

        logging.getLogger(__name__).debug("dual_graph_router._download_backbone.event")
        G = ox.graph_from_place(
            f"{self.city_name}, China",
            network_type="drive",
            custom_filter=custom_filter,
            simplify=True,  # osmnx 自动简化（合并 degree-2 节点）
        )

        # 转为无向图（忽略单行道、车道隔离带）
        G_undirected = ox.utils_graph.get_undirected(G)

        self._build_from_networkx(G_undirected)

    def _build_from_networkx(self, G):  # type: ignore — G 为 networkx.MultiGraph，仅 osmnx 路径使用
        """从 NetworkX 图构建邻接表。

        每个 OSM edge 提取: 名称, 长度, 几何坐标。
        """
        edge_id = 0
        edges_seen: Set[Tuple[int, int, str]] = set()

        for u, v, data in G.edges(data=True):
            # 道路名称：优先 name，其次 ref，最后 highway 类型
            road_name = (data.get("name") or data.get("ref") or
                         data.get("highway", "未命名道路"))

            # 确保是字符串
            if isinstance(road_name, list):
                road_name = road_name[0] if road_name else "未命名道路"
            road_name = str(road_name).strip()

            # highway 类型（用于代价计算：主路 vs 匝道 vs 快速路）
            highway = str(data.get("highway", "")).strip()

            # 归一化道路名
            norm_name = _normalize_road_name(road_name)

            # 跳过无名道路（osmnx 可能返回 highway 类型值作为名称）
            if not norm_name:
                continue

            # 路段长度
            length_m = float(data.get("length", 0))
            if length_m <= 0:
                # fallback: 用几何坐标估算
                if "geometry" in data:
                    coords_list = list(data["geometry"].coords)
                    length_m = sum(
                        _equirectangular_meters(coords_list[i], coords_list[i + 1])
                        for i in range(len(coords_list) - 1)
                    )

            if length_m < MIN_SEGMENT_LENGTH:
                continue

            # 去重（无向图可能有重复边）
            key = (min(u, v), max(u, v), road_name)
            if key in edges_seen:
                continue
            edges_seen.add(key)

            # 几何坐标
            if "geometry" in data:
                coords = [(round(c[0], 6), round(c[1], 6))
                          for c in data["geometry"].coords]
            else:
                ux, uy = G.nodes[u].get("x", 0), G.nodes[u].get("y", 0)
                vx, vy = G.nodes[v].get("x", 0), G.nodes[v].get("y", 0)
                coords = [(round(ux, 6), round(uy, 6)),
                          (round(vx, 6), round(vy, 6))]

            # 记录节点坐标
            if u not in self._node_coords and len(coords) > 0:
                self._node_coords[u] = coords[0]
            if v not in self._node_coords and len(coords) > 0:
                self._node_coords[v] = coords[-1]

            # 更新邻接表
            if u not in self.adjacency:
                self.adjacency[u] = []
            if v not in self.adjacency:
                self.adjacency[v] = []

            # 正向（邻接表格式: neighbor, road_name, norm_name, highway, length_m, coords）
            self.adjacency[u].append((v, road_name, norm_name, highway, length_m, coords))
            # 反向
            rev_coords = list(reversed(coords))
            self.adjacency[v].append((u, road_name, norm_name, highway, length_m, rev_coords))

            self.nodes[u] = self._node_coords.get(u, (0, 0))
            self.nodes[v] = self._node_coords.get(v, (0, 0))
            edge_id += 1

        logging.getLogger(__name__).debug("dual_graph_router._build_from_networkx.event")

    # ------------------------------------------------------------------
    # 缓存序列化
    # ------------------------------------------------------------------

    def _load_from_cache(self, cache_path: str):
        """从 JSON 缓存恢复图数据。"""
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 版本检测：旧格式缓存自动失效
        cached_version = data.get("cache_version", 1)
        if cached_version != CACHE_VERSION or data.get("source_identity") != self._cache_identity:
            raise ValueError(
                "路网缓存版本或数据源身份不匹配"
            )

        # 恢复节点
        for k, v in data["nodes"].items():
            nid = int(k)
            self.nodes[nid] = tuple(v)
            self._node_coords[nid] = tuple(v)

        # 恢复邻接表（格式: [neighbor, road_name, norm_name, highway, length_m, coords]）
        for k, v in data["adjacency"].items():
            nid = int(k)
            self.adjacency[nid] = [
                (item[0], item[1], item[2], item[3], item[4], [tuple(c) for c in item[5]])
                for item in v
            ]

        # 设置 loaded 标志
        self.contracted = data.get("contracted", False)

    def _save_to_cache(self, cache_path: str):
        """保存图数据到 JSON 缓存。"""
        data = {
            "cache_version": CACHE_VERSION,
            "source_identity": self._cache_identity,
            "city_name": self.city_name,
            "contracted": self.contracted,
            "nodes": {str(k): list(v) for k, v in self.nodes.items()},
            "adjacency": {
                str(k): [
                    [item[0], item[1], item[2], item[3], item[4],
                     [list(c) for c in item[5]]]
                    for item in v
                ]
                for k, v in self.adjacency.items()
            },
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logging.getLogger(__name__).debug("dual_graph_router._save_to_cache.event")

    # ------------------------------------------------------------------
    # 节点查找
    # ------------------------------------------------------------------

    # 多候选起终点搜索数量
    _ENDPOINT_CANDIDATES = 3       # 起终点各取 K 个最近节点
    _MAX_COMBINATIONS = 9          # K² = 9 种组合

    def _find_nearest_nodes(
        self, lon: float, lat: float, k: int = _ENDPOINT_CANDIDATES,
        max_dist: float = MAX_NEAREST_NODE_DIST,
    ) -> List[Tuple[int, float]]:
        """查找距离给定坐标最近的 K 个图节点。

        Args:
            lon, lat: 目标坐标 (WGS-84)
            k: 返回的候选节点数
            max_dist: 最大搜索半径（米）

        Returns:
            [(node_id, distance_meters), ...] 按距离升序排列，最多 K 个
        """
        target = (lon, lat)
        heap: List[Tuple[float, int]] = []  # (-dist, node_id) for max-heap behavior

        for node_id, coord in self._node_coords.items():
            d = _haversine_meters(target, coord)
            if d <= max_dist:
                heapq.heappush(heap, (-d, node_id))
                if len(heap) > k:
                    heapq.heappop(heap)

        # 按距离升序返回
        result = [(node_id, -neg_d) for neg_d, node_id in sorted(heap, reverse=True)]
        return result

    def _find_nearest_nodes_with_fallback(
        self, lon: float, lat: float, k: int = _ENDPOINT_CANDIDATES,
    ) -> List[Tuple[int, float]]:
        """先查找 500m 内候选；完全没有候选时才扩大到 1000m。"""
        candidates = self._find_nearest_nodes(lon, lat, k, MAX_NEAREST_NODE_DIST)
        if candidates:
            return candidates
        return self._find_nearest_nodes(lon, lat, k, MAX_ROUTE_SNAP_DISTANCE_M)

    # ------------------------------------------------------------------
    # 端点吸附：将起终点投影到最近路段上，消除"飞线"
    # ------------------------------------------------------------------

    def _snap_point_to_network(
        self, lon: float, lat: float, max_dist: float = MAX_ROUTE_SNAP_DISTANCE_M,
    ) -> Optional[Tuple[float, float]]:
        """将坐标吸附到路网上最近的路段投影点。

        遍历所有边，找到距离目标点最近的路段上的投影点。
        用于替代粗暴的"直线连接路网节点"，让起终点自然地接到道路上。

        Args:
            lon, lat: 目标坐标 (WGS-84)
            max_dist: 最大搜索半径（米），超出则放弃吸附

        Returns:
            (lon, lat) 吸附后的坐标，或 None（超出范围）
        """
        target = (lon, lat)
        best_dist = float("inf")
        best_point: Optional[Tuple[float, float]] = None

        for node_id, edges in self.adjacency.items():
            for edge in edges:
                # edge = (neighbor, road_name, norm_name, highway, length_m, coords)
                coords = edge[5] if len(edge) > 5 else []
                if len(coords) < 2:
                    continue

                # 检查该边的每一段
                for i in range(len(coords) - 1):
                    ax, ay = coords[i]
                    bx, by = coords[i + 1]
                    t, _ = _closest_point_on_segment(lon, lat, ax, ay, bx, by)
                    # Compare the actual rounded output with the same spherical
                    # distance used by itinerary import, including north/south gaps.
                    candidate = (round(ax + t * (bx - ax), 6), round(ay + t * (by - ay), 6))
                    dist_m = _haversine_meters(target, candidate)
                    if dist_m < best_dist:
                        best_dist = dist_m
                        best_point = candidate

        if best_point is None or best_dist > max_dist:
            return None

        logging.getLogger(__name__).debug("dual_graph_router._snap_point_to_network.event")
        return best_point

    # ------------------------------------------------------------------
    # Edge-Expanded State A* 寻路
    # ------------------------------------------------------------------

    def route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        via_points: Optional[List[Tuple[float, float]]] = None,
    ) -> Optional[List[List[float]]]:
        """计算两点（或带多个途经点）之间最少换路的示意折线。

        起终点各取最近的 K 个路网节点（K=3），尝试全部 K²=9 种组合，
        选择全局代价最低的路径。避免「最近节点恰好在断头路」的边界情况。

        当指定 via_points 时，将路径拆分为多段：起点→途经点1→...→终点，
        每段独立寻路后拼接。任一段失败则整体返回 None。

        Args:
            origin: (lon, lat) 起点坐标 (WGS-84)
            destination: (lon, lat) 终点坐标 (WGS-84)
            via_points: [(lon, lat), ...] 途经点坐标列表（用户改线指定经过的点）

        Returns:
            [[lon, lat], ...] 折线坐标列表，或 None（寻路失败）
        """
        # 途经点模式：拆分为多段 [起点, 途经点1, ..., 终点] 分段寻路后拼接
        if via_points:
            all_stops = [origin] + list(via_points) + [destination]
            full_polyline: List[List[float]] = []
            t0 = time.time()
            for i in range(len(all_stops) - 1):
                sub_origin = all_stops[i]
                sub_dest = all_stops[i + 1]
                sub_poly = self._route_single_leg(sub_origin, sub_dest, t0)
                if not sub_poly or len(sub_poly) < 2:
                    logging.getLogger(__name__).debug("dual_graph_router.route.event")
                    return None
                for pt in sub_poly:
                    rpt = [pt[0], pt[1]] if not isinstance(pt, list) else pt
                    if not full_polyline or full_polyline[-1] != rpt:
                        full_polyline.append(rpt)
            return full_polyline

        # 无途经点：走原有单段寻路
        return self._route_single_leg(origin, destination, time.time())

    def _route_single_leg(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        t0: float,
    ) -> Optional[List[List[float]]]:
        """单段起终点寻路（与 route 原有逻辑一致）。"""
        # 1. 查找候选节点
        start_candidates = self._find_nearest_nodes_with_fallback(*origin)
        goal_candidates = self._find_nearest_nodes_with_fallback(*destination)

        if not start_candidates:
            logging.getLogger(__name__).debug("dual_graph_router._route_single_leg.event")
            return None
        if not goal_candidates:
            logging.getLogger(__name__).debug("dual_graph_router._route_single_leg.event")
            return None

        # 2. 去重：起终点候选去重（避免 A→A 的无意义组合）
        start_unique = []
        seen_s = set()
        for nid, d in start_candidates:
            if nid not in seen_s:
                seen_s.add(nid)
                start_unique.append((nid, d))
        goal_unique = []
        seen_g = set()
        for nid, d in goal_candidates:
            if nid not in seen_g:
                seen_g.add(nid)
                goal_unique.append((nid, d))

        # 3. 尝试所有 (origin_node, dest_node) 组合
        best_path = None
        best_cost = float("inf")
        best_stats = ""
        tried = 0
        succeeded = 0

        for s_node, s_dist in start_unique:
            for g_node, g_dist in goal_unique:
                if s_node == g_node:
                    # A shared nearest node does not prove a road route exists.
                    # Keep best_path exclusively in A* path-data format; try
                    # other pairs, or return None for the caller's fallback.
                    continue

                tried += 1
                path_data, total_g = self._a_star_search(s_node, g_node, t0,
                                                         budget_remaining=(A_STAR_TIME_BUDGET - (time.time() - t0)))

                if path_data is None:
                    continue

                succeeded += 1

                if total_g < best_cost:
                    best_cost = total_g
                    best_path = path_data
                    # 统计
                    path_states = [item[0] for item in path_data]
                    n_roads = len(set(s.road_name for s in path_states))
                    phys_dist = sum(
                        _haversine_meters(
                            self._node_coords.get(path_states[i].node_id, (0, 0)),
                            self._node_coords.get(path_states[i + 1].node_id, (0, 0)),
                        )
                        for i in range(len(path_states) - 1)
                    )
                    best_stats = (f"{len(path_states)} 步, {n_roads} 条道路, "
                                  f"~{phys_dist / 1000:.1f}km")

                # 时间预算耗尽则停止尝试更多组合
                if time.time() - t0 > A_STAR_TIME_BUDGET:
                    break

        if best_path is None:
            logging.getLogger(__name__).debug("dual_graph_router._route_single_leg.event")
            return None

        elapsed = time.time() - t0
        logging.getLogger(__name__).debug("dual_graph_router._route_single_leg.event")

        # 4. 重建折线
        polyline = self._reconstruct_polyline(best_path, origin, destination)
        return polyline

    def _a_star_search(
        self, start_node: int, goal_node: int, t0: float,
        budget_remaining: float = A_STAR_TIME_BUDGET,
    ) -> Tuple[Optional[List[Tuple[AStarState, List[Tuple[float, float]]]]], float]:
        """Edge-Expanded State A* 搜索。

        状态: (node_id, road_name)
        初始状态不限定道路名（从任意邻近道路出发均可）。
        目标状态只检查 node_id（只要到达目标路口即成功）。

        代价 = 物理距离 + 换路惩罚（基于归一化道路名） + 转弯角度惩罚

        Args:
            start_node: 起点节点 ID
            goal_node: 终点节点 ID
            t0: 计时起点（用于全局时间预算）
            budget_remaining: 剩余时间预算（秒）

        Returns:
            (path_data, total_g) — path_data 为 [(state, edge_coords), ...]
            或 (None, inf) 表示无法到达。
        """
        goal_coord = self._node_coords.get(goal_node)
        if goal_coord is None:
            return None

        # 优先队列: (f_score, tiebreaker, state)
        # tiebreaker 用于避免比较 AStarState（不可比较）
        open_set: List[Tuple[float, int, AStarState]] = []
        tiebreaker = 0

        # g_scores: state -> best known g
        g_scores: Dict[AStarState, float] = {}
        # came_from: state -> (prev_state, edge_info)
        came_from: Dict[AStarState, Tuple[Optional[AStarState], Tuple[int, str, float, List]]] = {}

        # 初始化：从起点出发的所有可能道路
        start_coord = self._node_coords.get(start_node)
        start_h = _haversine_meters(start_coord, goal_coord) if start_coord else 0

        for neighbor, road_name, norm_name, highway, length_m, coords in self.adjacency.get(start_node, []):
            state = AStarState(node_id=neighbor, road_name=road_name, norm_name=norm_name, highway=highway)
            g = length_m
            h = _haversine_meters(
                self._node_coords.get(neighbor, (0, 0)), goal_coord
            )
            g_scores[state] = g
            came_from[state] = (
                AStarState(node_id=start_node, road_name="", norm_name="", highway=""),
                (neighbor, road_name, norm_name, highway, length_m, coords),
            )
            heapq.heappush(open_set, (g + h, tiebreaker, state))
            tiebreaker += 1

        best_goal_g = float("inf")
        best_goal_state: Optional[AStarState] = None
        expanded = 0

        while open_set:
            f, _, current = heapq.heappop(open_set)
            expanded += 1

            # 安全检查
            if expanded > MAX_EXPANDED_STATES:
                logging.getLogger(__name__).debug("dual_graph_router._a_star_search.event")
                break
            if time.time() - t0 > budget_remaining:
                logging.getLogger(__name__).debug("dual_graph_router._a_star_search.event")
                break

            # 若当前 f 已大于最优目标 g，可以提前结束
            if f >= best_goal_g:
                break

            # 检查是否到达目标
            if current.node_id == goal_node:
                if g_scores[current] < best_goal_g:
                    best_goal_g = g_scores[current]
                    best_goal_state = current
                    continue  # 可能还有更优路径到达目标

            current_g = g_scores.get(current, float("inf"))

            # 展开邻居
            for neighbor, next_road, next_norm, next_highway, length_m, coords in self.adjacency.get(current.node_id, []):
                # ═══════════════════════════════════════════════════
                # 代价模型：物理距离 + 换路惩罚（link 感知） + 转弯惩罚 + 快速路折扣
                # ═══════════════════════════════════════════════════

                # 1. 换路惩罚（link 感知）
                #    - 匝道↔主路 或 主路↔匝道：极低惩罚（上下高架是必要的）
                #    - 两条主路之间换路：施加换路惩罚
                #    - 同一归一化道路名：无惩罚
                penalty = 0.0
                curr_is_link = "_link" in current.highway
                next_is_link = "_link" in next_highway

                if curr_is_link or next_is_link:
                    # 涉及匝道的转换 → 极低惩罚
                    if current.norm_name and next_norm and next_norm != current.norm_name:
                        penalty = LINK_SWITCH_PENALTY
                else:
                    # 两条都是主路 → 正常换路惩罚
                    if current.norm_name and next_norm and next_norm != current.norm_name:
                        penalty = self.switch_penalty

                # 2. 快速路/高架折扣（motorway/trunk 成本 × 0.85，引导走大动脉）
                edge_cost = length_m
                if "motorway" in next_highway or "trunk" in next_highway:
                    edge_cost *= EXPRESSWAY_DISCOUNT

                # 3. 转弯角度惩罚（从 came_from 回溯前序节点坐标）
                turn_penalty = 0.0
                curr_coord = self._node_coords.get(current.node_id)
                neighbor_coord = self._node_coords.get(neighbor)
                if curr_coord and neighbor_coord:
                    prev_state, _ = came_from.get(current, (None, None))
                    if prev_state is not None and prev_state.node_id != start_node:
                        prev_coord = self._node_coords.get(prev_state.node_id)
                        if prev_coord:
                            angle = _calculate_turn_angle(prev_coord, curr_coord, neighbor_coord)
                            if angle > 60.0:  # 只对明显转弯（>60°）施加惩罚
                                turn_penalty = (angle / 90.0) * TURN_PENALTY_FACTOR

                next_g = current_g + edge_cost + penalty + turn_penalty
                next_state = AStarState(node_id=neighbor, road_name=next_road, norm_name=next_norm, highway=next_highway)

                # 剪枝
                if next_g >= g_scores.get(next_state, float("inf")):
                    continue
                if next_g >= best_goal_g:
                    continue

                g_scores[next_state] = next_g
                came_from[next_state] = (
                    current,
                    (neighbor, next_road, next_norm, next_highway, length_m, coords),
                )

                h = _haversine_meters(
                    self._node_coords.get(neighbor, (0, 0)), goal_coord
                )
                heapq.heappush(open_set, (next_g + h, tiebreaker, next_state))
                tiebreaker += 1

        # 回溯路径
        if best_goal_state is not None:
            # 从 came_from 反向追溯，收集 (state, edge_geometry) 对
            path_pairs = []  # [(state, edge_coords), ...]
            state = best_goal_state
            while state in came_from:
                prev_state, edge_info = came_from[state]
                # edge_info = (neighbor_node, road_name, norm_name, highway, length_m, coords)
                edge_coords = edge_info[5] if len(edge_info) > 5 and isinstance(edge_info[5], (list, tuple)) else []
                path_pairs.append((state, edge_coords))
                if prev_state is None or prev_state.node_id == start_node:
                    break
                state = prev_state
            path_pairs.reverse()
            return path_pairs, best_goal_g

        return None, float("inf")

    def _reconstruct_polyline(
        self,
        path_data: List[Tuple[AStarState, List[Tuple[float, float]]]],
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> List[List[float]]:
        """从 A* 路径数据重建连续的 WGS-84 折线。

        起终点吸附到最近路段投影点（而非粗暴直线连接），消除穿楼飞线。

        Args:
            path_data: [(state, edge_coords), ...] 从 _a_star_search 返回
            origin: 原始起点坐标
            destination: 原始终点坐标

        Returns:
            [[lon, lat], ...] 折线坐标列表
        """
        if not path_data:
            return [[origin[0], origin[1]], [destination[0], destination[1]]]

        result: List[List[float]] = []

        # 起点：吸附到最近路段（或退化为最近路网节点）
        snapped_origin = self._snap_point_to_network(*origin)
        if snapped_origin:
            result.append([snapped_origin[0], snapped_origin[1]])
        else:
            # 回退：使用第一个路径节点的坐标
            first_state = path_data[0][0]
            first_coord = self._node_coords.get(first_state.node_id)
            if first_coord:
                result.append([round(first_coord[0], 6), round(first_coord[1], 6)])
            else:
                result.append([round(origin[0], 6), round(origin[1], 6)])

        # 拼接各段的 edge geometry
        for state, edge_coords in path_data:
            if not isinstance(edge_coords, (list, tuple)):
                continue
            for pt in edge_coords:
                rpt = [round(pt[0], 6), round(pt[1], 6)]
                if not result or result[-1] != rpt:
                    result.append(rpt)

        # 终点：吸附到最近路段
        snapped_dest = self._snap_point_to_network(*destination)
        if snapped_dest:
            dest_pt = [snapped_dest[0], snapped_dest[1]]
        else:
            last_state = path_data[-1][0]
            last_coord = self._node_coords.get(last_state.node_id)
            if last_coord:
                dest_pt = [round(last_coord[0], 6), round(last_coord[1], 6)]
            else:
                dest_pt = [round(destination[0], 6), round(destination[1], 6)]

        if not result or result[-1] != dest_pt:
            result.append(dest_pt)

        return result

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values()) // 2

    def edge_count_for_node(self, node_id: int) -> int:
        return len(self.adjacency.get(node_id, []))


# ---------------------------------------------------------------------------
# 模块级工厂函数
# ---------------------------------------------------------------------------

_router_cache: Dict[str, Optional[DualGraphRouter]] = {}


def create_dual_graph_router(
    city_name: str = "Zhejiang",
    switch_penalty: float = DEFAULT_SWITCH_PENALTY,
    cache_dir: Optional[str] = None,
    geojson_path: Optional[str] = None,
    force_reload: bool = False,
    clip_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[DualGraphRouter]:
    """创建 DualGraphRouter 实例（带缓存）。

    数据源优先级：
      1. 本地 GeoJSON 文件（geojson_path 或默认路径）
      2. JSON 缓存（首次加载 GeoJSON 后自动生成）
      3. osmnx 在线下载（需要 osmnx + Overpass API）

    首次创建需要处理路网数据（5-30 秒），后续调用直接返回缓存实例。

    Args:
        city_name: 城市名（osmnx 查询用，GeoJSON 模式下仅用于缓存 key）
        switch_penalty: 换路惩罚（米）
        cache_dir: 缓存目录
        geojson_path: QGIS QuickOSM 导出的 GeoJSON 路径（None 则使用默认路径）
        force_reload: 强制重建（忽略缓存）
        clip_bbox: 路网裁剪范围 (min_lon, min_lat, max_lon, max_lat)，外扩 5km 推荐

    Returns:
        DualGraphRouter 实例，或 None（所有数据源均失败）
    """
    cache_key = network_cache_identity(city_name, switch_penalty, cache_dir, geojson_path, clip_bbox)
    if cache_key in _router_cache and not force_reload:
        return _router_cache[cache_key]

    try:
        router = DualGraphRouter(
            city_name=city_name,
            switch_penalty=switch_penalty,
            cache_dir=cache_dir,
            geojson_path=geojson_path,
            clip_bbox=clip_bbox,
            force_reload=force_reload,
        )
        _router_cache[cache_key] = router
        return router
    except Exception as e:
        logging.getLogger(__name__).debug("dual_graph_router.create_dual_graph_router.event")
        import traceback
        traceback.print_exc()
        _router_cache[cache_key] = None
        return None


def replace_leg_polyline(
    router: DualGraphRouter,
    from_point: Dict,
    to_point: Dict,
    via_points: Optional[List[Dict]] = None,
) -> Optional[List[List[float]]]:
    """用对偶图折线替换单个航段的 polyline（支持途经点改线）。

    Args:
        router: DualGraphRouter 实例
        from_point: 起点 dict，含 lon/lat (WGS-84)
        to_point: 终点 dict，含 lon/lat (WGS-84)
        via_points: 途经点列表 [{"lon": ..., "lat": ...}, ...]，用户改线指定经过的点

    Returns:
        [[lon, lat], ...] 新折线，或 None（用对偶图失败，调用方保留原折线）
    """
    origin = (from_point.get("lon", 0), from_point.get("lat", 0))
    destination = (to_point.get("lon", 0), to_point.get("lat", 0))

    if origin == (0, 0) or destination == (0, 0):
        return None

    via_coords = None
    if via_points:
        via_coords = [
            (float(p["lon"]), float(p["lat"]))
            for p in via_points
            if p.get("lon") and p.get("lat")
        ]
        if not via_coords:
            via_coords = None

    return router.route(origin, destination, via_points=via_coords)
