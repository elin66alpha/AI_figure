"""Read-only angle audit including endpoint and interior T/cross junctions."""
import json,math,sys
from pathlib import Path
root=Path(__file__).parent
b=json.loads((root/sys.argv[1]).read_text(encoding='utf-8-sig'))
lines=b['copper']['lines'];bad=[]
def distance(p,a,c):
    dx,dy=c[0]-a[0],c[1]-a[1];d=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d)) if d else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def cross(a,c,p):return(c[0]-a[0])*(p[1]-a[1])-(c[1]-a[1])*(p[0]-a[0])
for i,t in enumerate(lines):
    a,c=(t['startX'],t['startY']),(t['endX'],t['endY']);v=(c[0]-a[0],c[1]-a[1]);length=math.hypot(*v)
    for s in lines[:i]:
        if t['net']!=s['net'] or t['layer']!=s['layer']:continue
        d,e=(s['startX'],s['startY']),(s['endX'],s['endY']);w=(e[0]-d[0],e[1]-d[1]);sl=math.hypot(*w)
        if not length or not sl or abs((v[0]*w[0]+v[1]*w[1])/(length*sl))>.001:continue
        near=min(distance(a,d,e),distance(c,d,e),distance(d,a,c),distance(e,a,c))<.001
        intersects=cross(a,c,d)*cross(a,c,e)<0 and cross(d,e,a)*cross(d,e,c)<0
        if near or intersects:bad.append({'net':t['net'],'layer':t['layer'],'ids':[t['primitiveId'],s['primitiveId']],'kind':'endpoint/T' if near else 'crossing'})
endpoints=[];arc_joints=[]
for t in lines:
    a,c=(t['startX'],t['startY']),(t['endX'],t['endY']);length=math.dist(a,c)
    if not length:continue
    endpoints.extend([(t,a,((c[0]-a[0])/length,(c[1]-a[1])/length),'line'),(t,c,((a[0]-c[0])/length,(a[1]-c[1])/length),'line')])
for t in b['copper'].get('arcs',[]):
    a,c=(t['startX'],t['startY']),(t['endX'],t['endY']);theta=math.radians(t['arcAngle']);dx,dy=c[0]-a[0],c[1]-a[1]
    if abs(theta)<1e-8:continue
    factor=1/(2*math.tan(theta/2));center=((a[0]+c[0])/2-dy*factor,(a[1]+c[1])/2+dx*factor)
    for p,direction in [(a,1),(c,-1)]:
        rx,ry=p[0]-center[0],p[1]-center[1];length=math.hypot(rx,ry);sign=1 if theta>0 else -1
        endpoints.append((t,p,(-ry/length*sign*direction,rx/length*sign*direction),'arc'))
for i,(t,p,v,kind) in enumerate(endpoints):
    for s,q,w,skind in endpoints[:i]:
        if kind==skind=='line' or t['primitiveId']==s['primitiveId'] or t['net']!=s['net'] or t['layer']!=s['layer'] or math.dist(p,q)>.02:continue
        angle=math.degrees(math.acos(max(-1,min(1,v[0]*w[0]+v[1]*w[1]))))
        if abs(angle-90)<3 or angle<87:arc_joints.append({'net':t['net'],'layer':t['layer'],'point':p,'angleDegrees':round(angle,3),'ids':[t['primitiveId'],s['primitiveId']]})
report={'source':sys.argv[1],'tracks':len(lines),'arcs':len(b['copper'].get('arcs',[])),'rightAngleCenterlineJunctions':bad,'rightAngleCount':len(bad),'arcEndpointRightOrAcuteJunctions':arc_joints,'scope':'listed centerline endpoint/interior straight junctions plus signed-sweep arc endpoint tangency; full copper edge geometry and arc body intersections remain native DRC/visual scope'}
out=root/(Path(sys.argv[1]).stem+'-angle-audit.json');out.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
