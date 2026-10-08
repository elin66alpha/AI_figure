"""Plot a board window from a dump: python plotarea.py dump.json x0 x1 y0 y1 out.png"""
import json, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

d = json.load(open(sys.argv[1], encoding='utf-8-sig'))
x0, x1, y0, y1 = map(float, sys.argv[2:6])
fig, ax = plt.subplots(figsize=(14, 14 * (y1 - y0) / (x1 - x0)))
for c in d['components']:
    bb = c['bbox']
    if bb['maxX'] < x0 or bb['minX'] > x1 or bb['maxY'] < y0 or bb['minY'] > y1:
        continue
    col = 'tab:red' if c['layer'] == 1 else 'tab:blue'
    ax.add_patch(Rectangle((bb['minX'], bb['minY']), bb['maxX'] - bb['minX'], bb['maxY'] - bb['minY'], fill=False, ec=col, lw=0.6, ls='--'))
    ax.text((bb['minX'] + bb['maxX']) / 2, bb['maxY'] + 2, c['designator'], color=col, fontsize=8, ha='center', clip_on=True)
    for p in c['pads']:
        w, h = p.get('width', 10), p.get('height', 10)
        pc = 'salmon' if p['layer'] == 1 else ('lightblue' if p['layer'] == 2 else 'gold')
        ax.add_patch(Rectangle((p['x'] - w / 2, p['y'] - h / 2), w, h, color=pc, alpha=0.7))
        ax.text(p['x'], p['y'], f"{p['padNumber']}\n{p['net'][:8]}", fontsize=5, ha='center', va='center', clip_on=True)
for l in d['copper']['lines']:
    col = 'red' if l['layer'] == 1 else 'blue'
    ax.plot([l['startX'], l['endX']], [l['startY'], l['endY']], color=col, lw=max(0.5, l['lineWidth'] / 6), alpha=0.5, solid_capstyle='round')
for v in d['copper']['vias']:
    ax.add_patch(Circle((v['x'], v['y']), 12, color='green', alpha=0.6))
    ax.text(v['x'], v['y'] - 16, v['net'][:7], fontsize=5, ha='center', clip_on=True)
ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect('equal'); ax.grid(True, lw=0.3)
plt.savefig(sys.argv[6], dpi=110, bbox_inches='tight')

