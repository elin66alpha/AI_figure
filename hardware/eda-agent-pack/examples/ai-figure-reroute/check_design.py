"""Validate design.py fixed routes + moves against the board (exact clearance)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, sys, math
import geom as G
from router import Board, CLR, VIA_R
import design as D

b = json.load(open('before.json', encoding='utf-8-sig'))
params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
d = D.build(params)
gnd_vias = [v['primitiveId'] for v in b['copper']['vias'] if v['net'] == 'GND']
bd = Board(b, keep_via_ids=gnd_vias, moves=d['moves'])
for f in d['fixed']:
    bd.add_route(f['cid'], f['net'], f['segs'], f['vias'])
problems = []
conflict_vias = set()


def blockers(a, bpt, layer, w, net, cid):
    out = []
    bb = (min(a[0], bpt[0]), min(a[1], bpt[1]), max(a[0], bpt[0]), max(a[1], bpt[1]))
    for s in bd.near(bb, w / 2 + CLR + 2):
        if layer not in s['layers'] or s['net'] == net or s.get('cid') == cid:
            continue
        need = CLR if s['net'] != '__KEEPOUT__' else 0.5
        dist = G.seg_shape(a, bpt, s)
        if dist < w / 2 + need - 1e-6:
            out.append((s['id'], s['net'], round(dist - w / 2, 2)))
    return out


for f in d['fixed']:
    for a, bpt, l, w in f['segs']:
        bl = blockers(a, bpt, l, w, f['net'], f['cid'])
        for x in bl:
            if x[0].startswith('via:') and x[1] == 'GND':
                conflict_vias.add(x[0][4:])
            else:
                problems.append((f['cid'], 'seg', (a, bpt, l), x))
        dd = G.dir_of(a, bpt)
        if dd == -1:
            problems.append((f['cid'], 'angle', (a, bpt)))
    for v in f['vias']:
        c = G.finish({'k': 'circ', 'c': v, 'r': VIA_R, 'layers': {1, 2}})
        for s in bd.near(c['bb'], VIA_R + CLR + 30):
            if s.get('cid') == f['cid']:
                continue
            if s.get('via') and s['net'] != f['net']:
                if math.dist(s['c'], v) < 30 - 1e-6 or G.shape_shape(c, s) < CLR:
                    if s['id'].startswith('via:') and s['net'] == 'GND':
                        conflict_vias.add(s['id'][4:])
                    else:
                        problems.append((f['cid'], 'via', v, s['id']))
                continue
            if s['net'] == f['net']:
                if s.get('pad') and G.shape_shape(c, s) < 0.5:
                    problems.append((f['cid'], 'via-in-pad', v, s['id']))
                continue
            dist = G.shape_shape(c, s)
            if dist < CLR - 1e-6:
                problems.append((f['cid'], 'via', v, s['id'], s['net'], round(dist, 2)))
# moved pads vs everything static
for des, c2 in bd.moved.items():
    for p in c2['pads']:
        ps = G.pad_shape(p, {1, 2} if p['layer'] == 12 else {p['layer']}, des)
        for s in bd.near(ps['bb'], CLR + 2):
            if s.get('id', '').startswith(des + '.') or not (ps['layers'] & s['layers']):
                continue
            if s['net'] == ps['net'] and s.get('cid'):
                continue
            dist = G.shape_shape(ps, s)
            if dist < CLR - 1e-6:
                if s['id'].startswith('via:') and s['net'] == 'GND':
                    conflict_vias.add(s['id'][4:]); continue
                problems.append(('move', des, p['padNumber'], s['id'], s['net'], round(dist, 2)))
L = D.lengths(d)
print(json.dumps({'problems': problems, 'deleteGndVias': sorted(conflict_vias),
                  'len': {k: round(v, 1) for k, v in L.items() if 'USB' in k},
                  'connSkew': round(L['USB_DP_CONN'] - L['USB_DM_CONN'], 2), 'mcuSkew': round(L['USB_DP'] - L['USB_DM'], 2)}, indent=1, default=str))
from router import export_dump
export_dump(bd, 'design-state.json', delete_via_ids=conflict_vias)
