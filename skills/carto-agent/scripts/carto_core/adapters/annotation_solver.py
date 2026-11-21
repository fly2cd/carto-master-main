"""Bounded local annotation layout: candidate/greedy/annealing placement.

Migrated from the old framework's adapters/annotation_solver.py (v1), which
itself migrated the phase2_annotation approach. No OCR imports, global RNG,
logging or import-time filesystem side effects. Symbols, route strokes, panels,
fixed cards and map bounds are hard limits. Determinism comes from the
request-supplied seed; the solver runs at compile time (scenario candidate
compiler) and its result is re-verified by ``check_layout`` without
re-optimizing.

Production call sites invoke this only through the ToolGateway
``annotation-layout`` capability (adapters/image_tools.py); the handler runs
solve_layout + check_layout so only verified results become evidence.
"""
from __future__ import annotations

import math
import random

from ..errors import ProtocolError

CAPABILITY = "annotation-layout"
ALGORITHM = "greedy-sa-v2"
VERSION = "1.0.0"


def point_segment_distance_sq(x, y, a, b):
    dx, dy = b['x'] - a['x'], b['y'] - a['y']
    length = dx * dx + dy * dy
    t = max(0., min(1., ((x - a['x']) * dx + (y - a['y']) * dy) / length)) if length else 0.
    return (x - a['x'] - t * dx) ** 2 + (y - a['y'] - t * dy) ** 2


def segment_box_distance_sq(a, b, box):
    """Exact distance to a rectangle, including segment crossings and zero-length lines."""
    left, top = box['x'], box['y']
    right, bottom = left + box['w'], top + box['h']
    low, high = 0., 1.
    for start, delta, minimum, maximum in ((a['x'], b['x'] - a['x'], left, right),
                                          (a['y'], b['y'] - a['y'], top, bottom)):
        if delta == 0:
            if not minimum <= start <= maximum:
                break
        else:
            t1, t2 = (minimum - start) / delta, (maximum - start) / delta
            low, high = max(low, min(t1, t2)), min(high, max(t1, t2))
            if low > high:
                break
    else:
        return 0.

    def endpoint_distance(p):
        return (p['x'] - min(max(p['x'], left), right)) ** 2 + (p['y'] - min(max(p['y'], top), bottom)) ** 2
    return min(endpoint_distance(a), endpoint_distance(b),
               *(point_segment_distance_sq(x, y, a, b) for x, y in (
                   (left, top), (right, top), (right, bottom), (left, bottom))))


class RouteIndex:
    """Uniform-grid broad phase; test only nearby route segments against each card."""
    cell_size = 128

    def __init__(self, lines, gap, canvas):
        self.segments, self.cells = [], {}
        self.canvas = canvas
        entries = 0
        if sum(len(line['points']) - 1 for line in lines) > 30000:
            raise ProtocolError('ANNOTATION_WORK_LIMIT', 'too many route segments')
        for line in lines:
            radius = line['width_px'] / 2 + gap
            for a, b in zip(line['points'], line['points'][1:]):
                bounds = {'x': min(a['x'], b['x']) - radius, 'y': min(a['y'], b['y']) - radius,
                          'w': abs(a['x'] - b['x']) + 2 * radius, 'h': abs(a['y'] - b['y']) + 2 * radius}
                index = len(self.segments)
                self.segments.append((a, b, radius * radius))
                for cell in self.keys(bounds):
                    entries += 1
                    if entries > 1_000_000:
                        raise ProtocolError('ANNOTATION_WORK_LIMIT', 'route index is too large')
                    self.cells.setdefault(cell, []).append(index)

    def keys(self, box):
        left, top = max(0, box['x']), max(0, box['y'])
        right = min(self.canvas['width'], box['x'] + box['w'])
        bottom = min(self.canvas['height'], box['y'] + box['h'])
        if right < left or bottom < top:
            return
        for col in range(int(left // self.cell_size), int(right // self.cell_size) + 1):
            for row in range(int(top // self.cell_size), int(bottom // self.cell_size) + 1):
                yield col, row

    def collides(self, box):
        nearby = {index for cell in self.keys(box) for index in self.cells.get(cell, ())}
        for index in sorted(nearby):
            a, b, radius_sq = self.segments[index]
            if segment_box_distance_sq(a, b, box) <= radius_sq + 1e-9:
                return True
        return False


def collides(a, b, gap):
    return (a['x'] < b['x'] + b['w'] + gap and a['x'] + a['w'] + gap > b['x']
            and a['y'] < b['y'] + b['h'] + gap and a['y'] + a['h'] + gap > b['y'])


def inside(b, canvas):
    return b['x'] >= 0 and b['y'] >= 0 and b['x'] + b['w'] <= canvas['width'] and b['y'] + b['h'] <= canvas['height']


def validate_geometry(value):
    ids = [i['id'] for i in value['items']]
    if len(ids) != len(set(ids)):
        raise ProtocolError('ANNOTATION_DUPLICATE_ID', 'annotation IDs must be unique')
    for item in value['items']:
        if not 0 <= item['anchor_x'] <= value['canvas']['width'] or not 0 <= item['anchor_y'] <= value['canvas']['height']:
            raise ProtocolError('ANNOTATION_ANCHOR_OUTSIDE_MAP', item['id'])


def candidates(item, canvas, gap):
    w, h = item['w'], item['h']
    if 'fixed' in item:
        positions = [(item['fixed']['x'], item['fixed']['y'])]
    else:
        positions = []
        # Original 8 directions x 3 distances, followed by bounded wider search.
        for alpha in (.08, .4, .9, 1.5, 2.5, 4):
            dx, dy = gap + alpha * w, gap + alpha * h
            positions.extend((item['anchor_x'] + ox, item['anchor_y'] + oy) for ox, oy in (
                (dx, -h / 2), (dx, dy), (-w / 2, dy), (-w - dx, dy),
                (-w - dx, -h / 2), (-w - dx, -h - dy), (-w / 2, -h - dy), (dx, -h - dy)))
        # Search the rest of the map if the anchor neighbourhood is crowded.
        for row in range(5):
            for col in range(5):
                positions.append(((canvas['width'] - w) * col / 4, (canvas['height'] - h) * row / 4))
    boxes, seen = [], set()
    for x, y in positions:
        key = (round(x, 8), round(y, 8))
        box = {'x': x, 'y': y, 'w': w, 'h': h}
        if key not in seen and inside(box, canvas):
            boxes.append(box)
            seen.add(key)
    return boxes


def quality(box, item, value):
    nearest_x = min(max(item['anchor_x'], box['x']), box['x'] + box['w'])
    nearest_y = min(max(item['anchor_y'], box['y']), box['y'] + box['h'])
    dist = math.hypot(nearest_x - item['anchor_x'], nearest_y - item['anchor_y'])
    distance = math.exp(-dist / max(1., math.hypot(box['w'], box['h'])))
    edge = min(box['x'], box['y'], value['canvas']['width'] - box['x'] - box['w'],
               value['canvas']['height'] - box['y'] - box['h'])
    return .9 * distance + .1 * min(1., edge / 20)


def solve_layout(value):
    """Greedy initial placement + simulated annealing; fixed seed, bounded work."""
    validate_geometry(value)
    items = sorted(value['items'], key=lambda i: (-i['w'] * i['h'], i['id']))
    gap = value['gap_px']
    routes = RouteIndex(value['hard_lines'], gap, value['canvas'])
    pools = [[b for b in candidates(i, value['canvas'], gap)
              if not any(collides(b, obstacle, gap) for obstacle in value['hard_boxes'])
              and not routes.collides(b)] for i in items]
    scores = [[quality(b, i, value) for b in pool] for i, pool in zip(items, pools)]
    state = [None] * len(items)

    def fits(index, candidate, current):
        return all(j == index or chosen is None or not collides(candidate, pools[j][chosen], gap)
                   for j, chosen in enumerate(current))
    # Fixed cards reserve their space before movable cards, regardless of size.
    order = sorted(range(len(items)), key=lambda j: ('fixed' not in items[j], j))
    for j in order:
        for k in sorted(range(len(pools[j])), key=lambda k: (-scores[j][k], k)):
            if fits(j, pools[j][k], state):
                state[j] = k
                break

    def score(current):
        return sum(4 + scores[j][k] for j, k in enumerate(current) if k is not None)
    rng = random.Random(value['seed'])
    best, best_score, current_score = state[:], score(state), score(state)
    movable = [j for j, i in enumerate(items) if 'fixed' not in i]
    iterations = 0
    for step in range(value['iterations']):
        if not movable:
            break
        iterations += 1
        proposal = state[:]
        j = rng.choice(movable)
        if not pools[j]:
            continue
        k = rng.randrange(len(pools[j]))
        # A relocation can exchange the semantic candidate of two movable labels.
        if len(movable) > 1 and rng.random() < .35:
            other = rng.choice([n for n in movable if n != j])
            if pools[other]:
                proposal[other] = rng.randrange(len(pools[other]))
        proposal[j] = k
        if any(k is not None and not fits(n, pools[n][k], proposal) for n, k in enumerate(proposal)):
            continue
        new_score = score(proposal)
        temperature = max(.001, .965 ** step)
        if new_score >= current_score or rng.random() < math.exp((new_score - current_score) / temperature):
            state, current_score = proposal, new_score
            if new_score > best_score:
                best, best_score = state[:], new_score
    assignments = []
    for i, item in enumerate(items):
        chosen = best[i]
        if chosen is None:
            assignments.append({'id': item['id'], 'status': 'unplaced'})
            continue
        box = pools[i][chosen]
        assignments.append({'id': item['id'], 'status': 'placed',
                            **box, 'dx': box['x'] - item['anchor_x'], 'dy': box['y'] - item['anchor_y']})
    assignments.sort(key=lambda a: a['id'])
    status = 'unplaceable' if any(a['status'] == 'unplaced' for a in assignments) else 'placed'
    return {'schema_version': 1, 'algorithm': ALGORITHM, 'status': status,
            'assignments': assignments, 'iterations': iterations, 'seed': value['seed']}


def check_layout(value, result):
    """Recheck geometry and route clearance; never run optimization."""
    validate_geometry(value)
    if result['seed'] != value['seed'] or result['iterations'] > value['iterations']:
        raise ProtocolError('ANNOTATION_RESULT_INVALID', 'solver configuration mismatch')
    items = {i['id']: i for i in value['items']}
    assignments = result['assignments']
    if len(assignments) != len(items) or {a['id'] for a in assignments} != set(items):
        raise ProtocolError('ANNOTATION_COVERAGE_INVALID', 'all annotations must have exactly one assignment')
    placed = []
    routes = RouteIndex(value['hard_lines'], value['gap_px'], value['canvas'])
    for assignment in assignments:
        if assignment['status'] == 'unplaced':
            continue
        item = items[assignment['id']]
        if assignment['w'] != item['w'] or assignment['h'] != item['h'] or not inside(assignment, value['canvas']):
            raise ProtocolError('ANNOTATION_BOUNDS_INVALID', assignment['id'])
        if abs(assignment['dx'] - (assignment['x'] - item['anchor_x'])) > 1e-7 or abs(assignment['dy'] - (assignment['y'] - item['anchor_y'])) > 1e-7:
            raise ProtocolError('ANNOTATION_OFFSET_INVALID', assignment['id'])
        if 'fixed' in item and any(assignment[k] != item['fixed'][k] for k in ('x', 'y')):
            raise ProtocolError('ANNOTATION_FIXED_MOVED', assignment['id'])
        if any(collides(assignment, b, value['gap_px']) for b in [*value['hard_boxes'], *placed]):
            raise ProtocolError('ANNOTATION_HARD_CONFLICT', assignment['id'])
        if routes.collides(assignment):
            raise ProtocolError('ANNOTATION_ROUTE_CONFLICT', assignment['id'])
        if assignment['status'] != 'placed':
            raise ProtocolError('ANNOTATION_STATUS_INVALID', assignment['id'])
        placed.append(assignment)
    expected = 'unplaceable' if len(placed) != len(items) else 'placed'
    if result['status'] != expected:
        raise ProtocolError('ANNOTATION_STATUS_INVALID', 'inconsistent summary')
    return expected != 'unplaceable'
