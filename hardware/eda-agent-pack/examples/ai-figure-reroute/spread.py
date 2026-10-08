"""Spread the dense bottom-side passives (user request 2026-10-08, round 2):
 * SYS_ADC divider: C19 left 22 mil, R15 turned horizontal under R14 (C19.1 + R15.2 share one GND via)
 * R11/R12 pull-ups: R12 right to x 590, both up 12 mil; 3V3 from R13 comes down x 614
 * R18 down to y -540 on the left 3V3 rail (R10 stays)
Works incrementally on the fresh EDA dump (keeps user silk edits). Writes spread.json (model, audit input)
and spread.apply.json (delete affected copper, move parts, create new copper, save)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, math
import geom as G
from router import move_component

PROJ, DOC = '8c5d0d86032348a0a6c85102fe97607e', 'f39f5125c569691f'
d = json.load(open('now.json', encoding='utf-8-sig'))
C = {c['designator']: c for c in d['components']}


def pad(ref, n, comps=C):
    p = next(p for p in comps[ref]['pads'] if p['padNumber'] == n)
    return (p['x'], p['y'])


# ---- old anchors (exact)
r14_2, r14_1 = pad('R14', '2'), pad('R14', '1')
c19_1, c19_2 = pad('C19', '1'), pad('C19', '2')
r11_2, r12_2 = pad('R11', '2'), pad('R12', '2')
r18_2 = pad('R18', '2')
vias = {(round(v['x'], 1), round(v['y'], 1)): v for v in d['copper']['vias']}
VLED, VBOOT, VKEY = (523.7, -596.7), (555.2, -596.7), (115.0, -453.7)
for k in (VLED, VBOOT, VKEY):
    assert k in vias, k
VLED, VBOOT, VKEY = [(vias[k]['x'], vias[k]['y']) for k in (VLED, VBOOT, VKEY)]
RAILX = r18_2[0]

# ---- moves
Y_R15 = -830.0
moves = {
    'C19': {'pad': '1', 'at': (c19_1[0] - 22.0, c19_1[1]), 'rot': C['C19']['rotation']},
    'R15': {'pad': '1', 'at': (r14_2[0], Y_R15), 'rot': 180},
    'R11': {'pad': '2', 'at': (r11_2[0], r11_2[1] + 12.0), 'rot': C['R11']['rotation']},
    'R12': {'pad': '2', 'at': (590.0, r11_2[1] + 12.0), 'rot': C['R12']['rotation']},
    'R18': {'pad': '2', 'at': (RAILX, -540.0), 'rot': C['R18']['rotation']},
}
N = {}
for ref, mv in moves.items():
    c2, _ = move_component(C[ref], mv)
    N[ref] = c2
NC = dict(C); NC.update(N)
P = lambda ref, n: pad(ref, n, NC)

# ---- copper to remove: (net, a, b) old segments (matched by geometry) and old vias
def S(net, *pts):
    return [(net, pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


old = []
old += S('LED_GPIO8', VLED, (VLED[0], -700.0))
old += S('BOOT_GPIO9', VBOOT, (VBOOT[0], -700.0))
old += S('3V3', (523.7, -734.0), (555.2, -734.0))
old += S('REC_KEY', VKEY, (85.3, -453.7))
old += S('3V3', (RAILX, -453.7), (RAILX, -422.2))
old += S('3V3', (RAILX, -453.7), (RAILX, -640.0))
old += S('SYS_ADC', (429.0, -775.6), (463.3, -775.6))
old += S('SYS_ADC', (463.3, -775.6), (463.3, -810.0))
old += S('SYS_ADC', (240.2, -684.2), (342.7, -684.2), (425.2, -766.7))
old += S('3V3', (523.7, -734.1), (523.7, -891.6))
old += S('3V3', (701.5, -489.4), (579.6, -611.3), (579.6, -716.3), (564.6, -731.3))
old += S('GND', (396.0, -775.6), (372.5, -775.6))
old += S('GND', (463.3, -844.1), (438.8, -844.1))
old_vias = [(372.5, -775.6), (438.8, -844.1)]

del_lines = []
for net, a, b in old:
    hit = [l for l in d['copper']['lines'] if l['net'] == net and
           G.pt_seg((l['startX'], l['startY']), a, b) < 0.3 and G.pt_seg((l['endX'], l['endY']), a, b) < 0.3 and
           math.dist((l['startX'], l['startY']), (l['endX'], l['endY'])) > 0.5 * math.dist(a, b)]
    assert len(hit) == 1, (net, a, b, len(hit))
    del_lines.append(hit[0])
del_vias = []
for v in old_vias:
    hit = [x for x in d['copper']['vias'] if math.dist((x['x'], x['y']), v) < 0.3]
    assert len(hit) == 1, v
    del_vias.append(hit[0])

# ---- new copper (net, layer, width, polyline)
r11_1n, r11_2n, r12_1n, r12_2n = P('R11', '1'), P('R11', '2'), P('R12', '1'), P('R12', '2')
c19_1n, c19_2n = P('C19', '1'), P('C19', '2')
r15_1n, r15_2n = P('R15', '1'), P('R15', '2')
r18_1n, r18_2n = P('R18', '1'), P('R18', '2')
yA = r14_2[1]


def X(p):
    # exact coordinates of an existing track endpoint / via near p
    cand = [(l['startX'], l['startY']) for l in d['copper']['lines']] + [(l['endX'], l['endY']) for l in d['copper']['lines']] + [(v['x'], v['y']) for v in d['copper']['vias']]
    q = min(cand, key=lambda c: math.dist(c, p))
    assert math.dist(q, p) < 0.2, p
    return q


# snap link endpoints onto common axes (dump pad coords carry 0.1-mil rounding)
r12_1n = (r12_1n[0], r11_1n[1]); r12_2n = (r12_1n[0], r12_2n[1])
r15_2n = (r15_2n[0], Y_R15); r18_1n = (r18_1n[0], r18_2n[1])
y3 = r12_1n[1]
new = [
    ('LED_GPIO8', 2, 8, [VLED, r11_2n]),
    ('BOOT_GPIO9', 2, 8, [VBOOT, (VBOOT[0], -618.0), (r12_2n[0], -618.0 - (r12_2n[0] - VBOOT[0])), r12_2n]),
    ('3V3', 2, 10, [r11_1n, r12_1n]),
    ('3V3', 2, 12, [r11_1n, X((523.7, -891.6))]),
    ('3V3', 2, 12, [X((701.5, -489.4)), (614.0, X((701.5, -489.4))[1] - (X((701.5, -489.4))[0] - 614.0)), (614.0, y3 + 14.0), (600.0, y3), r12_1n]),
    ('REC_KEY', 2, 8, [VKEY, (VKEY[0], r18_1n[1] + 14.7), (VKEY[0] - 14.7, r18_1n[1]), r18_1n]),
    ('3V3', 2, 12, [X((RAILX, -422.2)), r18_2n]),
    ('3V3', 2, 12, [r18_2n, X((RAILX, -640.0))]),
    ('SYS_ADC', 2, 8, [X((240.2, -684.2)), (c19_2n[0] - 55.8, X((240.2, -684.2))[1]), (c19_2n[0], -740.0), (c19_2n[0], yA)]),
    ('SYS_ADC', 2, 8, [(c19_2n[0], yA), r14_2]),
    ('SYS_ADC', 2, 8, [r14_2, r15_1n]),
    ('GND', 2, 10, [c19_1n, (c19_1n[0], Y_R15)]),
    ('GND', 2, 10, [r15_2n, (c19_1n[0], Y_R15)]),
]
new_vias = [('GND', (c19_1n[0], Y_R15))]
for net, l, w, pts in new:
    for a, b in zip(pts, pts[1:]):
        assert G.dir_of(a, b) not in (-1, None), (net, a, b)

# ---- model dump for audit
m = json.loads(json.dumps(d))
m['components'] = [N.get(c['designator'], c) for c in d['components']]
dl = {l['primitiveId'] for l in del_lines}; dv = {v['primitiveId'] for v in del_vias}
m['copper']['lines'] = [l for l in m['copper']['lines'] if l['primitiveId'] not in dl]
m['copper']['vias'] = [v for v in m['copper']['vias'] if v['primitiveId'] not in dv]
for i, (net, l, w, pts) in enumerate(new):
    for j, (a, b) in enumerate(zip(pts, pts[1:])):
        m['copper']['lines'].append({'startX': a[0], 'startY': a[1], 'endX': b[0], 'endY': b[1], 'layer': l, 'net': net, 'lineWidth': w, 'primitiveId': f'new{i}:{net}#{j}'})
for net, (x, y) in new_vias:
    m['copper']['vias'].append({'x': x, 'y': y, 'net': net, 'diameter': 24, 'holeDiameter': 12, 'primitiveId': f'newvia:{net}'})
json.dump(m, open('spread.json', 'w'), indent=0)

# ---- placement spacing report (pad-to-pad between different bottom parts)
def ext(p):
    w, h = p['shape'][1], p['shape'][2]
    if round((p.get('rotation') or 0) / 90) % 2:
        w, h = h, w
    return p['x'] - w / 2, p['y'] - h / 2, p['x'] + w / 2, p['y'] + h / 2


bottom = [c for c in m['components'] if c['layer'] == 2]
for ref in moves:
    c = next(x for x in bottom if x['designator'] == ref)
    best = (1e9, None)
    for o in bottom:
        if o is c:
            continue
        for p in c['pads']:
            for q in o['pads']:
                if q['layer'] == 1:
                    continue
                if not q.get('shape') or len(q['shape']) < 3 or q['shape'][0] != 'RECT':
                    continue
                g = G.bb_gap(ext(p), ext(q))
                if g < best[0]:
                    best = (g, o['designator'])
    print(f'{ref}: nearest other-part pad gap {best[0]:.1f} mil ({best[1]})')

# ---- apply playbook
steps = [{'id': 'del', 'action': 'pcb.route.delete', 'payload': {'primitiveIds': [l['primitiveId'] for l in del_lines] + [v['primitiveId'] for v in del_vias]}, 'assert': {'$.count': 'exists'}}]
for ref, c2 in N.items():
    steps.append({'id': 'move-' + ref, 'action': 'pcb.component.modify',
                  'payload': {'primitiveId': C[ref]['primitiveId'], 'patch': {'x': round(c2['x'], 3), 'y': round(c2['y'], 3), 'rotation': c2['rotation']}},
                  'assert': {'$.verified': 'true'}})
n = 0
for net, (x, y) in new_vias:
    n += 1
    steps.append({'id': f'v{n}', 'action': 'pcb.via.create', 'payload': {'x': round(x, 3), 'y': round(y, 3), 'net': net, 'holeDiameter': 12, 'diameter': 24}, 'assert': {'$.primitiveId': 'exists'}})
for net, l, w, pts in new:
    for a, b in zip(pts, pts[1:]):
        n += 1
        steps.append({'id': f't{n}', 'action': 'pcb.line.create', 'payload': {'startX': round(a[0], 3), 'startY': round(a[1], 3), 'endX': round(b[0], 3), 'endY': round(b[1], 3), 'lineWidth': w, 'layer': l, 'net': net}, 'assert': {'$.primitiveId': 'exists'}})
steps.append({'id': 'save', 'action': 'pcb.save', 'assert': {'$.saved': 'true'}})
json.dump({'version': 1, 'meta': {'name': 'spread', 'project': PROJ, 'doc': DOC}, 'steps': steps}, open('spread.apply.json', 'w'), indent=1)
print('delete', len(del_lines), 'lines', len(del_vias), 'vias; steps', len(steps))
for ref, c2 in N.items():
    print(ref, 'pads', [(p['padNumber'], p['net'], round(p['x'], 2), round(p['y'], 2)) for p in c2['pads']])
