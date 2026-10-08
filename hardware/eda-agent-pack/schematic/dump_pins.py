import json,collections,sys
src=sys.argv[1]
d=json.load(open(src,encoding='utf-8'))['result']
comps=d['components']
nets=collections.defaultdict(list)
out=[]
for c in sorted([c for c in comps if c.get('componentType')=='part'], key=lambda c:(c.get('designator') or '')):
    op=c.get('otherProperty') or {}
    des=c.get('designator')
    out.append(f"\n## {des} | {c.get('manufacturerId')} | {c.get('supplierId')} | {(c.get('footprint') or {}).get('name')} | {op.get('Value','') or op.get('Capacitance','') or op.get('Resistance','')} | pid={c['primitiveId']} @({c['x']},{c['y']}) r{c['rotation']}")
    for p in c.get('pins',[]):
        out.append(f"   {p['pinNumber']}:{p['pinName']} -> {p['net']}{' [NC]' if p.get('noConnected') else ''}")
        nets[p['net'] or ('<NC>' if p.get('noConnected') else '<UNCONNECTED>')].append(f"{des}.{p['pinNumber']}({p['pinName']})")
out.append("\n\n==== NETS")
for n,v in sorted(nets.items()): out.append(f"{n} [{len(v)}]: "+' '.join(v))
open(sys.argv[2],'w',encoding='utf-8').write('\n'.join(out))
