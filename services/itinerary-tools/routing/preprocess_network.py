# -*- coding: utf-8 -*-
"""
preprocess_network.py — 骨干路网离线平面化与拓扑打断预处理工具

功能：
  1. 过滤：只提取骨干道路 (motorway, trunk, primary, secondary 含 link)，剔除小区/内部路/无名路
  2. 降维：剥离 layer/三维高程，统一压平到同一 2D 平面
  3. 平面化打断：在所有平面相交点处打断线段 (Planarize / Noding)，打通全城大动脉
  4. 属性找回：使用 STRtree 空间索引，高速将原始道路名 (name) 赋回打断后的各线段
  5. 导出：生成干净精简的 *_planar.geojson，供 DualGraphRouter 秒级加载

用法：
  python preprocess_network.py -i data/highway_hangzhou.geojson -o data/highway_hangzhou_planar.geojson
  python preprocess_network.py -i data/highway_hangzhou.geojson -o data/hangzhou_planar.geojson --bbox 120.0,30.1,120.5,30.4
"""

import os
import sys
import json
import time
import argparse
from typing import List, Tuple, Optional

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, desc="", total=None, **kwargs):
        if total:
            print(f"  [{desc}] 共 {total} 项...")
        else:
            print(f"  [{desc}] 处理中...")
        for i, item in enumerate(iterable):
            if total and i % max(1, total // 10) == 0:
                print(f"    ... {i}/{total} ({100 * i // total}%)")
            yield item
        if total:
            print(f"    ... {total}/{total} (100%)")

try:
    import shapely
    from shapely.geometry import shape, Point, LineString, MultiLineString
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    _SHAPELY_VERSION = tuple(int(x) for x in shapely.__version__.split(".")[:2])
except ImportError:
    print("[错误] 请先安装 shapely: pip install shapely")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
KEEP_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
}

NOISE_KEYWORDS = ["内部", "专用", "便道", "小区", "地下", "车库", "停车场"]

BBOX_BUFFER_KM = 5.0  # bbox 裁剪时的外扩距离（公里）


# ---------------------------------------------------------------------------
# 阶段 1：清洗过滤
# ---------------------------------------------------------------------------

def clean_and_filter_features(
    raw_features: list,
    clip_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[List[LineString], List[dict]]:
    """阶段 1：过滤骨干网，剔除噪声和无名道路，提取纯 2D 几何。

    Args:
        raw_features: GeoJSON features 列表
        clip_bbox: 可选裁剪范围 (min_lon, min_lat, max_lon, max_lat)

    Returns:
        (geoms, props): 几何列表 + 对应的属性字典列表
    """
    valid_geoms: List[LineString] = []
    valid_props: List[dict] = []

    if clip_bbox:
        min_lon, min_lat, max_lon, max_lat = clip_bbox
        print(f"  bbox 裁剪范围: lon=[{min_lon:.4f}, {max_lon:.4f}] "
              f"lat=[{min_lat:.4f}, {max_lat:.4f}]")

    skipped = {"non_highway": 0, "no_name": 0, "noise": 0, "short": 0, "bbox": 0}

    for feat in tqdm(raw_features, desc="要素清洗与初筛"):
        props = feat.get("properties", {}) or {}
        geom_dict = feat.get("geometry", {}) or {}

        if geom_dict.get("type") not in ("LineString", "MultiLineString"):
            continue

        # highway 类型过滤
        hw = str(props.get("highway", "")).strip()
        if hw not in KEEP_HIGHWAY_TYPES:
            skipped["non_highway"] += 1
            continue

        # 名称清洗
        name = str(props.get("name", "")).strip()
        if not name or name.lower() in ("null", "none", "未命名", "未命名道路"):
            # link 匝道允许无名（用 highway 类型兜底）
            if "_link" in hw:
                name = f"[匝道]_{hw}"
            else:
                # 尝试 ref（如 G2504）
                name = str(props.get("ref", "")).strip()
                if not name:
                    skipped["no_name"] += 1
                    continue

        if any(kw in name for kw in NOISE_KEYWORDS):
            skipped["noise"] += 1
            continue

        # 几何解析与降维（剥离 Z 坐标）
        try:
            g = shape(geom_dict)
            if g.is_empty:
                continue

            coords_list = []
            if g.geom_type == "LineString":
                coords_list = [g.coords]
            elif g.geom_type == "MultiLineString":
                coords_list = [part.coords for part in g.geoms]
            else:
                continue

            for coords in coords_list:
                pts_2d = [(round(c[0], 7), round(c[1], 7)) for c in coords]
                if len(pts_2d) < 2:
                    skipped["short"] += 1
                    continue

                # bbox 裁剪
                if clip_bbox:
                    g_min_lon = min(p[0] for p in pts_2d)
                    g_max_lon = max(p[0] for p in pts_2d)
                    g_min_lat = min(p[1] for p in pts_2d)
                    g_max_lat = max(p[1] for p in pts_2d)
                    if (g_max_lon < min_lon or g_min_lon > max_lon or
                        g_max_lat < min_lat or g_min_lat > max_lat):
                        skipped["bbox"] += 1
                        continue

                clean_geom = LineString(pts_2d)
                valid_geoms.append(clean_geom)
                valid_props.append({"name": name, "highway": hw})

        except Exception:
            continue

    print(f"  -> 保留骨干路段: {len(valid_geoms)} 条")
    if skipped["non_highway"]:
        print(f"     跳过非骨干: {skipped['non_highway']}")
    if skipped["no_name"]:
        print(f"     跳过无名路: {skipped['no_name']}")
    if skipped["noise"]:
        print(f"     跳过噪声路: {skipped['noise']}")
    if skipped["bbox"]:
        print(f"     跳过超出bbox: {skipped['bbox']}")

    return valid_geoms, valid_props


# ---------------------------------------------------------------------------
# 阶段 2：平面化打断
# ---------------------------------------------------------------------------

def planarize_lines(lines: List[LineString]) -> List[LineString]:
    """阶段 2：空间相交打断（平面化拓扑重建）。

    使用 unary_union 合并所有道路 → 在所有交叉处自动切断 → 提取子段。
    Shapely 2.x 底层调用 GEOS C 库，2 万+ 条路段通常在 10~60 秒内完成。
    """
    print(f"\n[步骤 2/4] 执行几何相交打断（平面化二维压缩）...")
    print(f"  -> 输入 {len(lines)} 条路段，使用 unary_union 合并打断...")
    t0 = time.time()

    merged = unary_union(lines)

    segments = []
    if isinstance(merged, LineString):
        segments = [merged]
    elif isinstance(merged, MultiLineString):
        segments = list(merged.geoms)
    elif hasattr(merged, "geoms"):
        # GeometryCollection
        for g in merged.geoms:
            if isinstance(g, LineString):
                segments.append(g)
            elif isinstance(g, MultiLineString):
                segments.extend(list(g.geoms))

    elapsed = time.time() - t0
    print(f"  -> 打断完成 ({elapsed:.1f}s)，生成拓扑子路段: {len(segments)} 条")
    return segments


# ---------------------------------------------------------------------------
# 阶段 3：属性回填
# ---------------------------------------------------------------------------

def reattach_attributes(
    segments: List[LineString],
    orig_geoms: List[LineString],
    orig_props: List[dict],
) -> List[dict]:
    """阶段 3：通过 STRtree 空间索引将道路名/类型回填到打断后的小段。

    Shapely 2.x → STRtree.nearest()（O(log n) 精确匹配）
    Shapely 1.x → STRtree.query() 后距离排序（兼容回退）
    """
    print(f"\n[步骤 3/4] 构建空间索引并恢复路名属性...")
    t0 = time.time()
    tree = STRtree(orig_geoms)
    output_features = []

    for seg in tqdm(segments, desc="匹配路名属性"):
        if seg.length == 0:
            continue

        mid_pt = seg.interpolate(0.5, normalized=True)

        if _SHAPELY_VERSION >= (2, 0):
            # Shapely 2.x: nearest() 返回最近几何的索引
            nearest_idx = tree.nearest(mid_pt)
            matched_prop = orig_props[nearest_idx]
        else:
            # Shapely 1.x: query() 返回候选几何列表，手动找最近
            candidates = tree.query(mid_pt)
            if not candidates:
                # fallback: 全量搜索
                candidates = orig_geoms
            best_idx = 0
            best_dist = float("inf")
            for i, cand in enumerate(candidates):
                d = cand.distance(mid_pt)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            # candidates[i] 对应的是 orig_geoms 中的某个几何
            # 但 query 返回的是几何对象本身，需要找回索引
            # 简化处理：遍历 candidates 找到对应的 orig_geoms 索引
            cand_geom = candidates[best_idx] if isinstance(best_idx, int) and best_idx < len(candidates) else candidates[0]
            # 在 orig_geoms 中找匹配
            matched_idx = 0
            for j, orig_g in enumerate(orig_geoms):
                if orig_g is cand_geom or orig_g.equals(cand_geom):
                    matched_idx = j
                    break
            matched_prop = orig_props[matched_idx]

        coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in seg.coords]
        output_features.append({
            "type": "Feature",
            "properties": {
                "name": matched_prop["name"],
                "highway": matched_prop["highway"],
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
        })

    elapsed = time.time() - t0
    print(f"  -> 属性回填完成 ({elapsed:.1f}s)，{len(output_features)} 个 feature")
    return output_features


# ---------------------------------------------------------------------------
# bbox 解析
# ---------------------------------------------------------------------------

def parse_bbox(bbox_str: str) -> Optional[Tuple[float, float, float, float]]:
    """解析 bbox 字符串 "min_lon,min_lat,max_lon,max_lat" 并外扩。"""
    if not bbox_str:
        return None
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        print(f"[错误] bbox 格式错误: '{bbox_str}'，应为 'min_lon,min_lat,max_lon,max_lat'")
        sys.exit(1)

    # 外扩 buffer
    mid_lat = (parts[1] + parts[3]) / 2.0
    import math as _math
    deg_per_km_lat = 1.0 / 111.32
    deg_per_km_lon = 1.0 / (111.32 * _math.cos(_math.radians(mid_lat)))
    buf_lon = BBOX_BUFFER_KM * deg_per_km_lon
    buf_lat = BBOX_BUFFER_KM * deg_per_km_lat

    return (parts[0] - buf_lon, parts[1] - buf_lat,
            parts[2] + buf_lon, parts[3] + buf_lat)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="路网二维平面化与打断预处理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 全城处理
  python preprocess_network.py -i data/highway_hangzhou.geojson -o data/hangzhou_planar.geojson

  # 仅处理指定范围（适合快速测试局部路段）
  python preprocess_network.py -i data/highway_hangzhou.geojson -o data/hangzhou_planar.geojson \\
      --bbox 120.0,30.1,120.5,30.4
        """,
    )
    parser.add_argument("--input", "-i", required=True, help="QGIS 导出的原始 GeoJSON 路径")
    parser.add_argument("--output", "-o", required=True, help="处理后的输出 GeoJSON 路径")
    parser.add_argument("--bbox", default=None,
                       help="裁剪范围: min_lon,min_lat,max_lon,max_lat（自动外扩 5km）")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[错误] 输入文件不存在: {args.input}")
        sys.exit(1)

    clip_bbox = parse_bbox(args.bbox)

    t_start = time.time()
    print(f"═" * 60)
    print(f"路网预处理工具")
    print(f"  输入: {args.input}")
    print(f"  输出: {args.output}")
    print(f"  Shapely 版本: {shapely.__version__}")
    if clip_bbox:
        print(f"  bbox 裁剪: {clip_bbox}")
    print(f"═" * 60)

    # 读取
    print(f"\n[步骤 0/4] 读取 GeoJSON...")
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw_features = data.get("features", [])
    if not raw_features:
        print("[错误] GeoJSON 中无有效 feature")
        sys.exit(1)
    print(f"  -> 读取 {len(raw_features)} 个 feature")

    # 阶段 1：清洗过滤
    orig_geoms, orig_props = clean_and_filter_features(raw_features, clip_bbox)
    if not orig_geoms:
        print("[错误] 过滤后无可用骨干道路，请检查 highway 标签或 bbox 范围！")
        sys.exit(1)

    # 阶段 2：相交打断
    segmented_lines = planarize_lines(orig_geoms)

    # 阶段 3：属性挂载
    final_features = reattach_attributes(segmented_lines, orig_geoms, orig_props)

    # 阶段 4：导出
    print(f"\n[步骤 4/4] 保存平面化路网文件...")
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)

    out_geojson = {
        "type": "FeatureCollection",
        "features": final_features,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out_geojson, f, ensure_ascii=False)

    size_mb = os.path.getsize(args.output) / (1024 * 1024)
    total_elapsed = time.time() - t_start

    print(f"\n{'═' * 60}")
    print(f"预处理完成！")
    print(f"  输入路段: {len(raw_features)}")
    print(f"  过滤后:   {len(orig_geoms)} 条骨干路段")
    print(f"  打断后:   {len(final_features)} 个拓扑子段")
    print(f"  输出文件: {args.output} ({size_mb:.2f} MB)")
    print(f"  总耗时:   {total_elapsed:.1f}s")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()