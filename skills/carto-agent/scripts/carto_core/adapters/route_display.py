"""Deterministic display geometry in screen pixels (x right, y down).

Migrated verbatim from the old framework's adapters/route_display.py (v1):
route right-offsets (bevelled miter joins) and arc-length-spaced direction
arrows. Pure math, no imports beyond the standard library.

Layering: mechanical-derivation-layer helper consumed inside the render backend
and style compiler; governed by the frozen scene digests, deliberately NOT a
ToolGateway capability (see adapters/image_tools.py for the capability boundary).
"""
from __future__ import annotations

import math


def display_points(graphic: dict, scale: float = 1, origin: tuple = (0, 0)) -> list[tuple]:
    points = []
    for p in graphic['points']:
        xy = (p['x'] * scale - origin[0], p['y'] * scale - origin[1])
        if not points or math.dist(points[-1], xy) > 1e-6:
            points.append(xy)
    distance = graphic.get('right_offset_px', 0)
    if len(points) == 1:
        return points * 2
    if not distance or len(points) < 2:
        return points
    normals = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        normals.append((-dy / length, dx / length))
    shifted = []
    for i, p in enumerate(points):
        before, after = normals[max(0, i - 1)], normals[min(i, len(normals) - 1)]
        denom = 1 + before[0] * after[0] + before[1] * after[1]
        # Bevel sharp turns and reversals instead of producing long miter spikes.
        if denom < .5:
            shifted.extend((p[0] + n[0] * distance, p[1] + n[1] * distance) for n in (before, after))
        else:
            shifted.append((p[0] + (before[0] + after[0]) * distance / denom,
                            p[1] + (before[1] + after[1]) * distance / denom))
    return shifted


def direction_arrows(points: list, config: dict):
    """Yield chevrons at arc-length intervals, with a midpoint on short routes."""
    segments = [(a, b, math.dist(a, b)) for a, b in zip(points, points[1:]) if math.dist(a, b) > 1e-6]
    total = sum(s[2] for s in segments)
    size, spacing = config['size_px'], config['spacing_px']
    if total < size * 3:
        return
    count = max(1, int(total / spacing))
    targets = [(i + .5) * total / count for i in range(count)]
    index, start = 0, 0
    for target in targets:
        while start + segments[index][2] < target:
            start += segments[index][2]
            index += 1
        a, b, length = segments[index]
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        t = (target - start) / length
        x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        yield [(x - ux * size / 2 - uy * size / 3, y - uy * size / 2 + ux * size / 3),
               (x + ux * size / 2, y + uy * size / 2),
               (x - ux * size / 2 + uy * size / 3, y - uy * size / 2 - ux * size / 3)]
