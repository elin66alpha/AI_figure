"""Conservative offline copper clearance screen; native DRC remains authoritative."""
import json, math, sys
from pathlib import Path
root=Path(__file__).parent
board=json.loads((root/sys.argv[1]).read_text(encoding='utf-8-sig'))
plan=json.loads((root/sys.argv[2]).read_text(encoding='utf-8-sig'))
def point_seg(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def segdist(a,b,c,d):
    if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0 and max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1])):return 0
    return min(point_seg(a,c,d),point_seg(b,c,d),point_seg(c,a,b),point_seg(d,a,b))
def rectdist(a,b,p):
    angle=-math.radians(p.get('rotation',0));cs,sn=math.cos(angle),math.sin(angle)
    def local(q):x,y=q[0]-p['x'],q[1]-p['y'];return(x*cs-y*sn,x*sn+y*cs)
    a,b=local(a),local(b);w,h=p['width']/2,p['height']/2
    if any(-w<=q[0]<=w and -h<=q[1]<=h for q in [a,b]):return 0
    corners=[(-w,-h),(w,-h),(w,h),(-w,h)]
    return min(segdist(a,b,corners[i-1],corners[i]) for i in range(4))
old=board['copper']['lines'];proposed=[];issues=[];unknown=[]
for r in plan['routes']:
    for i,(a,b) in enumerate(zip(r['points'],r['points'][1:])):
        proposed.append(dict(startX=a[0],startY=a[1],endX=b[0],endY=b[1],net=r['net'],layer=r['layer'],lineWidth=r['width'],primitiveId=f"{r['id']}-{i+1}"))
vias=board['copper']['vias']+[{**v,'diameter':plan['viaDiameterMil']} for v in plan['vias']]
for n,t in enumerate(proposed):
    a,b=(t['startX'],t['startY']),(t['endX'],t['endY']);radius=t['lineWidth']/2
    for c in board['components']:
        for p in c['pads']:
            if p.get('net')==t['net'] or p.get('layer') not in [t['layer'],12]:continue
            if p.get('width') is None or p.get('height') is None:unknown.append(c['designator']+'.'+p['padNumber']);continue
            gap=rectdist(a,b,p)-radius
            if gap<5.97:issues.append([t['primitiveId'],c['designator']+'.'+p['padNumber'],round(gap,3),'pad'])
    for v in vias:
        if v['net']==t['net']:continue
        gap=point_seg((v['x'],v['y']),a,b)-radius-v['diameter']/2
        if gap<5.97:issues.append([t['primitiveId'],v.get('primitiveId',v.get('id')),round(gap,3),'via'])
    for s in old+proposed[:n]:
        if s['layer']!=t['layer'] or s['net']==t['net']:continue
        gap=segdist(a,b,(s['startX'],s['startY']),(s['endX'],s['endY']))-radius-s['lineWidth']/2
        if gap<4.01:issues.append([t['primitiveId'],s['primitiveId'],round(gap,3),'line'])
print(json.dumps({'clearance_candidates':issues,'unsupported_pads':sorted(set(unknown))},ensure_ascii=False,indent=2))
