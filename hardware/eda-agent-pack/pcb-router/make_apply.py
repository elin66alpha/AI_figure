"""Build typed `easyeda apply` playbooks from a router model.

  python make_apply.py moves  routes.json --base base.json --project <uuid> --doc <uuid>
      -> moves.apply.json   (component moves only, from routes.json['moves'])
  python make_apply.py copper routes.json --base base.json --project <uuid> --doc <uuid>
      -> copper.apply.json  (delete ALL copper listed in base.json, create routes.json tracks/vias)

base.json is the `pcb dump --include-copper` snapshot the model was built from (component
primitiveIds and the old copper to delete come from it). routes.json has
{'moves': {ref: mv}, 'routes': {cid: {'net', 'segs': [[a, b, layer, width]], 'vias': [[x, y]]}}}.
The copper playbook contains pcb.route.delete steps, so it must be run with `easyeda apply ... --yes`.
"""
import argparse, json
import router
from router import move_component

ap = argparse.ArgumentParser()
ap.add_argument('mode', choices=('moves', 'copper'))
ap.add_argument('routes')
ap.add_argument('--base', required=True)
ap.add_argument('--project', required=True)
ap.add_argument('--doc', required=True)
ap.add_argument('--out')
a = ap.parse_args()

src = json.load(open(a.routes))
b = json.load(open(a.base, encoding='utf-8-sig'))
comps = {c['designator']: c for c in b['components']}
steps = []
if a.mode == 'moves':
    expect = {}
    for d, mv in sorted(src['moves'].items()):
        c2, pads = move_component(comps[d], mv)
        steps.append({'id': 'move-' + d, 'action': 'pcb.component.modify',
                      'payload': {'primitiveId': comps[d]['primitiveId'], 'patch': {'x': round(c2['x'], 3), 'y': round(c2['y'], 3), 'rotation': c2['rotation']}},
                      'assert': {'$.verified': 'true'}})
        expect[d] = {p['padNumber']: (round(p['x'], 2), round(p['y'], 2)) for p in pads}
    json.dump(expect, open('moves-expected.json', 'w'), indent=1)
    steps.append({'id': 'save', 'action': 'pcb.save', 'assert': {'$.saved': 'true'}})
    out = a.out or 'moves.apply.json'
else:
    old = [l['primitiveId'] for l in b['copper']['lines']] + [x['primitiveId'] for x in b['copper']['arcs']] + [v['primitiveId'] for v in b['copper']['vias']]
    for i in range(0, len(old), 100):
        steps.append({'id': f'del-old-{i//100}', 'action': 'pcb.route.delete', 'payload': {'primitiveIds': old[i:i + 100]}, 'assert': {'$.count': 'exists'}})
    n = 0
    for cid, r in src['routes'].items():
        for x, y in r['vias']:
            n += 1
            steps.append({'id': f'v{n}', 'action': 'pcb.via.create', 'payload': {'x': round(x, 3), 'y': round(y, 3), 'net': r['net'], 'holeDiameter': router.VIA_H, 'diameter': router.VIA_D},
                          'assert': {'$.primitiveId': 'exists'}})
        for p, q, l, w in r['segs']:
            n += 1
            steps.append({'id': f't{n}', 'action': 'pcb.line.create',
                          'payload': {'startX': round(p[0], 3), 'startY': round(p[1], 3), 'endX': round(q[0], 3), 'endY': round(q[1], 3), 'lineWidth': w, 'layer': l, 'net': r['net']},
                          'assert': {'$.primitiveId': 'exists'}})
    steps.append({'id': 'save', 'action': 'pcb.save', 'assert': {'$.saved': 'true'}})
    out = a.out or 'copper.apply.json'
json.dump({'version': 1, 'meta': {'name': out, 'project': a.project, 'doc': a.doc}, 'steps': steps}, open(out, 'w'), indent=1)
print(out, len(steps), 'steps')
