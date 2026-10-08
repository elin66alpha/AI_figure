import json,sys,collections
t=open(sys.argv[1],encoding='utf-8').read(); d=json.loads(t[t.find('{'):])['result']
targets=sys.argv[2].split(',')
segs=collections.defaultdict(list)
for w in d['wires']: segs[w['primitiveId']].append(((w['x0'],w['y0']),(w['x1'],w['y1'])))
def onseg(p,s):
  (a,b),(c,e)=s; x,y=p
  return min(a,c)-.01<=x<=max(a,c)+.01 and min(b,e)-.01<=y<=max(b,e)+.01 and abs((c-a)*(y-b)-(e-b)*(x-a))<.01
markers=[c for c in d['components'] if c.get('componentType') in ('netflag','netport')]
parts={c['designator']:c for c in d['components'] if c.get('designator')}
for des in targets:
  c=parts[des]; print(f"## {des} pid={c['primitiveId']} @({c['x']},{c['y']}) r{c['rotation']} bbox={c.get('bbox')}")
  for p in c['pins']:
    # flood wires from pin
    pts=[(p['x'],p['y'])]; seen=set(); 
    while pts:
      q=pts.pop()
      for pid,ss in segs.items():
        if pid in seen: continue
        if any(onseg(q,s) for s in ss):
          seen.add(pid); 
          for s in ss: pts+= [s[0],s[1]]
    ends=set()
    for pid in seen:
      for s in segs[pid]: ends|={s[0],s[1]}
    mk=[m for m in markers if (m['x'],m['y']) in ends or (m['x'],m['y'])==(p['x'],p['y'])]
    other=[f"{o['designator']}.{op['pinNumber']}" for o in parts.values() if o is not c for op in o.get('pins',[]) if (op['x'],op['y']) in ends]
    print(f"   pin {p['pinNumber']} ({p['x']},{p['y']}) net={p['net']!r} NC={p.get('noConnected')} wires={sorted(seen)} markers={[(m.get('net') or m.get('name'),m['primitiveId'],m['x'],m['y'],m['rotation']) for m in mk]} otherPins={other}")
