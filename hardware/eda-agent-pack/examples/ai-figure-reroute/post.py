"""Post-processing of a routed model: (1) re-route ugly connections with everything else fixed,
(2) GND stage: stub+via for every SMD GND pad, EP vias, stitching grid.

usage: python post.py routed-routes.json out.json
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, sys, math, time, collections
import geom as G
from router import Board, Router, export_dump, VIA_R, CLR

b = json.load(open('before.json', encoding='utf-8-sig'))
src = json.load(open(sys.argv[1]))
out = sys.argv[2]
import design as D
des = D.build()
FIXED = {f['cid'] for f in des['fixed']}
bd = Board(b, keep_via_ids=[], moves=src['moves'])
for cid, r in src['routes'].items():
    segs = [(tuple(a), tuple(c), l, w) for a, c, l, w in r['segs']]
    bd.add_route(cid, r['net'], segs, [tuple(v) for v in r['vias']], fixed=cid in FIXED)
R = Router(bd)


def bends(segs):
    n = 0
    for p, q in zip(segs, segs[1:]):
        if p[2] == q[2] and math.dist(p[1], q[0]) < 1e-6 and G.dir_of(p[0], p[1]) != G.dir_of(q[0], q[1]):
            n += 1
    return n


def score(r):
    L = sum(math.dist(a, c) for a, c, l, w in r['segs'])
    return bends(r['segs']) * 30 + len(r['vias']) * 120 + L * 0.2


HOPS = {c: h for c, h in src['hops'].items()}


def spec(x):
    return x if isinstance(x, str) else tuple(x)


def parse(cid):
    h = HOPS[cid]
    return h[0], spec(h[1]), spec(h[2]), h[3]


ESC = {}
for cid, h in HOPS.items():
    s = spec(h[1])
    if isinstance(s, str) and s.startswith('U1.'):
        c, _ = bd.endpoint_center(s)
        if abs(c[1] + 646.7) < 1:
            ESC[s] = 6

t0 = time.time()
if '--no-opt' not in sys.argv:
    for rnd in range(2):
        improved = 0
        order = sorted([c for c in bd.routes if c in HOPS], key=lambda c: -score(bd.routes[c]))
        for cid in order:
            old = bd.routes[cid]
            if bends(old['segs']) <= 1 and not old['vias']:
                continue
            net, s, d, opt = parse(cid)
            w = old['segs'][0][3]
            oldsc = score(old)
            bd.remove_route(cid)
            gv, gp = bd.net_group_of(net, s)
            dv, dp = bd.net_group_of(net, d)
            dsts = [d] + [('via', x, y) for x, y in sorted(dv) if (x, y) not in gv and not (not isinstance(d, str) and abs(d[1] - x) < 0.5 and abs(d[2] - y) < 0.5)]
            kw = {'start_dir': ESC[s], 'escape': 15} if isinstance(s, str) and s in ESC else {}
            best = None
            for bp, vp in ((60, 300), (90, 400), (40, 250)):
                res = R.route(cid, net, s, dsts, w, layers=tuple(opt.get('layers', (1, 2))), margin=600, max_vias=len(old['vias']), max_states=1500000, bend_pen=bp, via_pen=vp, **kw)
                if not res['ok']:
                    continue
                fin = R.finalize(cid, net, res, w, escape=kw.get('escape', 0))
                if fin is None:
                    continue
                cand = {'segs': fin['segs'], 'vias': fin['vias']}
                if best is None or score(cand) < score(best):
                    best = cand
            if best is not None and score(best) < oldsc - 1:
                bd.add_route(cid, net, best['segs'], best['vias'])
                improved += 1
                print(f'improved {cid}: bends {bends(old["segs"])}->{bends(best["segs"])} vias {len(old["vias"])}->{len(best["vias"])}', flush=True)
            else:
                bd.add_route(cid, net, old['segs'], old['vias'])
        print('round', rnd, 'improved', improved, f'{time.time()-t0:.0f}s', flush=True)
        if not improved:
            break

# ---------------------------------------------------------------- GND stage
gpads = []
for pid, shapes in bd.padsall.items():
    s = shapes[0]
    if s['net'] != 'GND':
        continue
    if s['layers'] == {1, 2}:
        continue          # THT: connects to both pours
    gpads.append(pid)
gvias = []          # placed GND vias


def edge_dist(shape, c, d):
    dx, dy = G.DIRS[d]
    n = math.hypot(dx, dy)
    t = 0.0
    while t < 200:
        p = (c[0] + dx / n * t, c[1] + dy / n * t)
        if G.seg_shape(p, p, shape) > 0:
            return t
        t += 0.5
    return t


def try_stub(pid, shape, w=10, extra=45.0, allow_diag=False):
    c = shape['center']
    layer = min(shape['layers'])
    an_p = [shape]
    for group in ((0, 2, 4, 6), (1, 3, 5, 7)):
        if group[0] == 1 and not allow_diag:
            break
        best = None
        used = set()
        for s2 in bd.near(shape['bb'], 2):
            if s2.get('cid') and s2['net'] == 'GND' and s2['k'] == 'cap' and layer in s2['layers']:
                for p0, p1 in ((s2['a'], s2['b']), (s2['b'], s2['a'])):
                    if G.seg_shape(p0, p0, shape) <= 0:
                        dd0 = G.dir_of(p0, p1)
                        if dd0 is not None and dd0 >= 0:
                            used.add(dd0)
        for dd in group:
            if dd in used:
                continue
            dx, dy = G.DIRS[dd]
            n = math.hypot(dx, dy)
            e = edge_dist(shape, c, dd)
            # reuse an existing GND via straight ahead
            for (vx, vy) in gvias:
                if G.dir_of(c, (vx, vy)) == dd and math.dist(c, (vx, vy)) <= e + extra:
                    if bd.seg_ok(c, (vx, vy), layer, w, 'GND', anchors=an_p + [G.finish({'k': 'circ', 'c': (vx, vy), 'r': VIA_R, 'layers': {1, 2}})]):
                        sc = math.dist(c, (vx, vy)) - e - 20
                        if best is None or sc < best[0]:
                            best = (sc, (vx, vy), False)
            r = e + VIA_R + 1.5
            while r <= e + extra:
                v = (round(c[0] + dx / n * r, 2), round(c[1] + dy / n * r, 2))
                if bd.via_ok(v[0], v[1], 'GND') and bd.seg_ok(c, v, layer, w, 'GND', anchors=an_p + [G.finish({'k': 'circ', 'c': v, 'r': VIA_R, 'layers': {1, 2}})]):
                    sc = r - e
                    if best is None or sc < best[0]:
                        best = (sc, v, True)
                    break
                r += 1.25
        if best is not None:
            return best
    return None


added = 0
# U1 exposed-pad squares: tie neighbours together with straight links
sq = [s for s in bd.padsall['U1.49']]
for i, a in enumerate(sq):
    for b2 in sq[:i]:
        ca, cb = a['center'], b2['center']
        if (abs(ca[0] - cb[0]) < 1 and 60 < abs(ca[1] - cb[1]) < 90) or (abs(ca[1] - cb[1]) < 1 and 60 < abs(ca[0] - cb[0]) < 90):
            if bd.seg_ok(ca, cb, 1, 16, 'GND', anchors=[a, b2]):
                bd.add_route(f'GND:U1.49:{i}-{sq.index(b2)}', 'GND', [(ca, cb, 1, 16)], [])
# U1 top row GND pads (36..48 + corners 53/50): one straight bus through the pad centres
top = sorted([p for p in gpads if p.startswith('U1.') and abs(bd.pads[p]['center'][1] + 260.8) < 3], key=lambda p: bd.pads[p]['center'][0])
yb = -260.8
pts = [(bd.pads[p]['center'][0], yb) for p in top]
for a, c in zip(pts, pts[1:]):
    bd.add_route(f'GND:toprow:{a[0]:.1f}', 'GND', [(a, c, 1, 10)], [])
# vias straight below as many top-row pads as fit (all at the same height)
for p in top:
    x = bd.pads[p]['center'][0]
    v = (x, -291.0)
    if bd.via_ok(v[0], v[1], 'GND') and bd.seg_ok((x, yb), v, 1, 10, 'GND', anchors=[bd.pads[p], G.finish({'k': 'circ', 'c': v, 'r': VIA_R, 'layers': {1, 2}})]):
        bd.add_route(f'GND:{p}>via', 'GND', [((x, yb), v, 1, 10)], [v])
        gvias.append(v)
done_pads = set(top)
for pid in sorted(gpads, key=lambda p: (p != 'U1.49', p)):
    if pid in done_pads:
        continue
    shapes = bd.padsall[pid]
    for k, shp in enumerate(shapes):
        big = max(shp['bb'][2] - shp['bb'][0], shp['bb'][3] - shp['bb'][1]) > 45
        if pid == 'U1.49' and abs(shp['center'][0] - 397.7) < 1 and abs(shp['center'][1] + 453.7) < 1:
            continue    # centre square: linked to its neighbours
        st = try_stub(pid, shp, w=16 if big else 10)
        if st is None and not pid.startswith('U1.'):
            st = try_stub(pid, shp, w=10, allow_diag=True)
        if st is None:
            print('GND no stub', pid, k, flush=True)
            continue
        _, v, new = st
        cid = f'GND:{pid}#{k}>via'
        bd.add_route(cid, 'GND', [(shp['center'], v, min(shp['layers']), 16 if big else 10)], [v] if new else [])
        if new:
            gvias.append(v)
        added += 1
print('gnd stubs', added, 'vias', len(gvias), flush=True)# stitching grid
pitch = 150.0
st = 0
y = -1968.5 + 40
while y < -30:
    x = 40.0
    while x < 1150:
        if bd.via_ok(x, y, 'GND', clr=CLR + 4) and all(math.dist((x, y), g) > 60 for g in gvias):
            bd.add_route(f'GND:stitch{st}', 'GND', [], [(x, y)])
            gvias.append((x, y)); st += 1
        x += pitch
    y += pitch
print('stitch vias', st)
export_dump(bd, out)
json.dump({'routes': bd.routes, 'moves': src['moves']}, open(out.replace('.json', '-routes.json'), 'w'), indent=0, default=list)
