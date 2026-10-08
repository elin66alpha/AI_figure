"""Independent audit of a dump-shaped board JSON (tracks/vias/pads):
angles, junction topology, bends per track chain, exact clearance, edge, connectivity.

usage: python audit.py state.json [--board x0,y0,x1,y1]
  board rect defaults to the dump outline bbox minus half the outline stroke;
  clearance thresholds come from the dump's live rules (dump['rules']).
"""
import json, sys, math, collections
import geom as G

b = json.load(open(sys.argv[1], encoding='utf-8-sig'))
skip_conn = {'GND'}
_bo = sys.argv[sys.argv.index('--board') + 1] if '--board' in sys.argv else None
X0, Y0, X1, Y1 = G.board_rect(b, override=_bo)
TT_CLR, OTHER_CLR, EDGE_CLR = G.dump_rules(b)

pads = []
for c in b['components']:
    for p in c['pads']:
        s = G.pad_shape(p, {1, 2} if p['layer'] == 12 else {p['layer']}, c['designator'])
        pads.append(s)
tracks = []
for i, l in enumerate(b['copper']['lines']):
    s = G.finish({'k': 'cap', 'a': (l['startX'], l['startY']), 'b': (l['endX'], l['endY']), 'r': l['lineWidth'] / 2,
                  'layers': {l['layer']}, 'net': l['net'], 'id': f"t{i}:{l.get('primitiveId','')}", 'w': l['lineWidth'], 'layer': l['layer']})
    tracks.append(s)
vias = []
for i, v in enumerate(b['copper']['vias']):
    vias.append(G.finish({'k': 'circ', 'c': (v['x'], v['y']), 'r': v['diameter'] / 2, 'layers': {1, 2}, 'net': v['net'], 'id': f"v{i}:{v.get('primitiveId','')}", 'via': True}))
allc = pads + tracks + vias

issues = collections.defaultdict(list)

# ---------------- angles
for t in tracks:
    d = G.dir_of(t['a'], t['b'])
    if d == -1:
        issues['non-octilinear'].append((t['net'], t['a'], t['b']))
    if d is None:
        issues['zero-length'].append((t['net'], t['a']))


def at_anchor(p, net, layer):
    for s in pads:
        if s['net'] == net and layer in s['layers'] and G.seg_shape(p, p, s) <= 0.01:
            return s['id']
    for v in vias:
        if v['net'] == net and math.dist(v['c'], p) <= v['r']:
            return v['id']
    return None


# endpoint graph
ends = collections.defaultdict(list)
for t in tracks:
    for e, p in ((0, t['a']), (1, t['b'])):
        ends[(t['net'], t['layer'], round(p[0], 3), round(p[1], 3))].append((t, e))
for k, lst in ends.items():
    net, layer, x, y = k
    p = (x, y)
    anc = at_anchor(p, net, layer)
    if len(lst) == 1 and not anc:
        # touching another track body?
        t = lst[0][0]
        body = [s for s in tracks if s is not t and s['net'] == net and s['layer'] == layer and G.pt_seg(p, s['a'], s['b']) < 0.01]
        if body:
            issues['T-junction(end-on-body)'].append((net, layer, p))
        else:
            issues['dangling-end'].append((net, layer, p))
        continue
    if len(lst) >= 3 and not anc:
        issues['branch-off-anchor'].append((net, layer, p, len(lst)))
    if len(lst) == 2 and not anc:
        (t1, e1), (t2, e2) = lst
        d1 = G.dir_of(t1['b'] if e1 == 0 else t1['a'], p)   # incoming direction of t1 into p
        d2 = G.dir_of(p, t2['b'] if e2 == 0 else t2['a'])   # outgoing direction of t2
        if d1 is not None and d2 is not None and d1 >= 0 and d2 >= 0:
            tt = G.turn(d1, d2)
            if tt >= 2:
                issues['corner>=90'].append((net, layer, p, tt * 45))
    if len(lst) == 2 and anc and not anc.startswith('v'):
        pass
# interior crossings / overlaps of same-net tracks (other than at shared endpoints)
for i, t in enumerate(tracks):
    for s in tracks[:i]:
        if s['net'] != t['net'] or s['layer'] != t['layer']:
            continue
        shared = any(math.dist(p, q) < 0.01 for p in (t['a'], t['b']) for q in (s['a'], s['b']))
        if shared:
            # collinear overlap check
            if G.dir_of(t['a'], t['b']) in (G.dir_of(s['a'], s['b']), (G.dir_of(s['b'], s['a']))) and G.seg_seg(t['a'], t['b'], s['a'], s['b']) < 0.01:
                mid = ((t['a'][0] + t['b'][0]) / 2, (t['a'][1] + t['b'][1]) / 2)
                if G.pt_seg(mid, s['a'], s['b']) < 0.01 or G.pt_seg(((s['a'][0] + s['b'][0]) / 2, (s['a'][1] + s['b'][1]) / 2), t['a'], t['b']) < 0.01:
                    issues['overlap'].append((t['net'], t['a'], t['b']))
            continue
        if G.seg_seg(t['a'], t['b'], s['a'], s['b']) < 0.01:
            issues['same-net-cross/touch'].append((t['net'], t['layer'], t['a'], t['b'], s['a'], s['b']))

# ---------------- clearance (different nets)
B = 50.0
grid = collections.defaultdict(list)
for idx, s in enumerate(allc):
    bb = s['bb']
    for i in range(int((bb[0] - 10) // B), int((bb[2] + 10) // B) + 1):
        for j in range(int((bb[1] - 10) // B), int((bb[3] + 10) // B) + 1):
            grid[(i, j)].append(idx)
checked = set()
minclr = {}
for cell, idxs in grid.items():
    for ai in range(len(idxs)):
        for bi in range(ai):
            i, j = idxs[ai], idxs[bi]
            key = (min(i, j), max(i, j))
            if key in checked:
                continue
            checked.add(key)
            s, t = allc[i], allc[j]
            if s['net'] == t['net'] or not (s['layers'] & t['layers']):
                continue
            if s.get('pad') and t.get('pad') and s['id'].split('.')[0] == t['id'].split('.')[0]:
                continue  # same footprint
            if G.bb_gap(s['bb'], t['bb']) > 8:
                continue
            if s.get('pad') and t.get('pad'):
                continue  # placement, not routing
            dist = G.shape_shape(s, t)
            need = TT_CLR if (s['k'] == 'cap' and t['k'] == 'cap') else OTHER_CLR
            if dist < need - 0.01:
                issues['clearance'].append((s['id'], s['net'], t['id'], t['net'], round(dist, 2)))
            kk = 'track-track' if (s['k'] == 'cap' and t['k'] == 'cap') else 'other'
            minclr[kk] = min(minclr.get(kk, 99), dist)
# edge
for s in tracks + vias:
    bb = s['bb']
    e = min(bb[0] - X0, X1 - bb[2], bb[1] - Y0, Y1 - bb[3])
    if e < EDGE_CLR:
        issues['edge'].append((s['id'], s['net'], round(e, 2)))

# ---------------- connectivity
parent = list(range(len(allc)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for cell, idxs in grid.items():
    for ai in range(len(idxs)):
        for bi in range(ai):
            i, j = idxs[ai], idxs[bi]
            s, t = allc[i], allc[j]
            if s['net'] != t['net'] or not (s['layers'] & t['layers']):
                continue
            if find(i) == find(j):
                continue
            if G.bb_gap(s['bb'], t['bb']) > 0.1:
                continue
            if s.get('via') and t.get('pad') or t.get('via') and s.get('pad'):
                continue  # via-on-pad is not a connection in EasyEDA
            if G.shape_shape(s, t) <= 0.01:
                parent[find(i)] = find(j)
# multi-shape pads (same pad id) are one copper object
byid = collections.defaultdict(list)
for i, s in enumerate(pads):
    byid[s['id']].append(i)
for ids in byid.values():
    for i in ids[1:]:
        parent[find(i)] = find(ids[0])
comp = collections.defaultdict(set)
padcount = collections.Counter()
for i, s in enumerate(allc):
    if s.get('pad') and s['net'] and s['net'] not in skip_conn:
        comp[s['net']].add(find(i))
        padcount[s['net']] += 1
for net, cs in sorted(comp.items()):
    if len(cs) > 1:
        groups = collections.defaultdict(list)
        for i, s in enumerate(pads):
            if s['net'] == net:
                groups[find(i)].append(s['id'])
        issues['open'].append((net, len(cs), [sorted(set(g)) for g in groups.values()]))

# ---------------- bends per chain (between anchors)
summary = {k: len(v) for k, v in issues.items()}
summary['minClearance'] = {k: round(v, 2) for k, v in minclr.items()}
summary['tracks'] = len(tracks)
summary['vias'] = len(vias)
out = {'summary': summary, 'issues': {k: v[:60] for k, v in issues.items()}}
json.dump(out, open(sys.argv[1].replace('.json', '-audit.json'), 'w'), indent=1, default=str)
print(json.dumps(summary, indent=1))
for k, v in issues.items():
    print('==', k, len(v))
    for x in v[:12]:
        print('   ', x)

# ---------------- bends per routed connection (grouped by primitiveId = cid in model exports)
bycid = collections.defaultdict(list)
for l in b['copper']['lines']:
    bycid[l.get('primitiveId', '')].append(l)
rows = []
for cid, ls in bycid.items():
    if ':' not in cid:
        continue
    # order is creation order; count direction changes between consecutive segments on same layer
    bends = 0
    for p, q in zip(ls, ls[1:]):
        if p['layer'] == q['layer'] and abs(p['endX'] - q['startX']) < 1e-6 and abs(p['endY'] - q['startY']) < 1e-6:
            d1 = G.dir_of((p['startX'], p['startY']), (p['endX'], p['endY']))
            d2 = G.dir_of((q['startX'], q['startY']), (q['endX'], q['endY']))
            if d1 != d2:
                bends += 1
    vcount = sum(1 for v in b['copper']['vias'] if v.get('primitiveId', '').startswith(cid + ':'))
    length = sum(math.hypot(l['endX'] - l['startX'], l['endY'] - l['startY']) for l in ls)
    shortseg = min(math.hypot(l['endX'] - l['startX'], l['endY'] - l['startY']) for l in ls)
    rows.append((bends, cid, len(ls), vcount, round(length), round(shortseg, 1)))
rows.sort(reverse=True)
print('== bends per connection (bends, cid, segs, vias, len, shortest seg)')
for r in rows[:25]:
    print('   ', r)
print('   connections with >3 bends:', sum(1 for r in rows if r[0] > 3), 'of', len(rows))
