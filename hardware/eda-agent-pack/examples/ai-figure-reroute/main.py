"""Full re-route: fixed hand design + automatic octilinear routing (rip-up & reroute).

usage: python main.py out.json
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, sys, time, math, collections
import geom as G
from router import Board, Router, export_dump, VIA_R
import design as D

b = json.load(open('before.json', encoding='utf-8-sig'))
des = D.build()
bd = Board(b, keep_via_ids=[], moves=des['moves'])
for f in des['fixed']:
    bd.add_route(f['cid'], f['net'], f['segs'], f['vias'], fixed=True)
R = Router(bd)
FIXED = {f['cid'] for f in des['fixed']}

W = {'SYS': 20, 'VBAT': 20, 'VBUS_CHG': 20, 'VBUS_USB': 12, '$1N181': 24, '3V3_AMP': 16, 'SPK_P': 16, 'SPK_N': 16}
W3 = {('C16.2', 'U3.5'): 20, ('U1.3', 'U3.5'): 20, ('C3.1', 'U1.3'): 16, ('C2.1', 'C3.1'): 16}
V = des['vias']
B, T = {'layers': (2,)}, {'layers': (1,), 'maxv': 0}
via = lambda p: ('via', p[0], p[1])
HOPS = [
    # planned signal lanes first
    ('AMP_DIN', 'U1.21', via(V['U5.4']), T), ('I2S_WS', 'U1.19', via(V['U5.2']), T),
    ('I2S_BCLK', 'U1.18', via(V['U5.3']), T), ('AMP_CTRL', 'U1.16', via(V['AMP_CTRL']), T),
    ('BOOT_GPIO9', via(V['U1.23']), 'TP3.1', B), ('LED_GPIO8', via(V['U1.22']), 'D3.2', {'maxv': 1}),
    ('MIC_CLK', via(V['U1.20']), ('via', 936.4, -150.0), B), ('MIC_DATA', via(V['U1.12']), via(V['MIC_DATA']), B),
    ('CHIP_EN', via(V['U1.8']), 'TP1.1', B),
    ('CHIP_EN', 'U1.8', 'C15.2', {}), ('CHIP_EN', 'R9.2', 'C15.2', {}),
    ('SYS_ADC', 'U1.13', 'C19.2', {}), ('$1N317', 'D3.1', 'R13.2', {}),
    # power
    ('$1N181', 'U2.1', 'L1.1', B),
    ('SYS', 'C7.1', 'L1.2', {}), ('SYS', 'U2.7', 'C7.1', {}), ('SYS', 'C1.1', 'L1.2', B), ('SYS', 'U3.3', 'C1.1', B), ('SYS', 'U3.4', 'U3.3', B),
    ('SYS', 'R14.1', 'U3.4', {}), ('SYS', 'U7.3', 'U2.7', {}), ('SYS', 'U7.1', 'U7.3', B), ('SYS', 'C23.2', 'U7.1', B),
    ('VBUS_CHG', 'C6.1', 'U2.8', B), ('VBUS_CHG', 'R8.2', 'C6.1', {}), ('VBUS_CHG', 'D4.1', 'R8.2', {}),
    ('VBAT', 'C8.2', 'U2.6', B), ('VBAT', 'J2.1', 'C8.2', B),
    ('VBUS_USB', 'J1.A9', 'F1.1', {}),
    ('3V3_AMP', 'C4.2', 'U7.5', B), ('3V3_AMP', 'C5.1', 'C4.2', B), ('3V3_AMP', 'U5.6', 'C5.1', B),
    ('SPK_P', 'U5.8', 'J3.1', B), ('SPK_N', 'U5.5', 'J3.2', B), ('$1N189', 'U2.5', 'R3.1', {}),
    # 3V3 tree
    ('3V3', 'C16.2', 'U3.5', B),
    ('3V3', 'R9.1', 'U3.5', {}), ('3V3', 'R11.1', 'C16.2', {}),
    ('3V3', 'R13.1', 'R12.1', {}), ('3V3', 'C13.2', 'R13.1', {}),
]

# ---------------------------------------------------------------- U1 escape reservations
ESC_LEN = 37.5
ESC = {}
for net, src, dst, opt in HOPS:
    if isinstance(src, str) and src.startswith('U1.') and src not in ESC:
        c, _ = bd.endpoint_center(src)
        if abs(c[1] + 646.7) < 1:
            d = 6
        else:
            continue
        dx, dy = G.DIRS[d]
        e = (c[0] + dx * ESC_LEN, c[1] + dy * ESC_LEN)
        ESC[src] = d
        bd.add_route('esc:' + src, net, [(c, e, 1, 8)], [], fixed=True)


def width(net, src, dst):
    if net == '3V3':
        return W3.get((src, dst), 12)
    return W.get(net, 8)


def name(p):
    return p if isinstance(p, str) else f'via@{p[1]:.1f},{p[2]:.1f}'


def attempt(cid, net, src, dst, w, opt, soft=False):
    gv, gp = bd.net_group_of(net, src)
    dv, dp = bd.net_group_of(net, dst)
    if (isinstance(dst, str) and dst in gp) or (not isinstance(dst, str) and (round(dst[1], 3), round(dst[2], 3)) in gv):
        return 'skip', None
    # targets: the destination plus every via already connected to the destination (never one on our own side)
    dsts = [dst] + [('via', x, y) for x, y in sorted(dv) if (x, y) not in gv
                    and not (not isinstance(dst, str) and abs(dst[1] - x) < 0.5 and abs(dst[2] - y) < 0.5)]
    kw = {}
    if isinstance(src, str) and src in ESC:
        kw = {'start_dir': ESC[src], 'escape': int(round(ESC_LEN / R.g))}
    layers = opt.get('layers', (1, 2))
    mv0 = opt.get('maxv', 2)
    tries = ((260, min(mv0, 2), 600000), (600, mv0 if 'maxv' in opt else 3, 1500000)) if not soft else ((600, mv0 if 'maxv' in opt else 3, 2500000),)
    for margin, mv, ms in tries:
        res = R.route(cid, net, src, dsts, w, layers=layers, margin=margin, max_vias=mv, max_states=ms, soft=soft,
                      layer_cost=opt.get('lc'), **kw)
        if res['ok']:
            ign = {c for c in bd.routes if not c.startswith('esc:') and c not in FIXED} if soft else ()
            fin = R.finalize(cid, net, res, w, ignore_cids=ign, escape=kw.get('escape', 0))
            if fin is not None:
                return res, fin
    return None, None


HOP = {}
queue = collections.deque()
for h in HOPS:
    cid = f'{h[0]}:{name(h[1])}>{name(h[2])}'
    HOP[cid] = h
    queue.append(cid)
ripcount = collections.Counter()
fails = []
t0 = time.time()
it = 0
while queue and it < 500:
    it += 1
    cid = queue.popleft()
    net, src, dst, opt = HOP[cid]
    w = width(net, src, dst)
    esc = bd.remove_route('esc:' + src) if isinstance(src, str) and src in ESC else None
    res, fin = attempt(cid, net, src, dst, w, opt)
    if res == 'skip':
        print('skip (already connected)', cid); continue
    victims = set()
    if fin is None:
        res, fin = attempt(cid, net, src, dst, w, opt, soft=True)
        if fin is not None:
            victims = bd.conflicts(fin['segs'], fin['vias'], net)
            if any(ripcount[v] >= 4 for v in victims):
                fin = None
    if fin is None:
        if esc:
            bd.add_route('esc:' + src, esc['net'], esc['segs'], esc['vias'], fixed=True)
        fails.append(cid)
        print(f'FAIL {cid}', flush=True)
        continue
    for v in victims:
        bd.remove_route(v)
        ripcount[v] += 1
        queue.append(v)
        vs = HOP[v][1]
        if isinstance(vs, str) and vs in ESC:
            c, _ = bd.endpoint_center(vs)
            dx, dy = G.DIRS[ESC[vs]]
            bd.add_route('esc:' + vs, HOP[v][0], [(c, (c[0] + dx * ESC_LEN, c[1] + dy * ESC_LEN), 1, 8)], [], fixed=True)
    bd.add_route(cid, net, fin['segs'], fin['vias'])
    print(f'ok {cid:40s} segs={len(fin["segs"]):2d} vias={len(fin["vias"])} rip={sorted(victims)} t={time.time()-t0:.0f}s', flush=True)

for c in [c for c in bd.routes if c.startswith('esc:')]:
    bd.remove_route(c)
out = sys.argv[1] if len(sys.argv) > 1 else 'routed.json'
export_dump(bd, out)
json.dump({'fails': fails, 'routes': {c: r for c, r in bd.routes.items()}, 'moves': des['moves'], 'hops': {c: list(h) for c, h in HOP.items()}},
          open(out.replace('.json', '-routes.json'), 'w'), indent=0, default=list)
print('fails', fails)