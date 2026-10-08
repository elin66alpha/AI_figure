import json, math, zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
before = json.loads((root / 'before.json').read_text(encoding='utf-8-sig'))
after = json.loads((root / 'after.json').read_text(encoding='utf-8-sig'))
plan = json.loads((root / 'thermal-plan.json').read_text(encoding='utf-8-sig'))
config = json.loads((root / 'config-after.json').read_text(encoding='utf-8-sig'))
lines = after['copper']['lines']
vias = after['copper']['vias']
old_ids = {t['primitiveId'] for t in before['copper']['lines']}
lines = [t for t in lines if t['primitiveId'] not in old_ids]

def endpoints(t):
    return [(t['startX'], t['startY']), (t['endX'], t['endY'])]

def point_segment(p, t):
    a, b = endpoints(t)
    dx, dy = b[0]-a[0], b[1]-a[1]
    fraction = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(p[0]-a[0]-fraction*dx, p[1]-a[1]-fraction*dy)

def inside_rect(p, pad):
    assert pad['shape'][0] == 'RECT'
    assert abs((pad.get('rotation') or 0) % 180) < 1e-6
    return abs(p[0]-pad['x']) <= pad['width']/2+1e-6 and abs(p[1]-pad['y']) <= pad['height']/2+1e-6

mask = config['result']['ruleConfiguration']['Expansion']['Solder Mask Expansion']['solderMaskExpansion']
assert mask['unit'] == 'mm' and mask['isSetDefault']
assert mask['form']['viaToplayerExpansion'] < -1 and mask['form']['viaBottomlayerExpansion'] < -1
native_vias = {}
with zipfile.ZipFile(root / 'with-thermal-vias.epro2') as archive:
    for line in archive.read('AI_figure.epru').decode('utf-8').splitlines():
        if not line.startswith('{') or '||' not in line:
            continue
        header, body = line.split('||', 1)
        header = json.loads(header)
        if header.get('type') == 'VIA':
            native_vias[header['id']] = json.loads(body.rstrip('|'))

results = []
for module in plan['modules']:
    ref = module['ref']
    part = next(c for c in after['components'] if c['designator'] == ref)
    ep = next(p for p in part['pads'] if p['padNumber'] == '9')
    expected = [(module[s+'X'], module[r+'Y']) for s in ['left','right'] for r in ['upper','lower']]
    module_vias = [v for v in vias if any(math.hypot(v['x']-x, v['y']-y) < 1e-5 for x,y in expected)]
    assert len(module_vias) == 4
    module_lines = [t for t in lines if t['net'] == 'GND' and min(point_segment((v['x'],v['y']),t) for v in module_vias) < 220]
    # Measured local track graph. Shared endpoints and exact via contact only;
    # no same-net-name inference and no direct via-to-pad edge.
    graph = {t['primitiveId']: set() for t in module_lines}
    graph['EP'] = set()
    for t in module_lines:
        tid = t['primitiveId']
        if t['layer'] == 2 and any(inside_rect(p,ep) for p in endpoints(t)):
            graph[tid].add('EP'); graph['EP'].add(tid)
        for u in module_lines:
            uid = u['primitiveId']
            if t['layer'] == u['layer'] and tid != uid and any(math.dist(p,q)<1e-5 for p in endpoints(t) for q in endpoints(u)):
                graph[tid].add(uid)
    for v in module_vias:
        vid = v['primitiveId']; graph[vid] = set()
        for t in module_lines:
            if point_segment((v['x'],v['y']),t) <= (v['diameter']+t['lineWidth'])/2+1e-5:
                graph[vid].add(t['primitiveId']); graph[t['primitiveId']].add(vid)
    reachable = {'EP'}; queue = ['EP']
    while queue:
        for node in graph[queue.pop()]-reachable:
            reachable.add(node); queue.append(node)
    for v in module_vias:
        vid = v['primitiveId']; native = native_vias[vid]
        assert native['netName'] == 'GND' and native['viaType'] == 'NORMAL'
        assert abs(native['holeDiameter']-plan['drillMil']) < 1e-5
        assert abs(native['viaDiameter']-plan['diameterMil']) < 1e-5
        assert native['topSolderExpansion'] is None and native['bottomSolderExpansion'] is None and native['ruleName'] == ''
        hole_gap = abs(v['x']-ep['x'])-ep['width']/2-native['holeDiameter']/2
        annulus_gap = abs(v['x']-ep['x'])-ep['width']/2-native['viaDiameter']/2
        assert hole_gap > 0 and annulus_gap > 0
        touching_layers = sorted({t['layer'] for t in module_lines if t['primitiveId'] in graph[vid]})
        assert touching_layers == [1,2] and vid in reachable
        results.append({'owner':ref,'primitiveId':vid,'x':v['x'],'y':v['y'],
                        'holeGapToEPmil':round(hole_gap,4),'annulusGapToEPmil':round(annulus_gap,4),
                        'layersWithActualTrackContact':touching_layers,'localCopperPathToEP':True,
                        'solderMask':'inherits verified closed TOP/BOTTOM mask rule',
                        'nativeHoleDiameterMil':native['holeDiameter'],'nativeViaDiameterMil':native['viaDiameter']})

report = {'status':'pass','scope':'eight local outside-EP normal vias and local explicit copper only',
          'vias':results,'limitations':['No whole-board GND island or thermal-performance proof.',
          'Manufacturing dimensions and mask inheritance checked in native archive; Gerber export not inspected.',
          'Local graph uses axis-aligned measured RECT EP pads, shared track endpoints and actual via-track contact.']}
(root/'local-thermal-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'pass','viasVerified':len(results),'allOutsideEP':True,'allContactBothLayers':True,'allHaveLocalPathToEP':True}))
