"""Replace measured 90-degree centerline bends with parameterized 45-degree chords."""
import json,math,collections,sys
from pathlib import Path
root=Path(__file__).parent
prefix=sys.argv[2] if len(sys.argv)>2 else 'angle-fix'
board=json.loads((root/sys.argv[1]).read_text(encoding='utf-8-sig'))
lines=board['copper']['lines'];nodes=collections.defaultdict(list)
def key(t,x,y):return(t['net'],t['layer'],round(x,5),round(y,5))
for i,t in enumerate(lines):
    nodes[key(t,t['startX'],t['startY'])].append((i,0))
    nodes[key(t,t['endX'],t['endY'])].append((i,1))
def endpoint(t,e):return(t['endX'],t['endY']) if e else(t['startX'],t['startY'])
changes={};diagonals=[];audit=[];branch=[]
for k,attached in nodes.items():
    if len(attached)<2:continue
    p=(k[2],k[3]);vectors=[]
    for i,e in attached:
        q=endpoint(lines[i],1-e);dx,dy=q[0]-p[0],q[1]-p[1];length=math.hypot(dx,dy)
        if length:vectors.append((i,e,dx/length,dy/length,length))
    if len(vectors)!=2:
        if len(vectors)==3:
            pair=next(((a,b) for n,a in enumerate(vectors) for b in vectors[:n] if abs(a[2]*b[2]+a[3]*b[3]+1)<.001),None)
            if pair:
                stem=next(v for v in vectors if v not in pair);trunk=max(pair,key=lambda v:v[4])
                if abs(stem[2]*trunk[2]+stem[3]*trunk[3])<.001:
                    d=min(max(lines[v[0]]['lineWidth'] for v in vectors),min(v[4] for v in vectors)*.35)
                    for pad in [p2 for component in board['components'] for p2 in component['pads']]:
                        if pad.get('net')==k[0] and pad.get('layer') in [k[1],12] and math.hypot(pad['x']-p[0],pad['y']-p[1])<.2:
                            dims=[v for v in [pad.get('width'),pad.get('height')] if isinstance(v,(int,float)) and v>0]
                            if dims:d=min(d,min(dims)*.3)
                    candidates=[(-.5*stem[2]-sign*math.sqrt(3)/2*stem[3],sign*math.sqrt(3)/2*stem[2]-.5*stem[3]) for sign in [1,-1]]
                    for arm in pair:
                        ux,uy=max(candidates,key=lambda v:v[0]*arm[2]+v[1]*arm[3]);q=(round(p[0]+ux*d,5),round(p[1]+uy*d,5));changes[(arm[0],arm[1])]=q
                        diagonals.append({'id':f'branch-{len(diagonals)+1}','net':k[0],'layer':k[1],'width':lines[arm[0]]['lineWidth'],'points':[p,q]})
                    branch.append({'net':k[0],'layer':k[1],'point':p,'degree':3,'oldId':lines[stem[0]]['primitiveId'],'junctionAnglesDegrees':[120,120,120],'trimMil':d})
        continue
    a,b=vectors
    if abs(a[2]*b[2]+a[3]*b[3])>.001:continue
    # Do not shorten either adjacent segment more than 40%; handles consecutive bends.
    distance=min(max(lines[a[0]]['lineWidth'],lines[b[0]]['lineWidth']),a[4]*.4,b[4]*.4)
    for component in board['components']:
        for pad in component['pads']:
            if pad.get('net')==k[0] and pad.get('layer') in [k[1],12] and math.hypot(pad['x']-p[0],pad['y']-p[1])<.2:
                shape=pad.get('shape',[])
                dims=shape[1:3] if shape and shape[0]=='RECT' else [pad.get('width'),pad.get('height')]
                dims=[v for v in dims if isinstance(v,(int,float)) and v>0]
                if dims:distance=min(distance,min(dims)*.3)
    pts=[]
    for i,e,dx,dy,length in vectors:
        q=(round(p[0]+dx*distance,5),round(p[1]+dy*distance,5));changes[(i,e)]=q;pts.append(q)
    diagonals.append({'id':f'corner-{len(diagonals)+1}','net':k[0],'layer':k[1],'width':max(lines[a[0]]['lineWidth'],lines[b[0]]['lineWidth']),'points':pts})
    audit.append({'net':k[0],'layer':k[1],'oldCorner':p,'trimMil':distance,'oldIds':[lines[a[0]]['primitiveId'],lines[b[0]]['primitiveId']]})
routes=[];ids=[]
for i in sorted(set(i for i,e in changes)):
    t=lines[i];ids.append(t['primitiveId']);a=changes.get((i,0),endpoint(t,0));b=changes.get((i,1),endpoint(t,1))
    routes.append({'id':f'trim-{i}','net':t['net'],'layer':t['layer'],'width':t['lineWidth'],'points':[a,b]})
plan={'units':'mil','viaDiameterMil':24.02,'viaDrillMil':12.01,'vias':[],'routes':routes+diagonals}
(root/(prefix+'-plan.json')).write_text(json.dumps(plan,indent=2))
(root/(prefix+'-audit.json')).write_text(json.dumps({'bends90':audit,'branchJunctionsWith90':branch,'deleteIds':ids},indent=2))
steps=[]
if ids:steps.append({'id':'delete-measured-old-corners','run':'pcb track-delete','flags':{'ids':','.join(ids)}})
for r in plan['routes']:
    a,b=r['points'];steps.append({'id':r['id'],'action':'pcb.line.create','payload':{'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],'layer':r['layer'],'lineWidth':r['width'],'net':r['net']},'assert':{'$.primitiveId':'exists'}})
steps.append({'id':'save','action':'pcb.save','assert':{'$.saved':'true'}})
(root/(prefix+'.apply.json')).write_text(json.dumps({'version':1,'meta':{'name':'Replace 90 degree bends with 45 degree chords and 120 degree branches','project':'8c5d0d86032348a0a6c85102fe97607e','doc':'f39f5125c569691f'},'steps':steps},indent=2))
print(json.dumps({'rightAngleBends':len(audit),'branchJunctions':branch,'replacedOldTracks':len(ids),'newTracks':len(plan['routes'])},indent=2))
