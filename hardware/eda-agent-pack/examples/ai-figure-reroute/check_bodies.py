"""Body/courtyard sanity for moved parts: moved part's pad extent (+margin) vs other parts' bbox on the same side."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json
from router import move_component
import design as D
b = json.load(open('before.json', encoding='utf-8-sig'))
des = D.build()
comps = {c['designator']: c for c in b['components']}
M = 8.0


def pad_ext(c):
    xs, ys = [], []
    for p in c['pads']:
        w, h = p.get('width', 0), p.get('height', 0)
        if c['designator'] in des['moves'] and abs(((p.get('rotation') or 0) - (comps[c['designator']]['pads'][0].get('rotation') or 0)) % 180) == 90:
            w, h = h, w
        xs += [p['x'] - w / 2, p['x'] + w / 2]; ys += [p['y'] - h / 2, p['y'] + h / 2]
    return min(xs), min(ys), max(xs), max(ys)


moved = {}
for d, mv in des['moves'].items():
    c2, _ = move_component(comps[d], mv)
    moved[d] = c2
for d, c2 in moved.items():
    e = pad_ext(c2)
    e = (e[0] - M, e[1] - M, e[2] + M, e[3] + M)
    for o, oc in comps.items():
        if o == d:
            continue
        oc = moved.get(o, oc)
        if o in moved:
            ob = pad_ext(oc)
        else:
            bb = oc['bbox']; ob = (bb['minX'], bb['minY'], bb['maxX'], bb['maxY'])
        same_side = oc['layer'] == c2['layer'] or any(p['layer'] == 12 for p in oc['pads'])
        if not same_side:
            continue
        if e[0] < ob[2] and ob[0] < e[2] and e[1] < ob[3] and ob[1] < e[3]:
            print(f'{d} (layer {c2["layer"]}) extent {tuple(round(v,1) for v in e)} overlaps {o} {tuple(round(v,1) for v in ob)}')
