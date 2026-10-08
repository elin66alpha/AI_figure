"""Independent ground component graph including real filled contours and holes."""
import json,math,sys,runpy,contextlib,io
from pathlib import Path
root=Path(__file__).parent;boardfile=sys.argv[1] if len(sys.argv)>1 else 'ground-repaired.json';dsnfile=sys.argv[2] if len(sys.argv)>2 else 'dsn-corner-verified.json'
sys.argv=['verify',boardfile,dsnfile,'ground-graph-baseline.json']
with contextlib.redirect_stdout(io.StringIO()):g=runpy.run_path(str(root/'verify_corner_connectivity.py'))
b=g['b'];objects=g['objects'];inside=g['inside'];segdist=g['segdist'];pointseg=g['pointseg'];distance=g['distance']
def contour(s):
    pts=[(s[0],s[1])];i=2
    while i<len(s):
        if s[i]=='L':i+=1;continue
        if s[i]=='ARC':
            sweep=s[i+1];a=pts[-1];c=(s[i+2],s[i+3]);i+=4;theta=math.radians(sweep);dx,dy=c[0]-a[0],c[1]-a[1];f=1/(2*math.tan(theta/2));center=((a[0]+c[0])/2-dy*f,(a[1]+c[1])/2+dx*f);ang=math.atan2(a[1]-center[1],a[0]-center[0]);r=math.dist(a,center);n=max(2,math.ceil(abs(sweep)));pts.extend((center[0]+r*math.cos(ang+theta*k/n),center[1]+r*math.sin(ang+theta*k/n)) for k in range(1,n+1));pts[-1]=c
        elif isinstance(s[i],(int,float)):pts.append((s[i],s[i+1]));i+=2
        else:raise ValueError(s[i])
    return pts
def polyedges(pts):return list(zip(pts,pts[1:]+pts[:1]))
nodes=[o for o in objects if o['net']=='GND'];lookup={id(o):i for i,o in enumerate(nodes)};parent=list(range(len(nodes)))
def find(i):
    while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
    return i
def join(a,c):parent[find(a)]=find(c)
for i,o in enumerate(objects):
    if id(o) not in lookup:continue
    for j in g['adj'][i]:
        if id(objects[j]) in lookup:join(lookup[id(o)],lookup[id(objects[j])])
extra=[]
for p in b['copper']['poured']:
    for f in p['fills']:
        rings=[contour(s) for s in f['source']];rad=f['lineWidth']/2
        # A single materialized primitive may contain several DISCONNECTED outer
        # contours. Its primitive ID is not an electrical connectivity witness.
        if f['fill']:
            areas=[abs(sum(a[0]*c[1]-c[0]*a[1] for a,c in polyedges(r)))/2 for r in rings]
            parents=[]
            for n,r in enumerate(rings):
                containers=[k for k,outer in enumerate(rings) if areas[k]>areas[n]+.001 and inside(r[0],outer)]
                parents.append(min(containers,key=lambda k:areas[k]) if containers else None)
            def depth(n):return 0 if parents[n] is None else 1+depth(parents[n])
            parts=[(n,[r]+[rings[k] for k in range(len(rings)) if parents[k]==n]) for n,r in enumerate(rings) if depth(n)%2==0]
        else:parts=[(0,rings)]
        for n,part in parts:
            pts=[pt for ring in part for pt in ring]
            extra.append({'kind':'complex' if f['fill'] else 'stroke','rings':part,'points':pts if f['fill'] else part[0],'radius':rad,'layer':p['layer'],'net':'GND','id':f['id']+f':contour-{n}','parentFill':f['id'],'box':(min(pt[0] for pt in pts)-rad,min(pt[1] for pt in pts)-rad,max(pt[0] for pt in pts)+rad,max(pt[1] for pt in pts)+rad)})
def contact(a,c):
    if c['kind']=='complex':a,c=c,a
    if a['kind']!='complex':return distance(a,c)<=a['radius']+c['radius']+.06
    rings=a['rings'];cp=c['points']
    if c['kind']=='complex':return False # distinct materialized solid islands are not merged by a guessed contour
    if any(sum(inside(pt,r) for r in rings)%2 for pt in cp):return True
    edges=[e for ring in rings for e in polyedges(ring)];threshold=a['radius']+c['radius']+.06
    if c['kind']=='circle':return any(pointseg(cp[0],x,y)<=threshold for x,y in edges)
    ce=polyedges(cp) if c['kind']=='polygon' else list(zip(cp,cp[1:]));return any(segdist(x,y,d,e)<=threshold for x,y in edges for d,e in ce)
for a in extra:
    i=len(nodes);nodes.append(a);parent.append(i);ba=a['box']
    for j,c in enumerate(nodes[:i]):
        if a['layer']!=c['layer']:continue
        bc=c['box']
        if ba[0]>bc[2]+.06 or bc[0]>ba[2]+.06 or ba[1]>bc[3]+.06 or bc[1]>ba[3]+.06:continue
        if contact(a,c):join(i,j)
for v in b['copper']['vias']:
    if v['net']=='GND':
        vi=[i for i,o in enumerate(nodes) if o['id']==v['primitiveId']]
        if len(vi)==2:join(*vi)
groups={}
for i,o in enumerate(nodes):groups.setdefault(find(i),[]).append(o)
rootid=max(groups,key=lambda k:len(groups[k]));main=groups[rootid];groundedViaIds={o['id'] for o in main if o.get('via')}
report={'board':boardfile,'scope':'sampled native pour arcs, holes excluded; physical contact graph; native DRC still authoritative','components':[{'root':key,'count':len(group),'groundVias':[o['id'] for o in group if o.get('via')],'pads':[o['id'] for o in group if o['id'] in g['padnodes']],'filledIslands':[o['id'] for o in group if o['kind']=='complex']} for key,group in sorted(groups.items(),key=lambda v:-len(v[1]))],'mainRoot':rootid,'mainGroundViaIds':sorted(groundedViaIds)}
(root/(Path(boardfile).stem+'-ground-graph.json')).write_text(json.dumps(report,indent=2));print(json.dumps({'components':[(len(z),sum(o['kind']=='complex' for o in z)) for z in sorted(groups.values(),key=len,reverse=True)],'mainVias':len(groundedViaIds)},indent=2))
