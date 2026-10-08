import json, collections, sys
b = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'before.json', encoding='utf-8-sig'))
nets = collections.defaultdict(list)
for c in b['components']:
    for p in c['pads']:
        s = p['shape'][0] if p.get('shape') else '?'
        nets[p.get('net', '')].append(f"{c['designator']}.{p['padNumber']}@L{p['layer']}({p['x']:.1f},{p['y']:.1f} {s} {p.get('width',0):.1f}x{p.get('height',0):.1f} r{p.get('rotation',0)} {p['shape'][1:] if s not in ('RECT','OVAL','ELLIPSE') else ''})")
for n, ps in sorted(nets.items()):
    if n == 'GND' and '-g' not in sys.argv:
        print(n, len(ps)); continue
    print(n or '<none>', len(ps))
    for p in ps:
        print('   ', p)
