import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / 'pcb-router'))  # pack: shared router modules
import json, time, sys
from router import Board, Router
b = json.load(open('before.json', encoding='utf-8-sig'))
gnd_vias = [v['primitiveId'] for v in b['copper']['vias'] if v['net'] == 'GND']
bd = Board(b, keep_via_ids=gnd_vias)
r = Router(bd)
net, src, dst, w = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
t = time.time()
res = r.route('c1', net, src, [dst], w)
print('astar', res.get('ok'), res.get('expanded'), round(time.time() - t, 2), 's')
if res['ok']:
    fin = r.finalize('c1', net, res, w)
    print(json.dumps(fin, indent=None)[:2000])
