"""Offline render of a `pcb dump --include-copper` snapshot (mil, y-up) to PNG per layer.

usage: python render.py board.json out_prefix [x0 y0 x1 y1]   (window optional)
"""
import json, math, sys
import geom as G
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Circle

b = json.load(open(sys.argv[1], encoding='utf-8-sig'))
prefix = sys.argv[2]
win = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else None
LCOL = {1: '#d02020', 2: '#2040e0'}


def pad_poly(p):
    shape = p.get('shape') or []
    w, h = p.get('width') or 0, p.get('height') or 0
    if shape and shape[0] in ('RECT', 'OVAL') and len(shape) >= 3:
        w, h = shape[1], shape[2]
    if shape and shape[0] == 'ELLIPSE':
        w, h = shape[1], shape[2]
    a = math.radians(p.get('rotation') or 0)
    co, si = math.cos(a), math.sin(a)
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return [(p['x'] + x * co - y * si, p['y'] + x * si + y * co) for x, y in pts]


def arc_points(a, n=24):
    (x0, y0), (x1, y1) = (a['startX'], a['startY']), (a['endX'], a['endY'])
    th = math.radians(a['arcAngle'])
    dx, dy = x1 - x0, y1 - y0
    f = 1 / (2 * math.tan(th / 2))
    cx, cy = (x0 + x1) / 2 - dy * f, (y0 + y1) / 2 + dx * f
    r = math.hypot(x0 - cx, y0 - cy)
    s = math.atan2(y0 - cy, x0 - cx)
    return [(cx + r * math.cos(s + th * i / n), cy + r * math.sin(s + th * i / n)) for i in range(n + 1)]


def seg(ax, a, c, w, col):
    dx, dy = c[0] - a[0], c[1] - a[1]
    L = math.hypot(dx, dy) or 1e-9
    nx, ny = -dy / L * w / 2, dx / L * w / 2
    ax.add_patch(Polygon([(a[0] + nx, a[1] + ny), (c[0] + nx, c[1] + ny), (c[0] - nx, c[1] - ny), (a[0] - nx, a[1] - ny)], closed=True, fc=col, ec='none', alpha=.8))
    ax.add_patch(Circle(a, w / 2, fc=col, ec='none', alpha=.8))
    ax.add_patch(Circle(c, w / 2, fc=col, ec='none', alpha=.8))


for layer in (1, 2):
    fig, ax = plt.subplots(figsize=(12, 20) if not win else (14, 14 * (win[3] - win[1]) / max(1, win[2] - win[0])))
    ax.set_facecolor('#202020')
    bx0, by0, bx1, by1 = G.board_rect(b)
    ax.add_patch(plt.Rectangle((bx0, by0), bx1 - bx0, by1 - by0, fill=False, ec='yellow', lw=1))
    for po in b['copper'].get('poured', []):
        if po.get('layer') != layer:
            continue
    for c in b['components']:
        for p in c['pads']:
            if p.get('layer') not in (layer, 12):
                continue
            ax.add_patch(Polygon(pad_poly(p), closed=True, fc='#c08000' if p.get('layer') == 12 else ('#a03030' if layer == 1 else '#3050a0'), ec='none', alpha=.9))
            if win:
                ax.text(p['x'], p['y'], f"{p['padNumber']}\n{p.get('net','')}", fontsize=5, ha='center', va='center', color='w', clip_on=True)
        if c['layer'] == layer or any(p.get('layer') == 12 for p in c['pads']):
            bb = c['bbox']
            ax.add_patch(plt.Rectangle((bb['minX'], bb['minY']), bb['maxX'] - bb['minX'], bb['maxY'] - bb['minY'], fill=False, ec='#60c060', lw=.5))
            ax.text(bb['minX'], bb['maxY'], c['designator'], fontsize=7, color='#80ff80', clip_on=True)
    for l in b['copper']['lines']:
        if l['layer'] != layer:
            continue
        seg(ax, (l['startX'], l['startY']), (l['endX'], l['endY']), l['lineWidth'], LCOL[layer])
    for a in b['copper']['arcs']:
        if a['layer'] != layer:
            continue
        pts = arc_points(a)
        for p0, p1 in zip(pts, pts[1:]):
            seg(ax, p0, p1, a['lineWidth'], '#ff60ff')
    for v in b['copper']['vias']:
        ax.add_patch(Circle((v['x'], v['y']), v['diameter'] / 2, fc='#909090', ec='none'))
        ax.add_patch(Circle((v['x'], v['y']), v['holeDiameter'] / 2, fc='black', ec='none'))
    ax.set_aspect('equal')
    if win:
        ax.set_xlim(win[0], win[2]); ax.set_ylim(win[1], win[3])
    else:
        ax.set_xlim(bx0 - 20, bx1 + 20); ax.set_ylim(by0 - 20, by1 + 20)
    ax.set_title(f'layer {layer}')
    fig.savefig(f'{prefix}-L{layer}.png', dpi=110 if not win else 130, bbox_inches='tight')
    plt.close(fig)
print('ok')
