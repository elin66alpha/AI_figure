import json, sys, math
b = json.load(open(sys.argv[1], encoding='utf-8-sig'))
for net in sys.argv[2:]:
    tot = 0
    print('==', net)
    for l in b['copper']['lines']:
        if l['net'] == net:
            L = math.hypot(l['endX'] - l['startX'], l['endY'] - l['startY']); tot += L
            print(f"  L{l['layer']} w{l['lineWidth']:<5} ({l['startX']:.1f},{l['startY']:.1f})->({l['endX']:.1f},{l['endY']:.1f}) len {L:.1f}")
    for a in b['copper']['arcs']:
        if a['net'] == net:
            print('  ARC', a)
    for v in b['copper']['vias']:
        if v['net'] == net:
            print(f"  VIA ({v['x']:.1f},{v['y']:.1f})")
    print('  total', round(tot, 1))
