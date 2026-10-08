"""Octilinear grid A* + exact string-pull router for 2-layer boards (first used on AI_figure 30x50).

All coordinates mil, y-up (same as `pcb dump`). The router never writes to EDA; it
produces route objects that `make_apply.py` turns into typed apply steps.

For a new board call `configure(...)` (or `configure_from_dump(dump)`) BEFORE building
`Board`; the module defaults below are the AI_figure 30x50 mm board's values.

Rules enforced on every produced connection:
  * segments are 0/45/90/135 degrees only
  * consecutive segments turn by exactly 45 degrees (no 90-degree corners, no acute)
  * branches only at pads / vias (a new connection never ends on a track body)
  * exact clearance >= CLR to every other-net copper, edge >= EDGE
"""
import heapq, math, json, collections
import numpy as np
import geom as G

CLR = 6.0          # copper clearance target (rule: 4 track-track, 6 others)
EDGE = 12.5        # copper to board edge (rule 11.8)
VIA_D, VIA_H = 24.0, 12.0
VIA_R = VIA_D / 2
BOARD = (0.0, -1968.5039, 1181.1024, 0.0)
CORNER_R = 60.0    # treat corners as rounded, keep away


def configure(board=None, clr=None, edge=None, corner_r=None, via_d=None, via_h=None):
    """Override the board/rule globals used by Board, Router and finalize."""
    global BOARD, CLR, EDGE, CORNER_R, VIA_D, VIA_H, VIA_R
    if board is not None:
        BOARD = tuple(board)
    if clr is not None:
        CLR = clr
    if edge is not None:
        EDGE = edge
    if corner_r is not None:
        CORNER_R = corner_r
    if via_d is not None:
        VIA_D = via_d
    if via_h is not None:
        VIA_H = via_h
    VIA_R = VIA_D / 2


def configure_from_dump(dump, board=None, margin=0.5, corner_r=None):
    """Board rect from the dump outline (or `board` override), clearance/edge from its live rules
    plus a small safety margin, via size from the rules."""
    tt, other, edge = G.dump_rules(dump)
    r = dump.get('rules') or {}
    configure(board=G.board_rect(dump, override=board), clr=round(other + margin, 2), edge=round(edge + margin, 2),
              corner_r=corner_r, via_d=round(r.get('viaDiameterMil', VIA_D)), via_h=round(r.get('viaDrillMil', VIA_H)))


def layers_of(padlayer):
    return {1, 2} if padlayer == 12 else {padlayer}


def move_component(c, mv):
    """mv: {'pad': n, 'at': (x, y), 'rot': r} (anchor pad lands at 'at') or {'x','y','rot'}.
    Returns (component-with-new-x/y/rotation, transformed pad list)."""
    r1 = mv['rot']
    dr = math.radians(r1 - c['rotation'])
    co, si = math.cos(dr), math.sin(dr)

    def rel(px, py):
        x, y = px - c['x'], py - c['y']
        return x * co - y * si, x * si + y * co
    if 'pad' in mv:
        ap = next(p for p in c['pads'] if p['padNumber'] == mv['pad'])
        ox, oy = rel(ap['x'], ap['y'])
        nx, ny = mv['at'][0] - ox, mv['at'][1] - oy
    else:
        nx, ny = mv['x'], mv['y']
    pads = []
    for p in c['pads']:
        q = dict(p)
        x, y = rel(p['x'], p['y'])
        q['x'], q['y'] = round(nx + x, 4), round(ny + y, 4)
        q['rotation'] = ((p.get('rotation') or 0) + (r1 - c['rotation']))
        if q.get('shape') and q['shape'][0] == 'POLYGON':
            raise ValueError('polygon pad move not supported')
        if 'layer' in mv and q['layer'] != 12:
            q['layer'] = mv['layer']
        pads.append(q)
    c2 = dict(c); c2['x'], c2['y'], c2['rotation'], c2['pads'] = round(nx, 4), round(ny, 4), r1, pads
    if 'layer' in mv:
        c2['layer'] = mv['layer']
    return c2, pads


class Board:
    def __init__(self, dump, keep_via_ids=None, drop_comp=(), moves=None):
        self.dump = dump
        self.shapes = []           # static shapes (pads, kept vias, keepouts)
        self.pads = {}             # 'U1.3' -> shape (first one), for multi-shape pads list in padsall
        self.padsall = collections.defaultdict(list)
        self.moved = {}
        for c in dump['components']:
            if c['designator'] in drop_comp:
                continue
            pads = c['pads']
            if moves and c['designator'] in moves:
                c2, pads = move_component(c, moves[c['designator']])
                self.moved[c['designator']] = c2
            for p in pads:
                s = G.pad_shape(p, layers_of(p['layer']), c['designator'])
                s['static'] = True
                self.shapes.append(s)
                pid = f"{c['designator']}.{p['padNumber']}"
                self.padsall[pid].append(s)
                self.pads.setdefault(pid, s)
        keep_via_ids = set(keep_via_ids or [])
        for v in dump['copper']['vias']:
            if v['primitiveId'] in keep_via_ids:
                self.shapes.append(G.finish({'k': 'circ', 'c': (v['x'], v['y']), 'r': v['diameter'] / 2, 'layers': {1, 2},
                                             'net': v['net'], 'id': 'via:' + v['primitiveId'], 'via': True, 'static': True}))
        for r in dump['copper']['regions']:
            names = r.get('ruleTypeNames') or []
            if 'no-wires' in names:
                bb = r['bbox']
                lay = {1, 2} if r['layer'] == 12 else {r['layer']}
                self.shapes.append(G.finish({'k': 'poly', 'pts': [(bb['minX'], bb['minY']), (bb['maxX'], bb['minY']), (bb['maxX'], bb['maxY']), (bb['minX'], bb['maxY'])],
                                             'r': 0, 'layers': lay, 'net': '__KEEPOUT__', 'id': 'keepout', 'static': True}))
        self.routes = {}           # cid -> dict(net, segs=[(a,b,layer,w)], vias=[(x,y)])
        self.dyn = {}              # cid -> list of shapes
        self._index()

    # ------------------------------------------------------------ spatial index
    def _index(self):
        self.B = 40.0
        self.bins = collections.defaultdict(list)
        self.all = list(self.shapes)
        for s in self.all:
            self._ins(s)

    def _keys(self, bb, m=0):
        B = self.B
        for i in range(int(math.floor((bb[0] - m) / B)), int(math.floor((bb[2] + m) / B)) + 1):
            for j in range(int(math.floor((bb[1] - m) / B)), int(math.floor((bb[3] + m) / B)) + 1):
                yield (i, j)

    def _ins(self, s):
        for k in self._keys(s['bb']):
            self.bins[k].append(s)

    def _rm(self, s):
        for k in self._keys(s['bb']):
            self.bins[k].remove(s)

    def near(self, bb, m):
        seen = set(); out = []
        for k in self._keys(bb, m):
            for s in self.bins.get(k, ()):
                if id(s) not in seen:
                    seen.add(id(s)); out.append(s)
        return out

    # ------------------------------------------------------------ routes
    def add_route(self, cid, net, segs, vias, fixed=False):
        shapes = []
        for a, b, l, w in segs:
            shapes.append(G.finish({'k': 'cap', 'a': a, 'b': b, 'r': w / 2, 'layers': {l}, 'net': net, 'id': f'{cid}:t', 'cid': cid, 'w': w, 'fixed': fixed}))
        for x, y in vias:
            shapes.append(G.finish({'k': 'circ', 'c': (x, y), 'r': VIA_R, 'layers': {1, 2}, 'net': net, 'id': f'{cid}:v', 'cid': cid, 'via': True, 'fixed': fixed}))
        self.routes[cid] = {'net': net, 'segs': segs, 'vias': vias}
        self.dyn[cid] = shapes
        for s in shapes:
            self._ins(s)

    def conflicts(self, segs, vias, net, clr=CLR):
        """cids of non-fixed other-net routes violating clearance with the given copper."""
        out = set()
        for a, b, l, w in segs:
            bb = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            for s in self.near(bb, w / 2 + clr + 2):
                if s.get('cid') and not s.get('fixed') and s['net'] != net and l in s['layers'] and s['cid'] not in out:
                    if G.seg_shape(a, b, s) < w / 2 + clr - 1e-6:
                        out.add(s['cid'])
        for x, y in vias:
            c = G.finish({'k': 'circ', 'c': (x, y), 'r': VIA_R, 'layers': {1, 2}})
            for s in self.near(c['bb'], VIA_R + clr + 30):
                if s.get('cid') and not s.get('fixed') and s['net'] != net and s['cid'] not in out:
                    if G.shape_shape(c, s) < clr - 1e-6 or (s.get('via') and math.dist(s['c'], (x, y)) < VIA_D + 6.0):
                        out.add(s['cid'])
        return out

    def net_group_of(self, net, spec):
        """Return (set of via centres, set of pad ids) electrically connected (by copper contact) to spec."""
        objs = [s for s in self.shapes if s['net'] == net] + [s for shs in self.dyn.values() for s in shs if s['net'] == net]
        n = len(objs)
        par = list(range(n))

        def f(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i in range(n):
            for j in range(i):
                a, b = objs[i], objs[j]
                if not (a['layers'] & b['layers']) or G.bb_gap(a['bb'], b['bb']) > 0.1:
                    continue
                if (a.get('via') and b.get('pad')) or (b.get('via') and a.get('pad')):
                    continue
                if a.get('pad') and b.get('pad') and a['id'] == b['id']:
                    par[f(i)] = f(j); continue
                if G.shape_shape(a, b) <= 0.01:
                    par[f(i)] = f(j)
        for i in range(n):          # multi-shape pads
            for j in range(i):
                if objs[i].get('pad') and objs[j].get('pad') and objs[i]['id'] == objs[j]['id']:
                    par[f(i)] = f(j)
        if isinstance(spec, str):
            seeds = [i for i, s in enumerate(objs) if s.get('pad') and s['id'] == spec]
        else:
            seeds = [i for i, s in enumerate(objs) if s.get('via') and math.dist(s['c'], (spec[1], spec[2])) < 0.5]
        roots = {f(i) for i in seeds}
        vias = {(round(s['c'][0], 3), round(s['c'][1], 3)) for i, s in enumerate(objs) if s.get('via') and f(i) in roots}
        pads = {s['id'] for i, s in enumerate(objs) if s.get('pad') and f(i) in roots}
        return vias, pads

    def remove_route(self, cid):
        for s in self.dyn.pop(cid, []):
            self._rm(s)
        return self.routes.pop(cid, None)

    def endpoint_shapes(self, spec):
        """spec: 'U1.3' pad id | ('via', x, y) | ('pt', x, y, layer)."""
        if isinstance(spec, str):
            return self.padsall[spec]
        if spec[0] == 'via':
            return [G.finish({'k': 'circ', 'c': (spec[1], spec[2]), 'r': VIA_R, 'layers': {1, 2}, 'net': None, 'id': 'ep'})]
        return [G.finish({'k': 'circ', 'c': (spec[1], spec[2]), 'r': 0.6, 'layers': {spec[3]}, 'net': None, 'id': 'ep'})]

    def endpoint_center(self, spec):
        if isinstance(spec, str):
            s = self.pads[spec]
            return s['center'], s['layers']
        if spec[0] == 'via':
            return (spec[1], spec[2]), {1, 2}
        return (spec[1], spec[2]), {spec[3]}

    # ------------------------------------------------------------ exact checks
    def seg_ok(self, a, b, layer, w, net, anchors=(), clr=CLR, ignore_cids=()):
        """exact clearance of a track segment. anchors: shapes the segment may touch."""
        x0, y0, x1, y1 = BOARD
        m = EDGE + w / 2
        for p in (a, b):
            if not (x0 + m - 1e-6 <= p[0] <= x1 - m + 1e-6 and y0 + m - 1e-6 <= p[1] <= y1 - m + 1e-6):
                return False
            # rounded corners
            for cx, cy, sx, sy in ((x0 + CORNER_R, y0 + CORNER_R, -1, -1), (x1 - CORNER_R, y0 + CORNER_R, 1, -1), (x0 + CORNER_R, y1 - CORNER_R, -1, 1), (x1 - CORNER_R, y1 - CORNER_R, 1, 1)):
                if (p[0] - cx) * sx > 0 and (p[1] - cy) * sy > 0 and math.hypot(p[0] - cx, p[1] - cy) > CORNER_R - m:
                    return False
        bb = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        anchor_ids = {id(s) for s in anchors}
        for s in self.near(bb, w / 2 + clr + 2):
            if layer not in s['layers'] or id(s) in anchor_ids or s.get('cid') in ignore_cids:
                continue
            if s['net'] == net:
                # same net: must not overlap (no implicit junctions) unless touching an anchor
                if s.get('cid') is not None and self._touches_anchor(s, anchors):
                    # may share the anchor, but must diverge right after it (no overlap / T)
                    if s['k'] == 'cap':
                        d1, d2 = G.dir_of(a, b), G.dir_of(s['a'], s['b'])
                        if d1 is not None and d2 is not None and d1 >= 0 and d2 >= 0 and d1 % 4 == d2 % 4 and G.seg_seg(a, b, s['a'], s['b']) < w / 2 + s['r']:
                            Lab = math.dist(a, b)
                            ux, uy = (b[0] - a[0]) / Lab, (b[1] - a[1]) / Lab
                            t1 = (s['a'][0] - a[0]) * ux + (s['a'][1] - a[1]) * uy
                            t2 = (s['b'][0] - a[0]) * ux + (s['b'][1] - a[1]) * uy
                            lo, hi = max(0.0, min(t1, t2)), min(Lab, max(t1, t2))
                            if hi - lo > 0.5:
                                inside = True
                                for tt in (lo + 0.01, (lo + hi) / 2, hi - 0.01):
                                    m = (a[0] + ux * tt, a[1] + uy * tt)
                                    if not any(G.seg_shape(m, m, an) <= 0 for an in anchors):
                                        inside = False
                                if not inside:
                                    return False
                    L = math.dist(a, b)
                    n = max(2, int(L / 1.0))
                    for k in range(n + 1):
                        p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                        if any(G.seg_shape(p, p, an) <= w / 2 + s['r'] + 2.0 for an in anchors):
                            continue
                        if G.seg_shape(p, p, s) < w / 2 + 0.5:
                            return False
                    continue
                if s.get('pad') and not s.get('cid'):
                    need = 0.5
                else:
                    need = 0.5
                if G.seg_shape(a, b, s) < w / 2 + need:
                    return False
                continue
            need = clr if s['net'] != '__KEEPOUT__' else 0.5
            if G.seg_shape(a, b, s) < w / 2 + need - 1e-6:
                return False
        return True

    def _touches_anchor(self, s, anchors):
        for an in anchors:
            if G.shape_shape(s, an) <= 0.05:
                return True
        return False

    def via_ok(self, x, y, net, clr=CLR, ignore_cids=()):
        x0, y0, x1, y1 = BOARD
        m = EDGE + VIA_R
        if not (x0 + m <= x <= x1 - m and y0 + m <= y <= y1 - m):
            return False
        c = G.finish({'k': 'circ', 'c': (x, y), 'r': VIA_R, 'layers': {1, 2}})
        for s in self.near(c['bb'], VIA_R + clr + 30):
            if s.get('cid') in ignore_cids:
                continue
            if s.get('via'):
                if math.dist(s['c'], (x, y)) < VIA_D + 6.0 - 1e-6:
                    return False
                if s['net'] != net and G.shape_shape(c, s) < clr:
                    return False
                continue
            if s['net'] == net and s.get('cid') is not None:
                continue  # same-net track may touch the via (it is the junction)
            if s['net'] == net and s.get('pad'):
                if G.shape_shape(c, s) < 1.0:   # no via in pad
                    return False
                continue
            need = clr if s['net'] != '__KEEPOUT__' else 0.5
            if G.shape_shape(c, s) < need - 1e-6:
                return False
        return True


# ================================================================ A*
class Router:
    def __init__(self, board, g=2.5):
        self.bd = board
        self.g = g

    def route(self, cid, net, src, dsts, w, layers=(1, 2), max_vias=2, margin=260, bend_pen=40.0, via_pen=180.0,
              layer_cost=None, K=4, max_states=1500000, clr=CLR, via_ok_extra=None, prefer_dirs=None, verbose=False,
              avoid=None, soft=False, soft_pen=60.0, start_dir=None, escape=0):
        bd = self.bd
        g = self.g
        S, src_layers = bd.endpoint_center(src)
        src_shapes = bd.endpoint_shapes(src)
        dst_shapes = []
        dst_centers = []
        for d in dsts:
            dst_shapes += bd.endpoint_shapes(d)
            dst_centers.append((d, bd.endpoint_center(d)))
        # window
        xs = [S[0]] + [c[0][0] for _, c in dst_centers]
        ys = [S[1]] + [c[0][1] for _, c in dst_centers]
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0, y1 = min(ys) - margin, max(ys) + margin
        bx0, by0, bx1, by1 = BOARD
        x0, x1 = max(x0, bx0), min(x1, bx1)
        y0, y1 = max(y0, by0), min(y1, by1)
        i0 = int(math.floor((x0 - S[0]) / g)); i1 = int(math.ceil((x1 - S[0]) / g))
        j0 = int(math.floor((y0 - S[1]) / g)); j1 = int(math.ceil((y1 - S[1]) / g))
        W, H = i1 - i0 + 1, j1 - j0 + 1
        Xs = S[0] + (np.arange(W) + i0) * g
        Ys = S[1] + (np.arange(H) + j0) * g
        X, Y = np.meshgrid(Xs, Ys)   # shape H x W
        anchor_ids = {id(s) for s in src_shapes + dst_shapes}
        lay_list = [1, 2]
        free = {}
        softm = {1: np.zeros(X.shape, bool), 2: np.zeros(X.shape, bool)}
        vsoft = np.zeros(X.shape, bool)
        rad = w / 2
        for l in lay_list:
            blk = np.zeros(X.shape, bool)
            if l in layers:
                m = EDGE + rad + 0.3
                blk |= (X < bx0 + m) | (X > bx1 - m) | (Y < by0 + m) | (Y > by1 - m)
                for cx, cy in ((bx0 + CORNER_R, by0 + CORNER_R), (bx1 - CORNER_R, by0 + CORNER_R), (bx0 + CORNER_R, by1 - CORNER_R), (bx1 - CORNER_R, by1 - CORNER_R)):
                    q = ((X < cx) if cx < (bx0 + bx1) / 2 else (X > cx)) & ((Y < cy) if cy < (by0 + by1) / 2 else (Y > cy))
                    blk |= q & (np.hypot(X - cx, Y - cy) > CORNER_R - m)
            else:
                blk[:] = True
            free[l] = blk
        vblk = np.zeros(X.shape, bool)
        mv = EDGE + VIA_R + 0.3
        vblk |= (X < bx0 + mv) | (X > bx1 - mv) | (Y < by0 + mv) | (Y > by1 - mv)
        cand = bd.near((x0, y0, x1, y1), 40)
        for s in cand:
            if id(s) in anchor_ids:
                continue
            same = s['net'] == net
            near_anchor = None
            if same:
                touching = [a for a in src_shapes + dst_shapes if s.get('cid') is not None and bd._touches_anchor(s, [a])]
                inflate = rad + 1.0
                if touching:
                    near_anchor = touching   # own track on an anchor: block it except right at the anchor
            elif s['net'] == '__KEEPOUT__':
                inflate = rad + 1.0
            else:
                inflate = rad + clr + 0.8
            bb = s['bb']
            reach = max(inflate or 0, VIA_R + clr + 1, 30 if s.get('via') else 0)
            ia = max(0, int(math.floor((bb[0] - reach - S[0]) / g)) - i0)
            ib = min(W - 1, int(math.ceil((bb[2] + reach - S[0]) / g)) - i0)
            ja = max(0, int(math.floor((bb[1] - reach - S[1]) / g)) - j0)
            jb = min(H - 1, int(math.ceil((bb[3] + reach - S[1]) / g)) - j0)
            if ia > ib or ja > jb:
                continue
            sub = G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], s)
            is_soft = soft and not same and s.get('cid') is not None and not s.get('fixed')
            if is_soft:
                for l in lay_list:
                    if l in s['layers']:
                        softm[l][ja:jb + 1, ia:ib + 1] |= sub < inflate
                vsoft[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + clr + 0.8
                continue
            if inflate is not None:
                blkm = sub < inflate
                if near_anchor:
                    for a in near_anchor:
                        blkm &= G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], a) > rad + s.get('r', 0) + 2.0
                for l in lay_list:
                    if l in s['layers']:
                        free[l][ja:jb + 1, ia:ib + 1] |= blkm
            # via clearance
            if s.get('via'):
                cen = G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], G.finish({'k': 'circ', 'c': s['c'], 'r': 0, 'layers': {1}}))
                vblk[ja:jb + 1, ia:ib + 1] |= cen < VIA_D + 6.0 + 0.3
                if not same:
                    vblk[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + clr + 0.8
            elif same and s.get('cid') is not None:
                pass
            elif same and s.get('pad'):
                vblk[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + 1.0
            elif s['net'] == '__KEEPOUT__':
                vblk[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + 0.5
            else:
                vblk[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + clr + 0.8
        # anchors: no via inside SMD anchor pads either
        for s in src_shapes + dst_shapes:
            if s.get('pad'):
                bb = s['bb']; reach = VIA_R + 2
                ia = max(0, int(math.floor((bb[0] - reach - S[0]) / g)) - i0); ib = min(W - 1, int(math.ceil((bb[2] + reach - S[0]) / g)) - i0)
                ja = max(0, int(math.floor((bb[1] - reach - S[1]) / g)) - j0); jb = min(H - 1, int(math.ceil((bb[3] + reach - S[1]) / g)) - j0)
                if ia <= ib and ja <= jb:
                    sub = G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], s)
                    vblk[ja:jb + 1, ia:ib + 1] |= sub < VIA_R + 1.0
        if avoid is not None:
            for l in lay_list:
                free[l] |= avoid(X, Y, l)
        # goal masks
        goal = {l: np.zeros(X.shape, bool) for l in lay_list}
        for s in dst_shapes:
            bb = s['bb']
            ia = max(0, int(math.floor((bb[0] - S[0]) / g)) - i0); ib = min(W - 1, int(math.ceil((bb[2] - S[0]) / g)) - i0)
            ja = max(0, int(math.floor((bb[1] - S[1]) / g)) - j0); jb = min(H - 1, int(math.ceil((bb[3] - S[1]) / g)) - j0)
            if ia > ib or ja > jb:
                continue
            sub = G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], s)
            if s['k'] == 'circ' and s.get('id') == 'ep':
                inner = np.hypot(X[ja:jb + 1, ia:ib + 1] - s['c'][0], Y[ja:jb + 1, ia:ib + 1] - s['c'][1]) <= 1.8
            else:
                inner = sub <= 0 if s['k'] != 'circ' or s['r'] > 2 else sub <= 1.3
            for l in lay_list:
                if l in s['layers'] and l in layers:
                    goal[l][ja:jb + 1, ia:ib + 1] |= inner
                    free[l][ja:jb + 1, ia:ib + 1] &= ~inner
        # source cells free
        for s in src_shapes:
            bb = s['bb']
            ia = max(0, int(math.floor((bb[0] - S[0]) / g)) - i0); ib = min(W - 1, int(math.ceil((bb[2] - S[0]) / g)) - i0)
            ja = max(0, int(math.floor((bb[1] - S[1]) / g)) - j0); jb = min(H - 1, int(math.ceil((bb[3] - S[1]) / g)) - j0)
            sub = G.grid_dist(X[ja:jb + 1, ia:ib + 1], Y[ja:jb + 1, ia:ib + 1], s)
            for l in lay_list:
                if l in s['layers'] and l in layers:
                    free[l][ja:jb + 1, ia:ib + 1] &= ~(sub <= 0)
        if via_ok_extra is not None:
            vblk |= via_ok_extra(X, Y)
        si, sj = -i0, -j0
        # ---- A*
        FREE = [None, (~free[1]).ravel().tolist(), (~free[2]).ravel().tolist()]
        GOAL = [None, goal[1].ravel().tolist(), goal[2].ravel().tolist()]
        VOK = (~vblk).ravel().tolist()
        SOFT = [None, softm[1].ravel().tolist(), softm[2].ravel().tolist()]
        VSOFT = vsoft.ravel().tolist()
        tgt = [((c[0][0] - S[0]) / g - i0, (c[0][1] - S[1]) / g - j0) for _, c in dst_centers]

        def h(i, j):
            best = 1e18
            for ti, tj in tgt:
                dx, dy = abs(i - ti), abs(j - tj)
                v = (max(dx, dy) - min(dx, dy)) + 1.41421356 * min(dx, dy)
                if v < best:
                    best = v
            return best * g

        D = G.DIRS
        stepc = [g * (1.41421356 if dx and dy else 1.0) for dx, dy in D]
        lc = layer_cost or {1: 1.0, 2: 1.0}
        openh = []
        best = {}
        start_layers = [l for l in src_layers if l in layers]
        cnt = 0
        for l in start_layers:
            st = (si, sj, l, 8, K, 0) if start_dir is None else (si, sj, l, start_dir, K - escape, 0)
            best[st] = 0.0
            heapq.heappush(openh, (h(si, sj), 0.0, cnt, st, None)); cnt += 1
        parent = {}
        found = None
        exp = 0
        while openh:
            f, gc, _, st, par = heapq.heappop(openh)
            if st in parent:
                continue
            parent[st] = par
            i, j, l, d, run, nv = st
            idx = j * W + i
            if GOAL[l][idx] and not (i == si and j == sj and par is None and len(dsts) and False):
                found = st
                break
            exp += 1
            if exp > max_states:
                break
            # moves
            for nd in range(8):
                if d != 8:
                    t = G.turn(d, nd)
                    if t > 1:
                        continue
                    if t == 1 and run < K:
                        continue
                else:
                    t = 0
                dx, dy = D[nd]
                ni, nj = i + dx, j + dy
                if ni < 0 or nj < 0 or ni >= W or nj >= H:
                    continue
                nidx = nj * W + ni
                if not FREE[l][nidx]:
                    continue
                if dx and dy:  # diagonal corner cutting check
                    if not FREE[l][j * W + ni] and not FREE[l][nj * W + i]:
                        continue
                nc = gc + stepc[nd] * lc[l] + (bend_pen if t == 1 else 0)
                if SOFT[l][nidx]:
                    nc += soft_pen
                if prefer_dirs is not None:
                    nc += prefer_dirs(nd, l)
                nrun = 1 if (t == 1 or d == 8) else min(run + 1, K)
                if d == 8:
                    nrun = 1
                ns = (ni, nj, l, nd, nrun, nv)
                if nc < best.get(ns, 1e18):
                    best[ns] = nc
                    heapq.heappush(openh, (nc + 1.1 * h(ni, nj), nc, cnt, ns, st)); cnt += 1
            # via
            if nv < max_vias and VOK[idx] and (run >= K or d == 8) and not (i == si and j == sj):
                ol = 3 - l
                if ol in layers and FREE[ol][idx]:
                    ns = (i, j, ol, 8, K, nv + 1)
                    nc = gc + via_pen + (soft_pen * 4 if VSOFT[idx] else 0)
                    if nc < best.get(ns, 1e18):
                        best[ns] = nc
                        heapq.heappush(openh, (nc + 1.1 * h(i, j), nc, cnt, ns, st)); cnt += 1
        if found is None:
            return {'ok': False, 'reason': 'no path', 'expanded': exp}
        # backtrack
        path = []
        st = found
        while st is not None:
            path.append(st)
            st = parent[st]
        path.reverse()
        pts = [((S[0] + (p[0] + i0) * g), (S[1] + (p[1] + j0) * g), p[2]) for p in path]
        # identify reached dst
        end = pts[-1]
        reached = None
        for dspec, (c, ls) in dst_centers:
            for s in bd.endpoint_shapes(dspec):
                if end[2] in s['layers'] and G.seg_shape((end[0], end[1]), (end[0], end[1]), s) <= 1.3:
                    reached = dspec
                    break
            if reached is not None:
                break
        return {'ok': True, 'raw': pts, 'src': src, 'dst': reached, 'expanded': exp, 'S': S}

    # ------------------------------------------------------------ post processing
    def finalize(self, cid, net, res, w, minseg=10.0, clr=CLR, ignore_cids=(), escape=0):
        """Turn a raw grid path into exact octilinear segments with exact endpoints."""
        bd = self.bd
        self.ignore = set(ignore_cids)
        raw = res['raw']
        src, dst = res['src'], res['dst']
        S = res['S']
        T, _ = bd.endpoint_center(dst)
        src_shapes = bd.endpoint_shapes(src)
        dst_shapes = bd.endpoint_shapes(dst)
        # split into pieces by layer changes (vias at same xy)
        pieces = []
        cur = [raw[0]]
        vias = []
        for p in raw[1:]:
            if p[2] != cur[-1][2]:
                vias.append((p[0], p[1]))
                pieces.append(cur)
                cur = [p]
            else:
                cur.append(p)
        pieces.append(cur)
        segs = []
        for k, pc in enumerate(pieces):
            layer = pc[0][2]
            P = [(q[0], q[1]) for q in pc]
            A = S if k == 0 else vias[k - 1]
            Bp = T if k == len(pieces) - 1 else vias[k]
            a_an = src_shapes if k == 0 else [G.finish({'k': 'circ', 'c': A, 'r': VIA_R, 'layers': {1, 2}})]
            b_an = dst_shapes if k == len(pieces) - 1 else [G.finish({'k': 'circ', 'c': Bp, 'r': VIA_R, 'layers': {1, 2}})]
            P[0] = A
            lock = False
            if k == 0 and escape > 0 and len(P) > escape + 1:
                P = [P[0]] + P[escape:]
                lock = True
            poly = self._pull(P, Bp, layer, w, net, a_an + b_an, minseg, clr, last_is_dst=(k == len(pieces) - 1), lock_first=lock, end_anchors=b_an)
            if poly is None:
                return None
            for a, b in zip(poly, poly[1:]):
                segs.append((a, b, layer, w))
        return {'segs': segs, 'vias': vias}

    def _ok(self, pts, layer, w, net, anchors, clr):
        for a, b in zip(pts, pts[1:]):
            if not self.bd.seg_ok(a, b, layer, w, net, anchors=anchors, clr=clr, ignore_cids=getattr(self, 'ignore', ())):
                return False
        return True

    def _pull(self, P, B, layer, w, net, anchors, minseg, clr, last_is_dst, lock_first=False, end_anchors=()):
        """octilinear string pulling over grid vertices P (P[0] exact start) to exact end B."""
        # compress collinear grid points into vertices
        V = [P[0]]
        for i in range(1, len(P) - 1):
            d1 = G.dir_of(P[i - 1], P[i]); d2 = G.dir_of(P[i], P[i + 1])
            if d1 != d2 or (lock_first and i == 1):
                V.append(P[i])
        V.append(P[-1])
        n = len(V) - 1
        dout = [G.dir_of(V[i], V[i + 1]) for i in range(n)] + [None]
        res = [V[0]]
        din = None
        i = 0
        C = V[0]
        if lock_first and n >= 2:
            res.append(V[1]); din = G.dir_of(V[0], V[1]); i = 1; C = V[1]
        guard = 0
        while True:
            guard += 1
            if guard > 400:
                return None
            done = False
            tries = [(n, B)] + ([(n, V[n])] if math.dist(B, V[n]) > 1e-6 and (any(an.get('pad') for an in end_anchors) or math.dist(B, V[n]) <= 2.0) else []) + [(j, V[j]) for j in range(n - 1, i, -1)]
            for j, Q in tries:
                cands = G.connectors(C, Q) + G.connectors3(C, Q)
                if j == n and Q is B and din is not None:
                    # end on the current heading inside the destination copper instead of jogging to its centre
                    ux, uy = G.DIRS[din]
                    un = math.hypot(ux, uy)
                    t = ((B[0] - C[0]) * ux + (B[1] - C[1]) * uy) / un
                    Pp = (C[0] + ux / un * t, C[1] + uy / un * t)
                    if t > minseg and math.dist(Pp, B) > 1e-6 and any(an.get('pad') and G.seg_shape(Pp, Pp, an) <= (-0.01 if an['k'] == 'poly' else -w / 2) for an in end_anchors):
                        cands = [[C, Pp]] + cands
                best = None
                for cpts in cands:
                    dirs = [G.dir_of(a, b) for a, b in zip(cpts, cpts[1:])]
                    if any(d is None or d == -1 for d in dirs):
                        continue
                    if din is not None and G.turn(din, dirs[0]) > 1:
                        continue
                    if any(G.turn(a, b) > 1 for a, b in zip(dirs, dirs[1:])):
                        continue
                    if j < n and dout[j] is not None and G.turn(dirs[-1], dout[j]) > 1:
                        continue
                    lens = [math.dist(a, b) for a, b in zip(cpts, cpts[1:])]
                    # every segment adjacent to a bend must be long enough to look clean (no micro jogs)
                    bad = False
                    for k, L in enumerate(lens):
                        prevd = din if k == 0 else dirs[k - 1]
                        nextd = dirs[k + 1] if k + 1 < len(dirs) else (dout[j] if j < n else None)
                        if L < minseg and ((prevd is not None and prevd != dirs[k]) or (nextd is not None and nextd != dirs[k]) or (k == 0 and din is None and len(lens) > 1)):
                            # a short last leg that lies completely inside the destination copper is invisible
                            if j == n and k == len(lens) - 1 and any(not an.get('pad') and G.seg_shape(cpts[k], cpts[k], an) <= -0.5 and G.seg_shape(cpts[k + 1], cpts[k + 1], an) <= -0.5 for an in end_anchors):
                                continue
                            bad = True
                    if bad:
                        continue
                    if not self._ok(cpts, layer, w, net, anchors, clr):
                        continue
                    key = (len(cpts) - 2 + (1 if (din is not None and dirs[0] != din) else 0), sum(lens))
                    if best is None or key < best[0]:
                        best = (key, cpts, dirs)
                if best is not None:
                    res += best[1][1:]
                    din = best[2][-1]
                    C = Q
                    i = j
                    done = True
                    if j == n and Q is not B:
                        self.offcenter = True
                    break
            if not done:
                # fall back: tiny fix-up inside target from last grid vertex
                if i == n - 0 or i >= n:
                    break
                return None
            if i == n:
                break
        # merge collinear
        out = [res[0]]
        for p in res[1:]:
            if len(out) >= 2 and G.dir_of(out[-2], out[-1]) == G.dir_of(out[-1], p):
                out[-1] = p
            elif math.dist(out[-1], p) > 1e-6:
                out.append(p)
        return out


def export_dump(bd, path, delete_via_ids=()):
    """Write a dump-shaped JSON of the current board model (for render.py / checks)."""
    import copy
    d = copy.deepcopy({k: v for k, v in bd.dump.items() if k != 'copper'})
    comps = []
    for c in bd.dump['components']:
        comps.append(bd.moved.get(c['designator'], c))
    d['components'] = comps
    lines, vias = [], []
    for cid, r in bd.routes.items():
        for a, b, l, w in r['segs']:
            lines.append({'startX': a[0], 'startY': a[1], 'endX': b[0], 'endY': b[1], 'layer': l, 'lineWidth': w, 'net': r['net'], 'primitiveId': cid})
        for x, y in r['vias']:
            vias.append({'x': x, 'y': y, 'diameter': VIA_D, 'holeDiameter': VIA_H, 'net': r['net'], 'primitiveId': cid + ':via'})
    for s in bd.shapes:
        if s.get('via'):
            pid = s['id'][4:]
            if pid not in delete_via_ids:
                vias.append({'x': s['c'][0], 'y': s['c'][1], 'diameter': VIA_D, 'holeDiameter': VIA_H, 'net': s['net'], 'primitiveId': pid})
    d['copper'] = {'lines': lines, 'arcs': [], 'vias': vias, 'regions': bd.dump['copper']['regions'], 'pours': [], 'poured': []}
    json.dump(d, open(path, 'w', encoding='utf-8'))
