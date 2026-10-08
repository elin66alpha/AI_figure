"""Exact copper geometry helpers (mil, y-up) shared by router and checker."""
import math
import numpy as np

EPS = 1e-9


# ---------------------------------------------------------------- board facts from a `pcb dump`
def board_rect(dump, stroke=10.0, override=None):
    """Board copper area (x0, y0, x1, y1) in mil.

    `override` = 'x0,y0,x1,y1' string or tuple wins. Otherwise the dump's outline bbox is used,
    shrunk by half the outline stroke (EasyEDA's bbox includes the 10-mil outline line).
    For non-rectangular outlines pass an explicit override."""
    if override:
        v = [float(x) for x in override.split(',')] if isinstance(override, str) else list(override)
        return tuple(v)
    bb = dump['outline']['bbox']
    h = stroke / 2
    return (bb['minX'] + h, bb['minY'] + h, bb['maxX'] - h, bb['maxY'] - h)


def dump_rules(dump):
    """(track-track, other, edge) clearances in mil from the dump's live DRC rules (JLC defaults otherwise)."""
    r = dump.get('rules') or {}
    # edge: never below JLC's 0.3 mm copper-to-outline even if the EDA rule is looser
    return (r.get('clearanceTrackTrackMil', 4.0), r.get('clearanceMil', 6.0), max(r.get('copperToEdgeMil', 11.8), 11.8))


# ---------------------------------------------------------------- shapes
# shape dict: {'k': 'cap'|'circ'|'poly', 'layers': set, 'net': str, 'id': str, ...}
#   cap : a=(x,y), b=(x,y), r
#   circ: c=(x,y), r
#   poly: pts=[(x,y),...] (closed implicitly), r=0
# every shape gets 'bb' = (x0, y0, x1, y1) of its copper


def finish(s):
    if s['k'] == 'cap':
        (ax, ay), (bx, by), r = s['a'], s['b'], s['r']
        s['bb'] = (min(ax, bx) - r, min(ay, by) - r, max(ax, bx) + r, max(ay, by) + r)
    elif s['k'] == 'circ':
        (cx, cy), r = s['c'], s['r']
        s['bb'] = (cx - r, cy - r, cx + r, cy + r)
    else:
        xs = [p[0] for p in s['pts']]; ys = [p[1] for p in s['pts']]
        s['bb'] = (min(xs), min(ys), max(xs), max(ys))
    return s


def pad_shape(p, layers, comp=''):
    """Pad dict from dump -> shape (RECT -> poly, OVAL -> cap, ELLIPSE -> circ/poly, POLYGON -> poly)."""
    sh = p.get('shape') or []
    kind = sh[0] if sh else 'RECT'
    rot = math.radians(p.get('rotation') or 0)
    co, si = math.cos(rot), math.sin(rot)
    x, y = p['x'], p['y']
    base = {'net': p.get('net', ''), 'layers': layers, 'id': f"{comp}.{p['padNumber']}", 'pad': True,
            'center': (x, y), 'padLayer': p.get('layer')}
    if kind == 'POLYGON':
        src = sh[1]
        pts = []
        i = 0
        # source is [x0,y0,'L',x1,y1,...]; absolute coords already
        nums = [v for v in src if not isinstance(v, str)]
        for j in range(0, len(nums) - 1, 2):
            pts.append((nums[j], nums[j + 1]))
        if len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6:
            pts = pts[:-1]
        return finish({**base, 'k': 'poly', 'pts': pts, 'r': 0})
    w, h = (sh[1], sh[2]) if len(sh) >= 3 else (p.get('width'), p.get('height'))
    if kind == 'ELLIPSE' and abs(w - h) < 1e-6:
        return finish({**base, 'k': 'circ', 'c': (x, y), 'r': w / 2})
    if kind == 'OVAL':
        if w >= h:
            hl = (w - h) / 2; r = h / 2; dx, dy = hl * co, hl * si
        else:
            hl = (h - w) / 2; r = w / 2; dx, dy = -hl * si, hl * co
        return finish({**base, 'k': 'cap', 'a': (x - dx, y - dy), 'b': (x + dx, y + dy), 'r': r})
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    pts = [(x + px * co - py * si, y + px * si + py * co) for px, py in pts]
    return finish({**base, 'k': 'poly', 'pts': pts, 'r': 0})


# ---------------------------------------------------------------- scalar distances
def pt_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = dx * dx + dy * dy
    t = 0 if d < EPS else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def seg_seg(a, b, c, d):
    d1, d2, d3, d4 = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def pt_in_poly(p, pts):
    x, y = p; inside = False; n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def seg_shape(a, b, s):
    """Distance from segment a-b (zero width) to shape copper (<=0 means touching/overlap)."""
    if s['k'] == 'cap':
        return seg_seg(a, b, s['a'], s['b']) - s['r']
    if s['k'] == 'circ':
        return pt_seg(s['c'], a, b) - s['r']
    pts = s['pts']
    if pt_in_poly(a, pts) or pt_in_poly(b, pts):
        return -1.0
    n = len(pts)
    return min(seg_seg(a, b, pts[i], pts[(i + 1) % n]) for i in range(n))


def shape_shape(s, t):
    """Distance between two shapes' copper (approximate for poly-poly via edges)."""
    if s['k'] == 'circ':
        return seg_shape(s['c'], s['c'], t) - s['r']
    if s['k'] == 'cap':
        return seg_shape(s['a'], s['b'], t) - s['r']
    if t['k'] != 'poly':
        return shape_shape(t, s)
    if pt_in_poly(s['pts'][0], t['pts']) or pt_in_poly(t['pts'][0], s['pts']):
        return -1.0
    n, m = len(s['pts']), len(t['pts'])
    return min(seg_seg(s['pts'][i], s['pts'][(i + 1) % n], t['pts'][j], t['pts'][(j + 1) % m]) for i in range(n) for j in range(m))


def bb_gap(b1, b2):
    return max(b1[0] - b2[2], b2[0] - b1[2], b1[1] - b2[3], b2[1] - b1[3])


# ---------------------------------------------------------------- vectorised distances (grids)
def grid_pt_seg(X, Y, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = dx * dx + dy * dy
    if d < EPS:
        return np.hypot(X - a[0], Y - a[1])
    t = np.clip(((X - a[0]) * dx + (Y - a[1]) * dy) / d, 0, 1)
    return np.hypot(X - a[0] - t * dx, Y - a[1] - t * dy)


def grid_in_poly(X, Y, pts):
    inside = np.zeros(X.shape, bool)
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % n]
        if y1 == y2:
            continue
        cond = (y1 > Y) != (y2 > Y)
        xi = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (xi > X)
    return inside


def grid_dist(X, Y, s):
    """distance from grid points to shape copper (0 inside)."""
    if s['k'] == 'cap':
        return np.maximum(grid_pt_seg(X, Y, s['a'], s['b']) - s['r'], 0)
    if s['k'] == 'circ':
        return np.maximum(np.hypot(X - s['c'][0], Y - s['c'][1]) - s['r'], 0)
    pts = s['pts']; n = len(pts)
    d = np.full(X.shape, np.inf)
    for i in range(n):
        d = np.minimum(d, grid_pt_seg(X, Y, pts[i], pts[(i + 1) % n]))
    d[grid_in_poly(X, Y, pts)] = 0
    return d


# ---------------------------------------------------------------- octilinear helpers
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def dir_of(a, b, tol=1e-6):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < tol:
        return None
    ang = math.degrees(math.atan2(dy, dx)) % 360
    k = round(ang / 45) % 8
    if abs(((ang - k * 45 + 180) % 360) - 180) > 0.05:
        return -1  # not octilinear
    return k


def turn(d1, d2):
    """absolute direction change in 45-degree units (0..4)."""
    t = abs(d1 - d2) % 8
    return min(t, 8 - t)


def connectors(p, q):
    """octilinear 1- or 2-segment polylines from p to q (lists of points incl. ends)."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    ax, ay = abs(dx), abs(dy)
    if ax < 1e-6 or ay < 1e-6 or abs(ax - ay) < 1e-6:
        return [[p, q]]
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    if ax > ay:
        m1 = (p[0] + sx * (ax - ay), p[1])          # horizontal then diagonal
        m2 = (p[0] + sx * ay, p[1] + sy * ay)       # diagonal then horizontal
    else:
        m1 = (p[0], p[1] + sy * (ay - ax))          # vertical then diagonal
        m2 = (p[0] + sx * ax, p[1] + sy * ax)       # diagonal then vertical
    return [[p, m1, q], [p, m2, q]]


def connectors3(p, q, fracs=(0.25, 0.5, 0.75)):
    """3-segment octilinear Z shapes (ortho-diag-ortho and diag-ortho-diag)."""
    out = []
    dx, dy = q[0] - p[0], q[1] - p[1]
    ax, ay = abs(dx), abs(dy)
    if ax < 1e-6 or ay < 1e-6 or abs(ax - ay) < 1e-6:
        return out
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    if ax > ay:
        orth = ax - ay
        for f in fracs:
            l1 = orth * f
            a = (p[0] + sx * l1, p[1]); b = (a[0] + sx * ay, a[1] + sy * ay)
            out.append([p, a, b, q])
            # diag-ortho-diag: split diagonal
            d1 = ay * f
            a = (p[0] + sx * d1, p[1] + sy * d1); b = (a[0] + sx * orth, a[1])
            out.append([p, a, b, q])
    else:
        orth = ay - ax
        for f in fracs:
            l1 = orth * f
            a = (p[0], p[1] + sy * l1); b = (a[0] + sx * ax, a[1] + sy * ax)
            out.append([p, a, b, q])
            d1 = ax * f
            a = (p[0] + sx * d1, p[1] + sy * d1); b = (a[0], a[1] + sy * orth)
            out.append([p, a, b, q])
    return out
