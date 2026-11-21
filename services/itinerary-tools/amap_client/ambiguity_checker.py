# -*- coding: utf-8 -*-
"""
ambiguity_checker.py — 地理编码歧义检查模块

三种使用方式：
  1. 库模式：从 geocoder 中调用 check_amap_pois() / check_datav_sample()
  2. CLI 预检：python -m phase1_geocoding.ambiguity_checker input.json
  3. CLI 单地名：python -m phase1_geocoding.ambiguity_checker --name "地名" --city "城市"

检查规则：
  - 阻断：同名多址（去重后 ≥2 个异址候选）
  - 阻断：城市不匹配
  - 阻断：API 无结果
  - 警告：名称近似但不完全匹配
  - 通过：单结果、名称匹配、城市匹配
"""

from __future__ import annotations
import logging
import math
import json
import sys
import os
import re
from .amap_rate_limit import wait_for_amap_slot
from dataclasses import dataclass, field
from typing import List, Optional

# ═══════════════════════════════════════════════════════════
# 可调参数
# ═══════════════════════════════════════════════════════════

DISTANCE_THRESHOLD_M = 100.0        # 坐标距离 < 此值视为同址（米）
JACCARD_THRESHOLD = 0.7             # Jaccard 地址相似度 > 此值视为同址
NAME_SIMILARITY_WARN_THRESHOLD = 0.6  # 名称编辑距离相似度 < 此值时警告
MAX_CANDIDATES_FETCH = 5            # 歧义时追加请求获取的候选数量上限


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Candidate:
    """单个地理编码候选"""
    name: str
    address: str
    city: str
    district: str
    lon: float
    lat: float
    poi_id: Optional[str] = None


@dataclass
class AmbiguityReport:
    """单个地名的检查报告"""
    input_name: str
    input_city: str
    total_candidates: int
    candidates: List[Candidate] = field(default_factory=list)
    verdict: str = "pass"           # "pass" | "block" | "warn"
    block_reason: str = ""          # "" | "同名多址" | "城市不匹配" | "API无结果" | "名称近似"
    severity: str = "block"         # "block" | "warn" — 前端据此区分样式
    warnings: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [f"地名「{self.input_name}」"]
        if self.input_city:
            parts.append(f"城市「{self.input_city}」")
        if self.verdict == "pass":
            parts.append(f"-> 通过 (共 {self.total_candidates} 个候选)")
        elif self.verdict == "warn":
            parts.append(f"-> 警告: {', '.join(self.warnings)}")
        else:
            parts.append(f"-> 阻断: {self.block_reason}")
            parts.append(f"  候选 ({len(self.candidates)}):")
            for i, c in enumerate(self.candidates, 1):
                parts.append(
                    f"    [{i}] {c.name} | {c.address} | "
                    f"{c.city} {c.district} | ({c.lon}, {c.lat})"
                )
        if self.warnings and self.verdict != "warn":
            for w in self.warnings:
                parts.append(f"  ⚠ {w}")
        return "\n".join(parts)


class GeoAmbiguityError(Exception):
    """单地点歧义阻断异常"""
    def __init__(self, report: AmbiguityReport):
        self.report = report
        super().__init__(str(report))


class MultiGeoAmbiguityError(Exception):
    """批量歧义阻断异常"""
    def __init__(self, items: List[AmbiguityReport], *, partial_points=None):
        self.partial_points = partial_points or []
        # 按 (input_name, input_city) 去重，保留首次出现
        seen = set()
        deduped = []
        for r in items:
            key = (r.input_name, r.input_city)
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        self.items = deduped
        # block 在前，warn 在后
        deduped.sort(key=lambda r: (0 if r.severity == "block" else 1, r.input_name))
        names = ", ".join(r.input_name for r in deduped)
        super().__init__(f"共 {len(deduped)} 处地名需要确认: {names}")


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """计算两点间的球面距离（米）"""
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _tokenize(s: str) -> set:
    """中文文本分词：按字符 bigram + 单字"""
    if not isinstance(s, str):
        s = "".join(str(x) for x in s) if isinstance(s, (list, tuple)) else str(s)
    s = s.strip()
    tokens = set()
    # bigram
    for i in range(len(s) - 1):
        tokens.add(s[i:i + 2])
    # 单字
    for ch in s:
        tokens.add(ch)
    # 数字序列整体作为一个 token
    import re
    for m in re.finditer(r'\d+', s):
        tokens.add(m.group())
    return tokens


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard 相似度（基于字符 bigram + 单字分词）"""
    set_a = _tokenize(a)
    set_b = _tokenize(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _edit_distance_ratio(a: str, b: str) -> float:
    """归一化编辑距离相似度（0~1，1 为完全相同）"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Levenshtein distance
    m, n = len(a), len(b)
    # 使用两行 DP 节省空间
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost  # substitution
            )
        prev, curr = curr, prev
    max_len = max(m, n)
    return 1.0 - (prev[n] / max_len)


def _city_matches(api_city: str, input_city: str) -> bool:
    """
    宽松城市匹配：处理 "杭州" vs "杭州市" 这类后缀差异。
    同时处理空值：api_city 为空时视为匹配（API 可能不返回 cityname）。
    """
    if not input_city:
        return True
    if not api_city:
        return True  # API 未返回城市信息时不阻断，由其他检查兜底
    # 直接相等
    if api_city == input_city:
        return True
    # 一方包含另一方（如 "杭州" in "杭州市"）
    if input_city in api_city or api_city in input_city:
        return True
    # 去掉常见后缀后再比
    for suffix in ("市", "区", "县", "省"):
        a = api_city.rstrip(suffix)
        b = input_city.rstrip(suffix)
        if a == b or (a and b and (a in b or b in a)):
            return True
    return False


def _deduplicate_by_address(candidates: List[Candidate]) -> List[List[Candidate]]:
    """
    地址去重：将候选按"是否为同一地点"分组。

    两个候选判为同址当满足任一：
      ① 坐标距离 < DISTANCE_THRESHOLD_M
      ② 行政区相同 AND 地址 Jaccard > JACCARD_THRESHOLD
      ③ 行政区相同 AND 名称存在包含关系（停车场/广场是主体的附属 POI）

    返回分组列表，每组内的候选视为同一地点。
    """
    n = len(candidates)
    if n <= 1:
        return [candidates] if candidates else []

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = candidates[i], candidates[j]

            # 条件①: 坐标距离
            dist = _haversine_meters(ci.lon, ci.lat, cj.lon, cj.lat)
            if dist < DISTANCE_THRESHOLD_M:
                union(i, j)
                continue

            # 条件②: 同行政区 + 地址高相似
            same_district = (
                ci.district == cj.district and
                ci.district != "" and cj.district != ""
            )
            if same_district:
                jaccard = _jaccard_similarity(ci.address, cj.address)
                if jaccard > JACCARD_THRESHOLD:
                    union(i, j)

            # 条件③: 同行政区 + 名称包含关系（如主体 vs 停车场/广场）
            if same_district:
                ni, nj = ci.name, cj.name
                if ni and nj and (ni in nj or nj in ni):
                    union(i, j)

    # 分组
    groups: dict = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(candidates[i])

    return list(groups.values())


# ═══════════════════════════════════════════════════════════
# 核心检查函数
# ═══════════════════════════════════════════════════════════

def _build_candidates_from_amap_pois(pois: list) -> List[Candidate]:
    """从 Amap POI 搜索结果构建候选列表"""
    result = []
    for poi in pois:
        loc_str = poi.get("location", "")
        if not loc_str:
            continue
        try:
            lon, lat = map(float, loc_str.split(","))
        except (ValueError, TypeError):
            continue
        raw_address = poi.get("address", "")
        if isinstance(raw_address, list):
            raw_address = "".join(str(a) for a in raw_address if a)
        result.append(Candidate(
            name=poi.get("name", ""),
            address=raw_address,
            city=poi.get("cityname", ""),
            district=poi.get("adname", ""),
            lon=round(lon, 6),
            lat=round(lat, 6),
            poi_id=poi.get("id", None),
        ))
    return result


def _build_candidates_from_datav_sample(sample: list) -> List[Candidate]:
    """从 DataV MCP sample 构建候选列表"""
    result = []
    for item in sample:
        try:
            lon = float(item.get("lng") or item.get("lon"))
            lat = float(item.get("lat"))
        except (ValueError, TypeError):
            continue
        result.append(Candidate(
            name=item.get("name", ""),
            address=item.get("address", ""),
            city=item.get("city", ""),
            district=item.get("district", ""),
            lon=round(lon, 6),
            lat=round(lat, 6),
            poi_id=None,
        ))
    return result


def check_amap_pois(
    name: str,
    city: str,
    pois_list: list,
    total_count: int,
) -> AmbiguityReport:
    """
    检查 Amap POI 搜索结果是否存在歧义。

    Args:
        name: 用户输入的地名
        city: 用户输入的城市
        pois_list: API 返回的 pois 数组
        total_count: API 返回的 count 字段（总命中数）

    Returns:
        AmbiguityReport
    """
    report = AmbiguityReport(
        input_name=name,
        input_city=city,
        total_candidates=total_count,
    )

    # ── 阻断: API 无结果 ──
    if total_count == 0 or not pois_list:
        report.verdict = "block"
        report.block_reason = "API无结果"
        return report

    candidates = _build_candidates_from_amap_pois(pois_list)
    if not candidates:
        report.verdict = "block"
        report.block_reason = "API无结果"
        return report

    report.candidates = candidates

    # ── 阻断: 城市不匹配 ──
    if city:
        city_matched = [c for c in candidates if _city_matches(c.city, city)]
        if not city_matched:
            # 所有候选的城市都不匹配
            report.verdict = "block"
            report.block_reason = "城市不匹配"
            return report
        # A passing report must never select an out-of-city candidate.
        candidates = city_matched
        report.candidates = candidates

    # ── 地址去重 ──
    groups = _deduplicate_by_address(candidates)

    if len(groups) >= 2:
        # 多个不同地址 -> 真歧义
        report.verdict = "block"
        report.block_reason = "同名多址"
        # 每组取第一个作为代表候选
        report.candidates = [g[0] for g in groups]
    else:
        # 同址 -> 通过（取第一组的第一条）
        report.candidates = [groups[0][0]]
        report.verdict = "pass"

        # A building centre cannot silently stand in for a requested entrance.
        entrances = re.findall(r'(?:东北|东南|西北|西南|东|西|南|北|正|侧|后)门|[一二三四五六七八九十0-9]+号门', name)
        selected_text = report.candidates[0].name + ' ' + str(report.candidates[0].address)
        if any(entrance not in selected_text for entrance in entrances):
            report.verdict = 'warn'
            report.severity = 'warn'
            report.block_reason = '入口不明确'
            report.warnings.append('返回地点未明确包含原文指定入口，需要用户确认。')
            return report

        # ── 警告: 名称近似度检查 ──
        sim = _edit_distance_ratio(name, report.candidates[0].name)
        if sim < NAME_SIMILARITY_WARN_THRESHOLD:
            report.verdict = "warn"
            report.severity = "warn"
            report.block_reason = "名称近似"
            report.warnings.append(
                f"返回名称「{report.candidates[0].name}」与输入「{name}」相似度过低 ({sim:.2f})"
            )

    return report


def check_datav_sample(
    name: str,
    city: str,
    sample_list: list,
) -> AmbiguityReport:
    """
    检查 DataV MCP GeoCoding 返回的 sample 是否存在歧义。

    Args:
        name: 用户输入的地名
        city: 用户输入的城市
        sample_list: MCP 返回的 sample 数组

    Returns:
        AmbiguityReport
    """
    report = AmbiguityReport(
        input_name=name,
        input_city=city,
        total_candidates=len(sample_list),
    )

    # ── 阻断: API 无结果 ──
    if not sample_list:
        report.verdict = "block"
        report.block_reason = "API无结果"
        return report

    candidates = _build_candidates_from_datav_sample(sample_list)
    if not candidates:
        report.verdict = "block"
        report.block_reason = "API无结果"
        return report

    report.candidates = candidates

    # ── 阻断: 城市不匹配 ──
    if city:
        city_matched = [c for c in candidates if _city_matches(c.city, city)]
        if not city_matched:
            report.verdict = "block"
            report.block_reason = "城市不匹配"
            return report

    # ── 地址去重 ──
    groups = _deduplicate_by_address(candidates)

    if len(groups) >= 2:
        report.verdict = "block"
        report.block_reason = "同名多址"
        report.candidates = [g[0] for g in groups]
    else:
        report.candidates = [groups[0][0]]
        report.verdict = "pass"

        sim = _edit_distance_ratio(name, report.candidates[0].name)
        if sim < NAME_SIMILARITY_WARN_THRESHOLD:
            report.verdict = "warn"
            report.severity = "warn"
            report.block_reason = "名称近似"
            report.warnings.append(
                f"返回名称「{report.candidates[0].name}」与输入「{name}」相似度过低 ({sim:.2f})"
            )

    return report


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def _cli_check_single(name: str, city: str, provider: str = "amap"):
    """CLI 模式：检查单个地名（同步封装，内部 asyncio.run）"""
    if provider == "amap":
        import asyncio
        import httpx
        from .geocoder_amap import AmapGeocoder

        amap_key = os.environ.get("CARTO_AMAP_KEY", "")

        async def _run():
            geocoder = AmapGeocoder(amap_key=amap_key)
            async with httpx.AsyncClient(trust_env=False, verify=True) as client:
                # offset=5 一次拿齐，与管线行为一致
                poi_params = {
                    "key": amap_key,
                    "keywords": name,
                    "extensions": "base",
                    "offset": MAX_CANDIDATES_FETCH,
                    "page": 1,
                }
                if city:
                    poi_params["city"] = city
                    poi_params["citylimit"] = "true"

                await wait_for_amap_slot()
                resp = await client.get(geocoder.POI_SEARCH_URL, params=poi_params, timeout=10.0)
                data = resp.json()

                if data.get("status") != "1":
                    logging.getLogger(__name__).debug("ambiguity_checker._run.event")
                    return None

                count = int(data.get("count", 0))
                pois = data.get("pois", [])
                return check_amap_pois(name, city, pois, count)

        return asyncio.run(_run())
    else:
        logging.getLogger(__name__).debug("ambiguity_checker._cli_check_single.event")
        return None


def _cli_check_file(filepath: str, provider: str = "amap"):
    """CLI 模式：检查 JSON 文件中所有地点（单次事件循环，共享 HTTP 连接）"""
    import asyncio
    import httpx

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 提取所有地点
    locations: List[tuple] = []  # (name, city)

    # 支持 test_3.json 格式（transit 数组）
    transit = data.get("transit") or data.get("days") or []
    for day in transit:
        for session in day.get("sessions", []):
            for key in ("startPoint", "endPoint"):
                pt = session.get(key, {})
                if pt and pt.get("name"):
                    locations.append((pt["name"], pt.get("city", "")))
            for pt in session.get("points", []):
                if pt and pt.get("name"):
                    locations.append((pt["name"], pt.get("city", "")))

    # 支持旧格式（locations 数组）
    if not locations:
        locs = data.get("locations", [])
        for loc in locs:
            if loc.get("name"):
                locations.append((loc["name"], loc.get("city", "")))

    if not locations:
        logging.getLogger(__name__).debug("ambiguity_checker._cli_check_file.event")
        return

    # 去重
    seen = set()
    unique_locations = []
    for name, city in locations:
        key = (name, city)
        if key not in seen:
            seen.add(key)
            unique_locations.append(key)

    logging.getLogger(__name__).debug("ambiguity_checker._cli_check_file.event")

    if provider != "amap":
        logging.getLogger(__name__).debug("ambiguity_checker._cli_check_file.event")
        return

    from .geocoder_amap import AmapGeocoder
    amap_key_batch = os.environ.get("CARTO_AMAP_KEY", "")

    async def _run_batch():
        geocoder = AmapGeocoder(amap_key=amap_key_batch)
        async with httpx.AsyncClient(trust_env=False, verify=True) as client:
            for name, city in unique_locations:
                logging.getLogger(__name__).debug("ambiguity_checker._run_batch.event")
                poi_params = {
                    "key": amap_key,
                    "keywords": name,
                    "extensions": "base",
                    "offset": MAX_CANDIDATES_FETCH,
                    "page": 1,
                }
                if city:
                    poi_params["city"] = city
                    poi_params["citylimit"] = "true"

                await wait_for_amap_slot()
                resp = await client.get(geocoder.POI_SEARCH_URL, params=poi_params, timeout=10.0)
                data_resp = resp.json()

                if data_resp.get("status") != "1":
                    logging.getLogger(__name__).debug("ambiguity_checker._run_batch.event")
                    continue

                count = int(data_resp.get("count", 0))
                pois = data_resp.get("pois", [])
                report = check_amap_pois(name, city, pois, count)
                logging.getLogger(__name__).debug("ambiguity_checker._run_batch.event")
                logging.getLogger(__name__).debug("ambiguity_checker._run_batch.event")

    asyncio.run(_run_batch())
        # (此处简化，实际 _cli_check_single 异步，需改为同步收集)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="地理编码歧义检查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m phase1_geocoding.ambiguity_checker test_3.json
  python -m phase1_geocoding.ambiguity_checker --name "浙江大学紫金港校区" --city "杭州"
  python -m phase1_geocoding.ambiguity_checker --name "人民广场"
        """.strip(),
    )
    parser.add_argument("file", nargs="?", help="包含地点的 JSON 文件路径")
    parser.add_argument("--name", "-n", help="单个地名")
    parser.add_argument("--city", "-c", help="城市（配合 --name 使用）")
    parser.add_argument("--provider", "-p", default="amap",
                        choices=["amap", "datav"], help="地理编码后端 (默认 amap)")

    args = parser.parse_args()

    if args.name:
        _cli_check_single(args.name, args.city or "", args.provider)
    elif args.file:
        _cli_check_file(args.file, args.provider)
    else:
        parser.print_help()
