"""Incremental DRC fix after the first write:
 * J1 footprint NPTH holes become obstacles; VBAT J2.1>C8.2 rerouted around them
 * R2 turned around (R2.2 on the AMP_CTRL column, R2.1 east -> straight to the U5 EP GND via)
 * U5 EP tied straight down to the existing U5.7 GND via
Writes fix1.apply.json, fix1-routes.json, fix1.json (model export)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, math
import geom as G
from router import Board, Router, VIA_R, CLR, move_component, export_dump
import design as D

b = json.load(open('before.json', encoding='utf-8-sig'))
fresh = json.load(open('after1.json', encoding='utf-8-sig'))
src = json.load(open('post16-routes.json'))
des = D.build()
FIXED = {f['cid'] for f in des['fixed']}
desf = {f['cid']: f for f in des['fixed']}
bd = Board(b, keep_via_ids=[], moves=des['moves'])
routes = dict(src['routes'])
routes['amp-ctrl-b'] = {'net': 'AMP_CTRL', 'segs': desf['amp-ctrl-b']['segs'], 'vias': desf['amp-ctrl-b']['vias']}
routes['r2-gnd'] = {'net': 'GND', 'segs': desf['r2-gnd']['segs'], 'vias': []}
for cid, r in routes.items():
    bd.add_route(cid, r['net'], [(tuple(a), tuple(c), l, w) for a, c, l, w in r['segs']], [tuple(v) for v in r['vias']], fixed=cid in FIXED)
HOLE_CLR = 11.811
for (hx, hy, hr) in ((738.19, -1338.585, 11.811), (442.91, -1338.585, 15.748)):
    s = G.finish({'k': 'circ', 'c': (hx, hy), 'r': hr + HOLE_CLR - CLR + 0.3, 'layers': {1, 2}, 'net': '__HOLE__', 'id': 'npth', 'static': True})
    bd.shapes.append(s); bd._ins(s)
R = Router(bd)
add = {'amp-ctrl-b': bd.routes['amp-ctrl-b'], 'r2-gnd': bd.routes['r2-gnd']}
cid = 'VBAT:J2.1>C8.2'
old_vbat = bd.remove_route(cid)['segs']
res = R.route(cid, 'VBAT', 'J2.1', ['C8.2'], 20, layers=(2,), margin=600, max_vias=0, max_states=2500000)
fin = R.finalize(cid, 'VBAT', res, 20)
bd.add_route(cid, 'VBAT', fin['segs'], fin['vias'])
add[cid] = bd.routes[cid]
a, c = (1011.4, -940.0), (1011.4, -987.9)
print('EP link ok', bd.seg_ok(a, c, 2, 16, 'GND', anchors=[bd.pads['U5.9'], G.finish({'k': 'circ', 'c': c, 'r': VIA_R, 'layers': {1, 2}})]))
bd.add_route('GND:U5.9-U5.7via', 'GND', [(a, c, 2, 16)], [])
add['GND:U5.9-U5.7via'] = bd.routes['GND:U5.9-U5.7via']
for k in ('amp-ctrl-b', 'r2-gnd'):
    for s0 in bd.dyn[k]:
        if s0['k'] == 'cap':
            print(k, 'seg ok', bd.seg_ok(s0['a'], s0['b'], 2, s0['w'], s0['net'], anchors=[bd.pads['R2.1'], bd.pads['R2.2'], bd.pads['U5.1']] + [x for x in bd.dyn['GND:U5.9#0>via'] if x.get('via')] + [x for x in bd.dyn['amp-ctrl-b'] if x.get('via')], ignore_cids=(k,)))

# fresh tracks to delete: old VBAT route + AMP_CTRL column at x=888
dels = []
for l in fresh['copper']['lines']:
    p, q = (l['startX'], l['startY']), (l['endX'], l['endY'])
    if l['net'] == 'VBAT' and any(G.pt_seg(p, s[0], s[1]) < 0.15 and G.pt_seg(q, s[0], s[1]) < 0.15 for s in old_vbat):
        dels.append(l['primitiveId'])
    if l['net'] == 'AMP_CTRL' and abs(p[0] - 888) < 0.2 and abs(q[0] - 888) < 0.2:
        dels.append(l['primitiveId'])
print('delete', len(dels))
comps = {x['designator']: x for x in b['components']}
c2, _ = move_component(comps['R2'], des['moves']['R2'])
steps = [{'id': 'move-R2', 'action': 'pcb.component.modify', 'payload': {'primitiveId': comps['R2']['primitiveId'], 'patch': {'x': round(c2['x'], 3), 'y': round(c2['y'], 3), 'rotation': c2['rotation']}}, 'assert': {'$.verified': 'true'}},
         {'id': 'del', 'action': 'pcb.route.delete', 'payload': {'primitiveIds': dels}, 'assert': {'$.count': 'exists'}}]
n = 0
for k, r in add.items():
    segs = r['segs']
    if k == 'amp-ctrl-b':
        segs = [s for s in segs if abs(s[0][0] - 888) < 0.2 and abs(s[1][0] - 888) < 0.2]
    for a, c, l, w in segs:
        n += 1
        steps.append({'id': f'ft{n}', 'action': 'pcb.line.create', 'payload': {'startX': round(a[0], 3), 'startY': round(a[1], 3), 'endX': round(c[0], 3), 'endY': round(c[1], 3), 'lineWidth': w, 'layer': l, 'net': r['net']}, 'assert': {'$.primitiveId': 'exists'}})
steps.append({'id': 'save', 'action': 'pcb.save', 'assert': {'$.saved': 'true'}})
json.dump({'version': 1, 'meta': {'name': 'fix1', 'project': '8c5d0d86032348a0a6c85102fe97607e', 'doc': 'f39f5125c569691f'}, 'steps': steps}, open('fix1.apply.json', 'w'), indent=1)
json.dump({'routes': bd.routes, 'moves': des['moves'], 'hops': src.get('hops', {})}, open('fix1-routes.json', 'w'), indent=0, default=list)
export_dump(bd, 'fix1.json')
print('steps', len(steps), [s['id'] for s in steps])
